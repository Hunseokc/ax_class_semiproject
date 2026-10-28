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
from dataclasses import dataclass
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
# OpenDART는 분당 100회 이상 호출하면 이용이 제한될 수 있다. 잠금이 회사 단위라 프로세스 2개(API 서비스 + Job)가
# 번갈아 부를 수 있어 프로세스마다 절반(45)으로 막는다 → 합계 90 이하 (D2). 프로세스가 3개 이상이 되면 다시 검토
_limiter = WindowLimiter(45, 60.0)

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
# 수정 4(D-033) 추가 계정 — 점수에는 아직 쓰지 않는다(측정 라운드 M1 입력). 같은 규칙(account_id → account_nm)
EXTRA_ACCOUNT_MAP: list[tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = [
    ("operating_cf", ("CF",), ("ifrs-full_CashFlowsFromUsedInOperatingActivities",),
     ("영업활동현금흐름", "영업활동으로인한현금흐름", "영업활동으로부터의현금흐름", "영업활동순현금흐름")),
    # 지배 몫이 없으면(비지배지분이 없는 회사) 총포괄이익 전체 — notes에 남는다
    ("comprehensive_income", ("CIS", "IS"),
     ("ifrs-full_ComprehensiveIncomeAttributableToOwnersOfParent", "ifrs-full_ComprehensiveIncome"),
     ("지배기업의소유주에게귀속되는총포괄이익", "지배기업의소유주에게귀속되는총포괄손익", "총포괄이익", "총포괄손익",
      "당기총포괄이익", "당기총포괄손익")),
    ("equity_method_income", ("IS", "CIS"),
     ("ifrs-full_ShareOfProfitLossOfAssociatesAndJointVenturesAccountedForUsingEquityMethod",),
     ("지분법이익", "지분법손익", "지분법이익(손실)", "지분법손익(손실)", "지분법투자관련손익", "관계기업투자손익",
      "관계기업및공동기업투자손익", "관계기업투자이익")),
    ("cash", ("BS",), ("ifrs-full_CashAndCashEquivalents",), ("현금및현금성자산",)),
    ("goodwill", ("BS",), ("ifrs-full_Goodwill",), ("영업권",)),
    ("interest_expense", ("IS", "CIS"), ("ifrs-full_InterestExpense", "dart_InterestExpense"), ("이자비용",)),
    ("nci_net_income", ("IS", "CIS"), ("ifrs-full_ProfitLossAttributableToNoncontrollingInterests",
                                       "ifrs-full_ProfitLossAttributableToNonControllingInterests"), ()),
]
# 차입금·사채: 재무상태표의 차입 줄을 모두 더한다(리스부채 제외). 단기차입금은 표준 계정코드가 없는 회사가 있어(삼성전자) 이름으로도 찾는다
BORROWING_IDS = {
    "ifrs-full_ShortTermBorrowings", "ifrs-full_CurrentPortionOfLongtermBorrowings", "ifrs-full_LongtermBorrowings",
    "ifrs-full_CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings", "ifrs-full_NoncurrentPortionOfNoncurrentBorrowings",
    "ifrs-full_NoncurrentPortionOfNoncurrentLoansReceived", "ifrs-full_CurrentPortionOfNoncurrentLoansReceived",
    "ifrs-full_BondsIssued", "ifrs-full_NoncurrentPortionOfNoncurrentBondsIssued",
    "ifrs-full_CurrentBondsIssuedAndCurrentPortionOfNoncurrentBondsIssued", "ifrs-full_CurrentPortionOfNoncurrentBondsIssued",
    "dart_ShortTermBorrowings", "dart_LongTermBorrowingsGross", "dart_BondsIssued", "dart_CurrentPortionOfBonds",
    "dart_CurrentPortionOfLongTermBorrowings",
}
BORROWING_NAMES = {"단기차입금", "장기차입금", "차입금", "유동차입금", "비유동차입금", "유동성장기차입금", "유동성장기부채",
                   "사채", "유동성사채", "전환사채", "교환사채", "신주인수권부사채", "장기차입금및사채", "단기사채"}
# 무형자산 합계(영업권 포함). 합계 줄이 없으면 영업권 외 무형자산 + 영업권
INTANGIBLE_TOTAL_IDS = ("ifrs-full_IntangibleAssetsAndGoodwill",)
INTANGIBLE_OTHER = (("ifrs-full_IntangibleAssetsOtherThanGoodwill",), ("무형자산", "영업권이외의무형자산", "기타무형자산"))
# 이자비용이 손익계산서에 따로 없으면(금융비용에 섞임) 현금흐름표의 이자 지급액
INTEREST_PAID = (("ifrs-full_InterestPaidClassifiedAsOperatingActivities", "ifrs-full_InterestPaidClassifiedAsFinancingActivities"),
                 ("이자의지급", "이자지급", "이자의지급(영업활동)", "이자지급액"))
CORE_COLS = [c for c, *_ in ACCOUNT_MAP]
FIN_COLS = CORE_COLS + [c for c, *_ in EXTRA_ACCOUNT_MAP] + ["borrowings", "intangibles"]
REPORT_FY, REPORT_Q = "11011", {1: "11013", 2: "11012", 3: "11014"}   # 사업보고서 / 1분기·반기·3분기 보고서
_NM_PREFIX = re.compile(r"^[\sⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVX\d\.\-]+")


def _norm_nm(nm: str) -> str:
    return re.sub(r"\s+", "", _NM_PREFIX.sub("", nm or ""))


@dataclass(frozen=True)
class FiledReport:
    """회사 지정 없는 사업보고서 목록 1건(공시 증분용)."""
    rcept_no: str                   # 접수번호 14자리 (YYYYMMDD + 일련번호) — 문자열 크기 비교가 접수 순서
    rcept_dt: date
    corp_code: str
    stock_code: str | None          # 비상장이면 None
    report_nm: str                  # 공백을 한 칸으로 정리한 제목. 정정은 "[기재정정]사업보고서 (2025.12)" 형태


class DartClient:
    """FinancialProvider + DisclosureProvider (KR)."""
    source = "DART"

    def __init__(self, api_key: str | None = None, http: httpx.Client | None = None):
        self.key = api_key or get_settings().dart_api_key
        if not self.key:
            raise ProviderError("DART_API_KEY 미설정")
        self.http = http or httpx.Client(timeout=60)
        # 같은 회사의 FY·분기 수집이 같은 보고서를 다시 부르지 않게(4분기 = 연간 − 3분기 누적). 회사가 바뀌면 비운다
        self._stmt_cache: dict[tuple[str, int, str], tuple[list[dict], str | None]] = {}

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

    def get_ksic(self, corp_code: str) -> str | None:
        """기업개황의 업종 코드(induty_code, 한국표준산업분류 KSIC 2~5자리). 없으면 None — 테마 분류(app/ingest/sectors.py)용."""
        code = (self.company(corp_code).get("induty_code") or "").strip()
        return code if code.isdigit() else None

    # ------------------------------------------------------------ 재무
    def _statement(self, corp_code: str, year: int, reprt_code: str = REPORT_FY) -> tuple[list[dict], str | None]:
        """보고서 1개(연결 우선 → 별도). 없으면 ([], None). 같은 회사 안에서는 받아 둔 것을 쓴다."""
        key = (corp_code, year, reprt_code)
        if key not in self._stmt_cache:
            if self._stmt_cache and next(iter(self._stmt_cache))[0] != corp_code:
                self._stmt_cache = {}
            got: tuple[list[dict], str | None] = ([], None)
            for fs_div in ("CFS", "OFS"):
                d = self._get("fnlttSinglAcntAll.json", corp_code=corp_code, bsns_year=str(year),
                              reprt_code=reprt_code, fs_div=fs_div)
                if d.get("status") == STATUS_OK and d.get("list"):
                    got = (d["list"], fs_div)
                    break
            self._stmt_cache[key] = got
        return self._stmt_cache[key]

    @staticmethod
    def _find(rows: list[dict], sj_divs: tuple[str, ...], ids: tuple[str, ...], nms: tuple[str, ...],
              amount_key: str) -> tuple[dict | None, str | None]:
        """account_id 후보 → account_nm 후보 순서로 값이 있는 첫 줄. 반환: (줄, 찾은 방법)."""
        cand = [r for r in rows if r.get("sj_div") in sj_divs and to_dec(r.get(amount_key)) is not None]
        for aid in ids:
            hit = next((r for r in cand if r.get("account_id") == aid), None)
            if hit:
                return hit, aid
        for nm in nms:
            hit = next((r for r in cand if _norm_nm(r.get("account_nm")) == nm), None)
            if hit:
                return hit, f"계정명:{hit.get('account_nm')}"
        return None, None

    @staticmethod
    def _extract(rows: list[dict], amount_key: str) -> tuple[dict[str, Decimal | None], list[str]]:
        """기본 6계정(ACCOUNT_MAP)만 — 일괄다운로드 적재(dart_bulk)도 같은 규칙을 쓴다."""
        values, notes = {}, []
        for col, sj_divs, ids, nms in ACCOUNT_MAP:
            hit, how = DartClient._find(rows, sj_divs, ids, nms, amount_key)
            values[col] = to_dec(hit.get(amount_key), 2) if hit else None
            if how and how != ids[0]:
                notes.append(f"{col}←{how}")
        return values, notes

    @staticmethod
    def _lines(rows: list[dict], amount_key: str = "thstrm_amount") -> dict[str, list[tuple[dict, str]]]:
        """컬럼 → 값을 읽을 줄(차입금·무형자산은 여러 줄을 더한다)과 찾은 방법(기본 계정이면 빈 문자열).
        줄을 먼저 고르고, 값은 쓰는 쪽이 칸(당기 3개월·누적·전기)을 골라 읽는다."""
        out: dict[str, list[tuple[dict, str]]] = {}
        for col, sj_divs, ids, nms in ACCOUNT_MAP + EXTRA_ACCOUNT_MAP:
            hit, how = DartClient._find(rows, sj_divs, ids, nms, amount_key)
            if hit:
                out[col] = [(hit, "" if how == ids[0] else how)]
        if "interest_expense" not in out:
            hit, how = DartClient._find(rows, ("CF",), *INTEREST_PAID, amount_key)
            if hit:
                out["interest_expense"] = [(hit, f"이자의 지급(현금흐름표 {how})")]
        hit, _ = DartClient._find(rows, ("BS",), INTANGIBLE_TOTAL_IDS, (), amount_key)
        if hit:
            out["intangibles"] = [(hit, "")]
        else:
            other, how = DartClient._find(rows, ("BS",), *INTANGIBLE_OTHER, amount_key)
            parts = ([(other, f"영업권 외 무형자산({how})")] if other else []) + out.get("goodwill", [])
            if parts:
                out["intangibles"] = parts
        borrow = [(r, str(r.get("account_nm")).strip()) for r in rows
                  if r.get("sj_div") == "BS" and to_dec(r.get(amount_key)) is not None
                  and (r.get("account_id") in BORROWING_IDS or _norm_nm(r.get("account_nm")) in BORROWING_NAMES)]
        if borrow:
            out["borrowings"] = borrow
        return out

    @staticmethod
    def _read(lines: dict[str, list[tuple[dict, str]]], col: str, key: str) -> Decimal | None:
        """col 줄들의 key 칸 합. 한 줄이라도 비면 None. 현금흐름표 이자 지급액은 부호와 상관없이 크기."""
        parts = lines.get(col)
        if not parts:
            return None
        vals = [to_dec(r.get(key), 2) for r, _ in parts]
        if any(v is None for v in vals):
            return None
        v = sum(vals, Decimal(0))
        return abs(v) if col == "interest_expense" and parts[0][0].get("sj_div") == "CF" else v

    @staticmethod
    def _how(lines: dict[str, list[tuple[dict, str]]], cols: list[str]) -> list[str]:
        out = []
        for c in cols:
            if c == "borrowings" and c in lines:
                out.append("borrowings=" + "+".join(h for _, h in lines[c]))
            elif c in lines and any(h for _, h in lines[c]):
                out.append(f"{c}←" + "+".join(h for _, h in lines[c] if h))
        return out

    @staticmethod
    def _filed(rows: list[dict]) -> date | None:
        """접수번호 앞 8자리 = 접수일."""
        no = next((str(r["rcept_no"]) for r in rows if str(r.get("rcept_no") or "")[:8].isdigit()), None)
        return datetime.strptime(no[:8], "%Y%m%d").date() if no else None

    @staticmethod
    def _currency(rows: list[dict]) -> str | None:
        """재무제표 표시통화(행마다 있는 currency). K-IFRS 1021은 원화 외 표시통화를 허용한다 — 두산밥캣은 USD(D-026)."""
        return next((str(r["currency"]).strip().upper() for r in rows if (r.get("currency") or "").strip()), None)

    def get_annual_financials(self, stock: StockRef, years: int, fiscal_month: int = 12,
                              last_year: int | None = None) -> list[Financial]:
        """사업보고서 FY years개. 빈 해·빈 칸은 다음 해 사업보고서의 전기(frmtrm) 값 — 감사받은 비교 수치(D-039, A-14).
        다른 구분(연결·별도)의 보고서에서는 칸 단위로 채우지 않는다(해 전체가 비었을 때만 다음 해 보고서 전기값 전체)."""
        last_year = last_year or date.today().year - 1
        target = list(range(last_year - years + 1, last_year + 1))
        reports = {y: self._statement(stock.corp_code, y) for y in target}
        out = []
        for y in target:
            rows, fs_div = reports[y]
            nxt_rows, nxt_fs = reports.get(y + 1, ([], None))
            lines = self._lines(rows) if rows else {}
            vals = {c: self._read(lines, c, "thstrm_amount") for c in FIN_COLS}
            notes, filed, cons, cur = self._how(lines, FIN_COLS), self._filed(rows), fs_div, self._currency(rows)
            if all(vals[c] is None for c in CORE_COLS):          # 그해 보고서가 없음 → 다음 해 보고서 전기값 전체
                prev = self._lines(nxt_rows, "frmtrm_amount") if nxt_rows else {}
                vals = {c: self._read(prev, c, "frmtrm_amount") for c in FIN_COLS}
                notes = [f"전체←{y + 1}년 보고서 전기값"] + self._how(prev, FIN_COLS)
                filed, cons, cur = self._filed(nxt_rows), nxt_fs, self._currency(nxt_rows)
            elif nxt_rows and nxt_fs == fs_div and any(vals[c] is None for c in FIN_COLS):
                prev = self._lines(nxt_rows, "frmtrm_amount")
                for c in FIN_COLS:
                    if vals[c] is None and (v := self._read(prev, c, "frmtrm_amount")) is not None:
                        vals[c] = v
                        notes.append(f"{c}←{y + 1}년 보고서 전기값")
            if all(vals[c] is None for c in CORE_COLS):
                continue
            last_day = calendar.monthrange(y, fiscal_month)[1]
            out.append(Financial(period_end=date(y, fiscal_month, last_day), period_type="FY",
                                 data_source="DART", accounting_std="K-IFRS",
                                 notes=["path=DART_API"] + ([f"fs_div={cons}"] if cons != "CFS" else []) + notes,
                                 currency=cur, filed_at=filed, consolidated=None if cons is None else cons == "CFS",
                                 **vals))
        have = {f.period_end.year for f in out}
        for f in out:                                        # 창 안 직전 해가 없으면 사유(보고서·전기값 모두 없음)
            if f.period_end.year - 1 in target and f.period_end.year - 1 not in have:
                f.notes.append("직전 연도 없음(보고서·전기값 모두 없음)")
        return out

    def get_quarterly_financials(self, stock: StockRef, quarters: int, fiscal_month: int = 12,
                                 last_year: int | None = None) -> list[Financial]:
        """최근 quarters개 분기(3개월치, D-033). 1분기·반기·3분기 보고서 손익은 당기(3개월) 칸, 현금흐름은 누적만 있어
        누적 차이, 4분기 = 사업보고서 연간 − 3분기 누적. 재무상태표는 분기 말 값. 누적 차이는 같은 구분(연결·별도)끼리만.
        회사의 첫 사업보고서 연도 전은 부르지 않는다(상장 전 — 호출 낭비)."""
        last_year = last_year or date.today().year - 1
        span = (quarters + 3) // 4                            # 20 → 지난 5개 사업연도 + 올해
        own = [y for y in range(last_year - span + 1, last_year + 1) if self._statement(stock.corp_code, y)[0]]
        out: list[Financial] = []
        for y in range(min(own) if own else last_year, last_year + 2):
            cum_prev: dict[str, Decimal | None] | None = {}   # 직전 분기 누적(1분기 앞은 0) — None이면 이어지지 않음
            fs_prev: str | None = None
            for k in (1, 2, 3, 4):
                if k < 4:
                    rows, fs = self._statement(stock.corp_code, y, REPORT_Q[k])
                else:
                    rows, fs = self._statement(stock.corp_code, y) if y <= last_year else ([], None)
                if not rows:
                    cum_prev, fs_prev = None, None
                    continue
                lines = self._lines(rows)
                linked = k == 1 or (cum_prev is not None and fs == fs_prev)
                vals: dict[str, Decimal | None] = {}
                cum: dict[str, Decimal | None] = {}
                for c in FIN_COLS:
                    sj = lines[c][0][0].get("sj_div") if c in lines else None
                    if sj is None:
                        vals[c] = None
                        continue
                    if sj == "BS":
                        vals[c] = self._read(lines, c, "thstrm_amount")
                        continue
                    if k == 4 or sj == "CF":                     # 사업보고서 연간·현금흐름 = 누적
                        q3, cum[c] = None, self._read(lines, c, "thstrm_amount")
                    else:                                        # 분기 손익: 당기 = 3개월, 누적 칸(1분기는 당기)
                        q3 = self._read(lines, c, "thstrm_amount")
                        cum[c] = q3 if k == 1 else self._read(lines, c, "thstrm_add_amount")
                    prev = Decimal(0) if k == 1 else ((cum_prev or {}).get(c) if linked else None)
                    if q3 is not None:
                        vals[c] = q3
                        if cum[c] is None and prev is not None:
                            cum[c] = prev + q3
                    else:
                        vals[c] = cum[c] - prev if cum[c] is not None and prev is not None else None
                cum_prev, fs_prev = cum, fs
                if all(vals[c] is None for c in CORE_COLS):
                    continue
                m = fiscal_month - 3 * (4 - k)
                qy, qm = (y, m) if m > 0 else (y - 1, m + 12)
                notes = ["path=DART_API", f"report={REPORT_Q.get(k, REPORT_FY)}"] + ([f"fs_div={fs}"] if fs != "CFS" else [])
                notes += self._how(lines, FIN_COLS) + (["Q4=연간−3분기 누적"] if k == 4 else [])
                if not linked:
                    notes.append("직전 분기 누적 없음·구분 다름 — 누적으로만 나오는 칸 비움")
                out.append(Financial(period_end=date(qy, qm, calendar.monthrange(qy, qm)[1]), period_type=f"Q{k}",
                                     data_source="DART", accounting_std="K-IFRS", notes=notes,
                                     currency=self._currency(rows), filed_at=self._filed(rows),
                                     consolidated=fs == "CFS", **vals))
        return sorted(out, key=lambda f: f.period_end)[-quarters:]

    # ------------------------------------------------------------ 공시
    def list_annual_reports(self, start: date, end: date, page_no: int = 1) -> tuple[list[FiledReport], int]:
        """회사 지정 없이 사업보고서(A001) 목록 한 페이지(100건). 정정·첨부 공시 포함. 반환: (목록, total_page).
        회사 지정이 없으면 조회 기간은 3개월까지다(초과는 호출 측이 나눔). 정렬은 접수번호 순이 보장되지 않는다
        ([첨부추가] 등이 앞에 섞임) — 호출 측은 기간 안 전체 페이지를 받아야 한다."""
        d = self._get("list.json", bgn_de=start.strftime("%Y%m%d"), end_de=end.strftime("%Y%m%d"), pblntf_ty="A",
                      pblntf_detail_ty="A001", sort="date", sort_mth="desc", page_no=page_no, page_count=100)
        if d.get("status") == STATUS_NO_DATA:
            return [], 0
        items = [FiledReport(rcept_no=x["rcept_no"], rcept_dt=datetime.strptime(x["rcept_dt"], "%Y%m%d").date(),
                             corp_code=x["corp_code"], stock_code=(x.get("stock_code") or "").strip() or None,
                             report_nm=re.sub(r"\s+", " ", x["report_nm"]).strip())
                 for x in d.get("list", [])]
        return items, int(d.get("total_page") or 0)

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
