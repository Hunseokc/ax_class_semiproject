"""적재 공통: upsert, 작업 로그(ingestion_logs), 격리 행 파일 기록."""
from __future__ import annotations

import csv
import json
import logging
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Connection, Engine, text

from app.core.config import ROOT_DIR
from app.ingest.preprocess import Quarantined

log = logging.getLogger(__name__)
QUARANTINE_DIR = ROOT_DIR / "data" / "quarantine"


def upsert(conn: Connection, table: str, rows: list[dict], conflict: list[str],
           update: list[str] | None = None) -> int:
    """INSERT … ON CONFLICT DO UPDATE. 재실행해도 행 수가 변하지 않는다."""
    if not rows:
        return 0
    cols = list(rows[0].keys())
    update = [c for c in (update if update is not None else cols) if c not in conflict]
    action = ("DO UPDATE SET " + ", ".join(f"{c} = EXCLUDED.{c}" for c in update)) if update else "DO NOTHING"
    sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)}) "
           f"ON CONFLICT ({', '.join(conflict)}) {action}")
    conn.execute(text(sql), rows)
    return len(rows)


DART_LOCK_KEY = 7_301_010       # DART 호출 작업(재무·공시)은 프로세스가 여러 개여도 한 번에 하나만 → 분당 호출 제한 보호
BENCHMARK_LOCK_KEY = 7_301_011  # 비교군 갱신


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


@contextmanager
def job_log(engine: Engine, *, source: str, job_type: str, stock_id: int | None = None,
            label: str = "") -> Iterator[JobResult]:
    """작업 1건(종목 1개 등)의 결과를 ingestion_logs에 남긴다.

    예외가 나면 FAILED로 기록하고 삼킨다 → 전체 적재는 계속된다.
    로그는 적재 트랜잭션과 별도 트랜잭션으로 쓴다(적재 롤백 시에도 실패 기록 보존).
    """
    started = datetime.now(timezone.utc)
    res = JobResult()
    error = None
    try:
        yield res
    except Exception as e:  # noqa: BLE001
        # SQLAlchemy 오류는 SQL 전문 대신 DB 오류 메시지만 남긴다
        msg = str(getattr(e, "orig", None) or e).strip().splitlines()
        res.status, error = "FAILED", f"{type(e).__name__}: {' '.join(msg[:3])}"[:500]
        log.error("%s %s 실패: %s", job_type, label, error)
    if res.quarantined:
        path = _write_quarantine(job_type, label, res.quarantined)
        reasons = Counter(q.reason for q in res.quarantined)
        res.notes.append(f"격리 {len(res.quarantined)}행 {dict(reasons)} → {path}")
    detail = "; ".join(res.notes) or None
    if error:
        detail = error + (f" | {detail}" if detail else "")
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO ingestion_logs (source, job_type, stock_id, status, rows_loaded, error, started_at, finished_at)
            VALUES (:source, :job_type, :stock_id, :status, :rows, :error, :started, :finished)"""),
            dict(source=source, job_type=job_type, stock_id=stock_id, status=res.status, rows=res.rows,
                 error=detail, started=started, finished=datetime.now(timezone.utc)))
    lvl = logging.INFO if res.status == "SUCCESS" else logging.WARNING
    log.log(lvl, "%-11s %-14s %-7s rows=%d%s", job_type, label, res.status, res.rows, f" ({detail})" if detail else "")
