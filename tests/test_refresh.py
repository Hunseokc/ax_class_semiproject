"""갱신 정책: TTL 이내 외부 호출 0회, TTL 초과 시 작업별 정확히 1회, 증분 일봉, 동시 갱신 직렬화."""
import threading
from datetime import timedelta

from sqlalchemy import text

from app.services.fx import FxService
from app.services.refresh import RETRY_AFTER, RefreshService
from tests.conftest import D, scalar
from tests.fakes import make_providers


def service(engine, providers):
    return RefreshService(engine, providers, FxService(engine, providers.fx, 4), 4)


def call_counts(p) -> dict:
    return {"fx_current": p.fx.current.count, "fx_daily": p.fx.daily.count, "indices": p.kr_index.count,
            "prices": p.kr_price.count, "valuation": p.kr_valuation.count}


def expire_all(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("UPDATE ingestion_logs SET started_at = started_at - interval '5 hours', "
                          "finished_at = finished_at - interval '5 hours'"))
        conn.execute(text("UPDATE fx_rates SET rate_at = rate_at - interval '5 hours' WHERE granularity = 'SNAPSHOT'"))


EXPECTED_ONE_RUN = {"fx_current": 1, "fx_daily": 1, "indices": 1, "prices": 4, "valuation": 4}  # 지수 1개, 종목 4개


def test_first_refresh_runs_every_job_once(engine):
    p = make_providers()
    result = service(engine, p).refresh()
    assert {j.job_type: j.status for j in result.jobs} == {
        "FX": "SUCCESS", "INDICES": "SUCCESS", "PRICES": "SUCCESS", "VALUATION": "SUCCESS", "SCORES": "SKIPPED"}
    assert call_counts(p) == EXPECTED_ONE_RUN


def test_refresh_within_ttl_makes_no_external_calls(engine):
    p = make_providers()
    svc = service(engine, p)
    svc.refresh()
    before = call_counts(p)
    second = svc.refresh()
    assert call_counts(p) == before                                  # 외부 호출 0회
    assert all(j.status == "SKIPPED" for j in second.jobs)
    assert scalar(engine, "SELECT count(*) FROM ingestion_logs WHERE status = 'SKIPPED'") == 4
    assert second.next_refresh_available_at > second.refreshed_at   # 다음 갱신 가능 시각은 미래


def test_refresh_after_ttl_calls_each_job_exactly_once_more(engine):
    p = make_providers()
    svc = service(engine, p)
    svc.refresh()
    expire_all(engine)
    svc.refresh()
    assert call_counts(p) == {k: v * 2 for k, v in EXPECTED_ONE_RUN.items()}


def test_incremental_prices_start_after_last_stored_date(engine):
    p = make_providers()
    service(engine, p).refresh()
    starts = {ticker: start for ticker, start, _ in p.kr_price.calls}
    assert starts == {t: D + timedelta(days=1) for t in ("005930", "000660", "AAPL", "NVDA")}
    last = scalar(engine, "SELECT max(trade_date) FROM daily_prices WHERE stock_id = 1")
    expire_all(engine)
    p.kr_price.calls.clear()
    service(engine, p).refresh()
    assert {start for _, start, _ in p.kr_price.calls} == {last + timedelta(days=1)}


def test_concurrent_refresh_requests_are_serialized(engine):
    p = make_providers()
    svc = service(engine, p)
    barrier, results = threading.Barrier(3), []

    def worker():
        barrier.wait()
        results.append(svc.refresh())

    threads = [threading.Thread(target=worker) for _ in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert call_counts(p) == EXPECTED_ONE_RUN                        # 3번 요청해도 한 번만 실행
    skipped_runs = [r for r in results if all(j.status == "SKIPPED" for j in r.jobs)]
    assert len(skipped_runs) == 2


def shift_logs(engine, minutes: int) -> None:
    with engine.begin() as conn:
        conn.execute(text("UPDATE ingestion_logs SET started_at = started_at - make_interval(mins => :m), "
                          "finished_at = finished_at - make_interval(mins => :m)"), {"m": minutes})


def failing_prices(p, failing: set[str]) -> list[str]:
    """failing에 든 종목은 일봉 조회가 실패하게 하고, 조회를 시도한 종목을 기록한다."""
    original, tried = p.kr_price.get_daily_prices, []

    def flaky(stock, start, end):
        tried.append(stock.ticker)
        if stock.ticker in failing:
            raise RuntimeError("boom")
        return original(stock, start, end)

    p.kr_price.get_daily_prices = flaky
    return tried


def test_partial_failure_retries_only_failed_stocks_after_retry_interval(engine):
    p = make_providers()
    failing = {"AAPL"}
    tried = failing_prices(p, failing)
    svc = service(engine, p)

    first = {j.job_type: j.status for j in svc.refresh().jobs}
    assert first["PRICES"] == "PARTIAL"
    assert scalar(engine, "SELECT status FROM ingestion_logs WHERE source = 'REFRESH' AND job_type = 'PRICES'") == "FAILED"

    tried.clear()
    second = {j.job_type: j for j in svc.refresh().jobs}                # 재시도 간격(30분) 이내
    assert second["PRICES"].status == "SKIPPED" and second["PRICES"].detail.startswith("최근 실패")
    assert tried == []

    shift_logs(engine, 31)
    failing.clear()
    third = {j.job_type: j for j in svc.refresh().jobs}
    assert third["PRICES"].status == "SUCCESS" and "실패 종목 1개 재시도" in third["PRICES"].detail
    assert tried == ["AAPL"]                                             # 성공했던 종목은 다시 받지 않음
    assert {j: third[j].status for j in ("FX", "INDICES", "VALUATION")} == dict.fromkeys(("FX", "INDICES", "VALUATION"), "SKIPPED")

    tried.clear()
    fourth = {j.job_type: j for j in svc.refresh().jobs}
    assert fourth["PRICES"].status == "SKIPPED" and fourth["PRICES"].detail.startswith("TTL 이내")
    assert tried == []


def test_next_available_is_retry_time_after_partial_failure(engine):
    p = make_providers()
    failing_prices(p, {"AAPL"})
    svc = service(engine, p)
    svc.refresh()
    failed_at = scalar(engine, "SELECT finished_at FROM ingestion_logs WHERE source = 'REFRESH' AND status = 'FAILED'")
    assert svc.next_available() == failed_at + RETRY_AFTER              # 다른 작업은 4시간 뒤, 실패한 일봉은 30분 뒤


def test_per_stock_logs_from_other_jobs_do_not_satisfy_ttl(engine):
    """비교군 갱신·상세 수집이 남긴 종목 단위 SUCCESS가 노출 종목 갱신을 막지 않는다."""
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO ingestion_logs (source, job_type, stock_id, status, started_at, finished_at)
                             VALUES ('YFINANCE', 'PRICES', 3, 'SUCCESS', now(), now())"""))
    p = make_providers()
    result = {j.job_type: j.status for j in service(engine, p).refresh().jobs}
    assert result["PRICES"] == "SUCCESS" and p.kr_price.count == 4


def test_refresh_api(client, engine):
    r = client.post("/api/v1/market/refresh")
    assert r.status_code == 200
    body = r.json()
    assert {j["job_type"] for j in body["jobs"]} == {"FX", "INDICES", "PRICES", "VALUATION", "SCORES"}
    assert body["ttl_hours"] == 4 and body["next_refresh_available_at"]
    status = client.get("/api/v1/market/refresh/status").json()
    assert all(j["status"] == "FRESH" for j in status["jobs"])
