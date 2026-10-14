"""수집·전처리: 이상 행 격리, 샘플 재적재 시 행 수 불변, 시세 수집(fake provider) 증분·실패 격리."""
import csv
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.ingest import jobs, sample
from app.ingest.preprocess import Bar, FxPoint, clean_bars, clean_fx
from app.ingest.universe import StockSpec, load_universe
from tests.conftest import TABLES, scalar

# ── [S1-D] 시세 수집 ──
from types import SimpleNamespace

from app.providers import http, yahoo
from app.providers.base import ProviderError
from app.providers.http import Throttle
from tests.fakes import FakeFx, make_providers


def bar(d, o=10, h=11, l=9, c=10, v=100):
    return Bar(d, Decimal(o), Decimal(h), Decimal(l), Decimal(c) if c is not None else None, v)


def test_clean_bars_quarantines_with_reason():
    d0 = date(2026, 1, 5)
    bars = [bar(d0), bar(d0, c=12),                      # 중복 → 마지막 값 유지
            bar(d0 + timedelta(1), h=8),                  # 고가 < 저가
            bar(d0 + timedelta(2), o=0, h=0, l=0, c=0),   # 거래정지
            bar(d0 + timedelta(3), c=None),               # 종가 결측
            bar(d0 + timedelta(4), v=-1)]                 # 음수 거래량
    ok, bad = clean_bars(bars, "Asia/Seoul", require_volume=True, now=datetime(2026, 2, 1, tzinfo=timezone.utc))
    assert [(b.trade_date, b.close) for b in ok] == [(d0, 12)]
    assert sorted(q.reason for q in bad) == sorted(["고가 < 저가", "가격 0 이하(거래정지 등)", "종가 결측", "음수 거래량"])


def test_clean_bars_drops_unfinished_session():
    now = datetime(2026, 3, 3, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))      # 장중
    ok, bad = clean_bars([bar(date(2026, 3, 2)), bar(date(2026, 3, 3))], "Asia/Seoul", require_volume=True, now=now)
    assert [b.trade_date for b in ok] == [date(2026, 3, 2)]
    assert bad[0].reason == "장 마감 전 미확정 봉"


def test_clean_fx_quarantines_spike():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # 문자열로 만든다: Decimal(13.01)은 float 오차가 섞여 Decimal("13.01")과 다른 값이 된다
    pts = [FxPoint(base + timedelta(days=i), Decimal(v))
           for i, v in enumerate(["1300", "1302", "1301", "13.01", "1303", "1304"])]
    ok, bad = clean_fx(pts)
    assert [p.usd_krw for p in ok] == [Decimal(v) for v in ("1300", "1302", "1301", "1303", "1304")]
    assert [q.row["usd_krw"] for q in bad] == [Decimal("13.01")]
    assert "초과 이탈" in bad[0].reason


def test_master_failure_is_logged_and_raised(engine, monkeypatch):
    """마스터 적재가 실패하면 FAILED 로그를 남기고 예외를 전파한다(CLI가 성공으로 끝나지 않는다)."""
    u = load_universe()
    broken = replace(u, indices=(replace(u.indices[0], market="NOPE"),))      # 없는 시장 코드
    monkeypatch.setattr(jobs, "load_universe", lambda: broken)
    with pytest.raises(KeyError):
        jobs.load_master(engine, offline=True)
    assert scalar(engine, "SELECT status FROM ingestion_logs WHERE job_type = 'MASTER'") == "FAILED"
    assert scalar(engine, "SELECT count(*) FROM stocks") == 4                 # 롤백: 픽스처 4종목 그대로


def test_master_rejects_ticker_listed_in_two_markets(engine, monkeypatch):
    """peer_groups.members는 티커만 적으므로, 같은 티커가 두 시장에 있으면 적재 전에 멈춘다."""
    u = load_universe()
    dup = replace(u, stocks=u.stocks + (StockSpec("NASDAQ", "005930", "Dup", "005930"),))
    monkeypatch.setattr(jobs, "load_universe", lambda: dup)
    with pytest.raises(ValueError, match="중복"):
        jobs.load_master(engine, offline=True)
    assert scalar(engine, "SELECT count(*) FROM ingestion_logs") == 0         # DB를 건드리기 전에 실패


def _csv_rows(name: str) -> int:
    with (sample.SAMPLE_DIR / name).open(encoding="utf-8") as f:
        return sum(1 for _ in csv.DictReader(f))


def _counts(engine) -> dict[str, int]:
    # ingestion_logs는 실행할 때마다 1행씩 쌓이는 것이 정상이라 비교에서 뺀다. 사용자 테이블(Stage 2)은 수집 대상이 아니라 뺀다
    user_tables = {"users", "watchlist_items", "portfolios", "portfolio_items"}
    return {t: scalar(engine, f"SELECT count(*) FROM {t}") for t in TABLES if t != "ingestion_logs" and t not in user_tables}


def test_sample_reload_is_idempotent(engine):
    # conftest의 고정 픽스처를 비우고, 실제 마스터 + 샘플만으로 시작한다
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))

    def run():
        jobs.load_master(engine, offline=True)
        sample.import_sample(engine)

    run()
    first = _counts(engine)
    run()
    assert _counts(engine) == first                                       # 두 번 실행해도 행 수 동일

    u = load_universe()
    assert first["markets"] == len(u.markets)
    assert first["stocks"] == len(u.stocks)
    assert first["indices"] == len(u.indices)
    assert first["peer_groups"] == len(u.peer_groups)
    assert first["peer_group_members"] == sum(len(g.members) for g in u.peer_groups)
    assert first["daily_prices"] == _csv_rows("daily_prices.csv")
    assert first["valuation_snapshots"] == _csv_rows("valuation_snapshots.csv")
    assert first["index_daily_prices"] == _csv_rows("index_daily_prices.csv")
    assert first["fx_rates"] == _csv_rows("fx_rates.csv")
    assert all(n > 0 for n in first.values())                             # 모든 Stage 1 테이블에 행이 있다
    assert scalar(engine, "SELECT count(*) FROM ingestion_logs WHERE job_type = 'MASTER' AND status = 'SUCCESS'") == 2


# ── [S1-D] 시세 수집 ──
def test_full_reload_is_idempotent(engine):
    p = make_providers()
    jobs.load_prices(engine, p, full=True)
    n1 = scalar(engine, "SELECT count(*) FROM daily_prices")
    jobs.load_prices(engine, p, full=True)
    jobs.load_indices(engine, p, full=True)
    n2 = scalar(engine, "SELECT count(*) FROM daily_prices")
    jobs.load_indices(engine, p, full=True)
    assert n1 == n2 > 12
    assert scalar(engine, "SELECT count(*) FROM index_daily_prices") == scalar(
        engine, "SELECT count(DISTINCT trade_date) FROM index_daily_prices")


def test_failure_of_one_stock_does_not_stop_others(engine):
    p = make_providers()
    original = p.kr_price.get_daily_prices

    def flaky(stock, start, end):
        if stock.ticker == "000660":
            raise RuntimeError("boom")
        return original(stock, start, end)

    p.kr_price.get_daily_prices = flaky
    statuses = jobs.load_prices(engine, p)
    assert statuses == {"005930": "SUCCESS", "000660": "FAILED", "AAPL": "SUCCESS", "NVDA": "SUCCESS"}
    assert scalar(engine, "SELECT error FROM ingestion_logs WHERE status = 'FAILED'").startswith("RuntimeError: boom")


def test_incremental_fx_refetches_last_day_only(engine):
    """환율 증분: 마지막 저장일 하루 전부터 다시 받아 upsert → 재실행해도 행 수 불변."""
    fx = FakeFx()
    p = make_providers(fx)
    assert jobs.load_fx_daily(engine, p) == "SUCCESS"
    n1 = scalar(engine, "SELECT count(*) FROM fx_rates WHERE granularity = 'DAILY'")
    jobs.load_fx_daily(engine, p)
    assert scalar(engine, "SELECT count(*) FROM fx_rates WHERE granularity = 'DAILY'") == n1
    start, _ = fx.daily.calls[-1]
    assert start >= date.today() - timedelta(days=10)                    # 2년 전체가 아니라 최근 구간만


def test_universe_indices_are_loadable():
    """universe.yaml 지수: code·표시 순서가 겹치지 않고, 시장이 있으며, 그 나라 소스로 조회할 심볼이 있다."""
    u = load_universe()
    markets = {m.code: m.country for m in u.markets}
    idx = u.indices
    assert len({i.code for i in idx}) == len(idx) and len({i.display_order for i in idx}) == len(idx)
    for i in idx:
        assert i.market in markets, i.code
        assert i.yf_symbol, i.code                                       # US 소스·KR 대체 소스(yfinance)
        if markets[i.market] == "KR":
            assert i.pykrx, i.code                                       # KR 기본 소스(pykrx)


def test_no_session_skips_empty_or_weekend_only_range():
    fri, sat, sun = date(2026, 10, 9), date(2026, 10, 10), date(2026, 10, 11)
    assert jobs._no_session(sat, fri) == "최신 상태"
    assert jobs._no_session(sat, sun) == "최신 상태(주말)"
    assert jobs._no_session(fri, sun) is None


def test_up_to_date_us_stock_is_not_requested_for_unopened_local_day(engine):
    """한국 오전에는 미국이 아직 전날 → 시장 현지 날짜까지 받았으면 외부 호출 없이 '최신 상태'."""
    ny_today = datetime.now(ZoneInfo("America/New_York")).date()
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO daily_prices (stock_id, trade_date, open, high, low, close, volume)
                             VALUES (3, :d, 200, 201, 199, 200, 500) ON CONFLICT DO NOTHING"""), {"d": ny_today})
    p = make_providers()
    assert jobs.load_prices(engine, p, tickers=["AAPL"]) == {"AAPL": "SUCCESS"}
    assert p.kr_price.calls == []
    assert scalar(engine, "SELECT error FROM ingestion_logs WHERE stock_id = 3 ORDER BY log_id DESC LIMIT 1") == "최신 상태"


def test_stock_refs_use_universe_yf_symbol(engine):
    """yfinance 대체 경로(PRICE_SOURCE_KR=yfinance)는 universe.yaml의 yf_symbol(.KS/.KQ)로 국내 종목을 받는다."""
    with engine.connect() as conn:
        refs = {r.ticker: r for r in jobs.stock_refs(conn)}
    assert refs["005930"].yf_symbol == "005930.KS" and refs["005930"].country == "KR"
    assert refs["AAPL"].yf_symbol == "AAPL" and refs["AAPL"].timezone == "America/New_York"


class YFPricesMissingError(Exception):
    """yfinance.exceptions.YFPricesMissingError와 같은 이름(클래스 이름으로 판별)."""


def test_yahoo_short_range_without_prices_is_holiday_not_failure(monkeypatch):
    calls = []

    class Ticker:
        def __init__(self, symbol):
            pass

        def history(self, **kw):
            calls.append(kw)
            raise YFPricesMissingError("Data doesn't exist")

    monkeypatch.setattr(yahoo, "_yf", lambda: SimpleNamespace(Ticker=Ticker))
    monkeypatch.setattr(yahoo, "_throttle", Throttle(0))
    monkeypatch.setattr(http, "BACKOFF_BASE", 0)
    holiday = date(2026, 11, 26)
    assert yahoo._history("AAPL", holiday, holiday, "America/New_York") == []
    assert len(calls) == 1                                               # 재시도 없음
    with pytest.raises(ProviderError):                                   # 긴 구간의 '데이터 없음'은 실패(상장폐지·심볼 오류)
        yahoo._history("AAPL", holiday - timedelta(days=30), holiday, "America/New_York")
