"""SEC EDGAR: 티커→CIK, 연간 재무(companyfacts), 공시 목록(submissions).

API 키는 없고 연락처(이메일)가 포함된 User-Agent가 필수다(ASSUMPTIONS A-16).
SEC 권고(초당 10건 이하)보다 보수적으로 초당 약 4건으로 제한한다.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal

import httpx

from app.core.config import get_settings
from app.providers.base import Disclosure, Financial, ProviderError, StockRef
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


class SecClient:
    """FinancialProvider + DisclosureProvider (US)."""
    source = "SEC"

    def __init__(self, user_agent: str | None = None, http: httpx.Client | None = None):
        ua = user_agent or get_settings().sec_user_agent
        if not ua or "@" not in ua:
            raise ProviderError("SEC_USER_AGENT에 연락처(이메일)가 필요합니다")
        self.http = http or httpx.Client(timeout=60, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})

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
    def get_annual_financials(self, stock: StockRef, years: int) -> list[Financial]:
        facts = self._json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{stock.cik}.json")
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
