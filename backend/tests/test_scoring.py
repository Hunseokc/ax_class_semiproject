"""매력도 다중 팩터 모델 v2 손계산 검증 (개발산출물/09, 검토_장부 D-002·D-003·D-010).

단계별: 로버스트 Z·부호 반전·±3 클리핑·MAD=0 대체·감점 전용 지표 / 축소 계수 n/(n+k) /
        팩터 가중 평균·이력 축소·재표준화·빠진 팩터 0·필수 팩터 / 같은 시장 백분위.
전체: 시세·재무·밸류에이션 픽스처에서 지표 원값 → Z → 점수를 파이썬 참조 구현과 비교, 경계 사례, 프리셋, API.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal as Dec

import pytest
from sqlalchemy import text

from app.services.fx import FxService
from app.services.refresh import RefreshService
from app.ingest.jobs import migrate
from app.queries import sql
from app.services.scoring import (FACTORS, METRICS, aggregate, compute_scores, load_config, metric_params, normalize,
                                  sync_presets, validate_presets)
from tests.conftest import D, scalar
from tests.fakes import make_providers
from tests.test_analysis import _path, _replace_prices

API = "/api/v1"
K = 5


def add_kr_stocks(conn, ids):
    conn.execute(text("INSERT INTO stocks (stock_id, market_id, ticker, name) VALUES (:i, 1, :t, :n)"),
                 [{"i": i, "t": f"9{i:05d}", "n": f"테스트{i}"} for i in ids])


def put_raw(conn, metric: str, values: dict[int, float], as_of=D):
    conn.execute(text("""INSERT INTO stock_metric_values (stock_id, as_of, metric, factor, raw_value)
                         VALUES (:s, :d, :m, :f, :v)"""),
                 [{"s": s, "d": as_of, "m": metric, "f": METRICS[metric].factor, "v": v} for s, v in values.items()])


def read(conn, col: str, metric: str, as_of=D) -> dict[int, float | None]:
    rows = conn.execute(text(f"SELECT stock_id, {col} FROM stock_metric_values WHERE metric = :m AND as_of = :d"),
                        {"m": metric, "d": as_of}).all()
    return {r[0]: (float(r[1]) if r[1] is not None else None) for r in rows}


# ------------------------------------------------------------------ 2단계: 로버스트 Z
def test_robust_z_sign_flip_and_clipping(engine):
    vals = {1: 0.10, 2: 0.12, 5: 0.08, 6: 0.11, 7: 0.50}       # 중앙값 0.11, |편차| 중앙값(MAD) 0.01
    with engine.begin() as conn:
        add_kr_stocks(conn, [5, 6, 7])
        put_raw(conn, "return_on_assets", vals)                               # 방향 +
        put_raw(conn, "volatility", vals)                        # 방향 −
        normalize(conn, D, K)
        roe, vol = read(conn, "z_raw", "return_on_assets"), read(conn, "z_raw", "volatility")
    s = 1.4826 * 0.01
    assert roe[1] == pytest.approx((0.10 - 0.11) / s, abs=1e-4)          # −0.6745
    assert roe[5] == pytest.approx((0.08 - 0.11) / s, abs=1e-4)          # −2.0235
    assert roe[6] == 0 and roe[7] == 3                                    # 26.3 → 3으로 클리핑
    assert vol[1] == pytest.approx(-roe[1], abs=1e-4) and vol[7] == -3   # 부호 반전 후 클리핑


def test_mad_zero_and_small_sample_fall_back_to_mean_sd(engine):
    with engine.begin() as conn:
        add_kr_stocks(conn, [5, 6, 7])
        put_raw(conn, "return_on_assets", {1: 1, 2: 1, 5: 1, 6: 1, 7: 5})               # MAD = 0 → 평균·표준편차
        put_raw(conn, "book_yield", {3: 1, 4: 3})                          # US 2개(표본 < 5)
        put_raw(conn, "operating_margin", {1: 2, 2: 2, 5: 2})               # 표준편차 0 → Z = 0
        put_raw(conn, "momentum", {3: 0.1})                                 # 표본 1개 → Z = 0
        normalize(conn, D, K)
        roe, by = read(conn, "z_raw", "return_on_assets"), read(conn, "z_raw", "book_yield")
        opm, mom = read(conn, "z_raw", "operating_margin"), read(conn, "z_raw", "momentum")
    sd = statistics.stdev([1, 1, 1, 1, 5])
    assert roe[7] == pytest.approx((5 - 1.8) / sd, abs=1e-4) and roe[1] == pytest.approx((1 - 1.8) / sd, abs=1e-4)
    assert by[4] == pytest.approx(1 / math.sqrt(2), abs=1e-4) and by[3] == pytest.approx(-1 / math.sqrt(2), abs=1e-4)
    assert set(opm.values()) == {0} and mom[3] == 0


def test_penalty_only_metric_is_clipped_at_zero(engine):
    """가치 함정 신호는 나쁠 때만 깎는다: Z를 [−3, 0]으로 자른다."""
    with engine.begin() as conn:
        add_kr_stocks(conn, [5, 6, 7])
        put_raw(conn, "trap_signal", {1: 0.2, 2: 0.6, 5: 0.8, 6: 1.0, 7: 0.4})   # 중앙값 0.6, MAD 0.2
        normalize(conn, D, K)
        z = read(conn, "z_raw", "trap_signal")
    assert z[1] == pytest.approx((0.2 - 0.6) / (1.4826 * 0.2), abs=1e-4) and z[7] < 0
    assert z[2] == 0 and z[5] == 0 and z[6] == 0                           # 중앙값 이상은 0(가점 없음)


def test_countries_are_normalized_separately(engine):
    with engine.begin() as conn:
        put_raw(conn, "return_on_assets", {1: 0.1, 2: 0.3, 3: 10, 4: 30})              # US 값이 커도 KR과 섞이지 않는다
        normalize(conn, D, K)
        z = read(conn, "z_raw", "return_on_assets")
    assert z[1] == pytest.approx(z[3], abs=1e-4) and z[2] == pytest.approx(z[4], abs=1e-4)


# ------------------------------------------------------------------ 2단계: 섹터 중립화(축소 추정)
def test_shrinkage_uses_primary_group_mean_including_self(engine):
    vals = {5: 0.30, 6: 0.20, 7: 0.25, 8: 0.05, 9: 0.10}              # 5·6·7은 같은 주 그룹, 8은 그룹 없음
    with engine.begin() as conn:
        add_kr_stocks(conn, [5, 6, 7, 8, 9])
        conn.execute(text("INSERT INTO peer_groups (group_id, name) VALUES (3, '자동차'), (4, '단독')"))
        conn.execute(text("INSERT INTO peer_group_members VALUES (3, 5, true), (3, 6, true), (3, 7, true), "
                          "(4, 9, true), (1, 8, false)"))
        put_raw(conn, "return_on_assets", vals)
        normalize(conn, D, K)
        z, adj = read(conn, "z_raw", "return_on_assets"), read(conn, "z_adj", "return_on_assets")
    group_mean = (z[5] + z[6] + z[7]) / 3                               # 자기 자신 포함
    for s in (5, 6, 7):
        assert adj[s] == pytest.approx(z[s] - 3 / (3 + K) * group_mean, abs=2e-4)
    assert adj[8] == z[8]                                                # 주 그룹 없음(비주 그룹만 소속)
    assert adj[9] == z[9]                                                # 주 그룹 표본 n = 1


def test_shrinkage_does_not_mix_countries(engine):
    """같은 주 그룹이라도 국가가 다르면 평균에 넣지 않는다(z는 국가 안에서 표준화한 값)."""
    with engine.begin() as conn:
        add_kr_stocks(conn, [5, 6, 7])
        conn.execute(text("INSERT INTO peer_group_members VALUES (1, 5, true), (1, 6, true), (1, 7, true)"))
        put_raw(conn, "return_on_assets", {1: 0.10, 2: 0.12, 5: 0.08, 6: 0.11, 7: 0.50, 3: 0.1, 4: 0.9})   # 반도체: KR 1·2·5·6·7, US 4
        normalize(conn, D, K)
        z, adj = read(conn, "z_raw", "return_on_assets"), read(conn, "z_adj", "return_on_assets")
    kr = [1, 2, 5, 6, 7]
    kr_mean = sum(z[s] for s in kr) / len(kr)
    for s in kr:
        assert adj[s] == pytest.approx(z[s] - 5 / (5 + K) * kr_mean, abs=2e-4)
    assert adj[4] == z[4]                                                # US 반도체는 4 혼자 → n = 1


# ------------------------------------------------------------------ 3단계: 합산·백분위
def put_z(conn, sid: int, z_by_metric: dict[str, float], as_of=D):
    conn.execute(text("""INSERT INTO stock_metric_values (stock_id, as_of, metric, factor, raw_value, z_raw, z_adj)
                         VALUES (:s, :d, :m, :f, 0, :z, :z)"""),
                 [{"s": sid, "d": as_of, "m": m, "f": METRICS[m].factor, "z": z} for m, z in z_by_metric.items()])


def scores_by(conn, preset="balanced", as_of=D) -> dict[int, dict]:
    rows = conn.execute(text("""SELECT st.* FROM stock_scores st JOIN scoring_presets p USING (preset_id)
                                WHERE p.code = :p AND st.as_of = :d"""), {"p": preset, "d": as_of}).mappings()
    return {r["stock_id"]: r for r in rows}


ALL_METRICS = list(METRICS)


def _std(xs: list[float]) -> list[float]:
    m, sd = statistics.mean(xs), statistics.stdev(xs)
    return [(x - m) / sd for x in xs]


def test_percentile_score_matches_rank_and_20_percent_bands(engine):
    """점수 = 100 × (n − 순위) / n → 80 이상이 정확히 상위 20%(D-003). 모든 지표 z = c면 종합 순서도 c 순서."""
    ids = list(range(5, 15))
    with engine.begin() as conn:
        add_kr_stocks(conn, ids)
        for i, sid in enumerate(ids):
            put_z(conn, sid, {m: -1 + 0.2 * i for m in ALL_METRICS})
        aggregate(conn, D)
        sc = scores_by(conn)
    kr = sorted((s for s in sc if s in ids), key=lambda s: -float(sc[s]["composite"]))
    n = len(kr)
    for pos, sid in enumerate(kr, 1):
        assert float(sc[sid]["score"]) == pytest.approx(100 * (n - pos) / n, abs=0.01)
    assert [s for s in kr if float(sc[s]["score"]) >= 80] == kr[:2]           # 10개 중 상위 2개 = 20%


def test_factor_weighting_restandardization_missing_zero_and_required(engine):
    with engine.begin() as conn:
        add_kr_stocks(conn, [5, 6, 7, 8])
        put_z(conn, 5, {"conservative_yield": 1.0, "book_yield": 2.0, "return_on_assets": 0.5, "revenue_cagr2": -1.0,
                        "volatility": 1.0, "liab_assets": -2.0})                       # 안정성 = (2 × 1 + 1 × −2) / 3 = 0
        put_z(conn, 6, {"conservative_yield": 0.2, "return_on_assets": -0.4, "momentum": 1.0})   # 3개 팩터
        put_z(conn, 7, {m: 0.3 for m in ALL_METRICS})
        put_z(conn, 8, {"book_yield": 1.0, "volatility": 0.5, "liab_assets": 0.5, "momentum": 0.2})   # 수익성 없음
        aggregate(conn, D)
        growth, balanced = scores_by(conn, "growth"), scores_by(conn, "balanced")
    # 재표준화 전 팩터 점수(KR — 픽스처 1·2는 지표 없음): value 5 = 1.5, 6 = 0.2, 7 = 0.3, 8 = 1.0
    raw_value = {5: 1.5, 6: 0.2, 7: 0.3, 8: 1.0}
    zs = dict(zip(raw_value, _std(list(raw_value.values()))))
    assert float(growth[5]["value_score"]) == pytest.approx(zs[5], abs=1e-4)
    raw_safety = {5: 0.0, 7: 0.3, 8: 0.5}                                        # 변동성 2 : 부채/자산 1
    ss = dict(zip(raw_safety, _std(list(raw_safety.values()))))
    assert float(growth[5]["safety_score"]) == pytest.approx(ss[5], abs=1e-4)
    # 빠진 팩터는 0 — 가중치를 다시 나누지 않는다: 종합 = Σ w × 재표준화 팩터
    s6 = balanced[6]
    assert s6["factor_coverage"] == 3 and s6["growth_score"] is None and s6["safety_score"] is None
    expect = 0.2 * float(s6["value_score"]) + 0.2 * float(s6["quality_score"]) + 0.2 * float(s6["momentum_score"])
    assert float(s6["composite"]) == pytest.approx(expect, abs=2e-4)
    # 수익성(필수)이 없으면 팩터 3개여도 점수 없음
    s8 = balanced[8]
    assert s8["factor_coverage"] == 3 and s8["composite"] is None and s8["score"] is None
    assert "저평가·수익성" in s8["data_quality"]["score_null_reason"]
    assert set(s8["data_quality"]["unavailable_factors"]) == {"quality", "growth"}


def test_short_financial_history_shrinks_value_factor(engine):
    """재무 FY가 3개 미만이면 저평가 팩터를 FY 수 / 3만큼 줄인 뒤 재표준화한다(D-010)."""
    with engine.begin() as conn:
        add_kr_stocks(conn, [5, 6, 7])
        for sid in (5, 6, 7):
            put_z(conn, sid, {"conservative_yield": 1.5, "return_on_assets": 0.1 * sid, "momentum": 0.0})
        aggregate(conn, D, history={5: 3, 6: 1, 7: 0})
        sc = scores_by(conn)
    zs = dict(zip((5, 6, 7), _std([1.5, 0.5, 0.0])))
    for sid in (5, 6, 7):
        assert float(sc[sid]["value_score"]) == pytest.approx(zs[sid], abs=1e-4)
    assert sc[6]["data_quality"]["fy_history"] == 1


# ------------------------------------------------------------------ 전체 파이프라인 손계산
# KR 6종목(1, 2, 5~8) · US 2종목(3, 4). 주 그룹: 반도체(1, 2, 4), 빅테크(3), 자동차(5, 6), 7·8은 없음
PRICES = {1: (300, 0, .1), 2: (300, 1, -.05), 5: (130, 2, .02), 6: (130, .7, .08), 7: (100, 1.5, 0), 8: (50, .3, .01),
          3: (130, .5, .2), 4: (300, 3, .3)}
VALUATION = {  # eps, bps, shares, market_cap
    1: (8, 80, 1000, None), 2: (-2, 50, 1000, None), 5: (None, 40, 1000, None), 6: (5, 120, 1000, None),
    7: (3, 30, None, 100_000), 8: (4, 60, 1000, None), 3: (6, 4, 1000, None), 4: (2, 10, 1000, None)}
FIN = {        # (결산일, 매출, 영업이익, 순이익, 자본, 부채, 자산) 오래된 FY → 최신 FY
    1: [("2022-12-31", 90, 9, 4, 100, 50, 150), ("2023-12-31", 100, 10, 8, 110, 50, 160),
        ("2024-12-31", 120, 15, 12, 126, 44, 170)],                                  # 3개 FY — 3년 평균이 더 작다
    2: [("2023-12-31", 200, 40, 30, 150, 60, 210), ("2024-12-31", 210, 30, -20, 160, 80, 240)],
    5: [("2023-12-31", 0, -5, -10, 50, 20, 70), ("2024-12-31", 50, -2, -15, 40, 30, 70)],   # 적자, 직전 매출 0
    6: [("2022-12-31", 70, -3, -4, -10, 85, 75), ("2023-12-31", 80, 8, 6, -10, 90, 80),
        ("2024-12-31", 90, 9, 30, -5, 100, 95)],                                     # 2년 전 적자 · 최신 해 일회성(순이익 > 영업이익)
    7: [("2024-12-31", 60, 6, 4, 40, 20, 60)],                                        # FY 1개 — 저평가 1/3로 축소
    3: [("2023-09-30", 300, 90, 80, 60, 120, 200), ("2024-09-30", 330, 99, 90, 70, 140, 220)],
    4: [("2024-01-31", 50, 20, 15, 40, 10, 60), ("2025-01-31", 120, 70, 60, 80, 20, 110)]}
PRIMARY = {1: 1, 2: 1, 4: 1, 3: 2, 5: 3, 6: 3}
COUNTRY = {1: "KR", 2: "KR", 5: "KR", 6: "KR", 7: "KR", 8: "KR", 3: "US", 4: "US"}
AFTER_TAX = 0.78


@pytest.fixture
def universe(engine):
    closes = {}
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO stocks (stock_id, market_id, ticker, name) VALUES
            (5, 1, '035420', 'NAVER'), (6, 1, '005380', '현대차'), (7, 1, '000270', '기아'), (8, 1, '035720', '카카오')"""))
        conn.execute(text("INSERT INTO peer_groups (group_id, name) VALUES (3, '자동차')"))
        conn.execute(text("INSERT INTO peer_group_members VALUES (3, 5, true), (3, 6, true)"))
        conn.execute(text("DELETE FROM valuation_snapshots"))
        conn.execute(text("""INSERT INTO valuation_snapshots (stock_id, as_of, eps, bps, shares_outstanding, market_cap, source)
                             VALUES (:s, :d, :eps, :bps, :sh, :mc, 'PYKRX')"""),
                     [{"s": s, "d": D, "eps": e, "bps": b, "sh": sh, "mc": mc} for s, (e, b, sh, mc) in VALUATION.items()])
        conn.execute(text("""INSERT INTO financial_statements (stock_id, period_end, period_type, revenue, operating_income,
                             net_income, total_equity, total_debt, total_assets, data_source)
                             VALUES (:s, :p, 'FY', :r, :o, :n, :e, :d, :a, 'DART')"""),
                     [{"s": s, "p": p, "r": r, "o": o, "n": n, "e": e, "d": d, "a": a}
                      for s, fy in FIN.items() for p, r, o, n, e, d, a in fy])
    for s, (n, phase, slope) in PRICES.items():
        closes[s] = [float(c) for c in _path(n, phase, slope)]
        _replace_prices(engine, s, _path(n, phase, slope), D)
    return closes


def _earn(ni, oi):
    """해마다 저평가 이익 e = min(순이익, 0.78 × 영업이익)."""
    return min(ni, AFTER_TAX * oi)


def _mcap(s, close):
    eps, bps, shares, mc = VALUATION[s]
    return mc if mc is not None else shares * close


def reference_raw(closes) -> tuple[dict[int, dict[str, float | None]], dict[int, int]]:
    out, hist = {}, {}
    for s, cl in closes.items():
        close = cl[-1]
        fy = FIN.get(s, [])
        hist[s] = len(fy)                                    # 픽스처 FY는 모두 1년 간격으로 이어진다
        t = fy[-1] if fy else None
        t2 = fy[-3] if len(fy) >= 3 else None
        r: dict[str, float | None] = {m: None for m in METRICS}
        if t:
            _, rev, oi, ni, _, debt, ta = t
            es = [_earn(f[3], f[2]) for f in fy[-3:]]
            e = min(es[-1], sum(es) / 3) if len(es) == 3 else es[-1]
            r["conservative_yield"] = e / _mcap(s, close)
            r["return_on_assets"] = oi / ta
            r["operating_margin"] = oi / rev if rev else None
            r["liab_assets"] = debt / ta
        r["book_yield"] = VALUATION[s][1] / close
        if t and t2:
            _, rev2, oi2, _, _, debt2, ta2 = t2
            r["revenue_cagr2"] = (math.sqrt(rev / rev2) - 1 if rev > 0 else -1.0) if rev2 > 0 else None
            r["profit_growth2"] = (oi - oi2) / ta2 if oi2 > 0 else None
            sig = [oi > 0, rev > rev2, debt / ta < debt2 / ta2]
            if oi2 > 0:
                sig += [oi > oi2, oi / rev > oi2 / rev2]
            r["trap_signal"] = sum(sig) / len(sig)
        r["volatility"] = (statistics.stdev([cl[-253:][i] / cl[-253:][i - 1] - 1 for i in range(1, 253)]) * math.sqrt(252)
                           if len(cl) >= 253 else None)
        r["momentum"] = (cl[-22] / cl[-253] - 1 if len(cl) >= 253 else cl[-22] / cl[-127] - 1 if len(cl) >= 127 else None)
        out[s] = r
    return out, hist


def reference_scores(raw, hist):
    def zs(vals):
        xs = list(vals.values())
        m = statistics.median(xs)
        mad = statistics.median([abs(x - m) for x in xs])
        if len(xs) >= 5 and mad > 0:
            return {k: (x - m) / (1.4826 * mad) for k, x in vals.items()}
        sd = statistics.stdev(xs) if len(xs) > 1 else 0
        return {k: (x - statistics.mean(xs)) / sd if sd > 0 else 0.0 for k, x in vals.items()}

    z_raw = {s: {} for s in raw}
    for metric, d in METRICS.items():
        for c in ("KR", "US"):
            vals = {s: raw[s][metric] for s in raw if COUNTRY[s] == c and raw[s][metric] is not None}
            for s, z in (zs(vals) if vals else {}).items():
                z_raw[s][metric] = round(max(-3, min(0 if d.penalty_only else 3, z * d.direction)), 4)
    z_adj = {s: {} for s in raw}
    for metric in METRICS:
        for s in raw:
            if metric not in z_raw[s]:
                continue
            g = PRIMARY.get(s)
            mates = [t for t in raw if g is not None and PRIMARY.get(t) == g and COUNTRY[t] == COUNTRY[s] and metric in z_raw[t]]
            n = len(mates)
            z = z_raw[s][metric]
            if METRICS[metric].factor == "safety":                    # 안정성은 섹터 중립화하지 않는다
                z_adj[s][metric] = z
                continue
            v = z - n / (n + K) * sum(z_raw[t][metric] for t in mates) / n if n > 1 else z
            z_adj[s][metric] = round(max(-3, min(3, v)), 4)
    fac = {}
    for s in raw:
        f_s = {}
        for f in FACTORS:
            pairs = [(METRICS[m].weight, v) for m, v in z_adj[s].items() if METRICS[m].factor == f]
            if pairs:
                f_s[f] = sum(w * v for w, v in pairs) / sum(w for w, _ in pairs)
        if "value" in f_s and hist[s] < 3:
            f_s["value"] *= hist[s] / 3
        fac[s] = f_s
    fz = {s: {} for s in raw}                                           # 국가 안 재표준화
    for c in ("KR", "US"):
        for f in FACTORS:
            xs = {s: fac[s][f] for s in raw if COUNTRY[s] == c and f in fac[s]}
            if not xs:
                continue
            m, sd = statistics.mean(xs.values()), statistics.stdev(xs.values()) if len(xs) > 1 else 0
            for s, v in xs.items():
                fz[s][f] = (v - m) / sd if sd > 0 else 0.0
    out = {}
    for p in load_config()["presets"]:
        w = p["weights"]
        comp = {s: (sum(w[f] * v for f, v in fz[s].items())
                    if {"value", "quality"} <= set(fz[s]) and len(fz[s]) >= 3 else None) for s in raw}
        res = {}
        for c in ("KR", "US"):
            cs = {s: v for s, v in comp.items() if COUNTRY[s] == c and v is not None}
            n = len(cs)
            for s, v in cs.items():
                pos = 1 + sum(1 for x in cs.values() if x > v)
                res[s] = 50.0 if n == 1 else 100 * (n - pos) / n
        out[p["code"]] = {"composite": comp, "score": res}
    return z_raw, z_adj, fz, out


def test_full_pipeline_matches_reference_implementation(engine, universe):
    n = compute_scores(engine, as_of=D)
    assert n == 8 * 4                                                    # 종목 × 프리셋
    raw_ref, hist = reference_raw(universe)
    z_raw_ref, z_adj_ref, fac_ref, scores_ref = reference_scores(raw_ref, hist)
    with engine.connect() as conn:
        mv = conn.execute(text("SELECT * FROM stock_metric_values WHERE as_of = :d"), {"d": D}).mappings().all()
        assert len(mv) == 8 * len(METRICS)
        for r in mv:
            s, m = r["stock_id"], r["metric"]
            exp = raw_ref[s][m]
            assert (r["raw_value"] is None) == (exp is None), (s, m)
            if exp is not None:
                assert float(r["raw_value"]) == pytest.approx(exp, rel=1e-5, abs=1e-6), (s, m)
            assert (r["z_raw"] is None) == (m not in z_raw_ref[s]), (s, m)
            if r["z_raw"] is not None:
                assert float(r["z_raw"]) == pytest.approx(z_raw_ref[s][m], abs=2e-4), (s, m)
                assert float(r["z_adj"]) == pytest.approx(z_adj_ref[s][m], abs=3e-4), (s, m)
        for code, ref in scores_ref.items():
            got = scores_by(conn, code)
            for s in COUNTRY:
                for f in FACTORS:
                    v = got[s][f"{f}_score"]
                    assert (v is None) == (f not in fac_ref[s]), (code, s, f)
                    if v is not None:
                        assert float(v) == pytest.approx(fac_ref[s][f], abs=5e-4), (code, s, f)
                if ref["composite"][s] is None:
                    assert got[s]["score"] is None, (code, s)
                else:
                    assert float(got[s]["composite"]) == pytest.approx(ref["composite"][s], abs=5e-4), (code, s)
                    assert float(got[s]["score"]) == pytest.approx(ref["score"][s], abs=0.01), (code, s)


def test_boundary_cases(engine, universe):
    compute_scores(engine, as_of=D)
    with engine.connect() as conn:
        cy, la = read(conn, "raw_value", "conservative_yield"), read(conn, "raw_value", "liab_assets")
        pg = read(conn, "raw_value", "profit_growth2")
        sc = scores_by(conn)
    # 일회성 해(현대차 순이익 30 > 영업이익 9)는 0.78 × 영업이익으로 자르고, 3년 평균이 더 작으면 3년 평균
    e = [_earn(-4, -3), _earn(6, 8), _earn(30, 9)]                       # −4, 6, 7.02
    assert e[-1] == pytest.approx(0.78 * 9)
    assert cy[6] == pytest.approx(sum(e) / 3 / _mcap(6, universe[6][-1]), rel=1e-5)
    assert any("3년 평균" in n for n in sc[6]["data_quality"]["notes"])
    # 2년 전 적자(현대차 2022 영업손실) → 이익 변화는 비우고 사유
    assert pg[6] is None and "흑자 전환" in sc[6]["data_quality"]["missing_metrics"]["profit_growth2"]
    # 자본 ≤ 0이어도 부채/자산은 원값 그대로(부채비율처럼 Z −3 고정 없음)
    assert la[6] == pytest.approx(100 / 95) and not any("고정" in n for n in sc[6]["data_quality"].get("notes", []))
    # 재무 FY 1개(기아) → 저평가 이력 축소 메모, 2년 지표 없음
    assert sc[7]["data_quality"]["fy_history"] == 1
    assert any("재무 이력 1년" in n for n in sc[7]["data_quality"]["notes"])
    assert "revenue_cagr2" in sc[7]["data_quality"]["missing_metrics"]
    # 일봉 253개 미만 → 6-1개월, 127개 미만 → 모멘텀 없음
    assert any("6-1개월" in n for n in sc[5]["data_quality"]["notes"])
    assert "momentum" in sc[7]["data_quality"]["missing_metrics"]
    # 재무 없는 카카오(8) → 수익성 없음 → 점수 없음
    assert sc[8]["score"] is None and "저평가·수익성" in sc[8]["data_quality"]["score_null_reason"]


def test_safety_factor_is_not_sector_neutralized(engine, universe):
    """안정성 지표는 z_adj = z_raw, 다른 팩터는 주 그룹(n > 1)이면 중립화가 그대로 걸린다."""
    compute_scores(engine, as_of=D)
    with engine.connect() as conn:
        safety = conn.execute(text("""SELECT z_raw, z_adj FROM stock_metric_values
                                      WHERE as_of = :d AND factor = 'safety' AND z_raw IS NOT NULL"""), {"d": D}).all()
        roe_raw, roe_adj = read(conn, "z_raw", "return_on_assets"), read(conn, "z_adj", "return_on_assets")
    assert safety and all(r.z_adj == r.z_raw for r in safety)
    assert roe_adj[1] != roe_raw[1] and roe_adj[2] != roe_raw[2]       # 반도체(1, 2) 수익성은 중립화


def test_incomplete_and_off_cycle_fy_rows_are_skipped(engine, universe):
    """자산이 빈 최신 FY(일부 칸만 들어온 행)는 건너뛰고, 결산월 변경으로 끼어든 FY는 2년 비교에서 건너뛴다."""
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO financial_statements (stock_id, period_end, period_type, net_income, data_source)
                             VALUES (1, '2025-12-31', 'FY', 99, 'YFINANCE')"""))
        conn.execute(text("""INSERT INTO financial_statements (stock_id, period_end, period_type, revenue, operating_income,
                             net_income, total_assets, total_debt, data_source) VALUES (1, '2024-03-31', 'FY', 1, 1, 1, 1, 1, 'DART')"""))
        rows = {r["metric"]: r for r in conn.execute(sql("score_metrics"), metric_params(stock_id=1)).mappings()}
    assert rows["return_on_assets"]["fy_count"] == 3                       # 2024-12-31 기준 그대로
    assert float(rows["return_on_assets"]["raw_value"]) == pytest.approx(15 / 170)
    assert float(rows["revenue_cagr2"]["raw_value"]) == pytest.approx(math.sqrt(120 / 90) - 1)


def test_listed_stocks_are_excluded_from_universe(engine, universe):
    with engine.begin() as conn:                                         # 상장 목록(검색용) 종목은 비교 표본이 아니다
        conn.execute(text("INSERT INTO stocks (stock_id, market_id, ticker, name, coverage) VALUES (9, 1, '999999', '상장', 'listed')"))
        conn.execute(text("""INSERT INTO valuation_snapshots (stock_id, as_of, eps, bps, shares_outstanding, source)
                             VALUES (9, :d, 500, 5000, 1000, 'PYKRX')"""), {"d": D})
    _replace_prices(engine, 9, _path(300, 0, .5), D)
    compute_scores(engine, as_of=D)
    assert scalar(engine, "SELECT count(*) FROM stock_metric_values WHERE stock_id = 9") == 0
    assert scalar(engine, "SELECT count(*) FROM stock_scores WHERE stock_id = 9") == 0


def test_score_metrics_with_stock_id_returns_only_that_stock(engine, universe):
    with engine.connect() as conn:
        rows = conn.execute(sql("score_metrics"), metric_params(stock_id=1)).mappings().all()
    assert {r["stock_id"] for r in rows} == {1} and len(rows) == len(METRICS)


def test_better_new_stock_takes_first_without_reaching_100(engine, universe):
    """백분위는 Min-Max처럼 최고 100·최저 0으로 늘이지 않는다: 1위도 100 × (n − 1) / n."""
    with engine.begin() as conn:                                         # 모든 지표가 극단적으로 좋은 종목 추가
        conn.execute(text("INSERT INTO stocks (stock_id, market_id, ticker, name) VALUES (9, 1, '999999', '극단')"))
        conn.execute(text("""INSERT INTO valuation_snapshots (stock_id, as_of, eps, bps, shares_outstanding, source)
                             VALUES (9, :d, 500, 5000, 1000, 'PYKRX')"""), {"d": D})
        conn.execute(text("""INSERT INTO financial_statements (stock_id, period_end, period_type, revenue, operating_income,
                             net_income, total_equity, total_debt, total_assets, data_source) VALUES
                             (9, '2022-12-31', 'FY', 100, 50, 40, 100, 1, 101, 'DART'),
                             (9, '2023-12-31', 'FY', 200, 120, 90, 200, 1, 201, 'DART'),
                             (9, '2024-12-31', 'FY', 400, 300, 250, 300, 1, 301, 'DART')"""))
    _replace_prices(engine, 9, _path(300, 0, .5), D)
    compute_scores(engine, as_of=D)
    with engine.connect() as conn:
        kr = {s: r for s, r in scores_by(conn).items() if r["score"] is not None and COUNTRY.get(s, "KR") == "KR"}
    n = len(kr)
    assert max(kr, key=lambda s: float(kr[s]["composite"])) == 9
    assert float(kr[9]["score"]) == pytest.approx(100 * (n - 1) / n, abs=0.01) and min(float(r["score"]) for r in kr.values()) == 0


# ------------------------------------------------------------------ 프리셋
def test_preset_weights_sum_to_one_in_config_and_db(engine):
    cfg = load_config()
    assert [p["code"] for p in sorted(cfg["presets"], key=lambda p: p["sort_order"])] == ["aggressive", "growth", "balanced", "value"]
    with engine.connect() as conn:
        sums = dict(conn.execute(text("""SELECT p.code, SUM(w.weight) FROM scoring_presets p
                                         JOIN scoring_weights w USING (preset_id) GROUP BY p.code""")).all())
        counts = set(conn.execute(text("SELECT count(*) FROM scoring_weights GROUP BY preset_id")).scalars())
    assert sums == {"aggressive": 1, "growth": 1, "balanced": 1, "value": 1} and counts == {5}


EVEN = {"value": 0.2, "quality": 0.2, "growth": 0.2, "safety": 0.2, "momentum": 0.2}


@pytest.mark.parametrize("presets, message", [
    ([{"code": "bad", "sort_order": 1, "weights": {**EVEN, "value": 0.5}}], "합이 1"),
    ([{"code": "bad", "sort_order": 1, "weights": {"value": 0.5, "quality": 0.5}}], "5개"),
    ([{"code": "bad", "sort_order": 1, "weights": {**EVEN, "value": 1.2, "quality": -0.2, "growth": 0, "safety": 0, "momentum": 0}}], "0~1"),
    ([{"code": "bad", "sort_order": 1, "weights": {**EVEN, "value": 0.2005, "momentum": 0.1995}}], "셋째 자리"),
    ([{"code": "a", "weights": EVEN}], "sort_order"),
    ([{"code": "a", "sort_order": 1, "weights": EVEN}, {"code": "b", "sort_order": 1, "weights": EVEN}], "sort_order"),
])
def test_invalid_presets_are_rejected(presets, message):
    with pytest.raises(ValueError, match=message):
        validate_presets(presets)


def _add_old_quality_preset(engine):
    with engine.begin() as conn:
        pid = conn.execute(text("INSERT INTO scoring_presets (code, name, sort_order) VALUES ('quality', '퀄리티형', 9) "
                                "RETURNING preset_id")).scalar_one()
        conn.execute(text("INSERT INTO scoring_weights SELECT :p, factor, weight FROM scoring_weights w "
                          "JOIN scoring_presets s USING (preset_id) WHERE s.code = 'balanced'"), {"p": pid})
        conn.execute(text("INSERT INTO stock_scores (stock_id, as_of, preset_id, score, factor_coverage) VALUES (1, :d, :p, 50, 5)"),
                     {"d": D, "p": pid})


def _presets_in_db(engine):
    with engine.connect() as conn:
        return conn.execute(text("""SELECT p.code, p.name, p.sort_order, (SELECT count(*) FROM stock_scores st WHERE st.preset_id = p.preset_id)
                                    FROM scoring_presets p ORDER BY p.sort_order""")).all()


def test_sync_removes_presets_missing_from_config(engine):
    _add_old_quality_preset(engine)
    with engine.begin() as conn:
        sync_presets(conn)
        sync_presets(conn)                                                   # 재실행 안전
    rows = _presets_in_db(engine)
    assert [(r[0], r[1], r[2]) for r in rows] == [("aggressive", "위험", 1), ("growth", "성장", 2), ("balanced", "균형", 3), ("value", "가치", 4)]


def test_migration_002_is_idempotent(engine):
    _add_old_quality_preset(engine)
    for _ in range(2):
        migrate(engine, "002_presets")
    rows = _presets_in_db(engine)
    assert [r[0] for r in rows] == ["aggressive", "growth", "balanced", "value"]
    with engine.connect() as conn:
        w = dict(conn.execute(text("""SELECT w.factor, w.weight FROM scoring_weights w JOIN scoring_presets p USING (preset_id)
                                      WHERE p.code = 'aggressive'""")).all())
    assert w == {"value": Dec("0.05"), "quality": Dec("0.1"), "growth": Dec("0.35"), "safety": Dec("0.1"), "momentum": Dec("0.4")}


# ------------------------------------------------------------------ API
def test_analysis_api_returns_contributions_metrics_and_rank(client, engine, universe):
    compute_scores(engine, as_of=D)
    a = client.get(f"{API}/stocks/KOSPI/005930/analysis?preset=growth").json()["attractiveness"]
    assert a["preset"]["code"] == "growth" and a["factor_total"] == 5
    assert a["factor_coverage"] == 5 and 0 <= a["score"] < 100
    assert sum(f["contribution"] for f in a["factors"].values()) == pytest.approx(a["composite"], abs=1e-3)
    assert a["factors"]["growth"]["weight"] == 0.4 and a["factors"]["growth"]["effective_weight"] == 0.4
    assert [m["metric"] for m in a["metrics"]] == list(METRICS) and a["metrics"][0]["label"] == "세후 보수 이익/시총"
    vol = next(m for m in a["metrics"] if m["metric"] == "volatility")
    assert vol["direction"] == -1 and vol["raw_value"] is not None and vol["z_adj"] is not None
    # 국가 내 순위: KR에서 점수가 있는 종목(1, 2, 5, 6, 7) 중 — 8은 재무가 없어 수익성(필수)이 없다
    assert a["rank"]["country"] == "KR" and a["rank"]["total"] == 5 and 1 <= a["rank"]["position"] <= 5
    assert a["score"] == pytest.approx(100 * (5 - a["rank"]["position"]) / 5, abs=0.01)
    assert a["data_quality"]["model_version"] == load_config()["model_version"]
    none = client.get(f"{API}/stocks/KOSPI/035720/analysis").json()["attractiveness"]
    assert none["score"] is None and none["rank"] is None and none["preset"]["code"] == "balanced"
    assert all(f["contribution"] is None for f in none["factors"].values())


def test_preset_parameter_on_lists_and_unknown_preset(client, engine, universe):
    compute_scores(engine, as_of=D)
    client.post(f"{API}/watchlist", json={"market": "KOSPI", "ticker": "005930"})
    by = {}
    for p in ("balanced", "value"):
        items = client.get(f"{API}/stocks?preset={p}&country=KR").json()
        assert items["preset"] == p
        by[p] = {x["ticker"]: x["score"] for x in items["items"]}
        w = client.get(f"{API}/watchlist?preset={p}").json()
        assert w["preset"] == p and w["items"][0]["score"] == by[p]["005930"]
        assert client.get(f"{API}/stocks/KOSPI/005930?preset={p}").json()["score"] == by[p]["005930"]
    assert by["balanced"] != by["value"]
    assert client.get(f"{API}/stocks").json()["preset"] == "balanced"
    assert client.get(f"{API}/stocks?preset=quality").status_code == 422          # 없어진 프리셋
    r = client.get(f"{API}/stocks?preset=buffett")
    assert r.status_code == 422 and r.json()["error"]["code"] == "UNKNOWN_PRESET"
    assert "balanced" in r.json()["error"]["detail"]["presets"]


def test_presets_endpoint(client):
    body = client.get(f"{API}/scoring/presets").json()
    assert "특정 인물의 판단이 아닙니다" in body["note"]
    assert [x["code"] for x in body["presets"]] == ["aggressive", "growth", "balanced", "value"]
    assert [x["sort_order"] for x in body["presets"]] == [1, 2, 3, 4]
    p = {x["code"]: x for x in body["presets"]}
    assert (p["aggressive"]["name"], p["aggressive"]["description"]) == ("위험", "모멘텀·성장 중심")
    assert list(p["value"]["weights"]) == list(FACTORS) and p["value"]["weights"]["value"] == 0.4
    assert p["aggressive"]["weights"] == {"value": 0.05, "quality": 0.1, "growth": 0.35, "safety": 0.1, "momentum": 0.4}
    assert p["balanced"]["is_default"] and not p["growth"]["is_default"]
    assert all(sum(x["weights"].values()) == pytest.approx(1) for x in body["presets"])


def test_refresh_runs_scorer(client, engine, universe):
    p = make_providers()
    svc = RefreshService(engine, p, FxService(engine, p.fx, 4), 4, scorer=compute_scores)
    job = next(j for j in svc.refresh().jobs if j.job_type == "SCORES")
    assert job.status == "SUCCESS" and job.counts["rows"] == 8 * 4
    body = client.get(f"{API}/stocks/KOSPI/005930/analysis").json()
    assert body["attractiveness"]["score"] is not None and "투자 권유가 아닙니다" in body["disclaimer"]
    assert client.get(f"{API}/statistics/overview").json()["stock_scores"] == 8 * 4

def test_analysis_includes_fin_basis(client, engine, universe):
    before = client.get(f"{API}/stocks/KOSPI/005930/analysis").json()["attractiveness"]
    assert before["fin_basis"] == []                                    # 점수가 없으면 빈 배열
    compute_scores(engine, as_of=D)
    kr = client.get(f"{API}/stocks/KOSPI/005930/analysis").json()["attractiveness"]
    us = client.get(f"{API}/stocks/NASDAQ/AAPL/analysis").json()["attractiveness"]
    assert kr["fin_basis"] == [{"fiscal_year": 2024, "stocks": 5}]       # KR 재무 있는 5종목 모두 FY2024
    assert us["fin_basis"] == [{"fiscal_year": 2025, "stocks": 1}, {"fiscal_year": 2024, "stocks": 1}]


# ------------------------------------------------------------------ 테마 규칙 (개발산출물/09 2~4절)
def _theme_rule(engine, group_id: int, **cols):
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE peer_groups SET {', '.join(f'{k} = :{k}' for k in cols)} WHERE group_id = :g"),
                     {**cols, "g": group_id})


def test_neutralized_z_is_clipped_to_3(engine):
    """그룹 평균이 크게 음수면 z − n/(n+k)·평균이 3을 넘는다 → 다시 ±3으로 자른다(Alcoa처럼 적자 종목이 섞인 그룹)."""
    with engine.begin() as conn:
        add_kr_stocks(conn, [5])
        conn.execute(text("INSERT INTO peer_group_members VALUES (1, 5, true)"))       # 반도체(KR): 1, 2, 5
        conn.execute(text("""INSERT INTO stock_metric_values (stock_id, as_of, metric, factor, raw_value, z_raw)
                             VALUES (1, :d, 'return_on_assets', 'quality', 0, 3), (2, :d, 'return_on_assets', 'quality', 0, -3),
                                    (5, :d, 'return_on_assets', 'quality', 0, -3)"""), {"d": D})
        conn.execute(sql("score_neutralize"), {"as_of": D, "k": K})
        adj = read(conn, "z_adj", "return_on_assets")
    assert 3 - 3 / (3 + K) * (-1) > 3 and adj[1] == 3                       # 3.375 → 3
    assert adj[2] == pytest.approx(-3 - 3 / (3 + K) * (-1), abs=1e-4)      # −2.625(범위 안이면 그대로)


def test_financial_theme_drops_revenue_metrics_and_scores_separately(engine, universe):
    _theme_rule(engine, 3, scoring="financial")                             # 자동차(5, 6)를 금융 묶음으로
    compute_scores(engine, as_of=D)
    with engine.connect() as conn:
        mv = {(r.stock_id, r.metric): r for r in conn.execute(
            text("SELECT * FROM stock_metric_values WHERE as_of = :d"), {"d": D})}
        st = scores_by(conn)
    for s in (5, 6):
        for m in ("operating_margin", "revenue_cagr2", "liab_assets", "trap_signal"):
            assert mv[(s, m)].raw_value is None, (s, m)
        dq = st[s]["data_quality"]
        assert dq["partition"] == "KR·금융" and dq["family"] == "financial"
        assert dq["missing_metrics"]["operating_margin"] == "금융 업종 — 매출 기준 지표는 쓰지 않음"
    # 금융은 순이익 기준: 총자산 이익률 = 순이익 / 자산
    assert float(mv[(6, "return_on_assets")].raw_value) == pytest.approx(30 / 95)
    assert mv[(1, "operating_margin")].raw_value is not None and st[1]["data_quality"]["partition"] == "KR"
    # 금융 2종목끼리 표준화: B/P는 표본 2개 → 평균·표준편차 Z = ±1/√2, 백분위는 50(1위)·0(2위)
    assert {round(float(mv[(s, "book_yield")].z_raw), 4) for s in (5, 6)} == {0.7071, -0.7071}
    assert {float(st[s]["score"]) for s in (5, 6) if st[s]["score"] is not None} <= {50.0, 0.0}


def test_three_year_conservative_earnings_apply_to_every_theme(engine, universe):
    """업황 정점 방지(최신 이익 > 3년 평균이면 3년 평균)는 원자재 테마만이 아니라 모든 종목에 건다(D-002)."""
    with engine.connect() as conn:
        rows = {(r["stock_id"], r["metric"]): r for r in conn.execute(sql("score_metrics"), metric_params()).mappings()}
    close = universe[1][-1]
    e = [_earn(4, 9), _earn(8, 10), _earn(12, 15)]                       # 4, 7.8, 11.7 → 3년 평균 7.83
    assert float(rows[(1, "conservative_yield")]["raw_value"]) == pytest.approx(sum(e) / 3 / (1000 * close), rel=1e-4)
    assert "3년 평균" in rows[(1, "conservative_yield")]["note"]
    assert "재무 이력 2년" in rows[(2, "conservative_yield")]["note"]          # FY 2개 → 최신 FY 이익
    assert float(rows[(2, "conservative_yield")]["raw_value"]) == pytest.approx(-20 / (1000 * universe[2][-1]), rel=1e-4)


def test_reit_theme_is_not_scored_and_reference_explains(client, engine, universe):
    _theme_rule(engine, 3, scoring="none", name="리츠·부동산")               # 자동차(5, 6)를 점수 없음(리츠)으로
    compute_scores(engine, as_of=D)
    assert scalar(engine, "SELECT count(*) FROM stock_metric_values WHERE stock_id IN (5, 6)") == 0
    b = client.get(f"{API}/stocks/KOSPI/005380/analysis").json()["attractiveness"]   # 비교 표본에 남은 점수 없음 종목도 사유
    assert b["score"] is None and "리츠" in b["unscored_reason"]
    with engine.begin() as conn:                                            # 상장 목록 리츠 종목 → 사유만
        conn.execute(text("UPDATE stocks SET coverage = 'listed' WHERE stock_id = 5"))
    a = client.get(f"{API}/stocks/KOSPI/035420/analysis").json()["attractiveness"]
    assert a["score"] is None and a["as_of"] is None and "리츠" in a["unscored_reason"]


def test_reference_score_neutralizes_with_primary_theme(engine, universe):
    from app.services.reference_score import neutralize, reference_score
    compute_scores(engine, as_of=D)
    with engine.begin() as conn:                                            # 상장 목록 종목 9 → 반도체 주 테마
        conn.execute(text("INSERT INTO stocks (stock_id, market_id, ticker, name, coverage) VALUES (9, 1, '999999', '상장', 'listed')"))
        conn.execute(text("INSERT INTO peer_group_members VALUES (1, 9, true)"))
        conn.execute(text("""INSERT INTO valuation_snapshots (stock_id, as_of, eps, bps, shares_outstanding, source)
                             VALUES (9, :d, 5, 50, 1000, 'PYKRX')"""), {"d": D})
        conn.execute(text("""INSERT INTO financial_statements (stock_id, period_end, period_type, revenue, operating_income,
                             net_income, total_equity, total_debt, total_assets, data_source) VALUES
                             (9, '2023-12-31', 'FY', 100, 10, 8, 60, 40, 100, 'DART'),
                             (9, '2024-12-31', 'FY', 110, 12, 9, 64, 40, 104, 'DART')"""))
    _replace_prices(engine, 9, _path(300, 0, .5), D)
    with engine.connect() as conn:
        preset = conn.execute(text("SELECT preset_id, code, name, description FROM scoring_presets WHERE code = 'balanced'")).mappings().one()
        out = reference_score(conn, 9, "KR", dict(preset))
        peers = [float(z) for z in conn.execute(text("""SELECT z_raw FROM stock_metric_values
                 WHERE as_of = :d AND metric = 'book_yield' AND stock_id IN (1, 2)"""), {"d": D}).scalars()]
    by = {m["metric"]: m for m in out["metrics"]}
    assert float(by["book_yield"]["z_adj"]) == pytest.approx(neutralize(float(by["book_yield"]["z_raw"]), peers, K), abs=2e-4)
    assert by["volatility"]["z_adj"] == by["volatility"]["z_raw"]           # 안정성은 중립화하지 않는다
    assert "주 테마 '반도체' 비교군 2개로 섹터 중립화" in out["reference_note"] and out["rank"]["family"] == "general"
    # 점수 = 유니버스 종합 사이 순위의 백분위, 재무 FY 2개 → 이력 기록
    assert float(out["score"]) == pytest.approx(100 * (out["rank"]["total"] - out["rank"]["position"]) / out["rank"]["total"], abs=0.01)
    assert out["data_quality"]["fy_history"] == 2
    assert sum(float(f["contribution"]) for f in out["factors"].values() if f["contribution"] is not None) == \
        pytest.approx(float(out["composite"]), abs=1e-3)
