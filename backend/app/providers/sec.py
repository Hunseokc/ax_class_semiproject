"""SEC EDGAR: 티커→CIK, 연간 재무(companyfacts), 공시 목록(submissions).

API 키는 없고 연락처(이메일)가 포함된 User-Agent가 필수다(ASSUMPTIONS A-16).
SEC 권고(초당 10건 이하)보다 보수적으로 초당 약 4건으로 제한한다.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from decimal import Decimal

import httpx

from app.core.config import get_settings
from app.providers.base import Disclosure, Financial, Listing, ProviderError, StockRef, ValuationBase
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
    ("net_income", ("NetIncomeLoss",), True),
    ("total_assets", ("Assets",), False),
    ("total_equity", ("StockholdersEquity",
                      "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"), False),
    ("total_debt", ("Liabilities",), False),
]
ANNUAL_FORMS = {"10-K", "10-K/A"}

# 상장 보통주 목록 필터 (company_tickers_exchange.json)
EXCHANGES = {"Nasdaq": "NASDAQ", "NYSE": "NYSE"}               # OTC·CBOE 등은 제외
COMMON_TICKER = re.compile(r"^[A-Z]{1,5}(-[A-OQ-Z])?$")         # BRK-B·MOG-A 허용, 우선주(-P·-PA)·워런트(-WT)·유닛(-UN) 제외
NASDAQ_5TH_NON_COMMON = set("MNOPQRTUVWXZ")                     # 나스닥 5번째 글자: 우선주·권리·유닛·워런트 등(L·Y·A·B는 보통주)
NON_COMMON_NAME = re.compile(r"\bETF\b|\bETN\b|\bFUND\b|\bACQUISITION\b", re.I)   # ETF·펀드·스팩


def is_common_us(ticker: str, name: str) -> bool:
    if not COMMON_TICKER.match(ticker) or NON_COMMON_NAME.search(name):
        return False
    return not (len(ticker) == 5 and ticker[-1] in NASDAQ_5TH_NON_COMMON)


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

    # ------------------------------------------------------------ 재무
    def _facts(self, cik: str) -> dict:
        """companyfacts는 재무와 기초값이 같은 응답이라, 바로 이어지는 두 번째 요청에는 받아 둔 것을 쓴다."""
        hit = self._facts_cache.get(cik)
        if hit is None:
            hit = self._json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
            self._facts_cache = {cik: hit}
        return hit

    # ------------------------------------------------------------ 시장 전체 발행주식수·업종·기초값
    def _frame(self, concept: str, period: str) -> list[dict]:
        """frames API 1회 = 그 기간 시장 전체 값. 아직 없는 기간(404)은 재시도 없이 빈 목록."""
        def call():
            r = self.http.get(f"https://data.sec.gov/api/xbrl/frames/{concept}/shares/{period}.json")
            if r.status_code == 404:
                return {"data": []}
            r.raise_for_status()
            return r.json()
        return call_with_retry(call, throttle=_throttle, what=f"SEC frame {concept} {period}").get("data", [])

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
        dps = dps_end = None
        gaap = facts.get("us-gaap", {})
        for concept in ("CommonStockDividendsPerShareDeclared", "CommonStockDividendsPerShareCashPaid"):
            rows = [e for e in gaap.get(concept, {}).get("units", {}).get("USD/shares", [])
                    if e.get("form") in ANNUAL_FORMS and "start" in e
                    and 350 <= (date.fromisoformat(e["end"]) - date.fromisoformat(e["start"])).days <= 380]
            if rows:
                best = max(rows, key=lambda e: (e["end"], e.get("filed", "")))
                dps, dps_end = to_dec(best.get("val"), 4), date.fromisoformat(best["end"])
                break
        return ValuationBase(shares_outstanding=shares if shares and shares > 0 else None, shares_as_of=shares_as_of,
                             dps=dps if dps is None or dps >= 0 else None, dps_period_end=dps_end)

    def get_annual_financials(self, stock: StockRef, years: int) -> list[Financial]:
        facts = self._facts(stock.cik)
        gaap = facts.get("facts", {}).get("us-gaap", {})

        def series(concept: str, duration: bool) -> dict[date, tuple[Decimal, str]]:
            """결산일 → (값, 제출일). 같은 결산일은 가장 최근 제출값(재작성 반영)."""
            out: dict[date, tuple[Decimal, str]] = {}
            for e in gaap.get(concept, {}).get("units", {}).get("USD", []):
                if e.get("form") not in ANNUAL_FORMS:
                    continue
                end = date.fromisoformat(e["end"])
                if duration:
                    if "start" not in e:
                        continue
                    days = (end - date.fromisoformat(e["start"])).days
                    if not 350 <= days <= 380:      # 52/53주 회계연도 허용
                        continue
                v = to_dec(e.get("val"), 2)
                if v is None:
                    continue
                if end not in out or e.get("filed", "") > out[end][1]:
                    out[end] = (v, e.get("filed", ""))
            return out

        merged: dict[str, dict[date, tuple[Decimal, str]]] = {}
        for col, concepts, duration in CONCEPTS:
            merged[col] = {}
            for c in concepts:                      # 우선순위 높은 개념이 먼저 채움
                for end, val in series(c, duration).items():
                    merged[col].setdefault(end, (val[0], c))
        # 회계연도 결산일 = 연간 순이익/매출이 있는 결산일
        fy_ends = sorted(set(merged["net_income"]) | set(merged["revenue"]))[-years:]
        out = []
        for end in fy_ends:
            vals, notes = {}, []
            for col, concepts, _ in CONCEPTS:
                hit = merged[col].get(end)
                vals[col] = hit[0] if hit else None
                if hit and hit[1] != concepts[0]:
                    notes.append(f"{col}←{hit[1]}")
            out.append(Financial(period_end=end, period_type="FY", data_source="SEC",
                                 accounting_std="US-GAAP", notes=notes, **vals))
        return out

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
