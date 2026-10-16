"""데이터 품질 현황 — GET /statistics/data-quality와 `python -m app.ingest status`가 같은 기준을 쓴다.

- 작업 종류별 마지막 성공·실패(사유·대상), 최근 days일 상태별 건수, 격리 행 수
- stale_jobs: 4시간 갱신 작업(FX·INDICES·PRICES·VALUATION·SCORES) 중 마지막 작업 단위 성공이 TTL의 2배를 넘은 것.
  로그에 한 번도 나오지 않은 작업은 판단하지 않는다(실행 전에는 '오래됨'이 아니라 '알 수 없음')
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import Connection

from app.queries import sql
from app.services.refresh import JOB_TYPES as REFRESH_JOB_TYPES

STATUSES = ("success", "failed", "partial", "skipped")


def data_quality(conn: Connection, *, days: int, ttl_hours: float, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    stale_after = timedelta(hours=ttl_hours * 2)
    rows = [dict(r) for r in conn.execute(sql("stats_data_quality"), {"since": since}).mappings()]
    jobs, stale = [], []
    for r in rows:
        last_ok = r.pop("last_refresh_success_at")
        is_stale = None                                 # 4시간 갱신 작업이 아니면 판단하지 않음
        if r["job_type"] in REFRESH_JOB_TYPES:
            is_stale = last_ok is None or now - last_ok > stale_after
            if is_stale:
                stale.append({"job_type": r["job_type"], "last_success_at": last_ok,
                              "hours_since_success": round((now - last_ok).total_seconds() / 3600, 1) if last_ok else None})
        jobs.append({**{k: r[k] for k in ("job_type", "last_success_at", "last_failure_at", "last_failure_reason",
                                          "last_failure_target", "quarantined_rows")},
                     "counts": {k: r[k] for k in STATUSES}, "stale": is_stale})
    totals = {k: sum(j["counts"][k] for j in jobs) for k in STATUSES}
    totals["quarantined_rows"] = sum(j["quarantined_rows"] for j in jobs)
    return {"days": days, "since": since, "generated_at": now, "ttl_hours": ttl_hours,
            "stale_after_hours": ttl_hours * 2, "totals": totals, "jobs": jobs, "stale_jobs": stale}
