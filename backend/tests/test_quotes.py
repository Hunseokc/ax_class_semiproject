"""현재가(관심종목·상세 화면 표시 전용): 1분 저장, 실패 시 저장값·일봉 대체, 갱신 작업 QUOTES, 관심종목 가격 칸 덮어쓰기."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text

from app.services.fx import FxService
from app.services.quotes import QuoteService
from app.services.refresh import RefreshService
from tests.conftest import D, scalar
from tests.fakes import FakeQuote

API = "/api/v1/stocks/KOSPI/005930/quote"


def test_quote_api_fetches_then_reuses_within_a_minute(engine, client, providers):
    providers.quote = FakeQuote()
    first = client.get(API).json()
    assert Decimal(str(first["price"])) == Decimal("71000") and first["stale"] is False and first["source"] == "KIS"
    assert first["change_rate"] is not None and first["quoted_at"]
    client.get(API)
    assert providers.quote.count == 1                                   # 1분 안 → 저장값
    assert scalar(engine, "SELECT count(*) FROM price_quotes") == 1


def test_quote_refetches_after_max_age(engine):
    fake, now = FakeQuote(), [datetime(2026, 10, 21, 5, 0, tzinfo=timezone.utc)]
    svc = QuoteService(engine, fake, clock=lambda: now[0])
    svc.get(1)
    now[0] += timedelta(seconds=61)
    svc.get(1)
    assert fake.count == 2


def test_quote_failure_falls_back_to_stored_then_none(engine, client, providers):
    providers.quote = FakeQuote(fail=True)
    assert client.get(API).json()["price"] is None                     # 저장값도 없으면 None → 화면은 일봉 종가
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO price_quotes (stock_id, price, quoted_at)
                             VALUES (1, 70500, now() - interval '10 minutes')"""))
    body = client.get(API).json()
    assert Decimal(str(body["price"])) == Decimal("70500") and body["stale"] is True


def test_quote_without_provider_returns_none(client, providers):
    providers.quote = None
    body = client.get(API).json()
    assert body["price"] is None and body["stale"] is False


def test_quote_unknown_stock_404(client):
    assert client.get("/api/v1/stocks/KOSPI/999999/quote").status_code == 404


def _watch(engine, *stock_ids):
    with engine.begin() as conn:
        for i, sid in enumerate(stock_ids):
            conn.execute(text("INSERT INTO watchlist_items (user_id, stock_id, sort_order) VALUES (1, :s, :o)"), {"s": sid, "o": i})


def test_refresh_quotes_job_fetches_watchlist_stocks_only(engine, providers):
    _watch(engine, 1, 3)
    providers.quote = FakeQuote()
    svc = RefreshService(engine, providers, FxService(engine, providers.fx, 1), 4, fast_ttl_hours=1)
    out = {j.job_type: j.status for j in svc.refresh().jobs}
    assert out["QUOTES"] == "SUCCESS"
    assert sorted(t for (t,) in providers.quote.calls) == ["005930", "AAPL"]   # 관심종목에 없는 000660·NVDA는 받지 않는다
    assert scalar(engine, "SELECT count(*) FROM price_quotes") == 2


def test_refresh_without_quote_provider_has_no_quotes_job(engine, providers):
    svc = RefreshService(engine, providers, FxService(engine, providers.fx, 4), 4)
    assert "QUOTES" not in [j.job_type for j in svc.refresh().jobs]


def test_watchlist_uses_quote_only_when_newer_than_daily_close(engine, client):
    _watch(engine, 1, 3)
    with engine.begin() as conn:
        # 005930: 마지막 일봉(D) 마감 뒤에 받은 현재가 → 덮어씀 / AAPL: 마감 전 장중 값 → 일봉 종가 유지
        conn.execute(text("""INSERT INTO price_quotes (stock_id, price, change, change_rate, quoted_at) VALUES
            (1, 71000, 1000, 0.014286, now()),
            (3, 199, -1, -0.005, ((CAST(:d AS date) + time '10:00') AT TIME ZONE 'America/New_York'))"""), {"d": D})
    items = {w["ticker"]: w for w in client.get("/api/v1/watchlist").json()["items"]}
    assert Decimal(str(items["005930"]["close"])) == Decimal("71000") and items["005930"]["quoted_at"]
    assert Decimal(str(items["AAPL"]["close"])) == Decimal("200") and items["AAPL"]["quoted_at"] is None
