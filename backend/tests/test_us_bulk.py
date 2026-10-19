"""미국 재무 일괄(SEC frames) — 결산일과 같은 날짜의 순간값만, 태그 우선순위, 임시 유효기간 (추가기능 API 정의서 8절, D8)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import text

from app.ingest.us_bulk import PROVISIONAL_TTL, load_us_bulk
from app.providers.sec_bulk import get_annual_financials_bulk
from app.services import freshness
from tests.conftest import scalar

A, B = "0000000201", "0000000202"     # A: 12월 결산, B: 6월 결산


class FakeFrames:
    """(개념, 기간) → frames data 목록."""

    def __init__(self, data: dict[tuple[str, str], list[dict]]):
        self.data, self.calls, self.asked = data, 0, []

    def frame(self, concept: str, period: str) -> list[dict]:
        self.calls += 1
        self.asked.append((concept, period))
        return self.data.get((concept, period), [])


def _d(cik, val, end, start=None):
    e = {"cik": int(cik), "val": val, "end": end}
    if start:
        e["start"] = start
    return e


def _frames():
    return FakeFrames({
        ("RevenueFromContractWithCustomerExcludingAssessedTax", "CY2025"): [_d(A, 1000, "2025-12-31", "2025-01-01")],
        ("Revenues", "CY2025"): [_d(A, 999, "2025-12-31", "2025-01-01"),                 # 우선순위 낮음 → 무시
                                 _d(B, 500, "2026-06-30", "2025-07-01")],
        ("NetIncomeLoss", "CY2025"): [_d(A, 100, "2025-12-31", "2025-01-01"), _d(B, 50, "2026-06-30", "2025-07-01"),
                                      _d(A, 7, "2025-12-31", "2025-10-01")],             # 분기(91일) → 무시
        ("Assets", "CY2025Q4I"): [_d(A, 5000, "2025-12-31")],
        ("Assets", "CY2026Q2I"): [_d(B, 800, "2026-06-30")],
        ("Assets", "CY2026Q1I"): [_d(B, 777, "2026-03-31")],                              # 결산일이 아닌 분기값 → 안 받음
        ("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "CY2025Q4I"): [_d(A, 2100, "2025-12-31")],
        ("Liabilities", "CY2025Q4I"): [_d(A, 2900, "2025-12-31")],
    })


def test_bulk_matches_fy_end_and_tag_priority():
    fr = _frames()
    fins = get_annual_financials_bulk({A, B}, 3, last_year=2026, frames=fr)
    a, b = fins[A][-1], fins[B][-1]
    assert (a.period_end, a.revenue, a.net_income, a.total_assets, a.total_equity, a.total_debt) == (
        date(2025, 12, 31), Decimal("1000.00"), Decimal("100.00"), Decimal("5000.00"), Decimal("2100.00"), Decimal("2900.00"))
    assert a.notes == ["total_equity←StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]
    assert (b.period_end, b.revenue, b.total_assets) == (date(2026, 6, 30), Decimal("500.00"), Decimal("800.00"))
    assert ("Assets", "CY2026Q1I") not in fr.asked                       # 결산일이 든 분기 frame만 받는다


def test_load_us_bulk_only_listed_without_record_and_provisional(engine):
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO stocks (stock_id, market_id, ticker, name, coverage, cik) VALUES
                             (201, 2, 'AAA', 'AAA', 'listed', :a), (202, 2, 'BBB', 'BBB', 'listed', :b),
                             (203, 2, 'CCC', 'CCC', 'listed', '0000000203')"""), {"a": A, "b": B})
        freshness.mark(conn, "financials", 203, True)                    # 이미 받은 종목은 대상 아님
    now = datetime.now(timezone.utc)
    out = load_us_bulk(engine, frames=_frames(), now=now)
    assert out["targets"] == 2 and out["companies"] == 2 and out["rows"] == 2
    until = scalar(engine, "SELECT valid_until FROM data_freshness WHERE stock_id = 201")
    assert abs((until - now) - PROVISIONAL_TTL) < timedelta(seconds=1)  # 7일 뒤 상세를 열면 회사별로 다시 받는다
    assert scalar(engine, "SELECT source FROM ingestion_logs WHERE job_type = 'FINANCIALS'") == "SEC_BULK"
    assert load_us_bulk(engine, frames=_frames())["targets"] == 0        # 기록이 생겨 다시 대상이 되지 않음
