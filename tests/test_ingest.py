"""수집·전처리: upsert 재실행 시 행 수 불변, 이상 행 격리, 재무 계정 매핑·보완."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.ingest import jobs
from app.ingest.preprocess import clean_bars, clean_fx
from app.providers.base import Bar, Financial, FxPoint
from app.providers.dart import DartClient
from tests.conftest import scalar
from tests.fakes import make_providers


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
    from zoneinfo import ZoneInfo
    now = datetime(2026, 3, 3, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))      # 장중
    ok, bad = clean_bars([bar(date(2026, 3, 2)), bar(date(2026, 3, 3))], "Asia/Seoul", require_volume=True, now=now)
    assert [b.trade_date for b in ok] == [date(2026, 3, 2)]
    assert bad[0].reason == "장 마감 전 미확정 봉"


def test_clean_fx_quarantines_spike():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    pts = [FxPoint(base + timedelta(days=i), Decimal(v)) for i, v in enumerate([1300, 1302, 1301, 13.01, 1303, 1304])]
    ok, bad = clean_fx(pts)
    assert Decimal("13.01") not in {p.usd_krw for p in ok} and len(ok) == 5
    assert "초과 이탈" in bad[0].reason


def test_dart_account_mapping_falls_back_to_account_name():
    rows = [
        {"sj_div": "CIS", "account_id": "-표준계정코드 미사용-", "account_nm": "Ⅰ. 영업수익", "thstrm_amount": "1,000"},
        {"sj_div": "CIS", "account_id": "dart_OperatingIncomeLoss", "account_nm": "영업이익", "thstrm_amount": "100"},
        {"sj_div": "CIS", "account_id": "ifrs-full_ProfitLoss", "account_nm": "당기순이익", "thstrm_amount": "80"},
        {"sj_div": "CIS", "account_id": "ifrs-full_ProfitLossAttributableToOwnersOfParent", "account_nm": "지배", "thstrm_amount": "70"},
        {"sj_div": "BS", "account_id": "ifrs-full_Assets", "account_nm": "자산총계", "thstrm_amount": "5000"},
        {"sj_div": "BS", "account_id": "ifrs-full_Equity", "account_nm": "자본총계", "thstrm_amount": "2000"},
        {"sj_div": "BS", "account_id": "x", "account_nm": "부채총계", "thstrm_amount": "3000"},
    ]
    vals, notes = DartClient._extract(rows, "thstrm_amount")
    assert vals == {"revenue": Decimal(1000), "operating_income": Decimal(100), "net_income": Decimal(70),
                    "total_assets": Decimal(5000), "total_equity": Decimal(2000), "total_debt": Decimal(3000)}
    assert "revenue←계정명:Ⅰ. 영업수익" in notes and "total_equity←ifrs-full_Equity" in notes


def test_merge_supplement_fills_only_missing_values():
    sec = [Financial(date(2025, 12, 31), "FY", revenue=Decimal(100), total_debt=None, data_source="SEC")]
    yf = [Financial(date(2025, 12, 31), "FY", revenue=Decimal(999), total_debt=Decimal(50), data_source="YFINANCE"),
          Financial(date(2021, 12, 31), "FY", revenue=Decimal(70), data_source="YFINANCE")]
    merged = jobs.merge_supplement(sec, yf)
    assert [(f.period_end.year, f.data_source) for f in merged] == [(2021, "YFINANCE"), (2025, "SEC")]
    assert merged[1].revenue == 100 and merged[1].total_debt == 50      # 주 소스 값 우선, 빈 값만 보완
    assert "total_debt←yfinance" in merged[1].notes
