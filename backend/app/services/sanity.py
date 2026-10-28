"""매력도 회귀 테스트 — 개발산출물/매력도_검토/sanity_cases.yaml의 cases·rules를 DB의 최신 점수로 판정한다.

실행: python -m app.ingest sanity [--cases 경로] [--as-of 날짜] [--out 결과.md] [--save [--env dev|deploy]]
  - 순위·백분위 정의는 sanity_cases.yaml 머리말(D-012): *_rank = 같은 시장·같은 묶음 안 프리셋 순위,
    *_percentile = 같은 범위 백분위(= stock_scores.score), *_factor = 재표준화한 팩터 점수, not_scored / scored
  - 일반 case는 check 식을 그대로 계산하고(and·or·비교), 식으로 쓸 수 없는 case·rule은 id별 함수로 판정한다
  - 결과는 네 칸으로 센다(D-030): 통과 / 감수한 실패(known_fail·결정 번호) / target 실패 / 미검증(데이터 없음·실행 불가).
    required 실패는 따로 적고 종료를 막는다. 감수한 실패는 종료를 막지 않지만 '통과'에 합치지 않는다
  - --save면 결과를 sanity_runs 표에 남긴다(배포 Job은 --env deploy — 배포 DB에서도 sanity를 돌린 기록, D-030)
  - 독립 기준(R10)은 개발산출물/11 5절 정의를 옮긴 것이다(I1 구조·I2 매출 2년 감소·I3 영업적자 이력·I5 극단 변동성, 상식적 우량)
반환 코드: required(known_fail은 결정 번호가 있으면 제외) 중 실패가 있으면 1. 미검증은 종료 코드에 넣지 않고 따로 적는다
"""
from __future__ import annotations

import json
import math
import re
import statistics as st
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml
from sqlalchemy import Connection, text

from app.core.config import CONFIG_DIR
from app.queries import sql
from app.services.scoring import (FACTORS, FISCAL_GAP_DAYS, METRICS, MIN_FACTORS, REQUIRED_FACTORS, load_config,
                                  theme_positions)

PRESET_KR = {"aggressive": "위험", "growth": "성장", "balanced": "균형", "value": "가치"}
FACTOR_ALIAS = {"stability": "safety"}
TRUSTS = {"GLD", "IAU", "SLV", "PSLV"}
FIN_LINKED = {"023590"}                                   # 다우기술(키움증권 연결)
HOLD_RE = re.compile(r"홀딩스|지주")
# R4 경기순환: 원자재 연동 테마 + 메모리·저장장치(테마가 '반도체'라 목록으로 정한다 — D-012의 '메모리 반도체', D-017)
# (국가, 티커)로 적는다 — R4는 시장마다 따로 세므로 SK하이닉스는 국내 가치 top10에서만 센다
MEMORY = {("US", "MU"), ("US", "SNDK"), ("US", "WDC"), ("US", "STX"), ("KR", "000660")}
MARKET_COUNTRY = {"US": "US", "KR": "KR"}           # sanity_cases.yaml의 market 값 → 국가
TOP_LABELS = ("매우 낮음", "낮음", "보통", "높음", "매우 높음")


def default_cases_path() -> Path:
    for root in (CONFIG_DIR.parent, CONFIG_DIR.parent.parent):        # 컨테이너 /srv, 저장소 backend/..
        p = root / "개발산출물" / "매력도_검토" / "sanity_cases.yaml"
        if p.exists():
            return p
    raise FileNotFoundError("sanity_cases.yaml을 찾지 못했습니다 — --cases로 경로를 주세요")


def stock_page(name: str = "stock.js") -> Path | None:
    """화면 코드(frontend/js/pages/<name>, 기본 종목 상세) — 컨테이너 /srv/frontend 또는 저장소 frontend."""
    for root in (CONFIG_DIR.parent, CONFIG_DIR.parent.parent):
        p = root / "frontend" / "js" / "pages" / name
        if p.exists():
            return p
    return None


def doc_09() -> Path | None:
    """09 정의서 — 저장소에서만 있다(배포 이미지에는 sanity 목록만 넣는다)."""
    for root in (CONFIG_DIR.parent, CONFIG_DIR.parent.parent):
        p = root / "개발산출물" / "09_매력도_점수_정의서.md"
        if p.exists():
            return p
    return None


@dataclass
class Stock:
    stock_id: int
    ticker: str
    name: str
    country: str
    family: str | None                  # 점수 묶음(점수 행이 없으면 테마 기준)
    theme: str | None
    commodity: bool
    rank: dict = field(default_factory=dict)        # preset → 순위
    pct: dict = field(default_factory=dict)         # preset → 백분위(score)
    n: dict = field(default_factory=dict)           # preset → 묶음 크기
    composite: dict = field(default_factory=dict)
    factors: dict = field(default_factory=dict)     # factor → Fs
    dq: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)         # metric → raw_value
    z_raw: dict = field(default_factory=dict)       # metric → z_raw(중립화 전)
    z_adj: dict = field(default_factory=dict)       # metric → z_adj(최종)
    fins: list = field(default_factory=list)        # FY 행(결산일 오름차순)

    @property
    def scored(self) -> bool:
        return self.pct.get("balanced") is not None

    def chain(self) -> list[dict]:
        """score_metrics.sql과 같은 FY 고르기: 자산·이익이 있는 FY, 330~400일 간격으로 이어지는 [t, t−1, t−2]."""
        ok = [f for f in self.fins if f["total_assets"] is not None
              and (f["net_income"] is not None or f["operating_income"] is not None)]
        if not ok:
            return []
        out = [ok[-1]]
        while len(out) < 3:
            prev = [f for f in ok if 330 <= (out[-1]["period_end"] - f["period_end"]).days <= 400]
            if not prev:
                break
            out.append(prev[-1])
        return out


class Data:
    def __init__(self, conn: Connection, as_of: date | None = None, save_env: str | None = None):
        self.conn = conn
        self.save_env = save_env            # 이번 실행을 sanity_runs에 남기면 그 환경(dev / deploy), 남기지 않으면 None
        self.as_of = as_of or conn.execute(text("SELECT MAX(as_of) FROM stock_scores")).scalar()
        self.cfg = load_config()
        self.stocks: dict[int, Stock] = {}
        self._load()

    def _load(self) -> None:
        c = self.conn
        for r in c.execute(text("""
                SELECT s.stock_id, s.ticker, s.name, mk.country, t.theme, t.family, COALESCE(t.commodity_linked, false) AS commodity
                FROM stocks s JOIN markets mk ON mk.market_id = s.market_id
                LEFT JOIN v_stock_theme t ON t.stock_id = s.stock_id
                WHERE s.is_active AND s.coverage <> 'listed'""")).mappings():
            self.stocks[r["stock_id"]] = Stock(r["stock_id"], r["ticker"], r["name"], r["country"],
                                               r["family"] or "general", r["theme"], r["commodity"])
        rows = c.execute(text("""
                SELECT st.*, p.code FROM stock_scores st JOIN scoring_presets p USING (preset_id)
                WHERE st.as_of = :d"""), {"d": self.as_of}).mappings().all()
        groups = defaultdict(list)
        for r in rows:
            s = self.stocks.get(r["stock_id"])
            if s is None:
                continue
            s.dq = r["data_quality"] or {}
            s.family = s.dq.get("family", s.family)
            for f in FACTORS:
                if r[f"{f}_score"] is not None:
                    s.factors[f] = float(r[f"{f}_score"])
            if r["composite"] is not None:
                s.composite[r["code"]] = float(r["composite"])
                s.pct[r["code"]] = float(r["score"])
                groups[(r["code"], s.country, s.family)].append(s)
        self.groups = groups
        for (code, _, _), lst in groups.items():
            for s in lst:                  # 저장된 백분위로 순위(SQL은 반올림 전 종합으로 매긴다 — 종합 4자리 동점을 피함)
                s.rank[code] = 1 + sum(1 for x in lst if x.pct[code] > s.pct[code])
                s.n[code] = len(lst)
        for r in c.execute(text("SELECT stock_id, metric, raw_value, z_raw, z_adj FROM stock_metric_values WHERE as_of = :d"),
                           {"d": self.as_of}):
            s = self.stocks.get(r.stock_id)
            if s is None:
                continue
            for name, v in (("raw", r.raw_value), ("z_raw", r.z_raw), ("z_adj", r.z_adj)):
                if v is not None:
                    getattr(s, name)[r.metric] = float(v)
        for r in c.execute(text("""SELECT stock_id, period_end, revenue, operating_income, net_income, total_assets, total_debt,
                                          total_equity
                                   FROM financial_statements WHERE period_type = 'FY' ORDER BY stock_id, period_end""")).mappings():
            if r["stock_id"] in self.stocks:
                self.stocks[r["stock_id"]].fins.append({k: (float(v) if k not in ("stock_id", "period_end") and v is not None else v)
                                                        for k, v in r.items()})
        self.mcap = {r.stock_id: float(r.mcap) for r in c.execute(text(
            "SELECT stock_id, market_cap AS mcap FROM v_stock_metrics WHERE market_cap IS NOT NULL")) if r.stock_id in self.stocks}
        # 최신 밸류에이션(KRX·yfinance EPS·BPS)과 상장주식수 — 통화(D-026)·우선주(D-029) 규칙이 DB 재무와 대조한다
        self.val = {r.stock_id: {k: None if r[k] is None else float(r[k]) for k in ("eps", "bps", "close", "shares")}
                    for r in c.execute(text("""
                        SELECT vm.stock_id, vm.eps, vm.bps, vm.close, vs.shares_outstanding AS shares
                        FROM v_stock_metrics vm
                        LEFT JOIN LATERAL (SELECT x.shares_outstanding FROM valuation_snapshots x WHERE x.stock_id = vm.stock_id
                                           ORDER BY x.as_of DESC LIMIT 1) vs ON true""")).mappings() if r["stock_id"] in self.stocks}
        self.weights = {p["code"]: p["weights"] for p in self.cfg["presets"]}

    # ------------------------------------------------------------ 조회
    def by_ticker(self, ticker: str, market: str | None = None) -> Stock | None:
        """market(US·KR)을 주면 그 국가 종목만 — 국내 숫자 티커와 미국 영문 티커가 겹치지 않아도 시장을 섞어 찾지 않는다."""
        country = MARKET_COUNTRY.get(market or "")
        return next((s for s in self.stocks.values() if s.ticker == ticker and (country is None or s.country == country)), None)

    def general(self, country: str) -> list[Stock]:
        return [s for s in self.stocks.values() if s.country == country and s.family == "general"]

    def top(self, country: str, preset: str, n: int) -> list[Stock]:
        lst = [s for s in self.general(country) if preset in s.rank]
        return sorted(lst, key=lambda s: s.rank[preset])[:n]


# ------------------------------------------------------------------ 일반 case: check 식
def namespace(s: Stock | None) -> dict:
    ns = {"not_scored": s is None or not s.scored, "scored": s is not None and s.scored,
          "family": None if s is None else s.family, "financial": "financial", "general": "general"}
    for p in PRESET_KR:
        ns[f"{p}_rank"] = None if s is None else s.rank.get(p)
        ns[f"{p}_percentile"] = None if s is None else s.pct.get(p)
    for f in FACTORS:
        ns[f"{f}_factor"] = None if s is None else s.factors.get(f)
    for alias, f in FACTOR_ALIAS.items():
        ns[f"{alias}_factor"] = ns[f"{f}_factor"]
    return ns


EXPR_OK = re.compile(r"^[\w\s<>=!.()]+$")


def eval_check(expr: str, s: Stock | None) -> bool | None:
    """'growth_rank > 50 and value_rank > 20' 같은 식. 값이 없는(None) 비교는 실패(점수 없음은 not_scored로 따로 쓴다)."""
    if not EXPR_OK.match(expr):
        return None
    ns = namespace(s)
    names = set(re.findall(r"[A-Za-z_]\w*", expr)) - {"and", "or", "not"}
    if not names <= set(ns):
        return None

    class Safe:            # None과의 비교는 False
        def __init__(self, v):
            self.v = v

        def _cmp(self, o, op):
            o = o.v if isinstance(o, Safe) else o
            return False if self.v is None or o is None else op(self.v, o)

        def __gt__(self, o): return self._cmp(o, lambda a, b: a > b)
        def __lt__(self, o): return self._cmp(o, lambda a, b: a < b)
        def __ge__(self, o): return self._cmp(o, lambda a, b: a >= b)
        def __le__(self, o): return self._cmp(o, lambda a, b: a <= b)
        def __eq__(self, o): return self._cmp(o, lambda a, b: a == b)
        def __ne__(self, o): return not self.__eq__(o)
        def __bool__(self): return bool(self.v)

    env = {k: (v if isinstance(v, bool) else Safe(v)) for k, v in ns.items()}
    return bool(eval(expr, {"__builtins__": {}}, env))   # noqa: S307 — 이름은 위 namespace로 제한


def describe(s: Stock | None) -> str:
    if s is None:
        return "표본에 없음"
    if not s.scored:
        return "점수 없음"
    return " ".join(f"{PRESET_KR[p]} {s.rank[p]}/{s.n[p]}" for p in ("balanced", "value", "growth") if p in s.rank)


# ------------------------------------------------------------------ 특수 case·rule
def _earn(f: dict, tax: float) -> float | None:
    ni, oi = f["net_income"], f["operating_income"]
    if ni is None:
        return None if oi is None else tax * oi
    return ni if oi is None else min(ni, tax * oi)


def oneoff_cut(d: Data, s: Stock) -> tuple[bool, str]:
    """일회성 해(순이익 > 1.2 × 영업이익)에 저평가 이익 e = 0.78 × 영업이익이고, 저장된 지표가 그 e로 계산됐는가."""
    tax = float(d.cfg["after_tax"])
    ch = s.chain()
    if not ch:
        return False, "재무 없음"
    t = ch[0]
    if not (t["net_income"] and t["operating_income"] and t["net_income"] > 1.2 * t["operating_income"] > 0):
        return True, "최신 FY에 일회성 해 없음"
    es = [_earn(f, tax) for f in ch]
    e = min(es[0], sum(es) / 3) if len(es) == 3 and None not in es else es[0]
    mc = d.mcap.get(s.stock_id)
    got = s.raw.get("conservative_yield")
    ok = abs(es[0] - tax * t["operating_income"]) < 1e-6 and mc and got is not None and abs(got - e / mc) <= 1e-6 + 1e-4 * abs(e / mc)
    return bool(ok), (f"순이익/영업이익 {t['net_income'] / t['operating_income']:.1f}배 → e = {tax} × 영업이익, "
                      f"지표 {got:.4f} (기대 {e / mc:.4f})" if mc and got is not None else "시총·지표 없음")


def e_cons(d: Data, s: Stock) -> float | None:
    """score_metrics.sql과 같은 저평가 이익: 해마다 e(금융은 순이익), 3개 FY가 이어지면 min(e_t, 3년 평균)."""
    tax = float(d.cfg["after_tax"])
    es = [f["net_income"] if s.family == "financial" else _earn(f, tax) for f in s.chain()]
    if not es or es[0] is None:
        return None
    return min(es[0], sum(es) / 3) if len(es) == 3 and None not in es else es[0]


def common_share(d: Data, s: Stock) -> float | None:
    """국내 우선주 보정(D-029): KRX BPS 주식수(최신 FY 지배 자본 ÷ BPS)가 보통주보다 3% 넘게 많으면 보통주 수 ÷ BPS 주식수."""
    v, ch = d.val.get(s.stock_id, {}), s.chain()
    eq, bps, shares = (ch[0]["total_equity"] if ch else None), v.get("bps"), v.get("shares")
    if s.country != "KR" or not (eq and eq > 0 and bps and bps > 0 and shares and shares > 0) or eq / bps <= 1.03 * shares:
        return None
    return shares / (eq / bps)


def case_bobcat_currency(d: Data, s: Stock):
    """세후 보수 이익/시총이 KRX EPS ÷ 종가의 0.5~2배(D-026 — USD 공시가 원화 칸에 들어가면 1/1,422)."""
    v, got = d.val.get(s.stock_id, {}), s.raw.get("conservative_yield")
    if not v.get("eps") or not v.get("close") or got is None:
        return None, "KRX EPS·종가 또는 지표 없음"
    r = got / (v["eps"] / v["close"])
    return 0.5 <= r <= 2, f"지표 {got:.4f} vs KRX EPS÷종가 {v['eps'] / v['close']:.4f} (비율 {r:.2f})"


def rule_currency_krw(d: Data):
    """국내 표본에서 KRX EPS·BPS ÷ DB 재무 기준(순이익·지배 자본 ÷ 상장주식수)이 50배를 넘게(또는 1/50 미만으로) 어긋나는 종목 0개."""
    bad, checked = [], 0
    for s in d.stocks.values():
        v, ch = d.val.get(s.stock_id, {}), s.chain()
        if s.country != "KR" or not ch or not v.get("shares"):
            continue
        for krx, db in ((v.get("eps"), ch[0]["net_income"]), (v.get("bps"), ch[0]["total_equity"])):
            if krx and db and krx * db > 0:
                checked += 1
                r = krx / (db / v["shares"])
                if max(r, 1 / r) > 50:
                    bad.append(f"{s.ticker} {r:.0f}배")
                    break
    return not bad, f"{checked}개 값 중 50배 넘게 어긋남 {len(bad)} {bad[:6]}"


def case_negative_equity_bp(d: Data, s: Stock):
    """자본 ≤ 0이면 B/P가 비고 사유 '자본 음수'(D-027)."""
    reason = (s.dq.get("missing_metrics") or {}).get("book_yield", "")
    ok = "book_yield" not in s.raw and "자본 음수" in reason
    eq = s.chain()[0]["total_equity"] if s.chain() else None
    return ok, f"자본 {eq:,.0f} · B/P {'없음' if 'book_yield' not in s.raw else s.raw['book_yield']} · {reason or '사유 없음'}" \
        if eq is not None else f"재무 없음 · B/P {s.raw.get('book_yield')}"


def rule_negative_equity_no_bp(d: Data):
    """최신 FY 지배 자본(또는 BPS) ≤ 0인 종목 중 B/P 값이 있는 종목 0개 — 테마 평균에도 들어가지 않는다(D-027)."""
    def negative(s: Stock) -> bool:
        eq, bps = s.chain()[0]["total_equity"], d.val.get(s.stock_id, {}).get("bps")
        return (eq is not None and eq <= 0) or (bps is not None and bps <= 0)
    neg = [s for s in d.stocks.values() if s.chain() and negative(s)]
    left = [s.ticker for s in neg if "book_yield" in s.raw or "book_yield" in s.z_raw]
    return not left, f"자본 ≤ 0 {len(neg)}종목 {[s.ticker for s in neg][:12]} 중 B/P 있음 {len(left)} {left[:6]}"


def rule_oneoff_badge_wording(d: Data):
    """순이익 > 영업이익 배지는 사실만(D-029): 이름 '순이익 > 영업이익', '일회성 이익으로 보고' 같은 단정 문구 없음."""
    badges = [(s.ticker, b) for s in d.stocks.values() for b in s.dq.get("badges", []) if b.get("code") == "oneoff"]
    bad = [t for t, b in badges if b.get("label") != "순이익 > 영업이익" or "일회성 이익으로 보고" in (b.get("detail") or "")]
    page = stock_page()
    js = page.read_text(encoding="utf-8") if page else ""
    left = "일회성 이익으로 보고" in js
    return not bad and not left, f"배지 {len(badges)}개 중 단정 문구 {len(bad)} {bad[:6]}" + (" · 화면 코드에 남음" if left else "")


def rule_preferred_share_basis(d: Data):
    """KRX BPS 주식수가 보통주보다 3% 넘게 많은 국내 종목에서 세후 보수 이익/시총 = e × 보통주 수 ÷ BPS 주식수 ÷ 보통주 시총(D-029)."""
    checked, bad = [], []
    for s in d.stocks.values():
        c = common_share(d, s)
        got, e = s.raw.get("conservative_yield"), (e_cons(d, s) if c else None)
        v = d.val.get(s.stock_id, {})
        mc = d.mcap.get(s.stock_id) or ((v.get("shares") or 0) * (v.get("close") or 0))
        if c is None or got is None or e is None or not mc:
            continue
        checked.append(f"{s.ticker}(+{1 / c - 1:.0%})")
        if abs(got - e * c / mc) > 1e-6 + 1e-4 * abs(e * c / mc):
            bad.append(s.ticker)
    if not checked:
        return None, "BPS 주식수가 보통주보다 3% 넘게 많은 종목 없음 — 판정 대상 없음"
    return not bad, f"대상 {len(checked)}종목 {checked[:8]} · 다름 {len(bad)} {bad[:6]}"


def has_badge(s: Stock | None, code: str) -> bool:
    return s is not None and any(b.get("code") == code for b in s.dq.get("badges", []))


def fiscal_mode(d: Data, country: str) -> date | None:
    ends = Counter(s.chain()[0]["period_end"] for s in d.stocks.values() if s.country == country and s.chain())
    return ends.most_common(1)[0][0] if ends else None


def rule_r1(d: Data):
    bad = []
    for c in ("US", "KR"):
        for p in PRESET_KR:
            for s in d.top(c, p, 10):
                ch = s.chain()
                if ch and ch[0]["net_income"] and ch[0]["operating_income"] is not None and ch[0]["net_income"] > 0 \
                        and (ch[0]["operating_income"] <= 0 or ch[0]["net_income"] > 2 * ch[0]["operating_income"]):
                    ok, _ = oneoff_cut(d, s)
                    if not ok:
                        bad.append(f"{c}{PRESET_KR[p]}:{s.ticker}")
    return not bad, f"잘리지 않은 일회성 {len(bad)}개 {bad[:6]}"


def rule_r2(d: Data):
    out = {}
    for c in ("US", "KR"):
        cagr = [s.raw["revenue_cagr2"] for s in d.general(c) if "revenue_cagr2" in s.raw]
        med = st.median(cagr) if cagr else 0
        hit = []
        for s in d.top(c, "growth", 20):
            ch = s.chain()
            if len(ch) == 3 and (ch[2]["operating_income"] or 0) < 0 and s.raw.get("revenue_cagr2", -9) <= med:
                hit.append(s.ticker)
        out[c] = hit
    return all(len(v) <= 2 for v in out.values()), " / ".join(f"{c} {len(v)} {v}" for c, v in out.items())


def rule_r3(d: Data):
    out = {}
    for c in ("US", "KR"):
        hit = []
        for s in d.top(c, "value", 20):
            ch = s.chain()
            rv = [f["revenue"] for f in ch]
            if len(rv) == 3 and None not in rv and rv[0] < rv[1] < rv[2]:
                hit.append(s.ticker)
        out[c] = hit
    return all(len(v) <= 2 for v in out.values()), " / ".join(f"{c} {len(v)} {v}" for c, v in out.items())


def rule_r4(d: Data):
    out = {c: [s.ticker for s in d.top(c, "value", 10) if s.commodity or (s.country, s.ticker) in MEMORY] for c in ("US", "KR")}
    return all(len(v) <= 3 for v in out.values()), " / ".join(f"{c} {len(v)} {v}" for c, v in out.items())


def rule_r5(d: Data):
    miss, total = [], 0
    for c in ("US", "KR"):
        mode = fiscal_mode(d, c)
        for s in d.stocks.values():
            if s.country != c or not s.scored or not s.chain() or mode is None:
                continue
            if abs((s.chain()[0]["period_end"] - mode).days) > FISCAL_GAP_DAYS:
                total += 1
                if not has_badge(s, "fiscal_gap"):
                    miss.append(s.ticker)
    return not miss, f"대상 {total}종목 · 배지 없음 {len(miss)} {miss[:6]}"


def rule_r6(d: Data):
    """① 점수 = 100 × (n − 순위) / n ② 종합이 확실히 큰 종목(반올림 오차 밖)의 점수가 더 작지 않음
    ③ 점수 20점 구간 라벨 = 실제 상위 p% 20% 구간(화면 scoreBand와 같은 floor(점수 / 20))."""
    formula = order = band = 0
    for (p, _, _), lst in d.groups.items():
        n = len(lst)
        for s in lst:
            pos = s.rank[p]
            if abs(s.pct[p] - (100 * (n - pos) / n if n > 1 else 50)) > 0.01:
                formula += 1
            top = 100 * pos / n
            band_rank = 4 if top <= 20 else 3 if top <= 40 else 2 if top <= 60 else 1 if top <= 80 else 0
            if n > 1 and min(4, int(s.pct[p] // 20)) != band_rank:
                band += 1
        srt = sorted(lst, key=lambda s: -s.composite[p])
        order += sum(1 for a, b in zip(srt, srt[1:]) if a.composite[p] > b.composite[p] + 2e-4 and a.pct[p] < b.pct[p])
    return formula == order == band == 0, f"식 불일치 {formula} · 종합 순서 뒤집힘 {order} · 구간 라벨 불일치 {band}"


def rule_r7(d: Data):
    parts, ok = [], True
    for c in ("US", "KR"):
        lst = [s for s in d.stocks.values() if s.country == c and s.scored]
        k = sum(1 for s in lst if s.dq.get("badges"))
        share = k / len(lst) if lst else 0
        ok &= share <= 0.30
        parts.append(f"{c} {share:.1%}")
    return ok, " / ".join(parts) + " (원자재 배지 제외)"


def rule_r8(d: Data):
    worst = {}
    for c in ("US", "KR"):
        for p, w in d.weights.items():
            lst = [s for s in d.general(c) if p in s.composite]
            base = {s.stock_id for s in sorted(lst, key=lambda s: -s.composite[p])[:10]}
            mins = []
            for f in FACTORS:
                for dd in (0.1, -0.1):
                    if not 0 <= w[f] + dd <= 1:
                        continue
                    new = w[f] + dd
                    w2 = {k: (new if k == f else w[k] * (1 - new) / (1 - w[f])) for k in FACTORS}
                    comp = {s.stock_id: sum(w2[k] * s.factors.get(k, 0.0) for k in FACTORS) for s in lst}
                    top = set(sorted(comp, key=lambda k: -comp[k])[:10])
                    mins.append(len(base & top))
            worst[f"{c}{PRESET_KR[p]}"] = min(mins)
    return all(v >= 7 for v in worst.values()), " ".join(f"{k} {v}" for k, v in worst.items())


def rule_r9(d: Data):
    """모델 버전이 바뀌기 전 마지막 계산일에 점수가 있던 종목 중, 재무가 있는데 칸이 비어 점수를 잃은 종목.
    재무가 아예 없는 종목(해외 상장 등)은 '재무 정보가 없어 표기할 수 없습니다'로 막는 것이 설계라 따로 센다(D-014).
    재무를 받던 종목이 0건이 되는 경우(XOM CIK 변경)는 SEC-tags-scored 같은 종목 case로 잡는다."""
    ver = d.cfg["model_version"]
    prev = d.conn.execute(text("""SELECT MAX(as_of) FROM stock_scores
                                  WHERE as_of < :d AND COALESCE(data_quality->>'model_version', '') <> :v"""),
                          {"d": d.as_of, "v": ver}).scalar()
    if prev is None:
        return True, "이전 모델 점수 없음 — 비교 대상 없음"
    before = set(d.conn.execute(text("""SELECT st.stock_id FROM stock_scores st JOIN scoring_presets p USING (preset_id)
                                        WHERE st.as_of = :d AND p.code = 'balanced' AND st.score IS NOT NULL"""),
                                {"d": prev}).scalars())
    lost = [s for sid, s in d.stocks.items() if sid in before and not s.scored]
    no_fin = [s.ticker for s in lost if s.family != "none" and not s.fins]
    data_loss = [s.ticker for s in lost if s.family != "none" and s.fins
                 and s.dq.get("score_null_code", "no_financials") == "no_financials"]
    intended = [s.ticker for s in lost if s.family == "none"]
    fin = [s.ticker for s in lost if s.dq.get("score_null_code") == "financial_profile"]
    return not data_loss, (f"이전 {prev}: 재무 칸 누락으로 잃음 {len(data_loss)} {data_loss[:15]} · "
                           f"재무 없음(표기 안 함, D-014) {len(no_fin)} {no_fin[:15]} · 점수 없음 테마 {len(intended)}"
                           + (f" · 금융 업종 비교로 바뀜(D-028) {len(fin)}" if fin else ""))


# ── 독립 기준(개발산출물/11 5절) ──
def _fins3(s: Stock) -> list[dict]:
    return s.fins[-3:]


def i1(s: Stock) -> bool:
    return s.family != "financial" and (s.ticker in TRUSTS or s.ticker in FIN_LINKED or s.theme == "지주회사"
                                        or (s.country == "KR" and bool(HOLD_RE.search(s.name or ""))))


def i2(s: Stock) -> bool:
    rv = [f["revenue"] for f in _fins3(s)]
    return len(rv) == 3 and None not in rv and rv[0] > rv[1] > rv[2]


def i3(s: Stock) -> bool:
    oi = [f["operating_income"] for f in _fins3(s) if f["operating_income"] is not None]
    return len(oi) >= 2 and any(x <= 0 for x in oi)


def independent(d: Data) -> tuple[int, int, dict]:
    vol90, volmed = {}, {}
    for c in ("US", "KR"):
        v = sorted(s.raw["volatility"] for s in d.general(c) if "volatility" in s.raw)
        if v:
            vol90[c], volmed[c] = v[int(len(v) * 0.9)], st.median(v)

    def i5(s):
        return "volatility" in s.raw and c_ok(s) and s.raw["volatility"] >= vol90[s.country]

    def c_ok(s):
        return s.country in vol90

    rules = {"aggressive": (i1, i2, i3), "growth": (i1, i2, i3), "balanced": (i1, i2, i3), "value": (i1, i2, i3, i5)}
    weird, per = 0, {}
    for c in ("US", "KR"):
        for p, fns in rules.items():
            hit = [s.ticker for s in d.top(c, p, 10) if any(fn(s) for fn in fns)]
            per[f"{c}{PRESET_KR[p]}"] = len(hit)
            weird += len(hit)

    def good(s):
        f = _fins3(s)
        oi, rv = [x["operating_income"] for x in f], [x["revenue"] for x in f]
        if len(f) < 3 or None in oi or any(x is None or x <= 0 for x in rv) or any(x <= 0 for x in oi):
            return False
        yrs = (f[-1]["period_end"] - f[0]["period_end"]).days / 365.25
        cagr = (rv[-1] / rv[0]) ** (1 / yrs) - 1 if yrs > 0 else 0
        margin = st.median([o / r for o, r in zip(oi, rv)])
        v = s.raw.get("volatility")
        return (cagr >= 0.03 and margin >= 0.10 and not oi[-1] > (oi[-2] + oi[-3]) and v is not None
                and s.country in volmed and v <= volmed[s.country] * 1.2)

    goods = [s for s in d.stocks.values() if s.family == "general" and good(s)]
    fn = sum(1 for s in goods if not s.scored or s.pct.get("balanced", 0) < 50)
    return weird, fn, per


def rule_r10(d: Data):
    """경계는 측정 잡음(k 3~8에서 이상 12~16, 거짓 음성 25~27)에 맞춘다(D-021)."""
    weird, fn, per = independent(d)
    return weird <= 16 and fn <= 27, f"이상 종목 {weird}(≤16) · 우량 거짓 음성 {fn}(≤27) · {per}"


def rule_trap(d: Data):
    """가치 함정 신호는 중립화하지 않아 최종 값(z_adj)도 0 이하 — 문자 그대로 감점만(D-018)."""
    vals = [s.z_adj["trap_signal"] for s in d.stocks.values() if "trap_signal" in s.z_adj]
    pos = [v for v in vals if v > 0]
    return not pos, f"{len(vals)}종목 중 양수 {len(pos)}" + (f" (최대 +{max(pos):.2f})" if pos else "")


def raw_factors(d: Data) -> dict[int, dict[str, float]]:
    """중립화 전 값(z_raw)으로 만든 팩터 F — score_aggregate.sql f1과 같은 규칙(지표 가중 평균, 재무 이력 축소)."""
    f0: dict[int, dict[str, float]] = {}
    for s in d.stocks.values():
        fs = {}
        for f in FACTORS:
            pairs = [(METRICS[m].weight, v) for m, v in s.z_raw.items() if METRICS[m].factor == f]
            if pairs:
                fs[f] = sum(w * v for w, v in pairs) / sum(w for w, _ in pairs)
        n = s.dq.get("fy_history") or 0
        if "value" in fs and n < 3:
            fs["value"] *= n / 3
        if fs:
            f0[s.stock_id] = fs
    return f0


def raw_composites(d: Data) -> dict[str, dict[int, float]]:
    """중립화 전 값(z_raw)으로 같은 모델을 다시 합산한 프리셋별 종합 — score_aggregate.sql과 같은 규칙
    (raw_factors → 국가·묶음 안 재표준화, 빠진 팩터 0, 저평가·수익성 필수, 유효 팩터 ≥ 3)."""
    f0 = raw_factors(d)
    fz: dict[int, dict[str, float]] = defaultdict(dict)
    for c in ("US", "KR"):
        for fam in ("general", "financial"):
            ids = [sid for sid in f0 if d.stocks[sid].country == c and d.stocks[sid].family == fam]
            for f in FACTORS:
                xs = {sid: f0[sid][f] for sid in ids if f in f0[sid]}
                sd = st.stdev(xs.values()) if len(xs) > 1 else 0.0
                m = st.fmean(xs.values()) if xs else 0.0
                for sid, v in xs.items():
                    fz[sid][f] = (v - m) / sd if sd > 0 else 0.0
    out: dict[str, dict[int, float]] = {}
    for p, w in d.weights.items():
        out[p] = {sid: sum(w[f] * v for f, v in fs.items()) for sid, fs in fz.items()
                  if all(f in fs for f in REQUIRED_FACTORS) and len(fs) >= MIN_FACTORS}
    return out


def weak_theme_firsts(d: Data, top_n: int = 20, share: float = 0.3) -> tuple[int, dict]:
    """프리셋 top20(시장 2 × 프리셋 4) 중 '중립화 전 테마 평균 종합이 같은 시장 테마 중 하위 30%인 테마의 1등' 수.
    테마 = 점수 있는 general 구성원 2개 이상인 주 테마, 1등 = 그 테마 안 프리셋 순위 1위(라운드 2 4-3 정의)."""
    raw = raw_composites(d)
    total, per = 0, {}
    for c in ("US", "KR"):
        for p in PRESET_KR:
            members: dict[str, list[Stock]] = defaultdict(list)
            for s in d.general(c):
                if s.theme and p in s.rank and s.stock_id in raw[p]:
                    members[s.theme].append(s)
            themes = {t: st.fmean(raw[p][s.stock_id] for s in lst) for t, lst in members.items() if len(lst) >= 2}
            weak = set(sorted(themes, key=themes.get)[:math.ceil(share * len(themes))])
            firsts = {min(members[t], key=lambda s: s.rank[p]).stock_id for t in weak}
            hit = [s.ticker for s in d.top(c, p, top_n) if s.stock_id in firsts]
            per[f"{c}{PRESET_KR[p]}"] = hit
            total += len(hit)
    return total, per


def rule_theme_position_raw(d: Data):
    """화면 '소속 테마 위치'(scoring.theme_positions — 상세 API가 쓰는 값)가 중립화 전 F의 테마 평균 순위를
    여기서 따로 계산한 값과 같은가(D-020). 테마 = 점수 있는 구성원 2개 이상, 순위 = 1 + 평균이 더 큰 테마 수."""
    f0 = raw_factors(d)
    checked, diff = 0, []
    for c in ("US", "KR"):
        for fam in ("general", "financial"):
            got = {t["group_name"]: t["factors"] for t in theme_positions(d.conn, d.as_of, c, fam).values()}
            members: dict[str, list[int]] = defaultdict(list)
            for s in d.stocks.values():
                if s.country == c and s.family == fam and s.scored and s.theme and s.stock_id in f0:
                    members[s.theme].append(s.stock_id)
            for f in FACTORS:
                avg = {t: st.fmean(f0[sid][f] for sid in ids if f in f0[sid]) for t, ids in members.items()
                       if sum(1 for sid in ids if f in f0[sid]) >= 2}
                for t, a in avg.items():
                    exp = (1 + sum(1 for b in avg.values() if b > a + 1e-9), len(avg))
                    g = got.get(t, {}).get(f)
                    checked += 1
                    if g is None or (g["position"], g["total"]) != exp:
                        diff.append(f"{c}{'·금융' if fam == 'financial' else ''} {t} {f} {g and g['position']} vs {exp[0]}")
            extra = [t for t in got if t not in members]
            diff += [f"{c} {t} 화면에만 있음" for t in extra]
    return not diff and checked > 0, f"테마·팩터 {checked}칸 중 차이 {len(diff)} {diff[:6]}"


def _ranks(xs: list[float]) -> list[float]:
    """오름차순 평균 순위(같은 값은 평균)."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(a: list[float], b: list[float]) -> float | None:
    """순위 상관(같은 값은 평균 순위). 한쪽이 모두 같으면 None."""
    ra, rb = _ranks(a), _ranks(b)
    if len(set(ra)) < 2 or len(set(rb)) < 2:
        return None
    return st.correlation(ra, rb)


def rule_clip_order(d: Data, share: float = 0.07):
    """지표마다 같은 시장·general 묶음에서 원값(방향 반영) 상위 7% 안의 최종 z(z_adj) 순서가 원값 순서와 Spearman ≥ 0.5인가(D-019).
    로버스트 Z를 ±3으로 자른 뒤 중립화하면 잘린 묶음 안 순서가 테마 약함 순서가 됐다(라운드 2 R2-1). 상위 값이 모두 같은 지표는 뺀다."""
    out, worst = [], None
    for c in ("US", "KR"):
        for m, md in METRICS.items():
            lst = [s for s in d.general(c) if m in s.raw and m in s.z_adj]
            lst.sort(key=lambda s: -md.direction * s.raw[m])
            top = lst[:math.ceil(share * len(lst))]
            r = spearman([md.direction * s.raw[m] for s in top], [s.z_adj[m] for s in top]) if len(top) >= 3 else None
            if r is None:
                continue
            out.append((f"{c} {m}", r))
            worst = r if worst is None else min(worst, r)
    bad = [f"{k} {r:.2f}" for k, r in out if r < 0.5]
    return worst is not None and not bad, (f"{len(out)}개 지표 최저 {worst:.2f}" if worst is not None else "지표 없음") +         (f" · 0.5 미만 {bad}" if bad else "")


def rule_weak_theme_first(d: Data):
    total, per = weak_theme_firsts(d)
    return True, f"{total}개 (기록만) · " + " ".join(f"{k} {len(v)}{v if v else ''}" for k, v in per.items())


def case_theme(d: Data, c: dict):
    """주 테마 == expected (D-024 — 연결 매출 최대 사업으로 직접 지정한 종목). 비교 표본 밖(상장 목록) 종목도 DB 주 테마로 본다.
    DB에 없는 종목은 판정하지 못한 것으로 남긴다(미검증)."""
    country = MARKET_COUNTRY.get(c.get("market") or "")
    rows = dict(d.conn.execute(text("""
        SELECT s.ticker, t.theme FROM stocks s JOIN markets m ON m.market_id = s.market_id
        LEFT JOIN v_stock_theme t ON t.stock_id = s.stock_id
        WHERE m.country = :c AND s.ticker = ANY(:t)"""), {"c": country, "t": [str(x) for x in c["ticker"]]}).all())
    expected = {str(k): v for k, v in c["expected"].items()}
    wrong = [f"{t} {rows[t]}≠{e}" for t, e in expected.items() if t in rows and rows[t] != e]
    missing = [t for t in expected if t not in rows]
    note = f"{len(expected) - len(missing)}종목 중 다름 {len(wrong)} {wrong[:6]}" + (f" · DB에 없음 {missing}" if missing else "")
    return (None if missing and not wrong else not wrong), note


def case_theme_unjudged(d: Data, c: dict):
    """D-024 기준으로 판정하지 못한 종목 — 업종 코드 그대로인 지금 주 테마를 보이고 미검증(None)으로 센다."""
    rows = dict(d.conn.execute(text("""
        SELECT s.ticker, t.theme FROM stocks s LEFT JOIN v_stock_theme t ON t.stock_id = s.stock_id
        WHERE s.ticker = ANY(:t)"""), {"t": [str(x) for x in c["ticker"]]}).all())
    return None, "판정 못함 " + " · ".join(f"{t} {rows.get(str(t), 'DB에 없음')}" for t in c["ticker"])


def rule_top20_theme_reviewed(d: Data):
    """프리셋 top20(시장 2 × 프리셋 4) 중 업종 코드로만 분류된(themes.tickers에 직접 지정되지 않은) 종목 — 기록만(D-024).
    새로 상위에 오른 종목의 주 테마를 라운드마다 사람이 사업보고서로 확인하게 하려는 목록이다."""
    from app.ingest.sectors import themes
    direct = {x for t in themes() for x in t.tickers}
    seen, per = set(), {}
    for c in ("US", "KR"):
        for p in PRESET_KR:
            hit = [s.ticker for s in d.top(c, p, 20) if s.ticker not in direct]
            per[f"{c}{PRESET_KR[p]}"] = hit
            seen |= {(c, t) for t in hit}
    return True, f"고유 {len(seen)}종목 (기록만) · " + " ".join(f"{k} {len(v)}{v if v else ''}" for k, v in per.items())


def rule_financial_no_composite(d: Data):
    """금융 묶음은 종합 점수·프리셋 순위·5단계 라벨이 없다(score_null_code = financial_profile), 홈 금융 탭에 순위 목록이 없다(D-028)."""
    fin = [s for s in d.stocks.values() if s.family == "financial" and s.dq]
    bad = [s.ticker for s in fin if s.composite or s.pct or s.dq.get("score_null_code") != "financial_profile"]
    listed = 0
    for c in ("US", "KR"):
        listed += len(d.conn.execute(sql("home_attractiveness"), {"country": c, "limit": 20, "preset": "balanced",
                                                                  "user_id": 0, "family": "financial"}).all())
    page = stock_page("home.js")
    tab = page is None or "getFinancialPeers" in page.read_text(encoding="utf-8")
    return bool(fin) and not bad and not listed and tab, (
        f"금융 {len(fin)}종목 중 종합 점수 있음 {len(bad)} {bad[:6]} · 홈 금융 순위 행 {listed}"
        + ("" if tab else " · 홈 금융 탭이 업종 비교가 아님"))


def case_financial_pb_roe_view(d: Data):
    """종목 화면(금융): 같은 하위 업종 P/B·ROE(3년 평균)·P/E와 산점도 위치 — 표본 ≥ 8이면 회귀선, 아니면 중앙값(D-028)."""
    from app.services.financial_profile import REGRESSION_MIN, financial_overview
    wrong, groups = [], []
    for c in ("US", "KR"):
        for g in financial_overview(d.conn, c):
            groups.append(f"{c} {g['theme']} {g['n']}개 {g['method']}")
            if (g["method"] == "regression") != (g["n"] >= REGRESSION_MIN) or any(
                    m["pb"] is not None and m["roe3"] is not None and not m["position"] for m in g["members"]):
                wrong.append(f"{c} {g['theme']}")
    screen, note = screen_check(["financial_profile", "ROE 대비 P/B", "회귀선", "중앙값", "P/E"], [])
    if screen is None:
        return None, note
    return bool(groups) and not wrong and screen, f"{' · '.join(groups)} · 규칙 어긋남 {wrong} · {note}"


def case_growth_label(d: Data):
    """팩터 이름 '과거 실적 성장', 성장 프리셋 설명에 '미래 성장 예측이 아닙니다'(D-032) — 화면·DB 프리셋·09."""
    screen, note = screen_check(['label: "과거 실적 성장"'], ['label: "성장성"'])
    desc = d.conn.execute(text("SELECT description FROM scoring_presets WHERE code = 'growth'")).scalar() or ""
    doc = doc_09()
    in_doc = doc is None or "과거 실적 성장" in doc.read_text(encoding="utf-8")
    ok = "미래 성장 예측이 아닙니다" in desc
    if screen is None:
        return None, note
    return screen and ok and in_doc, f"{note} · 성장 프리셋 설명 '{desc}'" + ("" if in_doc else " · 09에 없음")


def case_home_family_mix(d: Data):
    bad = []
    for c in ("US", "KR"):
        for fam in ("general", "financial"):
            rows = d.conn.execute(sql("home_attractiveness"), {"country": c, "limit": 20, "preset": "balanced",
                                                                "user_id": 0, "family": fam}).mappings().all()
            bad += [r["ticker"] for r in rows if d.stocks.get(r["stock_id"]) and d.stocks[r["stock_id"]].family != fam]
    return not bad, "family 섞임 없음" if not bad else f"섞임 {bad[:6]}"


def screen_check(markers: list[str], forbidden: list[str]):
    page = stock_page()
    if page is None:
        return None, "frontend 폴더 없음 — 확인 못함"
    js = page.read_text(encoding="utf-8")
    miss = [m for m in markers if m not in js]
    left = [m for m in forbidden if m in js]
    return not miss and not left, ("화면 코드 확인" if not miss and not left else f"없음 {miss} · 남음 {left}")


def case_buyback(d: Data):
    dist = []
    for s in d.general("US"):
        ch = s.chain()
        if ch and "safety" in s.factors:
            eq_neg = (ch[0]["total_debt"] or 0) >= (ch[0]["total_assets"] or 1)       # 자본 ≤ 0 ⇔ 부채 ≥ 자산
            if eq_neg and (ch[0]["operating_income"] or 0) < 0:
                dist.append(s.factors["safety"])
    med = st.median(dist) if dist else None
    vals = {t: (d.by_ticker(t, "US").factors.get("safety") if d.by_ticker(t, "US") else None) for t in ("MCK", "PM")}
    ok = med is not None and all(v is not None and v > med for v in vals.values())
    return ok, f"MCK {vals['MCK']} · PM {vals['PM']} vs 잠식+적자 중앙값 {med} (n={len(dist)})"


def _with_stock(d: Data, c: dict, fn):
    s = d.by_ticker(str(c["ticker"]), c.get("market"))
    return fn(d, s) if s is not None else (False, "표본에 없음")


def _all_stocks(d: Data, c: dict, fn):
    """ticker 목록의 종목마다 fn — 모두 통과해야 통과, 하나라도 판정 못하면(None) 판정 못함."""
    out = []
    for t in c["ticker"]:
        s = d.by_ticker(str(t), c.get("market"))
        out.append((t, *(fn(d, s) if s is not None else (None, "표본에 없음"))))
    res = [r for _, r, _ in out]
    return (None if None in res else all(res)), " · ".join(f"{t}: {v}" for t, _, v in out)


def case_cj_history(s: Stock):
    years = [f["period_end"].year for f in s.chain()]
    return len(years) >= 3 and 2024 in years, f"이어지는 FY {years}"


# ── 라운드 4 데이터 (수정 4 PR A, D-039) — 재무가 어느 경로로 들어왔는지(financial_statements.notes) ──
def _sample_fy(d: Data, country: str | None = None) -> list:
    return d.conn.execute(text("""
        SELECT s.stock_id, s.ticker, m.country, f.period_end, f.notes, f.total_equity, f.total_assets, f.total_debt
        FROM financial_statements f
        JOIN stocks s  ON s.stock_id = f.stock_id
        JOIN markets m ON m.market_id = s.market_id
        WHERE f.period_type = 'FY' AND s.is_active AND s.coverage <> 'listed'
          AND (CAST(:c AS text) IS NULL OR m.country = :c)
        ORDER BY s.stock_id, f.period_end"""), {"c": country}).all()


def _path(notes: str | None) -> str | None:
    return notes.split(";")[0].strip().removeprefix("path=") if notes and notes.startswith("path=") else None


def rule_dart_fy_path(d: Data, c: dict):
    """국내 표본 FY는 모두 API 한 경로이고, 5년 창 안에서 빠진 해는 provider가 '직전 연도 없음'(그해 보고서도, 다음 해 보고서
    전기값도 없음)을 남겼을 때만 — 일괄 경로(당기만)·경로 기록 없는 옛 행이 섞이면 실패(R4-1)."""
    by: dict[str, list] = defaultdict(list)
    for r in _sample_fy(d, "KR"):
        by[r.ticker].append(r)
    other = sorted({t for t, rs in by.items() for r in rs if _path(r.notes) != "DART_API"})
    gaps = []
    for t, rs in by.items():
        years = {r.period_end.year: r for r in rs}
        top = max(years)
        for y, r in years.items():
            if top - 4 < y and y - 1 not in years and "직전 연도 없음" not in (r.notes or ""):
                gaps.append(f"{t} {y - 1}")
    named = " · ".join(f"{t} FY {sorted(r.period_end.year for r in by.get(str(t), [])) or '없음'}" for t in c.get("ticker", []))
    missing = [t for t in c.get("ticker", []) if str(t) not in by]
    ok = not other and not gaps and not missing
    return ok, (f"국내 표본 {len(by)}종목 · API 밖 경로 {len(other)} {other[:10]} · 사유 없이 빠진 해 {len(gaps)} {gaps[:10]} · {named}")


def rule_sec_op_path(d: Data):
    """미국 표본 FY가 모두 현재 코드 경로(SEC_API, 빈 결산기 보완은 YFINANCE)로 쓴 행 — 수정 1 이전 경로 값 0(R4-2)."""
    rows = _sample_fy(d, "US")
    old = sorted({r.ticker for r in rows if _path(r.notes) not in ("SEC_API", "YFINANCE")})
    yf = sorted({r.ticker for r in rows if _path(r.notes) == "YFINANCE"})
    return not old, (f"미국 표본 FY {len(rows)}행 · 현재 코드 경로가 아닌 종목 {len(old)} {old[:15]}"
                     f" · yfinance 보완 결산기가 있는 종목 {len(yf)} {yf[:10]}")


def rule_lp_equity(d: Data):
    """자본이 정확히 0인데 자산 − 부채가 0이 아니면 신고값 0(파트너십)을 그대로 쓴 것 — 0개여야 함(R4-9)."""
    bad = sorted({r.ticker for r in _sample_fy(d) if r.total_equity is not None and r.total_equity == 0
                  and r.total_assets is not None and r.total_debt is not None and r.total_assets - r.total_debt != 0})
    lp = sorted({r.ticker for r in _sample_fy(d) if "total_equity←PartnersCapital" in (r.notes or "")
                 or "total_equity←자산−부채" in (r.notes or "")})
    return not bad, f"자본 0 · 자산−부채 ≠ 0: {len(bad)} {bad} · 파트너 자본·자산−부채로 채운 종목 {lp[:10]}"


# ── 라운드 4 데이터 (수정 4 PR B, D-039·D-036) — 표본·시가총액 ──
def rule_adr_mcap(d: Data):
    """미국 시가총액 순위 상위 300 중 재무가 있는 종목은 순위에 쓴 시가총액 ÷ 총자산 ≤ 200
    (AKTX — 매출 0인데 SEC 원주 수 × ADS 종가로 1.19조 달러·cap_rank 16, R4-3). 매출 1억 달러 미만은 기록만 — 매출 없는
    바이오(RVMD: yfinance 시총 399억·총자산의 17배)는 부푼 값이 아니다. 재무가 없는 상장 목록 종목은 셀 수 없어 따로 적는다."""
    rows = d.conn.execute(text("""
        SELECT s.ticker, s.cap_rank, s.cap_usd, f.revenue, f.total_assets
        FROM stocks s JOIN markets m ON m.market_id = s.market_id
        LEFT JOIN LATERAL (SELECT x.revenue, x.total_assets FROM financial_statements x
                           WHERE x.stock_id = s.stock_id AND x.period_type = 'FY' AND x.total_assets > 0
                           ORDER BY x.period_end DESC LIMIT 1) f ON true
        WHERE m.country = 'US' AND s.cap_rank <= 300 ORDER BY s.cap_rank""")).all()
    if not rows or all(r.cap_usd is None for r in rows):
        return None, "시가총액 순위(cap_usd)가 아직 없음 — background 순위 뒤 확인"
    checked = [r for r in rows if r.total_assets is not None and r.cap_usd is not None]
    def show(r):
        return (f"{r.ticker}(#{r.cap_rank} 매출 {0 if r.revenue is None else float(r.revenue) / 1e8:.1f}억·시총/자산 "
                f"{float(r.cap_usd / r.total_assets):.0f})")
    bad = [show(r) for r in checked if r.cap_usd > 200 * r.total_assets]
    low = [show(r) for r in checked if r.revenue is None or r.revenue < 1e8]
    return not bad, (f"상위 300 중 재무 있는 {len(checked)}종목 확인 · 위반 {len(bad)} {bad[:8]} · 매출 1억 달러 미만(기록만) "
                     f"{len(low)} {low[:8]} · 재무 없어 못 봄 {len(rows) - len(checked)}")


def rule_multiclass_ranked(d: Data, c: dict):
    """주식 종류가 여럿인 회사(SEC frames 발행주식수가 비는 회사)도 시가총액 순위에 들어옴(R4-4 — V·MA가 표본 밖이었다)."""
    rows = dict(d.conn.execute(text("""SELECT s.ticker, s.cap_rank FROM stocks s JOIN markets m ON m.market_id = s.market_id
                                       WHERE m.country = 'US' AND s.ticker = ANY(:t)"""), {"t": [str(t) for t in c["ticker"]]}).all())
    miss = [t for t in c["ticker"] if rows.get(str(t)) is None]
    return not miss, " · ".join(f"{t} {rows.get(str(t)) or '순위 없음'}" for t in c["ticker"])


def rule_halted(d: Data):
    """거래정지(마지막 일봉이 같은 국가 표본의 최근 21번째 거래일보다 앞섬)는 점수 없음·비교군 아님(R4-7 — 버킷스튜디오)."""
    from app.ingest.benchmark import HALTED_SQL                  # 선정과 같은 기준
    ids = list(d.conn.execute(text(HALTED_SQL)).scalars())
    rows = d.conn.execute(text("""
        SELECT s.ticker, s.name, s.coverage, lp.trade_date,
               EXISTS (SELECT 1 FROM stock_scores x WHERE x.stock_id = s.stock_id AND x.as_of = :d AND x.score IS NOT NULL) AS scored
        FROM stocks s JOIN v_latest_price lp ON lp.stock_id = s.stock_id WHERE s.stock_id = ANY(:ids)"""),
        {"ids": ids, "d": d.as_of}).all()
    bad = [f"{r.ticker} {r.name}({r.trade_date}, {'점수' if r.scored else ''}{' 비교군' if r.coverage == 'benchmark' else ''})"
           for r in rows if r.scored or r.coverage == "benchmark"]
    return not bad, (f"거래정지 {len(rows)}종목 — 점수 있거나 비교군 {len(bad)} {bad[:8]} · "
                     + ", ".join(f"{r.ticker} {r.name} {r.trade_date} {r.coverage}" for r in rows[:6]))


def case_spinoff(d: Data, c: dict):
    """분할(config corporate_actions) 완료일이 최신 FY 결산일보다 뒤면 저평가 지표 없음 + 사유(R4-8 — HON)."""
    from app.ingest.universe import load_universe
    out, res = [], []
    for a in load_universe().corporate_actions:
        s = d.by_ticker(str(a["ticker"]), a["market"])
        if s is None:
            out.append(f"{a['ticker']} 표본에 없음")
            continue
        end = s.fins[-1]["period_end"] if s.fins else None
        if end is not None and end >= a["date"]:
            out.append(f"{s.ticker} 최신 FY {end} ≥ 분할 {a['date']} — 해당 없음")
            continue
        value = [m for m in ("conservative_yield", "book_yield", "trap_signal") if m in s.raw]
        reason = (s.dq.get("missing_metrics") or {}).get("conservative_yield", "")
        ok = not value and "분할" in reason and s.dq.get("score_null_code") == "corporate_action"
        res.append(ok)
        out.append(f"{s.ticker} 최신 FY {end} · 분할 {a['date']} · 저평가 지표 {value or '없음'} · {s.dq.get('score_null_code')}")
    return (all(res) if res else None), " · ".join(out) or "분할 목록 없음"


SPECIAL = {
    "KCC-oneoff-cut": lambda d, c: _with_stock(d, c, oneoff_cut),
    "MICHANG-oneoff-cut": lambda d, c: _with_stock(d, c, oneoff_cut),
    "KCC-MICHANG-badge": lambda d, c: (all(has_badge(d.by_ticker(t, c.get("market")), "oneoff") for t in c["ticker"]),
                                        " · ".join(f"{t} {'있음' if has_badge(d.by_ticker(t, c.get('market')), 'oneoff') else '없음'}"
                                                   for t in c["ticker"])),
    "HOME-family-mix": lambda d, c: case_home_family_mix(d),
    "SCREEN-no-phi-number": lambda d, c: screen_check(["상위 ${topPercent", "개 중 <strong>"], ["toPos(", "erf("]),
    "SCREEN-theme-position": lambda d, c: screen_check(["theme_position", "소속 테마"], []),
    "SCREEN-theme-position-momentum": lambda d, c: screen_check(
        ['THEME_FACTORS = ["value", "quality", "growth", "momentum"]', "중립화 전"], []),
    "CJ-LOGISTICS-history": lambda d, c: _with_stock(d, c, lambda d, s: case_cj_history(s)),
    "BUYBACK-vs-DISTRESSED": lambda d, c: case_buyback(d),
    "R1-oneoff-top10": lambda d, c: rule_r1(d),
    "R2-turnaround-growth": lambda d, c: rule_r2(d),
    "R3-value-trap": lambda d, c: rule_r3(d),
    "R4-cycle-value": lambda d, c: rule_r4(d),
    "R5-fiscal-gap-badge": lambda d, c: rule_r5(d),
    "R6-score-honesty": lambda d, c: rule_r6(d),
    "R7-badge-inflation": lambda d, c: rule_r7(d),
    "R8-top10-stability": lambda d, c: rule_r8(d),
    "R9-no-score-loss": lambda d, c: rule_r9(d),
    "R10-independent-benchmark": lambda d, c: rule_r10(d),
    "TRAP-penalty-only": lambda d, c: rule_trap(d),
    "WEAK-theme-first": lambda d, c: rule_weak_theme_first(d),
    "THEME-position-raw": lambda d, c: rule_theme_position_raw(d),
    "CLIP-order": lambda d, c: rule_clip_order(d),
    "THEME-main-business-KR": case_theme,
    "THEME-main-business-US": case_theme,
    "THEME-main-business-unjudged": case_theme_unjudged,
    "TOP20-theme-reviewed": lambda d, c: rule_top20_theme_reviewed(d),
    "BOBCAT-currency": lambda d, c: _with_stock(d, c, case_bobcat_currency),
    "CURRENCY-krw": lambda d, c: rule_currency_krw(d),
    "NEG-EQUITY-bp": lambda d, c: _all_stocks(d, c, case_negative_equity_bp),
    "NEG-EQUITY-no-bp": lambda d, c: rule_negative_equity_no_bp(d),
    "ONEOFF-badge-recurring": lambda d, c: rule_oneoff_badge_wording(d),
    "PREF-share-basis": lambda d, c: rule_preferred_share_basis(d),
    "FIN-no-composite": lambda d, c: rule_financial_no_composite(d),
    "FIN-pb-roe-view": lambda d, c: case_financial_pb_roe_view(d),
    "INSURER-oci-roe": lambda d, c: (None, "총포괄이익(지배)을 아직 수집하지 않음 — D-033 수집 뒤 required"),
    "GROWTH-label": lambda d, c: case_growth_label(d),
    "DEPLOY-sanity-ran": lambda d, c: rule_deploy_sanity(d),
    "DATA-dart-fy-path": lambda d, c: rule_dart_fy_path(d, c),
    "DATA-sec-op-path": lambda d, c: rule_sec_op_path(d),
    "LP-equity-not-zero": lambda d, c: rule_lp_equity(d),
    "ADR-mcap-sane": lambda d, c: rule_adr_mcap(d),
    "MULTICLASS-ranked": rule_multiclass_ranked,
    "HALTED-not-scored": lambda d, c: rule_halted(d),
    "SPINOFF-basis": case_spinoff,
}


def rule_deploy_sanity(d: Data):
    """배포 DB 점수 재계산 뒤 sanity Job이 같은 as_of로 실행되어 결과가 남음(D-030). 이 실행이 배포 DB 기록(--save --env deploy)이면
    통과 — 결과가 sanity_runs에 남는다. 개발 DB·기록하지 않는 실행에서는 확인할 수 없어 미검증."""
    if d.save_env == "deploy":
        return True, f"이번 실행을 배포 DB sanity_runs에 기록(점수 계산일 {d.as_of})"
    last = d.conn.execute(text("""SELECT MAX(as_of) FROM sanity_runs WHERE environment = 'deploy'""")).scalar()
    return None, (f"배포 DB Job(--save --env deploy)에서만 확인 — 이번 실행은 {'개발 DB 기록' if d.save_env else '기록 안 함'}"
                  + (f" · 이 DB의 마지막 배포 기록 {last}" if last else ""))


KINDS = ("passed", "known_fail", "target_fail", "unverified", "required_fail")
KIND_LABEL = {"passed": "통과", "known_fail": "감수한 실패", "target_fail": "target 실패", "unverified": "미검증",
              "required_fail": "required 실패"}


def classify(status: str, ok: bool | None, decision: str | None) -> str:
    """네 칸(D-030) + required 실패. known_fail은 결정 번호가 있어야 '감수한 실패' — 없으면 required 실패로 센다."""
    if ok is None:
        return "unverified"
    if ok:
        return "passed"
    if status == "known_fail" and decision:
        return "known_fail"
    if status == "target":
        return "target_fail"
    return "required_fail"


def run_case(d: Data, c: dict) -> tuple[bool | None, str]:
    if c["id"] in SPECIAL:
        return SPECIAL[c["id"]](d, c)
    tickers = c["ticker"] if isinstance(c.get("ticker"), list) else [c.get("ticker")]
    results, vals = [], []
    for t in tickers:
        s = d.by_ticker(str(t), c.get("market"))
        r = eval_check(c["check"], s)
        results.append(r)
        vals.append(f"{t}: {describe(s)}")
    if any(r is None for r in results):
        return None, f"식을 해석하지 못함 — {c['check']}"
    return all(results), " · ".join(vals)


def run(conn: Connection, cases_path: Path | None = None, as_of: date | None = None, *,
        save: bool = False, env: str = "dev") -> tuple[str, bool]:
    """반환: (마크다운 보고, required 실패 없음). 결과는 네 칸(통과 / 감수한 실패 / target 실패 / 미검증)과 required 실패로
    따로 센다(D-030). save면 sanity_runs에 한 행을 남긴다(env = dev / deploy). 커밋은 호출한 쪽이 한다."""
    spec = yaml.safe_load((cases_path or default_cases_path()).read_text(encoding="utf-8"))
    d = Data(conn, as_of, save_env=env if save else None)
    rows, kinds = [], {k: [] for k in KINDS}
    req_total = 0
    for c in list(spec.get("cases", [])) + list(spec.get("rules", [])):
        ok, val = run_case(d, c)
        status = c.get("status", "required")
        kind = classify(status, ok, c.get("decision"))
        kinds[kind].append(c["id"])
        req_total += status in ("required", "known_fail")
        mark = "확인 못함" if ok is None else "통과" if ok else "실패"
        if status == "known_fail" and ok is False:
            mark = f"실패(감수 {c.get('decision', '결정 없음')})"
        rows.append({"id": c["id"], "status": status, "kind": kind, "result": mark, "value": str(val)})
    n = {k: len(v) for k, v in kinds.items()}
    req_unverified = [r["id"] for r in rows if r["kind"] == "unverified" and r["status"] in ("required", "known_fail")]
    lines = [f"## sanity 결과 — 점수 계산일 {d.as_of} · 모델 {d.cfg['model_version']}", "",
             f"**통과 {n['passed']} · 감수한 실패 {n['known_fail']} · target 실패 {n['target_fail']} · 미검증 {n['unverified']}**"
             + (f" · **required 실패 {n['required_fail']}** — {', '.join(kinds['required_fail'])}" if n["required_fail"] else ""),
             "",
             f"required(known_fail 포함) {req_total}개: 통과 {req_total - n['required_fail'] - len(req_unverified) - n['known_fail']}"
             f" + 감수한 실패 {n['known_fail']}" + (f" · 미검증 {len(req_unverified)} ({', '.join(req_unverified)})" if req_unverified else "")
             + (f" · 실패 {n['required_fail']}" if n["required_fail"] else ""),
             "",
             "| id | status | 결과 | 실제 값 |", "|---|---|---|---|"]
    lines += [f"| {r['id']} | {r['status']} | {r['result']} | {r['value'].replace('|', '/')} |" for r in rows]
    report, ok = "\n".join(lines), not kinds["required_fail"]
    if save:
        conn.execute(text("""
            INSERT INTO sanity_runs (as_of, model_version, environment, passed, known_fail, target_fail, unverified,
                                     required_fail, ok, results, report)
            VALUES (:as_of, :v, :env, :passed, :known_fail, :target_fail, :unverified, :required_fail, :ok,
                    CAST(:results AS jsonb), :report)"""),
            {"as_of": d.as_of, "v": d.cfg["model_version"], "env": env, **n, "ok": ok,
             "results": json.dumps(rows, ensure_ascii=False), "report": report})
    return report, ok
