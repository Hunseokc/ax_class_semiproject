"""매력도 회귀 테스트 — 개발산출물/매력도_검토/sanity_cases.yaml의 cases·rules를 DB의 최신 점수로 판정한다.

실행: python -m app.ingest sanity [--cases 경로] [--as-of 날짜] [--out 결과.md]
  - 순위·백분위 정의는 sanity_cases.yaml 머리말(D-012): *_rank = 같은 시장·같은 묶음 안 프리셋 순위,
    *_percentile = 같은 범위 백분위(= stock_scores.score), *_factor = 재표준화한 팩터 점수, not_scored / scored
  - 일반 case는 check 식을 그대로 계산하고(and·or·비교), 식으로 쓸 수 없는 case·rule은 id별 함수로 판정한다
  - known_fail은 결정 번호(decision)가 있으면 종료 조건상 통과로 센다(검토_장부 0절)
  - 독립 기준(R10)은 개발산출물/11 5절 정의를 옮긴 것이다(I1 구조·I2 매출 2년 감소·I3 영업적자 이력·I5 극단 변동성, 상식적 우량)
반환 코드: required(known_fail 제외) 중 실패가 있으면 1
"""
from __future__ import annotations

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


def stock_page() -> Path | None:
    """종목 상세 화면 코드(frontend/js/pages/stock.js) — 컨테이너 /srv/frontend 또는 저장소 frontend."""
    for root in (CONFIG_DIR.parent, CONFIG_DIR.parent.parent):
        p = root / "frontend" / "js" / "pages" / "stock.js"
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
    def __init__(self, conn: Connection, as_of: date | None = None):
        self.conn = conn
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
        for r in c.execute(text("""SELECT stock_id, period_end, revenue, operating_income, net_income, total_assets, total_debt
                                   FROM financial_statements WHERE period_type = 'FY' ORDER BY stock_id, period_end""")).mappings():
            if r["stock_id"] in self.stocks:
                self.stocks[r["stock_id"]].fins.append({k: (float(v) if k not in ("stock_id", "period_end") and v is not None else v)
                                                        for k, v in r.items()})
        self.mcap = {r.stock_id: float(r.mcap) for r in c.execute(text(
            "SELECT stock_id, market_cap AS mcap FROM v_stock_metrics WHERE market_cap IS NOT NULL")) if r.stock_id in self.stocks}
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
    return not data_loss, (f"이전 {prev}: 재무 칸 누락으로 잃음 {len(data_loss)} {data_loss[:15]} · "
                           f"재무 없음(표기 안 함, D-014) {len(no_fin)} {no_fin[:15]} · 점수 없음 테마 {len(intended)}")


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


def rule_weak_theme_first(d: Data):
    total, per = weak_theme_firsts(d)
    return True, f"{total}개 (기록만) · " + " ".join(f"{k} {len(v)}{v if v else ''}" for k, v in per.items())


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


def case_cj_history(s: Stock):
    years = [f["period_end"].year for f in s.chain()]
    return len(years) >= 3 and 2024 in years, f"이어지는 FY {years}"


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
}


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


def run(conn: Connection, cases_path: Path | None = None, as_of: date | None = None) -> tuple[str, bool]:
    """반환: (마크다운 보고, required 전부 통과 여부 — known_fail은 결정 번호가 있으면 통과)."""
    spec = yaml.safe_load((cases_path or default_cases_path()).read_text(encoding="utf-8"))
    d = Data(conn, as_of)
    lines = [f"## sanity 결과 — 점수 계산일 {d.as_of} · 모델 {d.cfg['model_version']}", "",
             "| id | status | 결과 | 실제 값 |", "|---|---|---|---|"]
    req_total = req_ok = 0
    failed_required = []
    for c in list(spec.get("cases", [])) + list(spec.get("rules", [])):
        ok, val = run_case(d, c)
        status = c.get("status", "required")
        mark = "확인 못함" if ok is None else "통과" if ok else "실패"
        if status == "known_fail" and not ok:
            mark = f"실패(감수 {c.get('decision', '결정 없음')})"
        lines.append(f"| {c['id']} | {status} | {mark} | {str(val).replace('|', '/')} |")
        if status in ("required", "known_fail"):
            req_total += 1
            passed = bool(ok) or (status == "known_fail" and bool(c.get("decision")))
            req_ok += passed
            if not passed:
                failed_required.append(c["id"])
    lines[1:1] = ["", f"required(known_fail 포함) 통과 **{req_ok}/{req_total}**"
                  + (f" — 실패: {', '.join(failed_required)}" if failed_required else "")]
    return "\n".join(lines), not failed_required
