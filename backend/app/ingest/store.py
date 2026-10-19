"""적재 공통: upsert, 작업 로그(ingestion_logs), 격리 행 파일 기록, 회사 단위 잠금(LockSession)·묶음 저장(BatchWriter)."""
from __future__ import annotations

import csv
import json
import logging
import time
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import Connection, Engine, text

from app.core.config import ROOT_DIR
from app.ingest.preprocess import Quarantined
from app.ingest.universe import load_universe
from app.services import freshness

log = logging.getLogger(__name__)
QUARANTINE_DIR = ROOT_DIR / "data" / "quarantine"


def upsert(conn: Connection, table: str, rows: list[dict], conflict: list[str],
           update: list[str] | None = None) -> int:
    """INSERT … ON CONFLICT DO UPDATE. 재실행해도 행 수가 변하지 않는다.

    table·컬럼 이름은 SQL 문자열에 직접 끼워 넣는다(값만 바인딩). 코드 내부 상수만 넘길 것 — 사용자 입력 금지.
    """
    if not rows:
        return 0
    cols = list(rows[0].keys())
    update = [c for c in (update if update is not None else cols) if c not in conflict]
    action = ("DO UPDATE SET " + ", ".join(f"{c} = EXCLUDED.{c}" for c in update)) if update else "DO NOTHING"
    sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)}) "
           f"ON CONFLICT ({', '.join(conflict)}) {action}")
    conn.execute(text(sql), rows)
    return len(rows)


# ── [S3-D] advisory lock ──
DART_LOCK_KEY = 7_301_010       # DART 호출 작업(재무·공시)은 프로세스가 여러 개여도 한 번에 하나만 → 분당 호출 제한 보호
BENCHMARK_LOCK_KEY = 7_301_011  # 비교군 갱신
SEC_LOCK_KEY = 7_301_012        # SEC 호출(미국 재무·기초값·공시) — 회사 1개 단위
LOCK_WAIT_NOTE_SECONDS = 1.0    # 잠금을 이보다 오래 기다렸으면 로그 비고에 남긴다


def provider_lock_key(country: str) -> int:
    """KR → DART_LOCK_KEY, US → SEC_LOCK_KEY."""
    if country == "KR":
        return DART_LOCK_KEY
    if country == "US":
        return SEC_LOCK_KEY
    raise ValueError(f"잠금 키가 없는 국가: {country}")


@contextmanager
def advisory_lock(engine: Engine, key: int, *, wait: bool = True) -> Iterator[bool]:
    """세션 수준 PostgreSQL advisory lock. wait=False면 이미 잡혀 있을 때 False를 돌려주고 기다리지 않는다."""
    with engine.connect() as conn:
        if wait:
            conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": key})
            got = True
        else:
            got = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar())
        conn.commit()
        try:
            yield got
        finally:
            if got:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
                conn.commit()


@dataclass
class JobResult:
    rows: int = 0
    status: str = "SUCCESS"
    notes: list[str] = field(default_factory=list)
    quarantined: list[Quarantined] = field(default_factory=list)


def _write_quarantine(job_type: str, label: str, items: list[Quarantined]) -> str:
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    path = QUARANTINE_DIR / f"{job_type.lower()}_{datetime.now():%Y%m%d}.csv"
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["logged_at", "target", "reason", "row"])
        for q in items:
            w.writerow([datetime.now().isoformat(timespec="seconds"), label, q.reason, json.dumps(q.row, default=str, ensure_ascii=False)])
    return str(path.relative_to(ROOT_DIR))


def error_text(e: BaseException) -> str:
    """로그·freshness에 남길 실패 사유. SQLAlchemy 오류는 SQL 전문 대신 DB 오류 메시지만 남긴다."""
    msg = str(getattr(e, "orig", None) or e).strip().splitlines()
    return f"{type(e).__name__}: {' '.join(msg[:3])}"[:500]


def _log_detail(error: str | None, notes: list[str]) -> str | None:
    detail = "; ".join(notes) or None
    return error + (f" | {detail}" if detail else "") if error else detail


@contextmanager
def job_log(engine: Engine, *, source: str, job_type: str, stock_id: int | None = None,
            label: str = "", reraise: bool = False) -> Iterator[JobResult]:
    """작업 1건(종목 1개 등)의 결과를 ingestion_logs에 남긴다.

    예외가 나면 FAILED로 기록하고 삼킨다 → 전체 적재는 계속된다.
    reraise=True면 FAILED를 기록한 뒤 예외를 다시 던진다 — 실패하면 뒤 작업이 의미 없는 작업(마스터 적재 등)에 쓴다.
    로그는 적재 트랜잭션과 별도 트랜잭션으로 쓴다(적재 롤백 시에도 실패 기록 보존).
    """
    started = datetime.now(timezone.utc)
    res = JobResult()
    error = exc = None
    try:
        yield res
    except Exception as e:  # noqa: BLE001
        exc = e
        res.status, error = "FAILED", error_text(e)
        log.error("%s %s 실패: %s", job_type, label, error)
    if res.quarantined:
        path = _write_quarantine(job_type, label, res.quarantined)
        reasons = Counter(q.reason for q in res.quarantined)
        res.notes.append(f"격리 {len(res.quarantined)}행 {dict(reasons)} → {path}")
    detail = _log_detail(error, res.notes)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO ingestion_logs (source, job_type, stock_id, status, rows_loaded, error, started_at, finished_at)
            VALUES (:source, :job_type, :stock_id, :status, :rows, :error, :started, :finished)"""),
            dict(source=source, job_type=job_type, stock_id=stock_id, status=res.status, rows=res.rows,
                 error=detail, started=started, finished=datetime.now(timezone.utc)))
    lvl = logging.INFO if res.status == "SUCCESS" else logging.WARNING
    log.log(lvl, "%-11s %-14s %-7s rows=%d%s", job_type, label, res.status, res.rows, f" ({detail})" if detail else "")
    if reraise and exc is not None:
        raise exc


# ---------------------------------------------------------------- 회사 단위 잠금 · 묶음 저장
# DART·SEC를 부르는 동안만 회사 1개 단위로 잠그고(상세 요청이 묶음 전체를 기다리지 않게),
# DB 쓰기는 여러 회사분을 모아 한 트랜잭션으로 한다(실적 시즌 트랜잭션 수를 줄임)

def default_flush_every() -> int:
    """config/universe.yaml ingest.flush_every (없으면 20)."""
    return int(load_universe().ingest.get("flush_every", 20))


class LockSession:
    """연결 1개를 잡아 두고 advisory lock 잠금·해제를 반복한다(회사마다 새 연결을 열지 않음).

    with LockSession(engine) as locks:
        with locks.hold(provider_lock_key("KR")) as waited:   # waited: 잠금을 기다린 초
            ...외부 호출...
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.conn: Connection | None = None
        self.held: list[int] = []

    def __enter__(self) -> "LockSession":
        self.conn = self.engine.connect()
        return self

    def __exit__(self, *exc) -> None:
        conn, self.conn = self.conn, None
        try:
            for key in self.held:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
            conn.commit()
        finally:
            self.held = []
            conn.close()

    @contextmanager
    def hold(self, key: int) -> Iterator[float]:
        if self.conn is None:
            raise RuntimeError("LockSession 밖에서 hold를 불렀습니다")
        started = time.monotonic()
        self.conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": key})
        self.conn.commit()
        self.held.append(key)
        try:
            yield time.monotonic() - started
        finally:
            self.held.remove(key)
            self.conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
            self.conn.commit()


@dataclass
class Unit:
    """회사 1개 작업의 결과. 외부 호출은 끝났고 DB에는 아직 쓰지 않은 상태."""
    source: str                       # ingestion_logs.source — "DART" / "SEC"
    job_type: str                     # "FINANCIALS" / "DISCLOSURES"
    stock_id: int
    label: str                        # 티커 (반환 딕셔너리 키, 로그 label)
    country: str                      # "KR" / "US" — freshness.mark의 country
    kind: str                         # data_freshness.kind — "financials" / "disclosures"
    started_at: datetime              # UTC
    writes: list[tuple[str, list[dict], list[str]]] = field(default_factory=list)  # (테이블, 행, 충돌 키) — 이 순서로 upsert
    after: list[Callable[[Connection, "Unit"], None]] = field(default_factory=list)  # upsert 뒤 같은 트랜잭션에서 실행
    notes: list[str] = field(default_factory=list)
    rows: int = 0                     # ingestion_logs.rows_loaded
    error: str | None = None          # 외부 호출 단계 실패 사유. 있으면 writes·after를 실행하지 않는다
    status: str = "PENDING"           # flush 뒤 "SUCCESS" / "FAILED"


def write_logs(engine: Engine, units: list[Unit]) -> None:
    """Unit마다 ingestion_logs 1행(적재와 별도 트랜잭션). 형식은 job_log와 같다. 실패해도 예외를 올리지 않는다."""
    if not units:
        return
    finished = datetime.now(timezone.utc)
    rows = [dict(source=u.source, job_type=u.job_type, stock_id=u.stock_id, status=u.status, rows=u.rows,
                 error=_log_detail(u.error, u.notes), started=u.started_at, finished=finished) for u in units]
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO ingestion_logs (source, job_type, stock_id, status, rows_loaded, error, started_at, finished_at)
                VALUES (:source, :job_type, :stock_id, :status, :rows, :error, :started, :finished)"""), rows)
    except Exception:  # noqa: BLE001
        log.exception("ingestion_logs 기록 실패 (%d행)", len(rows))
    for u, r in zip(units, rows):
        lvl = logging.INFO if u.status == "SUCCESS" else logging.WARNING
        log.log(lvl, "%-11s %-14s %-7s rows=%d%s", u.job_type, u.label, u.status, u.rows,
                f" ({r['error']})" if r["error"] else "")


class BatchWriter:
    """Unit을 모아 flush_every개마다 한 트랜잭션으로 저장한다. 행 upsert와 freshness 기록은 같은 트랜잭션,
    ingestion_logs는 별도 트랜잭션(저장이 롤백돼도 남음). 저장이 실패하면 그 묶음 전체를 FAILED로 기록한다."""

    def __init__(self, engine: Engine, flush_every: int,
                 on_flush: Callable[[list[Unit]], None] | None = None) -> None:
        self.engine, self.flush_every, self.on_flush = engine, max(1, flush_every), on_flush
        self.pending: list[Unit] = []
        self.done: list[Unit] = []
        self.flushes = 0

    def add(self, unit: Unit) -> None:
        self.pending.append(unit)
        if len(self.pending) >= self.flush_every:
            self.flush()

    def flush(self) -> list[Unit]:
        if not self.pending:
            return []
        batch, self.pending = self.pending, []
        now = datetime.now(timezone.utc)
        try:
            with self.engine.begin() as conn:
                for u in batch:
                    if u.error is None:
                        for table, rows, conflict in u.writes:
                            upsert(conn, table, rows, conflict)
                        for fn in u.after:
                            fn(conn, u)
                        freshness.mark(conn, u.kind, u.stock_id, True, country=u.country, now=now)
                    else:
                        freshness.mark(conn, u.kind, u.stock_id, False, country=u.country, error=u.error, now=now)
        except Exception as e:  # noqa: BLE001 — 묶음 저장 실패는 그 묶음 회사 모두 실패로 기록하고 계속
            msg = "묶음 저장 실패: " + error_text(e)
            log.error("%s (%d개 회사)", msg, len(batch))
            for u in batch:
                if u.error is None:
                    u.error = msg
            try:
                with self.engine.begin() as conn:
                    for u in batch:
                        freshness.mark(conn, u.kind, u.stock_id, False, country=u.country, error=u.error, now=now)
            except Exception:  # noqa: BLE001
                log.exception("묶음 저장 실패 뒤 freshness 기록 실패")
        for u in batch:
            u.status = "SUCCESS" if u.error is None else "FAILED"
        write_logs(self.engine, batch)
        self.flushes += 1
        self.done.extend(batch)
        if self.on_flush is not None:
            try:
                self.on_flush([u for u in batch if u.status == "SUCCESS"])
            except Exception:  # noqa: BLE001
                log.exception("묶음 저장 뒤 후처리 실패")
        return batch
