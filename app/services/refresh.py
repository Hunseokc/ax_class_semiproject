"""시장 데이터 갱신 (POST /market/refresh, python -m app.ingest refresh).

작업: FX(SNAPSHOT + DAILY 증분) → INDICES → PRICES(증분) → VALUATION → SCORES
- 작업 단위 결과를 ingestion_logs에 source='REFRESH' 1행으로 남기고, 그 마지막 성공 시각이 TTL 이내면 외부 호출 없이 SKIPPED
  (종목 단위 행은 비교군 갱신·상세 수집도 남기므로 TTL 판단에 쓰지 않는다)
- 일부 대상만 실패한 작업은 RETRY_AFTER(30분) 뒤 실패한 종목만 다시 받는다 → 성공한 종목은 TTL당 1회 유지
- 동시에 여러 갱신 요청이 와도 advisory lock으로 직렬화 → 뒤 요청은 앞 요청 결과를 보고 SKIPPED
- 대상 종목: 노출 종목 + 관심종목·포트폴리오에 담긴 종목(매력도 비교군은 app/ingest/benchmark.py가 1일 1회)
- 주기 실행: 앱 안 스케줄러(app/services/scheduler.py) 또는 cron의 python -m app.ingest refresh
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import Connection, Engine, text

from app.ingest import jobs
from app.ingest.universe import FREQUENT_SQL
from app.providers.factory import Providers
from app.services.fx import FxService, utcnow

log = logging.getLogger(__name__)

REFRESH_LOCK_KEY = 7_301_002
JOB_TYPES = ("FX", "INDICES", "PRICES", "VALUATION", "SCORES")
JOB_SOURCE = "REFRESH"                 # 작업 단위 결과 행의 source
RETRY_AFTER = timedelta(minutes=30)    # 실패한 작업을 다시 시도하기까지 최소 간격(갱신 버튼 연타 방지)
PER_STOCK_JOBS = ("PRICES", "VALUATION")


@dataclass
class JobOutcome:
    job_type: str
    status: str                        # SUCCESS / PARTIAL / FAILED / SKIPPED
    detail: str | None = None
    last_success_at: datetime | None = None
    counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class FailedRun:
    started_at: datetime
    finished_at: datetime


@dataclass
class RefreshResult:
    refreshed_at: datetime
    next_refresh_available_at: datetime
    jobs: list[JobOutcome]


def _summarize(statuses: dict[str, str]) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    for s in statuses.values():
        counts[s] = counts.get(s, 0) + 1
    if not statuses or counts.get("SUCCESS", 0) == len(statuses):
        return "SUCCESS", counts
    if counts.get("FAILED", 0) == len(statuses):
        return "FAILED", counts
    return "PARTIAL", counts


class RefreshService:
    def __init__(self, engine: Engine, providers: Providers, fx: FxService, ttl_hours: float,
                 scorer: Callable[[Engine], int] | None = None, clock: Callable[[], datetime] = utcnow):
        self.engine = engine
        self.providers = providers
        self.fx = fx
        self.ttl = timedelta(hours=ttl_hours)
        self.scorer = scorer
        self.clock = clock

    @staticmethod
    def last_success(conn: Connection) -> dict[str, datetime]:
        rows = conn.execute(text("""
            SELECT job_type, max(finished_at) FROM ingestion_logs
            WHERE source = :src AND status = 'SUCCESS' AND job_type = ANY(:jobs) GROUP BY job_type"""),
            {"src": JOB_SOURCE, "jobs": list(JOB_TYPES)}).all()
        return dict(rows)

    @staticmethod
    def last_failure(conn: Connection) -> dict[str, FailedRun]:
        """작업별 마지막 실패(부분 실패 포함) 중 마지막 성공보다 뒤인 것."""
        rows = conn.execute(text("""
            SELECT DISTINCT ON (f.job_type) f.job_type, f.started_at, f.finished_at FROM ingestion_logs f
            WHERE f.source = :src AND f.status = 'FAILED' AND f.job_type = ANY(:jobs)
              AND NOT EXISTS (SELECT 1 FROM ingestion_logs s WHERE s.source = :src AND s.status = 'SUCCESS'
                                AND s.job_type = f.job_type AND s.finished_at >= f.finished_at)
            ORDER BY f.job_type, f.finished_at DESC"""), {"src": JOB_SOURCE, "jobs": list(JOB_TYPES)}).all()
        return {r[0]: FailedRun(r[1], r[2]) for r in rows}

    def _due_at(self, last: datetime | None, failed: FailedRun | None, now: datetime) -> datetime:
        """작업을 다시 실행할 수 있는 시각: TTL 이내면 TTL 끝, 최근 실패면 재시도 간격 끝, 아니면 지금."""
        if last and now - last < self.ttl:
            return last + self.ttl
        if failed and now - failed.finished_at < RETRY_AFTER:
            return failed.finished_at + RETRY_AFTER
        return now

    @property
    def job_types(self) -> tuple[str, ...]:
        """실제로 실행 가능한 작업 (점수 계산기가 없으면 SCORES 제외)."""
        return JOB_TYPES if self.scorer is not None else tuple(j for j in JOB_TYPES if j != "SCORES")

    def next_available(self) -> datetime:
        """가장 먼저 다시 실행할 수 있는 작업의 시각."""
        with self.engine.connect() as conn:
            last, failed = self.last_success(conn), self.last_failure(conn)
        now = self.clock()
        return max(now, min(self._due_at(last.get(j), failed.get(j), now) for j in self.job_types))

    def status(self) -> RefreshResult:
        """외부 호출 없이 현재 갱신 상태만 반환 (사이드바 표시용)."""
        with self.engine.connect() as conn:
            last = self.last_success(conn)
        jobs_ = [JobOutcome(j, "FRESH" if j in last and self.clock() - last[j] < self.ttl else "STALE",
                            last_success_at=last.get(j)) for j in self.job_types]
        refreshed = max(last.values()) if last else None
        return RefreshResult(refreshed_at=refreshed, next_refresh_available_at=self.next_available(), jobs=jobs_)

    def _retry_targets(self, job_type: str, failed: FailedRun | None, now: datetime) -> list[int] | None:
        """TTL 안의 부분 실패 뒤 재시도면 그 실행에서 실패한 종목(갱신 대상 범위)만. 그 밖에는 None(전체)."""
        if job_type not in PER_STOCK_JOBS or failed is None or now - failed.finished_at >= self.ttl:
            return None
        with self.engine.connect() as conn:
            ids = conn.execute(text(f"""
                SELECT DISTINCT l.stock_id FROM ingestion_logs l JOIN stocks s ON s.stock_id = l.stock_id
                WHERE l.job_type = :job AND l.status = 'FAILED' AND l.source <> :src
                  AND l.started_at >= :start AND l.finished_at <= :end AND s.is_active AND {FREQUENT_SQL}"""),
                {"job": job_type, "src": JOB_SOURCE, "start": failed.started_at, "end": failed.finished_at}).scalars().all()
        return sorted(ids) or None

    def _run(self, job_type: str, stock_ids: list[int] | None = None) -> tuple[str, dict[str, int], str | None]:
        if job_type == "FX":
            quote = self.fx.get_current_rate(force=True)
            daily = jobs.load_fx_daily(self.engine, self.providers)
            status = "SUCCESS" if not quote.stale and daily == "SUCCESS" else ("FAILED" if quote.stale and daily != "SUCCESS" else "PARTIAL")
            return status, {}, f"USD/KRW {quote.usd_krw}" + (" (stale)" if quote.stale else "")
        if job_type == "INDICES":
            return (*_summarize(jobs.load_indices(self.engine, self.providers)), None)
        if job_type == "PRICES":
            return (*_summarize(jobs.load_prices(self.engine, self.providers, stock_ids=stock_ids)), None)
        if job_type == "VALUATION":
            return (*_summarize(jobs.load_valuations(self.engine, self.providers, stock_ids=stock_ids)), None)
        if job_type == "SCORES":
            n = self.scorer(self.engine)
            return "SUCCESS", {"rows": n}, None
        raise ValueError(job_type)

    def refresh(self) -> RefreshResult:
        outcomes: list[JobOutcome] = []
        with self.engine.connect() as lock_conn:
            # 세션 수준 lock: 갱신 작업들이 각자 트랜잭션을 쓰므로 전체 구간 동안 잡아 둔다
            lock_conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": REFRESH_LOCK_KEY})
            try:
                for job_type in JOB_TYPES:
                    if job_type not in self.job_types:
                        outcomes.append(JobOutcome(job_type, "SKIPPED", "점수 계산기 미연결"))
                        continue
                    with self.engine.connect() as conn:
                        last = self.last_success(conn).get(job_type)
                        failed = self.last_failure(conn).get(job_type)
                    now = self.clock()
                    due = self._due_at(last, failed, now)
                    if due > now:
                        note = (f"TTL 이내 — 마지막 성공 {last.isoformat()}" if last and now - last < self.ttl
                                else f"최근 실패 — {due.isoformat()} 이후 재시도")
                        self._log_skip(job_type, note, now)
                        outcomes.append(JobOutcome(job_type, "SKIPPED", note, last))
                        continue
                    retry_ids = self._retry_targets(job_type, failed, now)
                    try:
                        status, counts, detail = self._run(job_type, retry_ids)
                    except Exception as e:  # noqa: BLE001 — 한 작업 실패가 나머지를 막지 않는다
                        log.exception("갱신 작업 %s 실패", job_type)
                        status, counts, detail = "FAILED", {}, f"{type(e).__name__}: {e}"
                    if retry_ids:
                        detail = f"실패 종목 {len(retry_ids)}개 재시도" + (f"; {detail}" if detail else "")
                    self._log_job(job_type, status, counts, detail, now)
                    with self.engine.connect() as conn:
                        last = self.last_success(conn).get(job_type)
                    outcomes.append(JobOutcome(job_type, status, detail, last, counts))
            finally:
                lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": REFRESH_LOCK_KEY})
                lock_conn.commit()
        return RefreshResult(refreshed_at=self.clock(), next_refresh_available_at=self.next_available(), jobs=outcomes)

    def _log_skip(self, job_type: str, note: str, now: datetime) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO ingestion_logs (source, job_type, status, rows_loaded, error, started_at, finished_at)
                VALUES ('INTERNAL', :job, 'SKIPPED', 0, :note, :now, :now)"""),
                {"job": job_type, "note": note, "now": now})

    def _log_job(self, job_type: str, status: str, counts: dict[str, int], detail: str | None, started: datetime) -> None:
        """작업 단위 결과 1행. 부분 실패(PARTIAL)도 FAILED로 남겨 TTL을 시작하지 않는다."""
        parts = [status, ", ".join(f"{k} {v}" for k, v in sorted(counts.items())), detail or ""]
        with self.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO ingestion_logs (source, job_type, status, rows_loaded, error, started_at, finished_at)
                VALUES (:src, :job, :status, 0, :note, :started, :finished)"""),
                {"src": JOB_SOURCE, "job": job_type, "status": "SUCCESS" if status == "SUCCESS" else "FAILED",
                 "note": " | ".join(p for p in parts if p)[:500], "started": started,
                 "finished": max(self.clock(), started)})
