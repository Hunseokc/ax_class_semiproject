"""재무 수집 한 경로·5년·분기·추가 계정 (수정 4 PR A — 검토_장부 D-033·D-039, 개발산출물/09 2절 '재무 수집').

- DART: 빈 해는 다음 해 사업보고서 전기값, 분기 손익은 3개월 칸·현금흐름은 누적 차이·4분기 = 연간 − 3분기 누적
- SEC: 10-Q 3개월 값(없으면 누적 차이)·4분기 = 연간 − 3분기 누적, 파트너십 자본, 20-F 기업
- 적재: 다시 받으면 이번 결과에 없는 옛 결산기를 지운다, 자본 0 처리(R4-9), 20-F 기업 재무 삭제
- sanity: DATA-dart-fy-path·DATA-sec-op-path·LP-equity-not-zero
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import httpx
from sqlalchemy import text

from app.ingest import jobs
from app.providers.base import Financial, ForeignFilerError, StockRef
from app.providers.dart import DartClient
from app.providers.sec import SecClient
from app.services.sanity import Data, rule_dart_fy_path, rule_lp_equity, rule_sec_op_path
from tests.conftest import scalar
from tests.fakes import make_providers

KR = StockRef(stock_id=1, market="KOSPI", country="KR", ticker="005930", yf_symbol="005930.KS", timezone="Asia/Seoul",
              corp_code="C1")


# ------------------------------------------------------------------ DART
def _line(sj: str, aid: str, nm: str, th=None, add=None, frm=None, rcept="20260310000001") -> dict:
    return {"sj_div": sj, "account_id": aid, "account_nm": nm, "thstrm_amount": th, "thstrm_add_amount": add,
            "frmtrm_amount": frm, "rcept_no": rcept, "currency": "KRW"}


def _report(rev, oi, ocf, assets, *, add_rev=None, add_oi=None, frm_rev=None, frm_oi=None, frm_assets=None,
            rcept="20260310000001", short_debt=None):
    """매출·영업이익(IS), 영업현금흐름(CF — 누적), 자산·부채·자본(BS), 순이익, 단기차입금(표준 코드 없음), 이자 지급(CF)."""
    rows = [_line("IS", "ifrs-full_Revenue", "매출액", rev, add_rev, frm_rev, rcept),
            _line("IS", "dart_OperatingIncomeLoss", "영업이익", oi, add_oi, frm_oi, rcept),
            _line("IS", "ifrs-full_ProfitLossAttributableToOwnersOfParent", "지배기업 소유주지분", oi, add_oi, frm_oi, rcept),
            _line("CF", "ifrs-full_CashFlowsFromUsedInOperatingActivities", "영업활동현금흐름", ocf, None, None, rcept),
            _line("CF", "ifrs-full_InterestPaidClassifiedAsOperatingActivities", "이자의 지급", "-7", None, None, rcept),
            _line("BS", "ifrs-full_Assets", "자산총계", assets, None, frm_assets, rcept),
            _line("BS", "ifrs-full_Liabilities", "부채총계", "100", None, "100" if frm_assets else None, rcept),
            _line("BS", "ifrs-full_EquityAttributableToOwnersOfParent", "지배기업 소유주지분", "300", None,
                  "300" if frm_assets else None, rcept)]
    if short_debt:
        rows.append(_line("BS", "-표준계정코드 미사용-", "단기차입금", short_debt, None, None, rcept))
        rows.append(_line("BS", "ifrs-full_NoncurrentPortionOfNoncurrentBondsIssued", "사채", "5", None, None, rcept))
    return rows


# (연도, 보고서) → 행. 2024 사업보고서는 없다(2025 상장) — 2025 보고서 전기값으로 FY2024가 생겨야 한다
REPORTS = {
    (2025, "11011"): _report("1000", "100", "90", "400", frm_rev="800", frm_oi="80", frm_assets="350",
                             short_debt="20"),
    (2025, "11013"): _report("200", "20", "15", "380", rcept="20250515000001"),
    (2025, "11012"): _report("250", "25", "40", "390", add_rev="450", add_oi="45", rcept="20250814000001"),
    (2025, "11014"): _report("260", "26", "70", "395", add_rev="710", add_oi="71", rcept="20251114000001"),
    (2026, "11013"): _report("300", "30", "33", "410", rcept="20260515000001"),
}


def _dart() -> tuple[DartClient, list]:
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        q = req.url.params
        calls.append((q["bsns_year"], q["reprt_code"], q["fs_div"]))
        rows = REPORTS.get((int(q["bsns_year"]), q["reprt_code"])) if q["fs_div"] == "CFS" else None
        return httpx.Response(200, json={"status": "000", "list": rows} if rows else {"status": "013"})
    return DartClient(api_key="k", http=httpx.Client(transport=httpx.MockTransport(handler))), calls


def test_dart_fills_missing_year_from_next_report_prior_period():
    d, _ = _dart()
    fins = d.get_annual_financials(KR, 5, last_year=2025)
    assert [f.period_end.year for f in fins] == [2024, 2025]
    f24, f25 = fins
    assert f24.revenue == 800 and f24.total_assets == 350               # 2025 보고서 전기(frmtrm) 값
    assert "전체←2025년 보고서 전기값" in f24.notes and f24.filed_at == date(2026, 3, 10)
    assert "직전 연도 없음(보고서·전기값 모두 없음)" in f24.notes       # 2023은 보고서·전기값 모두 없음
    assert f25.notes[0] == "path=DART_API" and f25.consolidated is True
    assert f25.borrowings == 25 and "borrowings=단기차입금+사채" in f25.notes   # 표준 코드 없는 단기차입금도 이름으로
    assert f25.interest_expense == 7                                   # 손익계산서에 없으면 현금흐름표 이자 지급액(크기)
    assert f25.operating_cf == 90


def test_dart_quarters_use_three_month_columns_cumulative_cash_flow_and_q4_from_annual():
    d, calls = _dart()
    d.get_annual_financials(KR, 5, last_year=2025)
    n_annual = len(calls)
    qs = d.get_quarterly_financials(KR, 20, last_year=2025)
    by = {(f.period_end, f.period_type): f for f in qs}
    q1, q2, q3, q4 = (by[(date(2025, m, 30 if m in (6, 9) else 31), f"Q{k}")] for k, m in ((1, 3), (2, 6), (3, 9), (4, 12)))
    assert (q1.revenue, q2.revenue, q3.revenue) == (200, 250, 260)    # 분기 손익 = 당기(3개월) 칸
    assert q4.revenue == 1000 - 710 and q4.operating_income == 100 - 71   # 4분기 = 연간 − 3분기 누적
    assert (q1.operating_cf, q2.operating_cf, q3.operating_cf, q4.operating_cf) == (15, 25, 30, 20)   # 누적 차이
    assert q2.total_assets == 390 and q4.total_assets == 400          # 재무상태표 = 분기 말
    assert q2.filed_at == date(2025, 8, 14) and "Q4=연간−3분기 누적" in q4.notes
    assert by[(date(2026, 3, 31), "Q1")].revenue == 300               # 올해 1분기
    # 첫 사업보고서(2025) 전 연도의 분기 보고서는 부르지 않는다, 사업보고서는 다시 부르지 않는다(받아 둔 것)
    q_calls = calls[n_annual:]
    assert all(int(y) >= 2025 for y, _, _ in q_calls) and not any(r == "11011" for _, r, _ in q_calls)


# ------------------------------------------------------------------ SEC
def _q(start: str, end: str, val, form="10-Q", filed=None) -> dict:
    return {"start": start, "end": end, "val": val, "form": form, "filed": filed or end}


def _i(end: str, val, form="10-Q") -> dict:
    return {"end": end, "val": val, "form": form, "filed": end}


LP, FOREIGN = "0000000010", "0000000020"
SEC_FACTS = {
    LP: {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [
            _q("2024-01-01", "2024-12-31", 400, "10-K", "2025-02-20"), _q("2025-01-01", "2025-12-31", 500, "10-K", "2026-02-20"),
            _q("2025-01-01", "2025-03-31", 110), _q("2025-04-01", "2025-06-30", 120), _q("2025-01-01", "2025-06-30", 230),
            _q("2025-07-01", "2025-09-30", 130), _q("2025-01-01", "2025-09-30", 360),
            _q("2026-01-01", "2026-03-31", 140)]}},
        "NetIncomeLoss": {"units": {"USD": [
            _q("2024-01-01", "2024-12-31", 40, "10-K", "2025-02-20"), _q("2025-01-01", "2025-12-31", 50, "10-K", "2026-02-20"),
            _q("2025-01-01", "2025-03-31", 11), _q("2025-04-01", "2025-06-30", 12), _q("2025-07-01", "2025-09-30", 13),
            _q("2026-01-01", "2026-03-31", 14)]}},
        "OperatingIncomeLoss": {"units": {"USD": [_q("2025-01-01", "2025-12-31", 70, "10-K"),
                                                  _q("2025-01-01", "2025-03-31", 15)]}},
        # 현금흐름은 누적(YTD)만
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
            _q("2025-01-01", "2025-12-31", 100, "10-K"), _q("2025-01-01", "2025-03-31", 20),
            _q("2025-01-01", "2025-06-30", 45), _q("2025-01-01", "2025-09-30", 75)]}},
        "Assets": {"units": {"USD": [_i("2024-12-31", 900, "10-K"), _i("2025-12-31", 1000, "10-K"), _i("2025-06-30", 950)]}},
        "LiabilitiesAndStockholdersEquity": {"units": {"USD": [_i("2025-12-31", 1000, "10-K")]}},
        # 파트너십: StockholdersEquity가 0으로 와도 신고하지 않은 것으로 보고 PartnersCapital을 쓴다(R4-9)
        "StockholdersEquity": {"units": {"USD": [_i("2025-12-31", 0, "10-K")]}},
        "PartnersCapital": {"units": {"USD": [_i("2025-12-31", 380, "10-K")]}},
        "PartnersCapitalIncludingPortionAttributableToNoncontrollingInterest": {"units": {"USD": [
            _i("2025-12-31", 400, "10-K")]}},
    }}},
    FOREIGN: {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"end": "2025-03-31", "val": 1, "form": "20-F", "filed": "2025-06-30"}]}}}, "us-gaap": {}}},
}


def _sec() -> SecClient:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SEC_FACTS[req.url.path.rsplit("CIK", 1)[1].removesuffix(".json")])
    return SecClient(user_agent="test test@example.com", http=httpx.Client(transport=httpx.MockTransport(handler)))


def _us(cik: str) -> StockRef:
    return StockRef(stock_id=3, market="NASDAQ", country="US", ticker="EPD", yf_symbol="EPD", timezone="America/New_York",
                    cik=cik)


def test_sec_partnership_equity_and_annual_path():
    fins = _sec().get_annual_financials(_us(LP), 5)
    f = fins[-1]
    assert f.total_equity == 380 and "total_equity←PartnersCapital" in f.notes      # 0이 아니라 파트너 자본
    assert f.total_debt == 600 and "total_debt←부채와자본총계−자본" in f.notes          # 1,000 − 비지배 포함 400
    assert f.notes[0] == "path=SEC_API" and f.filed_at == date(2026, 2, 20) and f.operating_cf == 100


def test_sec_quarters_three_month_values_cumulative_cash_flow_and_q4():
    qs = _sec().get_quarterly_financials(_us(LP), 20)
    by = {f.period_type + str(f.period_end): f for f in qs}
    assert [by[k].revenue for k in ("Q12025-03-31", "Q22025-06-30", "Q32025-09-30")] == [110, 120, 130]
    q4 = by["Q42025-12-31"]
    assert q4.revenue == 500 - 360 and "Q4=연간−3분기 누적" in q4.notes          # 연간 − 3분기 누적
    assert q4.net_income == 50 - 36                                              # 누적 사실이 없으면 3개월 합으로 누적
    assert [by[k].operating_cf for k in ("Q12025-03-31", "Q22025-06-30", "Q32025-09-30")] == [20, 25, 30]
    assert q4.operating_cf == 25 and by["Q22025-06-30"].total_assets == 950
    assert by["Q12026-03-31"].revenue == 140                                     # 진행 중인 회계연도


def test_sec_foreign_filer_raises():
    try:
        _sec().get_annual_financials(_us(FOREIGN), 5)
    except ForeignFilerError as e:
        assert "20-F" in str(e)
    else:
        raise AssertionError("20-F 기업은 ForeignFilerError")


# ------------------------------------------------------------------ 적재
class _Fin:
    """FY 2개 + 분기 2개를 주는 가짜 provider. foreign이면 ForeignFilerError."""
    source = "SEC"

    def __init__(self, foreign=False, equity=Decimal(30)):
        self.foreign, self.equity = foreign, equity

    def get_annual_financials(self, stock, years):
        if self.foreign:
            raise ForeignFilerError("20-F·40-F 제출 기업 — SEC 10-K 재무 없음(D-014)")
        return [Financial(date(y, 12, 31), "FY", revenue=Decimal(100), net_income=Decimal(10), total_assets=Decimal(90),
                          total_debt=Decimal(40), total_equity=self.equity, data_source="SEC", accounting_std="US-GAAP",
                          notes=["path=SEC_API"], filed_at=date(y + 1, 2, 1), consolidated=True) for y in (2024, 2025)]

    def get_quarterly_financials(self, stock, quarters):
        return [Financial(date(2025, m, 30), f"Q{k}", revenue=Decimal(25), total_assets=Decimal(90), data_source="SEC",
                          notes=["path=SEC_API"]) for k, m in ((2, 6), (3, 9))]


def _providers(fin):
    return replace(make_providers(), us_financial=fin, us_financial_supplement=None, us_reference=None)


def test_recollection_replaces_old_rows_and_stores_quarters_with_notes(engine):
    with engine.begin() as conn:
        conn.execute(text("UPDATE stocks SET cik = '0000000010' WHERE stock_id = 3"))
        conn.execute(text("""INSERT INTO financial_statements (stock_id, period_end, period_type, revenue, data_source)
                             VALUES (3, '2021-12-31', 'FY', 1, 'SEC'), (3, '2025-12-31', 'FY', 999, 'SEC')"""))
    assert jobs.load_financials(engine, _providers(_Fin()), years=5, stock_ids=[3]) == {"AAPL": "SUCCESS"}
    with engine.connect() as conn:
        rows = conn.execute(text("""SELECT period_type, period_end, revenue, notes, filed_at FROM financial_statements
                                    WHERE stock_id = 3 ORDER BY period_type, period_end""")).all()
    assert [(r.period_type, r.period_end.year, int(r.revenue)) for r in rows] == [
        ("FY", 2024, 100), ("FY", 2025, 100), ("Q2", 2025, 25), ("Q3", 2025, 25)]      # 옛 2021·999 행이 사라짐
    assert all(r.notes.startswith("path=SEC_API") for r in rows) and rows[0].filed_at == date(2025, 2, 1)
    assert "옛 행 1개 지움" in scalar(engine, "SELECT error FROM ingestion_logs WHERE job_type = 'FINANCIALS'")


def test_zero_equity_filled_from_assets_minus_liabilities_and_foreign_filer_rows_deleted(engine):
    with engine.begin() as conn:
        conn.execute(text("UPDATE stocks SET cik = '0000000010' WHERE stock_id = 3"))
    jobs.load_financials(engine, _providers(_Fin(equity=Decimal(0))), years=5, stock_ids=[3], quarters=0)
    assert scalar(engine, "SELECT total_equity FROM financial_statements WHERE stock_id = 3 AND period_end = '2025-12-31'") == 50
    assert "total_equity←자산−부채(신고값 0)" in scalar(engine, "SELECT notes FROM financial_statements WHERE stock_id = 3 LIMIT 1")
    # 20-F 기업: 성공으로 기록하고 남은 재무를 지운다(D-014 — 재무 정보가 없어 표기하지 않음)
    assert jobs.load_financials(engine, _providers(_Fin(foreign=True)), years=5, stock_ids=[3]) == {"AAPL": "SUCCESS"}
    assert scalar(engine, "SELECT count(*) FROM financial_statements WHERE stock_id = 3") == 0
    f = Financial(date(2025, 12, 31), "FY", total_equity=Decimal(0), total_assets=Decimal(5), total_debt=Decimal(5))
    jobs.fix_zero_equity(f)
    assert f.total_equity is None and "자본 정보 없음" in f.notes[-1]       # 채울 수 없으면 비운다


# ------------------------------------------------------------------ sanity
def test_sanity_data_path_rules(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO financial_statements (stock_id, period_end, period_type, total_assets, total_debt, total_equity,
                                              data_source, notes) VALUES
              (1, '2024-12-31', 'FY', 10, 4, 6, 'DART', 'path=DART_API; 전체←2025년 보고서 전기값; 직전 연도 없음(보고서·전기값 모두 없음)'),
              (1, '2025-12-31', 'FY', 10, 4, 6, 'DART', 'path=DART_API'),
              (2, '2021-12-31', 'FY', 10, 4, 6, 'DART', 'path=DART_API'),
              (2, '2022-12-31', 'FY', 10, 4, 6, 'DART', 'path=DART_API'),
              (2, '2023-12-31', 'FY', 10, 4, 6, 'DART', 'path=DART_API'),
              (2, '2025-12-31', 'FY', 10, 4, 6, 'DART', 'path=DART_API'),
              (3, '2025-12-31', 'FY', 10, 4, 6, 'SEC', 'path=SEC_API'),
              (4, '2025-12-31', 'FY', 10, 4, 0, 'SEC', NULL)"""))
    with engine.connect() as conn:
        d = Data(conn)
        ok, val = rule_dart_fy_path(d, {"ticker": ["005930"]})
        assert not ok and "사유 없이 빠진 해 1 ['000660 2024']" in val and "005930 FY [2024, 2025]" in val
        ok, val = rule_sec_op_path(d)
        assert not ok and "['NVDA']" in val                                    # 경로 기록 없는 옛 행
        ok, val = rule_lp_equity(d)
        assert not ok and "['NVDA']" in val                                    # 자본 0인데 자산 − 부채 6
