"""SEC 연간 재무 태그 보완 (D-010, 개발산출물/11 R1-6).

- 영업이익 태그가 없는 회사(CLX·EMN·GTX): 세전이익 + 이자비용(EBIT 근사)
- 부채 태그가 없는 회사(OSK): 부채와자본총계 − 자본(비지배 포함)
- 지배주주 순이익이 끊긴 회사(OSK·AEIS): ProfitLoss
- CIK가 바뀐 회사(XOM): 새 CIK에 없는 해를 이전 CIK(config ingest.sec_predecessor_cik)로 채운다
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx

from app.providers.base import StockRef
from app.providers.sec import SecClient, predecessor_cik

NEW_XOM, OLD_XOM, OTHER = "0002115436", "0000034088", "0000000001"


def _dur(end: str, val: float) -> dict:
    """12월 결산 1년치(10-K)."""
    y = int(end[:4])
    return {"start": f"{y}-01-01", "end": end, "val": val, "form": "10-K", "filed": f"{y + 1}-02-15"}


def _inst(end: str, val: float) -> dict:
    return {"end": end, "val": val, "form": "10-K", "filed": f"{int(end[:4]) + 1}-02-15"}


def _facts(**concepts) -> dict:
    return {"facts": {"us-gaap": {c: {"units": {"USD": rows}} for c, rows in concepts.items()}}}


FACTS = {
    NEW_XOM: {"facts": {}},                                         # 재편 직후: 재무 사실 없음
    OLD_XOM: _facts(Revenues=[_dur("2024-12-31", 300), _dur("2025-12-31", 320)],
                    OperatingIncomeLoss=[_dur("2024-12-31", 40), _dur("2025-12-31", 45)],
                    NetIncomeLoss=[_dur("2024-12-31", 30), _dur("2025-12-31", 33)],
                    Assets=[_inst("2024-12-31", 400), _inst("2025-12-31", 420)],
                    StockholdersEquity=[_inst("2024-12-31", 250), _inst("2025-12-31", 260)],
                    Liabilities=[_inst("2024-12-31", 150), _inst("2025-12-31", 160)]),
    OTHER: _facts(Revenues=[_dur("2025-12-31", 100)],
                  IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest=[_dur("2025-12-31", 12)],
                  InterestExpense=[_dur("2025-12-31", 3)],
                  ProfitLoss=[_dur("2025-12-31", 9)],
                  Assets=[_inst("2025-12-31", 200)],
                  StockholdersEquity=[_inst("2025-12-31", 70)],
                  StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest=[_inst("2025-12-31", 80)],
                  LiabilitiesAndStockholdersEquity=[_inst("2025-12-31", 200)]),
}


def _client() -> SecClient:
    def handler(req: httpx.Request) -> httpx.Response:
        cik = req.url.path.rsplit("CIK", 1)[1].removesuffix(".json")
        return httpx.Response(200, json=FACTS[cik])
    return SecClient(user_agent="test test@example.com", http=httpx.Client(transport=httpx.MockTransport(handler)))


def _ref(ticker: str, cik: str) -> StockRef:
    return StockRef(stock_id=1, market="NYSE", country="US", ticker=ticker, yf_symbol=ticker, timezone="America/New_York",
                    cik=cik)


def test_missing_operating_income_and_liabilities_are_derived():
    (f,) = _client().get_annual_financials(_ref("CLX", OTHER), 3)
    assert f.period_end == date(2025, 12, 31)
    assert f.operating_income == Decimal(15)                       # 세전이익 12 + 이자비용 3
    assert f.net_income == Decimal(9)                              # NetIncomeLoss 없음 → ProfitLoss
    assert f.total_debt == Decimal(120)                            # 부채와자본총계 200 − 자본(비지배 포함) 80
    assert {"operating_income←세전이익+이자비용", "net_income←ProfitLoss", "total_debt←부채와자본총계−자본"} <= set(f.notes)


def test_predecessor_cik_fills_years_missing_under_new_cik():
    assert predecessor_cik("XOM") == OLD_XOM and predecessor_cik("CLX") is None
    fins = _client().get_annual_financials(_ref("XOM", NEW_XOM), 3)
    assert [f.period_end for f in fins] == [date(2024, 12, 31), date(2025, 12, 31)]
    assert fins[-1].operating_income == Decimal(45) and fins[-1].total_debt == Decimal(160)
    assert not any(n.startswith(("operating_income←", "total_debt←")) for n in fins[-1].notes)   # 계산으로 채우지 않음
