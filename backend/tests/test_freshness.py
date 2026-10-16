"""데이터 유효기간(공시 일정 기반 + 90일 상한)·사업보고서 공시 시 만료, 국내 밸류에이션은 확정된 거래일까지만, 마이그레이션 006.

미국 밸류에이션 = 기초값 × 종가, 업종 섹터 매핑은 업종 섹터 작업(sectors.py·us_reference)과 함께 원본 test_freshness에서 옮긴다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.ingest import jobs
from app.services import freshness
from app.services.freshness import SEOUL, financials_valid_until
from tests.fakes import make_providers

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


def test_kr_valuation_requests_only_confirmed_days(engine):
    pv = make_providers()
    jobs.load_valuations(engine, pv, stock_ids=[1], full=True)
    _, _, end = pv.kr_valuation.calls[-1]
    assert end <= jobs.last_closed_day("KR")                      # KRX 공표 전 당일(0 → 빈 행)은 요청하지 않는다


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
