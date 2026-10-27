"""SEC 미국 재무 일괄 — frames API로 지표·기간마다 시장 전체 값을 받아 회사별 FY 재무를 만든다 (D8).

companyfacts.zip(전 종목 원본)은 1.4GB라 Cloud Run 메모리에서 다루기 어렵고, frames는 호출 1회가 0.3~0.9MB다.
태그 규칙은 sec.py get_annual_financials와 같다(CONCEPTS 우선순위, 기간형은 350~380일, 빈 영업이익·부채는 derive_missing).
이전 CIK 연결(sec_predecessor_cik)은 회사별 API에서만 한다 — 대상이 노출 종목·비교군(XOM)이라 listed 일괄에는 필요 없다.

- 기간형(매출·영업이익·순이익): CY{연도} frame. 회계연도가 12월에 끝나지 않아도 그 기간이 들어 있다(end가 결산일).
- 순간형(자산·자본·부채): frames의 분기 순간값(CY{연도}Q{n}I)은 달력 분기에 맞춘 값이라, 회사마다 결산일과
  **같은 날짜**의 값만 쓴다(12월 결산이 아니면 분기 frame에 10-Q 값이 섞이기 때문).
- 회계연도 결산일 = 연간 순이익·매출이 있는 end. 최근 years개.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from decimal import Decimal

import httpx

from app.core.config import get_settings
from app.providers.base import Financial, ProviderError
from app.providers.convert import to_dec
from app.providers.http import Throttle, call_with_retry
from app.providers.sec import AUX_CONCEPTS, CONCEPTS, derive_missing

log = logging.getLogger(__name__)
_throttle = Throttle(0.25)            # sec.py와 같은 간격(초당 약 4건)


class SecFrames:
    source = "SEC"

    def __init__(self, user_agent: str | None = None, http: httpx.Client | None = None):
        ua = user_agent or get_settings().sec_user_agent
        if not ua or "@" not in ua:
            raise ProviderError("SEC_USER_AGENT에 연락처(이메일)가 필요합니다")
        self.http = http or httpx.Client(timeout=120, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})
        self.calls = 0

    def frame(self, concept: str, period: str) -> list[dict]:
        """us-gaap/{concept}/USD/{period} 1회. 아직 없는 기간(404)은 빈 목록."""
        def call():
            r = self.http.get(f"https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/USD/{period}.json")
            if r.status_code == 404:
                return {"data": []}
            r.raise_for_status()
            return r.json()
        self.calls += 1
        return call_with_retry(call, throttle=_throttle, what=f"SEC frame {concept} {period}").get("data", [])


def _cik(v) -> str:
    return str(v).zfill(10)


def get_annual_financials_bulk(ciks: set[str], years: int, *, last_year: int | None = None,
                               frames: SecFrames | None = None) -> dict[str, list[Financial]]:
    """CIK → FY 재무 목록(결산일 오름차순). sec.py와 같은 태그 대체 규칙·같은 Financial 모양. 받지 못한 CIK는 없음.
    last_year: 가장 최근 CY frame 연도(기본: 올해). 회계연도가 어긋난 회사도 잡도록 years + 1개 연도를 받는다."""
    frames = frames or SecFrames()
    last_year = last_year or date.today().year      # 올해 frame에도 6·9월 결산 회사의 끝난 회계연도가 들어 있다
    cy = list(range(last_year - years, last_year + 1))
    # 기간형: col → cik → end → (값, 개념)  — 우선순위 높은 개념이 먼저 채운다
    dur: dict[str, dict[str, dict[date, tuple[Decimal, str]]]] = {}
    for col, concepts, duration in CONCEPTS + AUX_CONCEPTS:
        if not duration:
            continue
        dur[col] = defaultdict(dict)
        for c in concepts:
            for y in cy:
                for e in frames.frame(c, f"CY{y}"):
                    k = _cik(e["cik"])
                    if k not in ciks or "start" not in e:
                        continue
                    end = date.fromisoformat(e["end"])
                    if not 350 <= (end - date.fromisoformat(e["start"])).days <= 380:
                        continue
                    v = to_dec(e.get("val"), 2)
                    if v is not None:
                        dur[col][k].setdefault(end, (v, c))
    fy_ends = {k: sorted(set(dur["net_income"].get(k, {})) | set(dur["revenue"].get(k, {})))[-years:] for k in ciks}
    need_q = sorted({(e.year, (e.month - 1) // 3 + 1) for ends in fy_ends.values() for e in ends})
    # 순간형: 결산일이 들어 있는 달력 분기 frame만 받아 결산일과 같은 날짜 값만 쓴다
    inst: dict[str, dict[str, dict[date, tuple[Decimal, str]]]] = {}
    for col, concepts, duration in CONCEPTS + AUX_CONCEPTS:
        if duration:
            continue
        inst[col] = defaultdict(dict)
        for c in concepts:
            for y, q in need_q:
                for e in frames.frame(c, f"CY{y}Q{q}I"):
                    k = _cik(e["cik"])
                    if k not in ciks:
                        continue
                    v = to_dec(e.get("val"), 2)
                    if v is not None:
                        inst[col][k].setdefault(date.fromisoformat(e["end"]), (v, c))
    out: dict[str, list[Financial]] = {}
    for k, ends in fy_ends.items():
        fins = []
        for end in ends:
            vals, notes = {}, []
            for col, concepts, duration in CONCEPTS:
                hit = (dur if duration else inst)[col].get(k, {}).get(end)
                vals[col] = hit[0] if hit else None
                if hit and hit[1] != concepts[0]:
                    notes.append(f"{col}←{hit[1]}")
            aux = {col: ((dur if duration else inst)[col].get(k, {}).get(end) or (None,))[0]
                   for col, _, duration in AUX_CONCEPTS}
            derive_missing(vals, aux, notes)
            fins.append(Financial(period_end=end, period_type="FY", data_source="SEC", accounting_std="US-GAAP",
                                  notes=notes, **vals))
        if fins:
            out[k] = fins
    log.info("SEC frames %d회 → %d개 회사", frames.calls, len(out))
    return out
