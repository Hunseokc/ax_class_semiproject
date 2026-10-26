"""데이터 유효기간(공시 일정 기반 + 90일 상한)·사업보고서 공시 시 만료, 미국 밸류에이션 = 기초값 × 종가,
국내 밸류에이션은 확정된 거래일까지만, 업종 섹터 매핑, 마이그레이션 006.

배당(dps·dividend_yield)은 Stage 6 migration 005와 함께 원본 검증을 붙인다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.ingest import jobs
from app.ingest.sectors import commodity_code, primary_theme, secondary_themes
from app.providers.base import ValuationBase
from app.providers.sec import annual_dps
from app.services import freshness
from app.services.freshness import SEOUL, financials_valid_until
from tests.conftest import D
from tests.fakes import FakeReference, make_providers

T0 = datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------ 유효기간 계산
@pytest.mark.parametrize("fy_end, fetched, expected", [
    # FY2025 사업보고서를 이미 받음 → 다음 보고서(FY2026)는 2027-04 → 90일 상한이 먼저 (stock_id 7 → 분산 0일)
    (date(2025, 12, 31), T0, T0 + timedelta(days=90)),
    # FY2024만 있음 → FY2025 사업보고서 예상일(2025-12-31 + 90일 + 7일 = 2026-04-07)이 상한보다 먼저
    (date(2024, 12, 31), T0, datetime(2026, 4, 7, tzinfo=SEOUL)),
    # 예상일이 지났는데 아직 FY2024뿐(제출 지연) → 7일 뒤 다시
    (date(2024, 12, 31), datetime(2026, 5, 1, tzinfo=timezone.utc), datetime(2026, 5, 8, tzinfo=timezone.utc)),
    # 재무가 하나도 없음 → 7일 뒤
    (None, T0, T0 + timedelta(days=7)),
])
def test_financials_valid_until_follows_filing_calendar(fy_end, fetched, expected):
    assert financials_valid_until("KR", fy_end, fetched, stock_id=7) == expected


def test_valid_until_is_staggered_by_stock():
    a = financials_valid_until("US", date(2025, 12, 31), T0, stock_id=1)
    b = financials_valid_until("US", date(2025, 12, 31), T0, stock_id=3)
    assert a == T0 + timedelta(days=89) and b == T0 + timedelta(days=87)    # 같은 날 받은 종목도 만료일이 흩어진다


def test_mark_due_and_failure_retry(engine):
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        assert freshness.due(conn, "financials", [1, 2], now) == [1, 2]                  # 기록 없음
        conn.execute(text("""INSERT INTO financial_statements (stock_id, period_end, period_type, data_source)
                             VALUES (1, :d, 'FY', 'DART')"""), {"d": date(now.year - 1, 12, 31)})
        u1 = freshness.mark(conn, "financials", 1, True, now=now)
        u2 = freshness.mark(conn, "financials", 2, False, error="boom", now=now)
        assert u1 > now + timedelta(days=30) and u2 == now + timedelta(days=1)           # 실패는 하루 뒤 재시도
        assert freshness.due(conn, "financials", [1, 2], now) == []
        assert freshness.due(conn, "financials", [1, 2], now + timedelta(days=2)) == [2]
        freshness.mark(conn, "disclosures", 1, True, now=now)
        assert freshness.due(conn, "disclosures", [1], now + timedelta(hours=23)) == []
        assert freshness.due(conn, "disclosures", [1], now + timedelta(hours=25)) == [1]   # 공시는 1일


def test_new_annual_report_expires_financials(engine):
    with engine.begin() as conn:
        freshness.mark(conn, "financials", 1, True, now=datetime.now(timezone.utc) - timedelta(hours=1))
        conn.execute(text("""INSERT INTO disclosures (stock_id, rcept_no, title, report_type, filed_at, data_source)
                             VALUES (1, 'r-old', '분기보고서 (2026.06)', '정기공시', now(), 'DART')"""))
        assert freshness.invalidate_on_annual_report(conn, 1) == 0                       # 분기보고서는 연간 재무와 무관
        conn.execute(text("""INSERT INTO disclosures (stock_id, rcept_no, title, report_type, filed_at, data_source)
                             VALUES (1, 'r-new', '사업보고서 (2025.12)', '정기공시', now(), 'DART')"""))
        assert freshness.invalidate_on_annual_report(conn, 1) == 1
        assert freshness.due(conn, "financials", [1]) == [1]


def test_load_financials_and_disclosures_record_freshness(engine):
    pv = make_providers(with_fundamentals=True)
    with engine.begin() as conn:
        conn.execute(text("UPDATE stocks SET corp_code = 'C' || ticker WHERE stock_id IN (1, 2)"))
    jobs.load_financials(engine, pv, stock_ids=[1])
    jobs.load_disclosures(engine, pv, stock_ids=[1])
    with engine.connect() as conn:
        rows = dict(conn.execute(text("SELECT kind, status FROM data_freshness WHERE stock_id = 1")).all())
    assert rows == {"financials": "SUCCESS", "disclosures": "SUCCESS"}


# ------------------------------------------------------------------ 미국 밸류에이션 = 기초값 × 종가
def test_us_valuation_is_derived_from_base_and_close(engine):
    pv = make_providers(with_fundamentals=True)
    pv.us_reference = FakeReference(bases={"AAPL": ValuationBase(shares_outstanding=1000, shares_as_of=D,
                                                                 dps=Decimal(2), dps_period_end=D)})
    with engine.begin() as conn:
        conn.execute(text("UPDATE stocks SET cik = '0000320193' WHERE stock_id = 3"))
    jobs.load_financials(engine, pv, stock_ids=[3])               # FY 순이익 9, 자본 100 (fake 최신 FY)
    with engine.connect() as conn:
        v = conn.execute(text("""SELECT per, pbr, eps, bps, market_cap, dps, source FROM valuation_snapshots
                                 WHERE stock_id = 3 AND as_of = :d"""), {"d": D}).mappings().one()
        base = conn.execute(text("SELECT shares_outstanding, dps FROM fundamental_bases WHERE stock_id = 3")).one()
    # 종가 200: EPS = 9/1000, PER = 200/0.009, BPS = 100/1000, PBR = 2000, 시총 = 200×1000
    assert v["source"] == "DERIVED" and v["eps"] == Decimal("0.009") and v["per"] == Decimal("22222.2222")
    assert v["bps"] == Decimal("0.1") and v["pbr"] == 2000 and v["market_cap"] == 200000
    assert tuple(base) == (1000, 2) and v["dps"] == 2             # 기초값의 주당 배당이 밸류에이션으로 옮겨진다
    calls = pv.us_valuation.count
    st = jobs.load_valuations(engine, pv, stock_ids=[3])          # 4시간 갱신 경로도 외부 호출 없이 계산
    assert st == {"AAPL": "SUCCESS"} and pv.us_valuation.count == calls


def test_valuation_keeps_dividend_per_share(engine):
    pv = make_providers()
    jobs.load_valuations(engine, pv, stock_ids=[1], full=True)    # 종목별 경로: provider의 dps를 그대로 저장
    with engine.connect() as conn:
        latest = conn.execute(text("""SELECT dps FROM valuation_snapshots WHERE stock_id = 1
                                      ORDER BY as_of DESC LIMIT 1""")).scalar()
        row = conn.execute(text("SELECT dps, dividend_yield FROM v_stock_metrics WHERE stock_id = 1")).one()
    assert latest == Decimal("1.5") and row.dps == Decimal("1.5") and row.dividend_yield is not None


def test_kr_valuation_requests_only_confirmed_days(engine):
    pv = make_providers()
    jobs.load_valuations(engine, pv, stock_ids=[1], full=True)
    _, _, end = pv.kr_valuation.calls[-1]
    assert end <= jobs.last_closed_day("KR")                      # KRX 공표 전 당일(0 → 빈 행)은 요청하지 않는다


def _dps(start, end, val, form="10-Q", filed="2026-08-01"):
    return {"start": start, "end": end, "val": val, "form": form, "filed": filed}


def test_annual_dps_prefers_fy_value_and_sums_four_quarters_otherwise():
    today = date(2026, 10, 19)
    quarters = [_dps("2025-09-29", "2025-12-31", 1.5, "10-K"), _dps("2026-01-01", "2026-04-05", 1.59),
                _dps("2026-04-06", "2026-07-05", 1.59), _dps("2025-06-30", "2025-09-28", 1.5),
                _dps("2026-01-01", "2026-07-05", 3.18),                       # 반기 누계는 분기가 아니다
                _dps("2026-04-06", "2026-07-05", 1.59, filed="2026-07-30")]   # 같은 분기 이전 제출본
    gaap = {"CommonStockDividendsPerShareDeclared": {"units": {"USD/shares": quarters}}}
    assert annual_dps(gaap, today) == (Decimal("6.18"), date(2026, 7, 5))     # 분기만 신고(GD): 최근 4개 분기 합
    gaap["CommonStockDividendsPerShareCashPaid"] = {"units": {"USD/shares": [
        _dps("2025-01-01", "2025-12-31", 5.8, "10-K")]}}
    assert annual_dps(gaap, today) == (Decimal("5.8"), date(2025, 12, 31))    # 1년치 값이 있으면 그 값
    assert annual_dps({"CommonStockDividendsPerShareCashPaid": {"units": {"USD/shares": [   # 2009년에 끊긴 분기 값
        _dps(f"2009-{m:02d}-01", f"2009-{m + 2:02d}-28", 0.3) for m in (1, 4, 7, 10) if m + 2 <= 12]}}}, today) == (None, None)
    assert annual_dps({}, today) == (None, None)


# ------------------------------------------------------------------ 테마 분류 (config/universe.yaml themes)
def _theme(country, ticker="X", ksic=None, sic=None):
    t = primary_theme(country, ticker, ksic, sic)
    return (t.name, t.sector) if t else None


def test_theme_uses_narrowest_sic_range_and_longest_ksic_prefix():
    assert _theme("US", sic=3674) == ("반도체", "반도체·전자")
    assert _theme("US", sic=3826)[0] == "의료기기·서비스"             # 3820-3829(기계·로봇)보다 좁은 범위가 이긴다
    assert _theme("US", sic=3334) == ("비철금속", "소재") and _theme("US", sic=3312)[0] == "철강"   # 알루미늄 ≠ 철강
    assert _theme("KR", ksic="29271")[0] == "반도체 장비·소재"         # '29'(기계)보다 긴 접두어가 이긴다
    assert _theme("KR", ksic="28202") == ("2차전지", "에너지·유틸리티")
    assert _theme("KR", ksic="70113") == ("바이오", "헬스케어")          # 신약 연구개발(KRX 업종은 '일반서비스')
    assert _theme("KR", ksic="64992") == ("지주회사", "산업재") and _theme("KR", ksic="64121")[0] == "은행·카드"
    assert _theme("US", sic=6798)[0] == "리츠·부동산" and _theme("US", sic=9999) is None and _theme("KR") is None


def test_theme_tickers_override_codes_and_secondary_themes():
    assert _theme("KR", "005930", ksic="264")[0] == "반도체"            # KSIC는 통신장비지만 직접 지정이 이긴다
    assert _theme("US", "AMZN", sic=5961)[0] == "빅테크"
    assert [t.name for t in secondary_themes("AMZN")] == ["유통·커머스", "소프트웨어·IT서비스"]
    assert _theme("KR", "105560", ksic="64992") == ("은행·카드", "금융")  # 금융지주는 지주회사가 아니라 은행


def test_commodity_code_prefers_ticker_then_theme():
    metals, battery = primary_theme("US", "X", sic=3334), primary_theme("KR", "X", ksic="28202")
    assert commodity_code(metals, "AA") == "ALUMINUM" and commodity_code(metals, "FCX") == "COPPER"
    assert battery.commodity_linked and commodity_code(battery, "373220") is None    # 연동이지만 무료 시세 없음(리튬)
    assert commodity_code(primary_theme("US", "X", sic=3674), "NVDA") is None and commodity_code(None, "X") is None


# ------------------------------------------------------------------ 마이그레이션
def test_migration_006_is_idempotent_and_removes_empty_valuations(engine):
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO valuation_snapshots (stock_id, as_of, source) VALUES (1, CURRENT_DATE, 'PYKRX')"""))
    for _ in range(2):
        jobs.migrate(engine, "006_sector_freshness")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM valuation_snapshots WHERE stock_id = 1 AND as_of = CURRENT_DATE")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM valuation_snapshots WHERE stock_id = 1")).scalar() == 1   # 정상 행은 유지
        cols = set(conn.execute(text("""SELECT column_name FROM information_schema.columns
                                        WHERE table_name IN ('stocks', 'peer_groups')""")).scalars())
    assert {"industry", "sic", "sector", "industry_checked_at", "kind"} <= cols
