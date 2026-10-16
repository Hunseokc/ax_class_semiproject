"""데이터 품질 현황 — GET /statistics/data-quality와 `python -m app.ingest status`가 같은 기준을 쓴다.

- 작업 종류별 마지막 성공·실패(사유·대상), 최근 days일 상태별 건수, 격리 행 수
- stale_jobs: 4시간 갱신 작업(FX·INDICES·PRICES·VALUATION·SCORES) 중 마지막 작업 단위 성공이 TTL의 2배를 넘은 것.
  로그에 한 번도 나오지 않은 작업은 판단하지 않는다(실행 전에는 '오래됨'이 아니라 '알 수 없음')

TODO(껍데기): C — 본문을 원본대로 교체(B의 queries/stats_data_quality.sql 결과를 작업 종류별로 묶고 stale 판단).
  이름·인자·반환 모양은 원본 그대로다(B가 이 시그니처로 부른다). 지금은 DB를 읽지 않고 docs/06 3-6 예시 값을 돌려준다
  (days·since·generated_at·ttl_hours만 실제 값).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import Connection

STATUSES = ("success", "failed", "partial", "skipped")


def data_quality(conn: Connection, *, days: int, ttl_hours: float, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    jobs = [
        {"job_type": "FINANCIALS", "last_success_at": datetime(2026, 10, 7, 5, 40, 52, tzinfo=timezone.utc),
         "last_failure_at": None, "last_failure_reason": None, "last_failure_target": None, "quarantined_rows": 0,
         "counts": {"success": 0, "failed": 0, "partial": 0, "skipped": 0}, "stale": None},
        {"job_type": "PRICES", "last_success_at": datetime(2026, 10, 8, 6, 10, 37, tzinfo=timezone.utc),
         "last_failure_at": datetime(2026, 10, 8, 1, 51, 9, tzinfo=timezone.utc),
         "last_failure_reason": "ProviderError: yfinance history AMD: YFPricesMissingError: $AMD: Data doesn't exist for startDate = 1791432000, endDate = 1791518400",
         "last_failure_target": "AMD", "quarantined_rows": 164,
         "counts": {"success": 258, "failed": 46, "partial": 0, "skipped": 2}, "stale": False},
    ]
    totals = {k: sum(j["counts"][k] for j in jobs) for k in STATUSES}
    totals["quarantined_rows"] = sum(j["quarantined_rows"] for j in jobs)
    return {"days": days, "since": since, "generated_at": now, "ttl_hours": ttl_hours,
            "stale_after_hours": ttl_hours * 2, "totals": totals, "jobs": jobs, "stale_jobs": []}
