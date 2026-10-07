"""OpenDART: 고유번호 매핑, 연간 재무(사업보고서), 공시 목록.

- 재무: 단일회사 전체 재무제표(fnlttSinglAcntAll), 사업보고서(11011), 연결(CFS) 우선 → 별도(OFS)
- 계정 매핑: account_id 후보 → account_nm 후보 순서 (회사·연도마다 계정 ID가 다름, ASSUMPTIONS A-13)
- 공시: 지분공시(D)는 제외 (삼성전자 기준 1년 2,851건 중 2,730건이 지분공시)
"""
from __future__ import annotations

import calendar
import io
import logging
import re
import zipfile
from datetime import date, datetime, time
from decimal import Decimal
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import httpx

from app.core.config import get_settings
from app.providers.base import Disclosure, Financial, ProviderError, StockRef
from app.providers.convert import to_dec
from app.providers.http import Throttle, WindowLimiter, call_with_retry

log = logging.getLogger(__name__)
BASE = "https://opendart.fss.or.kr/api"
SEOUL = ZoneInfo("Asia/Seoul")
_throttle = Throttle(0.6)
# OpenDART는 분당 100회 이상 호출하면 이용이 제한될 수 있다 → 재시도를 포함해 60초에 90회 이하로 막는다
_limiter = WindowLimiter(90, 60.0)

STATUS_OK, STATUS_NO_DATA = "000", "013"

# 공시유형 (D 지분공시, G 펀드, H 자산유동화, J 공정위 제외)
DISCLOSURE_TYPES = {"A": "정기공시", "B": "주요사항보고", "C": "발행공시", "E": "기타공시",
                    "F": "외부감사관련", "I": "거래소공시"}

# (컬럼, 재무제표 구분, account_id 후보, account_nm 후보)
ACCOUNT_MAP: list[tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = [
    ("revenue", ("IS", "CIS"), ("ifrs-full_Revenue",),
     ("매출액", "수익(매출액)", "영업수익", "매출", "매출액(영업수익)", "수익")),
    ("operating_income", ("IS", "CIS"), ("dart_OperatingIncomeLoss",),
     ("영업이익(손실)", "영업이익", "영업손실", "영업손익")),
    ("net_income", ("IS", "CIS"), ("ifrs-full_ProfitLossAttributableToOwnersOfParent", "ifrs-full_ProfitLoss"),
     ("지배기업의소유주에게귀속되는당기순이익(손실)", "지배기업소유주지분", "당기순이익(손실)", "당기순이익", "연결당기순이익")),
    ("total_assets", ("BS",), ("ifrs-full_Assets",), ("자산총계",)),
    ("total_equity", ("BS",), ("ifrs-full_EquityAttributableToOwnersOfParent", "ifrs-full_Equity"),
     ("지배기업의소유주에게귀속되는자본", "지배기업소유주지분", "자본총계")),
    ("total_debt", ("BS",), ("ifrs-full_Liabilities",), ("부채총계",)),
]
_NM_PREFIX = re.compile(r"^[\sⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVX\d\.\-]+")


def _norm_nm(nm: str) -> str:
    return re.sub(r"\s+", "", _NM_PREFIX.sub("", nm or ""))


class DartClient:
    """FinancialProvider + DisclosureProvider (KR)."""
    source = "DART"

    def __init__(self, api_key: str | None = None, http: httpx.Client | None = None):
        self.key = api_key or get_settings().dart_api_key
        if not self.key:
            raise ProviderError("DART_API_KEY 미설정")
        self.http = http or httpx.Client(timeout=60)

    def _get(self, path: str, **params) -> dict:
        def call():
            r = self.http.get(f"{BASE}/{path}", params={"crtfc_key": self.key, **params})
            r.raise_for_status()
            return r.json()
        data = call_with_retry(call, throttle=_throttle, what=f"DART {path}", limiter=_limiter,
                               retry_if=lambda d: d.get("status") == "020")  # 020: 요청 제한 초과
        if data.get("status") not in (STATUS_OK, STATUS_NO_DATA):
            raise ProviderError(f"DART {path} status={data.get('status')} {data.get('message')}")
        return data

    # ------------------------------------------------------------ 매핑
    def corp_codes(self, stock_codes: set[str]) -> dict[str, str]:
        def call():
            r = self.http.get(f"{BASE}/corpCode.xml", params={"crtfc_key": self.key})
            r.raise_for_status()
            return r.content
        content = call_with_retry(call, throttle=_throttle, what="DART corpCode.xml", limiter=_limiter)
        z = zipfile.ZipFile(io.BytesIO(content))
        root = ElementTree.fromstring(z.read(z.namelist()[0]))
        out = {}
        for el in root.iter("list"):
            sc = (el.findtext("stock_code") or "").strip()
            if sc in stock_codes:
                out[sc] = el.findtext("corp_code").strip()
        return out

    def company(self, corp_code: str) -> dict:
        """기업개황: corp_name_eng, acc_mt(결산월) 등."""
        return self._get("company.json", corp_code=corp_code)

    # ------------------------------------------------------------ 재무
    def _statement(self, corp_code: str, year: int) -> tuple[list[dict], str | None]:
        for fs_div in ("CFS", "OFS"):
            d = self._get("fnlttSinglAcntAll.json", corp_code=corp_code, bsns_year=str(year),
                          reprt_code="11011", fs_div=fs_div)
            if d.get("status") == STATUS_OK and d.get("list"):
                return d["list"], fs_div
        return [], None

    @staticmethod
    def _extract(rows: list[dict], amount_key: str) -> tuple[dict[str, Decimal | None], list[str]]:
        values, notes = {}, []
        for col, sj_divs, ids, nms in ACCOUNT_MAP:
            cand = [r for r in rows if r.get("sj_div") in sj_divs]
            val, how = None, None
            for aid in ids:
                hit = next((r for r in cand if r.get("account_id") == aid and to_dec(r.get(amount_key)) is not None), None)
                if hit:
                    val, how = to_dec(hit.get(amount_key), 2), aid
                    break
            if val is None:
                for nm in nms:
                    hit = next((r for r in cand if _norm_nm(r.get("account_nm")) == nm
                                and to_dec(r.get(amount_key)) is not None), None)
                    if hit:
                        val, how = to_dec(hit.get(amount_key), 2), f"계정명:{hit.get('account_nm')}"
                        break
            values[col] = val
            if how and how != ids[0]:
                notes.append(f"{col}←{how}")
        return values, notes

    def get_annual_financials(self, stock: StockRef, years: int, fiscal_month: int = 12,
                              last_year: int | None = None) -> list[Financial]:
        last_year = last_year or date.today().year - 1
        target = list(range(last_year - years + 1, last_year + 1))
        reports: dict[int, tuple[list[dict], str | None]] = {}
        for y in target:
            reports[y] = self._statement(stock.corp_code, y)
        out = []
        for y in target:
            rows, fs_div = reports[y]
            vals, notes = self._extract(rows, "thstrm_amount") if rows else ({}, [])
            # 비어 있는 값은 다음 연도 사업보고서의 전기(frmtrm) 값으로 보완 (A-14)
            nxt_rows, _ = reports.get(y + 1, ([], None))
            if nxt_rows and (not vals or any(v is None for v in vals.values())):
                prev_vals, _ = self._extract(nxt_rows, "frmtrm_amount")
                for k, v in prev_vals.items():
                    if vals.get(k) is None and v is not None:
                        vals[k] = v
                        notes.append(f"{k}←{y + 1}년 보고서 전기값")
            if not vals or all(v is None for v in vals.values()):
                continue
            last_day = calendar.monthrange(y, fiscal_month)[1]
            out.append(Financial(period_end=date(y, fiscal_month, last_day), period_type="FY",
                                 data_source="DART", accounting_std="K-IFRS",
                                 notes=([f"fs_div={fs_div}"] if fs_div != "CFS" else []) + notes, **vals))
        return out

    # ------------------------------------------------------------ 공시
    def get_disclosures(self, stock: StockRef, start: date, end: date) -> list[Disclosure]:
        out: dict[str, Disclosure] = {}
        for ty, label in DISCLOSURE_TYPES.items():
            page = 1
            while True:
                d = self._get("list.json", corp_code=stock.corp_code, bgn_de=start.strftime("%Y%m%d"),
                              end_de=end.strftime("%Y%m%d"), pblntf_ty=ty, last_reprt_at="Y",
                              page_no=page, page_count=100)
                for item in d.get("list", []):
                    no = item["rcept_no"]
                    out[no] = Disclosure(
                        rcept_no=no,
                        title=re.sub(r"\s+", " ", item["report_nm"]).strip(),
                        report_type=label,
                        filed_at=datetime.combine(datetime.strptime(item["rcept_dt"], "%Y%m%d").date(), time(0), SEOUL),
                        url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={no}",
                    )
                if page >= int(d.get("total_page") or 1):
                    break
                page += 1
        return list(out.values())
