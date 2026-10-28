"""SEC EDGAR: 티커→CIK, 연간 재무(companyfacts), 공시 목록(submissions).

API 키는 없고 연락처(이메일)가 포함된 User-Agent가 필수다(ASSUMPTIONS A-16).
SEC 권고(초당 10건 이하)보다 보수적으로 초당 약 4건으로 제한한다.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal

import httpx

from app.core.config import get_settings
from app.providers.base import (Disclosure, Financial, ForeignFilerError, Listing, ProviderError, StockRef,
                                ValuationBase)
from app.providers.convert import to_dec
from app.providers.http import Throttle, call_with_retry

log = logging.getLogger(__name__)
_throttle = Throttle(0.25)

# 수집 대상 서식 (Form 4 등 내부자 지분 보고 제외 — DART 지분공시 제외와 같은 기준)
FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A", "DEF 14A", "S-3", "S-3ASR", "S-8", "SD", "11-K"}

# (컬럼, 우선순위 개념 목록, 기간형 여부)
CONCEPTS: list[tuple[str, tuple[str, ...], bool]] = [
    ("revenue", ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                 "RevenueFromContractWithCustomerIncludingAssessedTax"), True),
    ("operating_income", ("OperatingIncomeLoss",), True),
    # 지배주주 순이익 우선. 비지배 포함 순이익(ProfitLoss)은 지배주주 값을 신고하지 않는 해만(OSK·AEIS — D-010)
    ("net_income", ("NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss"), True),
    ("total_assets", ("Assets",), False),
    # 파트너십(EPD)은 StockholdersEquity 대신 PartnersCapital로 신고한다(R4-9). 비지배 포함 값은 지배 값이 없을 때만
    ("total_equity", ("StockholdersEquity", "PartnersCapital",
                      "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                      "PartnersCapitalIncludingPortionAttributableToNoncontrollingInterest"), False),
    ("total_debt", ("Liabilities",), False),
]
# 기본 개념이 없을 때 계산으로 채우는 데 쓰는 보조 개념 (derive_missing, D-010 — CLX·EMN·GTX는 영업이익 태그가 없다)
AUX_CONCEPTS: list[tuple[str, tuple[str, ...], bool]] = [
    ("pretax", ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"), True),
    ("interest", ("InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt", "InterestAndDebtExpense"), True),
    ("liabilities_and_equity", ("LiabilitiesAndStockholdersEquity",), False),
    ("equity_with_nci", ("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                         "PartnersCapitalIncludingPortionAttributableToNoncontrollingInterest"), False),
]
# 수정 4(D-033) 추가 계정 — 점수에는 아직 쓰지 않는다(측정 라운드 M1 입력). 대체 개념 순서는 CONCEPTS와 같은 방식
EXTRA_CONCEPTS: list[tuple[str, tuple[str, ...], bool]] = [
    ("operating_cf", ("NetCashProvidedByUsedInOperatingActivities",
                      "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"), True),
    ("comprehensive_income", ("ComprehensiveIncomeNetOfTax",
                              "ComprehensiveIncomeNetOfTaxIncludingPortionAttributableToNoncontrollingInterest"), True),
    ("equity_method_income", ("IncomeLossFromEquityMethodInvestments",), True),
    ("cash", ("CashAndCashEquivalentsAtCarryingValue",
              "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"), False),
    ("goodwill", ("Goodwill",), False),
    ("interest_expense", ("InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt",
                          "InterestAndDebtExpense"), True),
    ("nci_net_income", ("NetIncomeLossAttributableToNoncontrollingInterest",), True),
]
# 합계로 만드는 추가 계정의 재료(derive_extra): 무형자산(영업권 포함), 차입금·사채(리스부채 제외)
PART_CONCEPTS: list[tuple[str, tuple[str, ...], bool]] = [
    ("intangibles_total", ("IntangibleAssetsNetIncludingGoodwill",), False),
    ("intangibles_other", ("IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet"), False),
    ("ltd_total", ("LongTermDebt",), False),
    ("ltd_noncurrent", ("LongTermDebtNoncurrent",), False),
    ("ltd_current", ("LongTermDebtCurrent",), False),
    ("short_debt", ("ShortTermBorrowings", "CommercialPaper"), False),
]
ANNUAL_FORMS = {"10-K", "10-K/A"}
QUARTER_FORMS = {"10-Q", "10-Q/A", "10-K", "10-K/A"}
FOREIGN_FORMS = {"20-F", "20-F/A", "40-F", "40-F/A"}     # 해외 기업 연차 보고서 — 재무를 받지 않는다(D-014)


def derive_missing(vals: dict, aux: dict, notes: list[str]) -> None:
    """기본 개념이 비었을 때만 채운다(제자리 수정).
    영업이익 ≈ 세전이익 + 이자비용(EBIT 근사 — 영업외 손익이 섞인다), 부채 = 부채와자본총계 − 자본(비지배 포함)."""
    if vals.get("operating_income") is None and aux.get("pretax") is not None:
        interest = aux.get("interest")
        vals["operating_income"] = aux["pretax"] + (interest or 0)
        notes.append("operating_income←세전이익+이자비용" if interest is not None else "operating_income←세전이익")
    equity = aux.get("equity_with_nci") if aux.get("equity_with_nci") is not None else vals.get("total_equity")
    if vals.get("total_debt") is None and aux.get("liabilities_and_equity") is not None and equity is not None:
        vals["total_debt"] = aux["liabilities_and_equity"] - equity
        notes.append("total_debt←부채와자본총계−자본")


def derive_extra(vals: dict, parts: dict, notes: list[str]) -> None:
    """추가 계정 합계(제자리 수정). 무형자산 = 영업권 포함 합계(없으면 영업권 + 영업권 외 무형자산),
    차입금·사채 = 장기부채(유동 포함 — 없으면 비유동 + 유동) + 단기차입금(없으면 기업어음)."""
    if parts.get("intangibles_total") is not None:
        vals["intangibles"] = parts["intangibles_total"]
    elif parts.get("intangibles_other") is not None or vals.get("goodwill") is not None:
        vals["intangibles"] = (parts.get("intangibles_other") or 0) + (vals.get("goodwill") or 0)
        notes.append("intangibles←영업권+영업권 외 무형자산")
    long, how = parts.get("ltd_total"), ["LongTermDebt"]
    if long is None and (parts.get("ltd_noncurrent") is not None or parts.get("ltd_current") is not None):
        long = (parts.get("ltd_noncurrent") or 0) + (parts.get("ltd_current") or 0)
        how = [c for c in ("LongTermDebtNoncurrent", "LongTermDebtCurrent")
               if parts.get("ltd_" + c.removeprefix("LongTermDebt").lower()) is not None]
    short = parts.get("short_debt")
    if long is not None or short is not None:
        vals["borrowings"] = (long or 0) + (short or 0)
        notes.append("borrowings=" + "+".join((how if long is not None else []) + (["단기차입금"] if short is not None else [])))


def predecessor_cik(ticker: str) -> str | None:
    """지주사 재편 등으로 CIK가 바뀐 종목의 이전 CIK(config/universe.yaml ingest.sec_predecessor_cik). 새 CIK에 없는 해를 채운다."""
    from app.ingest.universe import load_universe     # 순환 import 방지
    v = (load_universe().ingest.get("sec_predecessor_cik") or {}).get(ticker)
    return str(v).zfill(10) if v else None

# 상장 보통주 목록 필터 (company_tickers_exchange.json)
EXCHANGES = {"Nasdaq": "NASDAQ", "NYSE": "NYSE"}               # OTC·CBOE 등은 제외
COMMON_TICKER = re.compile(r"^[A-Z]{1,5}(-[A-OQ-Z])?$")         # BRK-B·MOG-A 허용, 우선주(-P·-PA)·워런트(-WT)·유닛(-UN) 제외
NASDAQ_5TH_NON_COMMON = set("MNOPQRTUVWXZ")                     # 나스닥 5번째 글자: 우선주·권리·유닛·워런트 등(L·Y·A·B는 보통주)
NON_COMMON_NAME = re.compile(r"\bETF\b|\bETN\b|\bFUND\b|\bACQUISITION\b", re.I)   # ETF·펀드·스팩


def is_common_us(ticker: str, name: str) -> bool:
    if not COMMON_TICKER.match(ticker) or NON_COMMON_NAME.search(name):
        return False
    return not (len(ticker) == 5 and ticker[-1] in NASDAQ_5TH_NON_COMMON)


DPS_CONCEPTS = ("CommonStockDividendsPerShareDeclared", "CommonStockDividendsPerShareCashPaid")


def _days(e: dict) -> int:
    return (date.fromisoformat(e["end"]) - date.fromisoformat(e["start"])).days


def annual_dps(gaap: dict, today: date | None = None) -> tuple[Decimal | None, date | None]:
    """최근 FY 주당 배당(선언 기준 우선) → (금액, 기간 끝).

    1) 10-K의 1년(350~380일) 값. 2) 없으면 분기(85~100일)로만 신고하는 회사(GD·CRM 등):
    겹치지 않게 이어지는 최근 4개 분기를 더한다. 4개 분기가 1년(350~380일)을 덮고, 마지막 분기가
    400일 안이어야 한다(오래전에 끊긴 값을 지금 배당으로 쓰지 않는다)."""
    today = today or date.today()
    rows_of = {c: [e for e in gaap.get(c, {}).get("units", {}).get("USD/shares", []) if "start" in e and "val" in e]
               for c in DPS_CONCEPTS}
    for rows in rows_of.values():
        annual = [e for e in rows if e.get("form") in ANNUAL_FORMS and 350 <= _days(e) <= 380]
        if annual:
            best = max(annual, key=lambda e: (e["end"], e.get("filed", "")))
            return to_dec(best["val"], 4), date.fromisoformat(best["end"])
    for rows in rows_of.values():
        latest: dict[tuple[str, str], dict] = {}                   # 같은 분기가 10-Q·10-K에 거듭 나오면 최신 제출본
        for e in rows:
            if 85 <= _days(e) <= 100:
                key = (e["start"], e["end"])
                if key not in latest or e.get("filed", "") > latest[key].get("filed", ""):
                    latest[key] = e
        picked: list[dict] = []
        for e in sorted(latest.values(), key=lambda e: e["end"], reverse=True):
            if not picked or e["end"] < picked[-1]["start"]:
                picked.append(e)
            if len(picked) == 4:
                break
        if len(picked) < 4:
            continue
        end, start = date.fromisoformat(picked[0]["end"]), date.fromisoformat(picked[-1]["start"])
        if 350 <= (end - start).days <= 380 and (today - end).days <= 400:
            return to_dec(sum(Decimal(str(e["val"])) for e in picked), 4), end
    return None, None


class SecClient:
    """FinancialProvider + DisclosureProvider (US)."""
    source = "SEC"

    def __init__(self, user_agent: str | None = None, http: httpx.Client | None = None):
        ua = user_agent or get_settings().sec_user_agent
        if not ua or "@" not in ua:
            raise ProviderError("SEC_USER_AGENT에 연락처(이메일)가 필요합니다")
        self.http = http or httpx.Client(timeout=60, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})
        self._facts_cache: dict[str, dict] = {}

    def _json(self, url: str) -> dict:
        def call():
            r = self.http.get(url)
            r.raise_for_status()
            return r.json()
        return call_with_retry(call, throttle=_throttle, what=f"SEC {url.rsplit('/', 1)[-1]}")

    def ciks(self, tickers: set[str]) -> dict[str, str]:
        data = self._json("https://www.sec.gov/files/company_tickers.json")
        return {v["ticker"]: str(v["cik_str"]).zfill(10) for v in data.values() if v["ticker"] in tickers}

    # ------------------------------------------------------------ 재무
    def _facts(self, cik: str) -> dict:
        """companyfacts는 재무와 기초값이 같은 응답이라, 바로 이어지는 두 번째 요청에는 받아 둔 것을 쓴다."""
        hit = self._facts_cache.get(cik)
        if hit is None:
            hit = self._json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
            if len(self._facts_cache) >= 2:                  # 지금 CIK + 이전 CIK까지만 들고 있는다
                self._facts_cache = {}
            self._facts_cache[cik] = hit
        return hit

    def _gaaps(self, stock: StockRef) -> list[dict]:
        """us-gaap 사실 묶음(우선순위 순). 이전 CIK가 설정돼 있으면 뒤에 붙여 새 CIK에 없는 해만 채운다(XOM — D-010)."""
        out = [self._facts(stock.cik).get("facts", {}).get("us-gaap", {})]
        old = predecessor_cik(stock.ticker)
        if old and old != stock.cik:
            out.append(self._facts(old).get("facts", {}).get("us-gaap", {}))
        return out

    # ── [S5-D] 시장 전체 발행주식수·업종·기초값 ──
    def _frame(self, concept: str, period: str) -> list[dict]:
        """frames API 1회 = 그 기간 시장 전체 값. 아직 없는 기간(404)은 재시도 없이 빈 목록."""
        def call():
            r = self.http.get(f"https://data.sec.gov/api/xbrl/frames/{concept}/shares/{period}.json")
            if r.status_code == 404:
                return {"data": []}
            r.raise_for_status()
            return r.json()
        return call_with_retry(call, throttle=_throttle, what=f"SEC frame {concept} {period}").get("data", [])

    def get_listed_stocks(self, as_of: date) -> list[Listing]:
        """NASDAQ·NYSE 보통주 목록(SEC 등록 회사, CIK 포함). as_of는 인터페이스 공통 인자(현재 목록만 제공)."""
        d = self._json("https://www.sec.gov/files/company_tickers_exchange.json")
        idx = {f: i for i, f in enumerate(d["fields"])}
        out, seen = [], set()
        for r in d["data"]:
            ticker, name, ex = r[idx["ticker"]], r[idx["name"]], r[idx["exchange"]]
            if ex not in EXCHANGES or not ticker or not name or ticker in seen or not is_common_us(ticker, name):
                continue
            seen.add(ticker)
            out.append(Listing(market=EXCHANGES[ex], ticker=ticker, name=name, name_en=name,
                               cik=str(r[idx["cik"]]).zfill(10)))
        return out

    def get_shares_frame(self, as_of: date) -> dict[str, int]:
        """CIK → 발행주식수. 끝난 분기부터 3개 분기를 거슬러 가며 표지 기재값(dei)으로 채우고,
        dei가 없는 회사(주식 종류별로만 기재 — 예: Alphabet)는 재무상태표 발행주식수(us-gaap)로 채운다(호출 최대 6회)."""
        out: dict[str, int] = {}
        y, q = as_of.year, (as_of.month - 1) // 3          # 끝난 분기
        if q == 0:
            y, q = y - 1, 4
        periods = []
        for _ in range(3):
            periods.append(f"CY{y}Q{q}I")
            y, q = (y, q - 1) if q > 1 else (y - 1, 4)
        for concept in ("dei/EntityCommonStockSharesOutstanding", "us-gaap/CommonStockSharesOutstanding"):
            for period in periods:
                for r in self._frame(concept, period):
                    if r.get("val"):
                        out.setdefault(str(r["cik"]).zfill(10), int(r["val"]))
        return out

    def files_us_reports(self, cik: str) -> bool:
        """10-K·10-Q를 내는 회사인가(submissions 최근 공시 서식). 20-F·40-F만 내는 해외 기업은 재무를 받지 않아(D-014)
        미국 시가총액 순위에서 뺀다(수정 4 — 발행주식수가 비는 회사). 조회에 실패하면 True(빼지 않음)."""
        try:
            forms = set(self._json(f"https://data.sec.gov/submissions/CIK{cik}.json")["filings"]["recent"]["form"])
        except (ProviderError, KeyError) as e:
            log.warning("submissions 실패 %s: %s", cik, e)
            return True
        return bool(forms & (ANNUAL_FORMS | QUARTER_FORMS))

    def get_sic(self, cik: str) -> tuple[int | None, str | None]:
        d = self._json(f"https://data.sec.gov/submissions/CIK{cik}.json")
        sic = d.get("sic")
        return (int(sic) if str(sic or "").isdigit() else None), (d.get("sicDescription") or None)

    def get_valuation_base(self, stock: StockRef) -> ValuationBase:
        """발행주식수(표지 기재값, 같은 날짜의 여러 주식 종류는 합산)와 최근 FY 주당 배당(선언 기준)."""
        facts = self._facts(stock.cik).get("facts", {})
        by_end: dict[str, dict[str, int]] = {}
        for e in facts.get("dei", {}).get("EntityCommonStockSharesOutstanding", {}).get("units", {}).get("shares", []):
            by_end.setdefault(e["end"], {})[e.get("accn", "")] = by_end.get(e["end"], {}).get(e.get("accn", ""), 0) + int(e["val"])
        shares = shares_as_of = None
        if by_end:
            end = max(by_end)
            shares, shares_as_of = max(by_end[end].values()), date.fromisoformat(end)
        else:                               # 표지 값이 없으면(주식 종류별 기재) 재무상태표 발행주식수
            rows = facts.get("us-gaap", {}).get("CommonStockSharesOutstanding", {}).get("units", {}).get("shares", [])
            if rows:
                best = max(rows, key=lambda e: (e["end"], e.get("filed", "")))
                shares, shares_as_of = int(best["val"]), date.fromisoformat(best["end"])
        dps, dps_end = None, None
        for gaap in self._gaaps(stock):                     # 새 CIK에 배당이 없으면 이전 CIK
            dps, dps_end = annual_dps(gaap)
            if dps is not None:
                break
        return ValuationBase(shares_outstanding=shares if shares and shares > 0 else None, shares_as_of=shares_as_of,
                             dps=dps if dps is None or dps >= 0 else None, dps_period_end=dps_end)

    def _collect(self, gaaps: list[dict], concept: str, forms: set[str]) -> dict[tuple[str | None, str], tuple[Decimal, str, str]]:
        """(start, end) → (값, 최근 제출일, 처음 제출일). 같은 기간은 가장 최근 제출값(재작성 반영)이고, 처음 제출일은 그 기간
        값이 처음 공시된 날이다(D-033 — 신호 유효 시점). 이전 CIK(gaaps[1:])는 앞 묶음에 없는 기간만 채운다."""
        out: dict[tuple[str | None, str], tuple[Decimal, str, str]] = {}
        for gaap in gaaps:
            mine: dict[tuple[str | None, str], tuple[Decimal, str, str]] = {}
            for e in gaap.get(concept, {}).get("units", {}).get("USD", []):
                if e.get("form") not in forms or "end" not in e:
                    continue
                v = to_dec(e.get("val"), 2)
                if v is None:
                    continue
                key, filed = (e.get("start"), e["end"]), e.get("filed", "")
                old = mine.get(key)
                if old is None:
                    mine[key] = (v, filed, filed)
                else:
                    mine[key] = (v if filed > old[1] else old[0], max(filed, old[1]), min(filed, old[2]))
            for key, val in mine.items():
                out.setdefault(key, val)
        return out

    def _foreign(self, stock: StockRef) -> bool:
        """10-K·10-Q 없이 20-F·40-F만 낸 회사(SEC 표지 dei 포함 모든 사실의 서식으로 판정)."""
        forms: set[str] = set()
        for tax in self._facts(stock.cik).get("facts", {}).values():
            for c in tax.values():
                for rows in c.get("units", {}).values():
                    forms.update(e.get("form") for e in rows)
        return bool(forms & FOREIGN_FORMS) and not forms & (ANNUAL_FORMS | QUARTER_FORMS)

    def _by_period(self, gaaps: list[dict], forms: set[str]) -> dict[str, dict]:
        """컬럼마다 기간형은 {(start, end): 값}, 순간형은 {end: 값} — 개념 우선순위 순서로 채움(먼저 나온 개념이 이김).
        자본이 정확히 0인 값은 신고하지 않은 것으로 본다(파트너십 — R4-9). '처음 제출일'은 매출·순이익 기준(결산일별)."""
        vals: dict[str, dict] = {}
        first: dict[str, str] = {}
        for col, concepts, duration in CONCEPTS + EXTRA_CONCEPTS + AUX_CONCEPTS + PART_CONCEPTS:
            vals[col] = {}
            for c in concepts:
                for (start, end), (v, _, f0) in self._collect(gaaps, c, forms).items():
                    if duration != (start is not None) or (col == "total_equity" and v == 0):
                        continue
                    vals[col].setdefault((start, end) if duration else end, (v, c))
                    if col in ("revenue", "net_income") and f0:
                        first[end] = min(first.get(end, f0), f0)
        vals["_first"] = first
        return vals

    @staticmethod
    def _row(get: Callable[[str], tuple[Decimal, str] | None], notes: list[str]) -> dict:
        """컬럼별 (값, 개념) 조회 함수 → Financial 칸. 기본 개념이 아니면 notes에 남기고 비어 있는 칸은 파생 계산."""
        vals: dict = {}
        for col, concepts, _ in CONCEPTS + EXTRA_CONCEPTS:
            hit = get(col)
            vals[col] = hit[0] if hit else None
            if hit and hit[1] != concepts[0]:
                notes.append(f"{col}←{hit[1]}")
        aux = {col: (get(col) or (None,))[0] for col, _, _ in AUX_CONCEPTS + PART_CONCEPTS}
        derive_missing(vals, aux, notes)
        derive_extra(vals, aux, notes)
        return vals

    def get_annual_financials(self, stock: StockRef, years: int) -> list[Financial]:
        """10-K FY years개(기간형은 350~380일 — 52/53주 회계연도 허용). 20-F·40-F만 내는 회사는 ForeignFilerError(D-014)."""
        p = self._by_period(self._gaaps(stock), ANNUAL_FORMS)
        fy: dict[str, dict[date, tuple[Decimal, str]]] = {}
        for col, _, duration in CONCEPTS + EXTRA_CONCEPTS + AUX_CONCEPTS + PART_CONCEPTS:
            fy[col] = {}
            for key, hit in p[col].items():
                if duration:
                    start, end = key
                    if not 350 <= (date.fromisoformat(end) - date.fromisoformat(start)).days <= 380:
                        continue
                else:
                    end = key
                fy[col].setdefault(date.fromisoformat(end), hit)
        # 회계연도 결산일 = 연간 순이익/매출이 있는 결산일
        fy_ends = sorted(set(fy["net_income"]) | set(fy["revenue"]))[-years:]
        if not fy_ends and self._foreign(stock):
            raise ForeignFilerError("20-F·40-F 제출 기업 — SEC 10-K 재무 없음(D-014)")
        out = []
        for end in fy_ends:
            notes = ["path=SEC_API"]
            vals = self._row(lambda col: fy[col].get(end), notes)
            filed = p["_first"].get(end.isoformat())
            out.append(Financial(period_end=end, period_type="FY", data_source="SEC", accounting_std="US-GAAP",
                                 notes=notes, filed_at=date.fromisoformat(filed) if filed else None, consolidated=True,
                                 **vals))
        return out

    def get_quarterly_financials(self, stock: StockRef, quarters: int) -> list[Financial]:
        """최근 quarters개 분기(3개월치, D-033). 10-Q의 3개월 값(85~100일), 없으면 회계연도 시작부터의 누적 차이,
        4분기 = 10-K 연간 − 3분기 누적. 재무상태표 값은 분기 말. 회계연도 경계는 10-K 결산일로 정한다."""
        p = self._by_period(self._gaaps(stock), QUARTER_FORMS)
        cols = CONCEPTS + EXTRA_CONCEPTS + AUX_CONCEPTS + PART_CONCEPTS
        d = date.fromisoformat
        annual: dict[str, dict[date, tuple[Decimal, str]]] = {}
        three: dict[str, dict[date, tuple[Decimal, str]]] = {}
        ytd: dict[str, dict[tuple[date, date], tuple[Decimal, str]]] = {}
        inst: dict[str, dict[date, tuple[Decimal, str]]] = {}
        for col, _, duration in cols:
            annual[col], three[col], ytd[col], inst[col] = {}, {}, {}, {}
            for key, hit in p[col].items():
                if not duration:
                    inst[col].setdefault(d(key), hit)
                    continue
                s, e = d(key[0]), d(key[1])
                days = (e - s).days
                if 350 <= days <= 380:
                    annual[col].setdefault(e, hit)
                elif 85 <= days <= 100:
                    three[col].setdefault(e, hit)
                elif 150 <= days < 350:
                    ytd[col].setdefault((s, e), hit)
        fy_ends = sorted(set(annual["net_income"]) | set(annual["revenue"]))
        if not fy_ends:
            return []
        spans = []                                       # (회계연도 시작, 결산일, 결산일이 확정된 해인가)
        for i, end in enumerate(fy_ends):
            prev = fy_ends[i - 1] if i else None
            start = prev + timedelta(days=1) if prev and 350 <= (end - prev).days <= 380 else end - timedelta(days=364)
            spans.append((start, end, True))
        spans.append((fy_ends[-1] + timedelta(days=1), fy_ends[-1] + timedelta(days=371), False))   # 진행 중인 회계연도
        out: list[Financial] = []
        for start, end, closed in spans:
            ends = {e for c in ("revenue", "net_income") for e in three[c] if start < e < end - timedelta(days=20)}
            ends |= {e for c in ("revenue", "net_income") for (s, e) in ytd[c]
                     if abs((s - start).days) <= 7 and start < e < end - timedelta(days=20)}
            qs = {min(3, max(1, round((e - start).days / 91.3))): e for e in sorted(ends)}
            if closed:
                qs[4] = end
            cum_prev: dict[str, Decimal | None] = {c: Decimal(0) for c, _, _ in cols}
            for k in sorted(qs):
                e = qs[k]
                got: dict[str, tuple[Decimal, str] | None] = {}
                cum: dict[str, Decimal | None] = {}
                for col, _, duration in cols:
                    if not duration:
                        got[col] = inst[col].get(e)
                        continue
                    run = annual[col].get(e) if k == 4 else next(
                        (h for (s, x), h in ytd[col].items() if x == e and abs((s - start).days) <= 7), None)
                    q = three[col].get(e)                     # 4분기는 10-K에 3개월 값이 있어도 연간 − 누적을 먼저 쓴다
                    prev = cum_prev.get(col) if k - 1 in qs or k == 1 else None
                    if k == 1:
                        run = run or q
                    if q is not None and k < 4:
                        got[col] = q
                    elif run is not None and prev is not None:
                        got[col] = (run[0] - prev, run[1])
                    else:
                        got[col] = q
                    cum[col] = run[0] if run is not None else (prev + q[0] if prev is not None and q is not None else None)
                cum_prev = cum
                notes = ["path=SEC_API"] + (["Q4=연간−3분기 누적"] if k == 4 else [])
                vals = self._row(lambda col: got.get(col), notes)
                if all(vals[c] is None for c in ("revenue", "operating_income", "net_income")):
                    continue                             # 재무상태표 값만 있는 결산기(앞 회계연도 4분기 등)는 분기 행이 아니다
                filed = p["_first"].get(e.isoformat())
                out.append(Financial(period_end=e, period_type=f"Q{k}", data_source="SEC", accounting_std="US-GAAP",
                                     notes=notes, filed_at=date.fromisoformat(filed) if filed else None,
                                     consolidated=True, **vals))
        return sorted(out, key=lambda f: f.period_end)[-quarters:]

    # ------------------------------------------------------------ 공시
    def get_disclosures(self, stock: StockRef, start: date, end: date) -> list[Disclosure]:
        sub = self._json(f"https://data.sec.gov/submissions/CIK{stock.cik}.json")
        rec = sub["filings"]["recent"]
        cik_int = str(int(stock.cik))
        out = []
        for i, acc in enumerate(rec["accessionNumber"]):
            form = rec["form"][i]
            filed = date.fromisoformat(rec["filingDate"][i])
            if form not in FORMS or not (start <= filed <= end):
                continue
            accepted = rec["acceptanceDateTime"][i]           # 예: 2026-01-30T16:30:12.000Z
            filed_at = datetime.fromisoformat(accepted.replace("Z", "+00:00"))
            desc = (rec.get("primaryDocDescription") or [""] * len(rec["form"]))[i] or ""
            items = (rec.get("items") or [""] * len(rec["form"]))[i] or ""
            title = desc if desc and desc.upper() != form.upper() else form
            if form.startswith("8-K") and items:
                title = f"{form} (Item {items})"
            doc = rec["primaryDocument"][i]
            out.append(Disclosure(
                rcept_no=acc, title=title, report_type=form, filed_at=filed_at,
                url=f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc.replace('-', '')}/{doc}",
            ))
        return out
