"""데이터 품질 현황: GET /statistics/data-quality, app/services/data_quality.py(ingest status와 공용)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.services.data_quality import data_quality

API = "/api/v1/statistics/data-quality"


def log(conn, job, status, *, source="FAKE", stock_id=None, error=None, ago=timedelta(hours=1), now=None):
    t = (now or datetime.now(timezone.utc)) - ago
    conn.execute(text("""INSERT INTO ingestion_logs (source, job_type, stock_id, status, error, started_at, finished_at)
                         VALUES (:src, :job, :sid, :st, :err, :t, :t)"""),
                 {"src": source, "job": job, "sid": stock_id, "st": status, "err": error, "t": t})


def test_empty_when_no_logs(client):
    d = client.get(API).json()
    assert d["jobs"] == [] and d["stale_jobs"] == [] and d["days"] == 7
    assert d["totals"] == {"success": 0, "failed": 0, "partial": 0, "skipped": 0, "quarantined_rows": 0}


def test_mixed_success_failure_aggregation(client, engine):
    with engine.begin() as conn:
        log(conn, "PRICES", "SUCCESS", stock_id=1, error="2026-01-01~2026-01-02; 격리 2행 {'장 마감 전 미확정 봉': 2} → x.csv")
        log(conn, "PRICES", "SUCCESS", stock_id=2)
        log(conn, "PRICES", "SUCCESS", stock_id=3, ago=timedelta(days=10))           # 기간(7일) 밖: 건수 제외
        log(conn, "PRICES", "FAILED", stock_id=4, error="ProviderError: yfinance history NVDA: boom", ago=timedelta(minutes=30))
        log(conn, "PRICES", "FAILED", source="REFRESH", error="PARTIAL | FAILED 1, SUCCESS 2", ago=timedelta(minutes=29))
        log(conn, "PRICES", "SKIPPED", source="INTERNAL", error="TTL 이내")
        log(conn, "DISCLOSURES", "SUCCESS", source="DART", stock_id=1, ago=timedelta(days=3))
    d = client.get(API).json()
    jobs = {j["job_type"]: j for j in d["jobs"]}
    assert list(jobs) == ["DISCLOSURES", "PRICES"]
    p = jobs["PRICES"]
    assert p["counts"] == {"success": 2, "failed": 1, "partial": 1, "skipped": 1}     # 대상 단위 / 실행 단위 분리
    assert p["quarantined_rows"] == 2
    assert p["last_failure_reason"] == "PARTIAL | FAILED 1, SUCCESS 2"                   # 가장 최근 실패
    assert p["stale"] is True                                                            # 작업 단위(REFRESH) 성공 기록 없음
    assert jobs["DISCLOSURES"]["stale"] is None and jobs["DISCLOSURES"]["counts"]["success"] == 1
    assert d["totals"] == {"success": 3, "failed": 1, "partial": 1, "skipped": 1, "quarantined_rows": 2}
    assert [s["job_type"] for s in d["stale_jobs"]] == ["PRICES"] and d["stale_jobs"][0]["last_success_at"] is None


def test_last_failure_target_is_ticker(client, engine):
    with engine.begin() as conn:
        log(conn, "VALUATION", "FAILED", stock_id=4, error="ProviderError: yfinance info NVDA: x")
    j = client.get(API).json()["jobs"][0]
    assert (j["job_type"], j["last_failure_target"], j["last_success_at"]) == ("VALUATION", "NVDA", None)


def test_days_window(client, engine):
    with engine.begin() as conn:
        log(conn, "INDICES", "SUCCESS", ago=timedelta(days=5))
    assert client.get(API, params={"days": 7}).json()["jobs"][0]["counts"]["success"] == 1
    assert client.get(API, params={"days": 1}).json()["jobs"][0]["counts"]["success"] == 0
    assert client.get(API, params={"days": 1}).json()["jobs"][0]["last_success_at"]     # 마지막 성공은 기간과 무관


@pytest.mark.parametrize("minutes_after_ttl2, expected", [(-1, False), (1, True)])
def test_stale_boundary_is_twice_ttl(engine, minutes_after_ttl2, expected):
    """TTL 4시간 → 마지막 작업 단위 성공이 8시간을 넘으면 stale (8시간 1분 전 → stale, 7시간 59분 전 → 아님)."""
    now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    with engine.begin() as conn:
        log(conn, "FX", "SUCCESS", source="REFRESH", now=now, ago=timedelta(hours=8, minutes=minutes_after_ttl2))
        d = data_quality(conn, days=7, ttl_hours=4, now=now)
    fx = d["jobs"][0]
    assert fx["stale"] is expected and d["stale_after_hours"] == 8
    assert [s["job_type"] for s in d["stale_jobs"]] == (["FX"] if expected else [])
    if expected:
        assert d["stale_jobs"][0]["hours_since_success"] == 8.0


@pytest.mark.parametrize("days, status", [(1, 200), (90, 200), (0, 422), (91, 422), ("x", 422)])
def test_days_range(client, days, status):
    r = client.get(API, params={"days": days})
    assert r.status_code == status
    if status == 422:
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"
