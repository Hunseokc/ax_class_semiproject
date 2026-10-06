"""시장 데이터 갱신 (POST /market/refresh, python -m app.ingest refresh).

작업: FX(SNAPSHOT + DAILY 증분) → INDICES → PRICES(증분) → VALUATION → SCORES
- 작업별 마지막 성공 시각(ingestion_logs)이 TTL 이내면 외부 호출 없이 SKIPPED로 기록
- 동시에 여러 갱신 요청이 와도 advisory lock으로 직렬화 → 뒤 요청은 앞 요청 결과를 보고 SKIPPED
- 앱 내부 스케줄러는 두지 않는다(주기 실행은 README의 cron 예시)
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import Connection, Engine, text

from app.ingest import jobs
from app.providers.factory import Providers
from app.services.fx import FxService, utcnow

log = logging.getLogger(__name__)

REFRESH_LOCK_KEY = 7_301_002
JOB_TYPES = ("FX", "INDICES", "PRICES", "VALUATION", "SCORES")


@dataclass
class JobOutcome:
    job_type: str
    status: str                        # SUCCESS / PARTIAL / FAILED / SKIPPED
    detail: str | None = None
    last_success_at: datetime | None = None
    counts: dict[str, int] = field(default_factory=dict)


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
            WHERE status = 'SUCCESS' AND job_type = ANY(:jobs) GROUP BY job_type"""), {"jobs": list(JOB_TYPES)}).all()
        return dict(rows)

    @property
    def job_types(self) -> tuple[str, ...]:
        """실제로 실행 가능한 작업 (점수 계산기가 없으면 SCORES 제외)."""
        return JOB_TYPES if self.scorer is not None else tuple(j for j in JOB_TYPES if j != "SCORES")

    def next_available(self, last: dict[str, datetime]) -> datetime:
        """가장 먼저 TTL이 끝나는 작업의 시각. 한 번도 성공하지 않은 작업이 있으면 지금."""
        now = self.clock()
        return max(now, min((last[j] + self.ttl if j in last else now) for j in self.job_types))

    def status(self) -> RefreshResult:
        """외부 호출 없이 현재 갱신 상태만 반환 (사이드바 표시용)."""
        with self.engine.connect() as conn:
            last = self.last_success(conn)
        jobs_ = [JobOutcome(j, "FRESH" if j in last and self.clock() - last[j] < self.ttl else "STALE",
                            last_success_at=last.get(j)) for j in self.job_types]
        refreshed = max(last.values()) if last else None
        return RefreshResult(refreshed_at=refreshed, next_refresh_available_at=self.next_available(last), jobs=jobs_)

    def _run(self, job_type: str) -> tuple[str, dict[str, int], str | None]:
        if job_type == "FX":
            quote = self.fx.get_current_rate(force=True)
            daily = jobs.load_fx_daily(self.engine, self.providers)
            status = "SUCCESS" if not quote.stale and daily == "SUCCESS" else ("FAILED" if quote.stale and daily != "SUCCESS" else "PARTIAL")
            return status, {}, f"USD/KRW {quote.usd_krw}" + (" (stale)" if quote.stale else "")
        if job_type == "INDICES":
            return (*_summarize(jobs.load_indices(self.engine, self.providers)), None)
        if job_type == "PRICES":
            return (*_summarize(jobs.load_prices(self.engine, self.providers)), None)
        if job_type == "VALUATION":
            return (*_summarize(jobs.load_valuations(self.engine, self.providers)), None)
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
                    now = self.clock()
                    if last and now - last < self.ttl:
                        self._log_skip(job_type, last, now)
                        outcomes.append(JobOutcome(job_type, "SKIPPED", f"TTL 이내 (마지막 성공 {last.isoformat()})", last))
                        continue
                    try:
                        status, counts, detail = self._run(job_type)
                    except Exception as e:  # noqa: BLE001 — 한 작업 실패가 나머지를 막지 않는다
                        log.exception("갱신 작업 %s 실패", job_type)
                        status, counts, detail = "FAILED", {}, f"{type(e).__name__}: {e}"
                    with self.engine.connect() as conn:
                        last = self.last_success(conn).get(job_type)
                    outcomes.append(JobOutcome(job_type, status, detail, last, counts))
            finally:
                lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": REFRESH_LOCK_KEY})
                lock_conn.commit()
        with self.engine.connect() as conn:
            last_all = self.last_success(conn)
        return RefreshResult(refreshed_at=self.clock(), next_refresh_available_at=self.next_available(last_all),
                             jobs=outcomes)

    def _log_skip(self, job_type: str, last: datetime, now: datetime) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO ingestion_logs (source, job_type, status, rows_loaded, error, started_at, finished_at)
                VALUES ('INTERNAL', :job, 'SKIPPED', 0, :note, :now, :now)"""),
                {"job": job_type, "note": f"TTL 이내 — 마지막 성공 {last.isoformat()}", "now": now})
