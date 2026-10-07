"""매력도 다중 팩터 모델 손계산 검증 (docs/09).

단계별: 로버스트 Z·부호 반전·±3 클리핑·MAD=0 대체 / 축소 계수 n/(n+k) / 팩터 평균·재정규화·유효 팩터 3개 미만 NULL / Φ 변환.
전체: 시세·재무·밸류에이션 픽스처에서 지표 원값 → Z → 점수를 파이썬 참조 구현과 비교, 경계 사례, 프리셋, API.
"""
from __future__ import annotations

import math
import statistics
from datetime import timedelta
from decimal import Decimal as Dec

import pytest
from sqlalchemy import text

from app.services.fx import FxService
from app.services.refresh import RefreshService
from app.ingest.jobs import migrate
from app.services.scoring import (FACTORS, METRICS, aggregate, compute_scores, load_config, normalize, sync_presets,
                                  validate_presets)
from tests.conftest import D
from tests.fakes import make_providers
from tests.test_analysis import _path, _replace_prices

API = "/api/v1"
K = 5


def phi(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


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
        put_raw(conn, "roe", vals)                               # 방향 +
        put_raw(conn, "volatility", vals)                        # 방향 −
        normalize(conn, D, K)
        roe, vol = read(conn, "z_raw", "roe"), read(conn, "z_raw", "volatility")
    s = 1.4826 * 0.01
    assert roe[1] == pytest.approx((0.10 - 0.11) / s, abs=1e-4)          # −0.6745
    assert roe[5] == pytest.approx((0.08 - 0.11) / s, abs=1e-4)          # −2.0235
    assert roe[6] == 0 and roe[7] == 3                                    # 26.3 → 3으로 클리핑
    assert vol[1] == pytest.approx(-roe[1], abs=1e-4) and vol[7] == -3   # 부호 반전 후 클리핑


def test_mad_zero_and_small_sample_fall_back_to_mean_sd(engine):
    with engine.begin() as conn:
        add_kr_stocks(conn, [5, 6, 7])
        put_raw(conn, "roe", {1: 1, 2: 1, 5: 1, 6: 1, 7: 5})               # MAD = 0 → 평균·표준편차
        put_raw(conn, "book_yield", {3: 1, 4: 3})                          # US 2개(표본 < 5)
        put_raw(conn, "operating_margin", {1: 2, 2: 2, 5: 2})               # 표준편차 0 → Z = 0
        put_raw(conn, "momentum", {3: 0.1})                                 # 표본 1개 → Z = 0
        normalize(conn, D, K)
        roe, by = read(conn, "z_raw", "roe"), read(conn, "z_raw", "book_yield")
        opm, mom = read(conn, "z_raw", "operating_margin"), read(conn, "z_raw", "momentum")
    sd = statistics.stdev([1, 1, 1, 1, 5])
    assert roe[7] == pytest.approx((5 - 1.8) / sd, abs=1e-4) and roe[1] == pytest.approx((1 - 1.8) / sd, abs=1e-4)
    assert by[4] == pytest.approx(1 / math.sqrt(2), abs=1e-4) and by[3] == pytest.approx(-1 / math.sqrt(2), abs=1e-4)
    assert set(opm.values()) == {0} and mom[3] == 0


def test_countries_are_normalized_separately(engine):
    with engine.begin() as conn:
        put_raw(conn, "roe", {1: 0.1, 2: 0.3, 3: 10, 4: 30})              # US 값이 커도 KR과 섞이지 않는다
        normalize(conn, D, K)
        z = read(conn, "z_raw", "roe")
    assert z[1] == pytest.approx(z[3], abs=1e-4) and z[2] == pytest.approx(z[4], abs=1e-4)


# ------------------------------------------------------------------ 2단계: 섹터 중립화(축소 추정)
def test_shrinkage_uses_primary_group_mean_including_self(engine):
    vals = {5: 0.30, 6: 0.20, 7: 0.25, 8: 0.05, 9: 0.10}              # 5·6·7은 같은 주 그룹, 8은 그룹 없음
    with engine.begin() as conn:
        add_kr_stocks(conn, [5, 6, 7, 8, 9])
        conn.execute(text("INSERT INTO peer_groups (group_id, name) VALUES (3, '자동차'), (4, '단독')"))
        conn.execute(text("INSERT INTO peer_group_members VALUES (3, 5, true), (3, 6, true), (3, 7, true), "
                          "(4, 9, true), (1, 8, false)"))
        put_raw(conn, "roe", vals)
        normalize(conn, D, K)
        z, adj = read(conn, "z_raw", "roe"), read(conn, "z_adj", "roe")
    group_mean = (z[5] + z[6] + z[7]) / 3                               # 자기 자신 포함
    for s in (5, 6, 7):
        assert adj[s] == pytest.approx(z[s] - 3 / (3 + K) * group_mean, abs=2e-4)
    assert adj[8] == z[8]                                                # 주 그룹 없음(비주 그룹만 소속)
    assert adj[9] == z[9]                                                # 주 그룹 표본 n = 1


# ------------------------------------------------------------------ 3단계: 합산·Φ 변환
def put_z(conn, sid: int, z_by_metric: dict[str, float], as_of=D):
    conn.execute(text("""INSERT INTO stock_metric_values (stock_id, as_of, metric, factor, raw_value, z_raw, z_adj)
                         VALUES (:s, :d, :m, :f, 0, :z, :z)"""),
                 [{"s": sid, "d": as_of, "m": m, "f": METRICS[m].factor, "z": z} for m, z in z_by_metric.items()])


def scores_by(conn, preset="balanced", as_of=D) -> dict[int, dict]:
    rows = conn.execute(text("""SELECT st.* FROM stock_scores st JOIN scoring_presets p USING (preset_id)
                                WHERE p.code = :p AND st.as_of = :d"""), {"p": preset, "d": as_of}).mappings()
    return {r["stock_id"]: r for r in rows}


ALL_METRICS = list(METRICS)


def test_phi_transform_z0_is_50_and_z1_is_8413(engine):
    with engine.begin() as conn:
        add_kr_stocks(conn, [5, 6, 7])
        for sid, c in {5: -1.0, 6: 0.0, 7: 1.0}.items():                 # 모든 지표 z = c → 종합 = c
            put_z(conn, sid, {m: c for m in ALL_METRICS})
        aggregate(conn, D)
        sc = scores_by(conn)
    # 종합 −1, 0, 1 → 국가 내 평균 0, 표본표준편차 1 → Z_c = −1, 0, 1
    assert float(sc[6]["score"]) == 50.0
    assert float(sc[7]["score"]) == pytest.approx(100 * phi(1), abs=0.01) == pytest.approx(84.13, abs=0.01)
    assert float(sc[5]["score"]) == pytest.approx(100 * phi(-1), abs=0.01)


def test_factor_average_reweighting_and_minimum_coverage(engine):
    with engine.begin() as conn:
        add_kr_stocks(conn, [5, 6, 7])
        put_z(conn, 5, {"earnings_yield": 1.0, "book_yield": 2.0, "roe": 0.5, "revenue_yoy": -1.0})   # 3개 팩터
        put_z(conn, 6, {"earnings_yield": 0.2, "roe": -0.4})                                           # 2개 팩터
        put_z(conn, 7, {m: 0.3 for m in ALL_METRICS})
        aggregate(conn, D)
        growth, balanced = scores_by(conn, "growth"), scores_by(conn, "balanced")
    s5 = growth[5]
    assert float(s5["value_score"]) == 1.5                              # 지표 2개 평균
    assert s5["factor_coverage"] == 3 and s5["safety_score"] is None
    # 성장형 가중치 value 0.10 · quality 0.20 · growth 0.40 → 유효 팩터만 재정규화
    assert float(s5["composite"]) == pytest.approx((0.10 * 1.5 + 0.20 * 0.5 + 0.40 * -1.0) / 0.70, abs=1e-4)
    assert float(balanced[5]["composite"]) == pytest.approx((1.5 + 0.5 - 1.0) / 3, abs=1e-4)
    s6 = balanced[6]                                                     # 유효 팩터 2개 → 점수 NULL
    assert s6["factor_coverage"] == 2 and s6["composite"] is None and s6["score"] is None
    assert "2/5" in s6["data_quality"]["score_null_reason"]
    assert set(s6["data_quality"]["unavailable_factors"]) == {"growth", "safety", "momentum"}


# ------------------------------------------------------------------ 전체 파이프라인 손계산
# KR 6종목(1, 2, 5~8) · US 2종목(3, 4). 주 그룹: 반도체(1, 2, 4), 빅테크(3), 자동차(5, 6), 7·8은 없음
PRICES = {1: (300, 0, .1), 2: (300, 1, -.05), 5: (130, 2, .02), 6: (130, .7, .08), 7: (100, 1.5, 0), 8: (50, .3, .01),
          3: (130, .5, .2), 4: (300, 3, .3)}
VALUATION = {  # eps, bps, shares, market_cap
    1: (8, 80, 1000, None), 2: (-2, 50, 1000, None), 5: (None, 40, 1000, None), 6: (5, 120, 1000, None),
    7: (3, 30, None, 100_000), 8: (4, 60, 1000, None), 3: (6, 4, 1000, None), 4: (2, 10, 1000, None)}
FIN = {        # (결산일, 매출, 영업이익, 순이익, 자본, 부채) 직전 FY → 최신 FY
    1: [("2023-12-31", 100, 10, 8, 100, 50), ("2024-12-31", 120, 15, 12, 110, 44)],
    2: [("2023-12-31", 200, 40, 30, 150, 60), ("2024-12-31", 210, 30, -20, 160, 80)],
    5: [("2023-12-31", 0, -5, -10, 50, 20), ("2024-12-31", 50, -2, -15, 40, 30)],     # 직전 매출 0, 적자(EPS 미제공)
    6: [("2023-12-31", 80, 8, 6, -10, 90), ("2024-12-31", 90, 9, 7, -5, 100)],        # 자본 ≤ 0
    7: [("2024-12-31", 60, 6, 4, 40, 20)],                                            # 직전 FY 없음
    3: [("2023-09-30", 300, 90, 80, 60, 120), ("2024-09-30", 330, 99, 90, 70, 140)],
    4: [("2024-01-31", 50, 20, 15, 40, 10), ("2025-01-31", 120, 70, 60, 80, 20)]}
PRIMARY = {1: 1, 2: 1, 4: 1, 3: 2, 5: 3, 6: 3}
COUNTRY = {1: "KR", 2: "KR", 5: "KR", 6: "KR", 7: "KR", 8: "KR", 3: "US", 4: "US"}


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
                             net_income, total_equity, total_debt, data_source) VALUES (:s, :p, 'FY', :r, :o, :n, :e, :d, 'DART')"""),
                     [{"s": s, "p": p, "r": r, "o": o, "n": n, "e": e, "d": d} for s, fy in FIN.items() for p, r, o, n, e, d in fy])
    for s, (n, phase, slope) in PRICES.items():
        closes[s] = [float(c) for c in _path(n, phase, slope)]
        _replace_prices(engine, s, _path(n, phase, slope), D)
    return closes


def reference_raw(closes) -> dict[int, dict[str, float | None]]:
    out = {}
    for s, cl in closes.items():
        close = cl[-1]
        eps, bps, shares, mc = VALUATION[s]
        shares = shares if shares is not None else mc / close
        fy = FIN.get(s, [])
        cur = fy[-1] if fy else None
        prev = fy[-2] if len(fy) > 1 else None
        if eps is None and cur:
            eps = cur[3] / shares
        r: dict[str, float | None] = {
            "earnings_yield": eps / close if eps is not None else None,
            "book_yield": bps / close,
            "roe": cur[3] / cur[4] if cur and cur[4] > 0 else None,
            "operating_margin": cur[2] / cur[1] if cur and cur[1] else None,
            "revenue_yoy": cur[1] / prev[1] - 1 if prev and prev[1] > 0 else None,
            "eps_change_yield": (cur[3] - prev[3]) / shares / close if prev else None,
            "debt_ratio": cur[5] / cur[4] if cur and cur[4] > 0 else None,
            "volatility": (statistics.stdev([cl[-253:][i] / cl[-253:][i - 1] - 1 for i in range(1, 253)]) * math.sqrt(252)
                           if len(cl) >= 253 else None),
            "momentum": (cl[-22] / cl[-253] - 1 if len(cl) >= 253 else cl[-22] / cl[-127] - 1 if len(cl) >= 127 else None),
        }
        out[s] = r
    return out


def reference_scores(raw):
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
                z_raw[s][metric] = round(max(-3, min(3, z * d.direction)), 4)
        for s in raw:                                                   # 자본 ≤ 0 부채비율
            if metric == "debt_ratio" and FIN.get(s) and FIN[s][-1][4] <= 0:
                z_raw[s][metric] = -3.0
    z_adj = {s: {} for s in raw}
    for metric in METRICS:
        for s in raw:
            if metric not in z_raw[s]:
                continue
            g = PRIMARY.get(s)
            mates = [t for t in raw if g is not None and PRIMARY.get(t) == g and metric in z_raw[t]]
            n = len(mates)
            z = z_raw[s][metric]
            z_adj[s][metric] = round(z - n / (n + K) * sum(z_raw[t][metric] for t in mates) / n if n > 1 else z, 4)
    fac = {s: {f: statistics.mean(v for m, v in z_adj[s].items() if METRICS[m].factor == f)
               for f in FACTORS if any(METRICS[m].factor == f for m in z_adj[s])} for s in raw}
    out = {}
    for p in load_config()["presets"]:
        w = p["weights"]
        comp = {s: (sum(w[f] * v for f, v in fac[s].items()) / sum(w[f] for f in fac[s]) if len(fac[s]) >= 3 else None)
                for s in raw}
        res = {}
        for c in ("KR", "US"):
            cs = {s: v for s, v in comp.items() if COUNTRY[s] == c and v is not None}
            mean, sd = statistics.mean(cs.values()), statistics.stdev(cs.values()) if len(cs) > 1 else 0
            res.update({s: 100 * phi((v - mean) / sd if sd > 0 else 0) for s, v in cs.items()})
        out[p["code"]] = {"composite": comp, "score": res}
    return z_raw, z_adj, fac, out


def test_full_pipeline_matches_reference_implementation(engine, universe):
    n = compute_scores(engine, as_of=D)
    assert n == 8 * 4                                                    # 종목 × 프리셋
    raw_ref = reference_raw(universe)
    z_raw_ref, z_adj_ref, fac_ref, scores_ref = reference_scores(raw_ref)
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
                    assert float(got[s]["score"]) == pytest.approx(ref["score"][s], abs=0.05), (code, s)


def test_boundary_cases(engine, universe):
    compute_scores(engine, as_of=D)
    with engine.connect() as conn:
        ep = read(conn, "z_raw", "earnings_yield")
        debt, roe = read(conn, "z_raw", "debt_ratio"), read(conn, "raw_value", "roe")
        sc = scores_by(conn)
    positive_eps = [s for s in (1, 6, 7, 8)]
    # 적자(EPS < 0 제공 / EPS 미제공 + 순이익 < 0 → 대체 계산)는 E/P 하위
    assert max(ep[2], ep[5]) < min(ep[s] for s in positive_eps)
    assert any("EPS 미제공" in n for n in sc[5]["data_quality"]["notes"])
    # 자본 ≤ 0: ROE NULL, 부채비율 Z = −3 고정
    assert roe[6] is None and debt[6] == -3
    assert sc[6]["data_quality"]["missing_metrics"]["roe"] == METRICS["roe"].null_reason
    # 직전 매출 ≤ 0 → 매출 YoY NULL
    assert "revenue_yoy" in sc[5]["data_quality"]["missing_metrics"]
    # 일봉 253개 미만 → 6-1개월, 127개 미만 → 모멘텀 없음
    assert any("6-1개월" in n for n in sc[5]["data_quality"]["notes"])
    assert "momentum" in sc[7]["data_quality"]["missing_metrics"] and "notes" not in sc[1]["data_quality"]
    # 유효 팩터 1개(value)뿐인 카카오(8) → 점수 NULL
    assert sc[8]["factor_coverage"] == 1 and sc[8]["score"] is None


def test_adding_a_stock_does_not_rescale_like_min_max(engine, universe):
    compute_scores(engine, as_of=D)
    with engine.connect() as conn:
        before = {s: float(r["score"]) for s, r in scores_by(conn).items() if r["score"] is not None and COUNTRY[s] == "KR"}
    with engine.begin() as conn:                                         # 모든 지표가 극단적으로 좋은 종목 추가
        conn.execute(text("INSERT INTO stocks (stock_id, market_id, ticker, name) VALUES (9, 1, '999999', '극단')"))
        conn.execute(text("""INSERT INTO valuation_snapshots (stock_id, as_of, eps, bps, shares_outstanding, source)
                             VALUES (9, :d, 500, 5000, 1000, 'PYKRX')"""), {"d": D})
        conn.execute(text("""INSERT INTO financial_statements (stock_id, period_end, period_type, revenue, operating_income,
                             net_income, total_equity, total_debt, data_source) VALUES
                             (9, '2023-12-31', 'FY', 100, 50, 40, 100, 1, 'DART'), (9, '2024-12-31', 'FY', 400, 300, 250, 300, 1, 'DART')"""))
    _replace_prices(engine, 9, _path(300, 0, .5), D)
    compute_scores(engine, as_of=D)
    with engine.connect() as conn:
        after = {s: float(r["score"]) for s, r in scores_by(conn).items() if r["score"] is not None}
    for scores in (before, after):                                        # Min-Max라면 최고 100·최저 0으로 고정
        assert 0 < min(scores.values()) and max(scores.values()) < 100
    top = max(before, key=before.get)
    assert after[top] < 100 and after[9] < 100


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
    assert a["factor_coverage"] == 5 and 0 < a["score"] < 100
    assert sum(f["contribution"] for f in a["factors"].values()) == pytest.approx(a["composite"], abs=1e-3)
    assert a["factors"]["growth"]["weight"] == 0.4 and a["factors"]["growth"]["effective_weight"] == 0.4
    assert [m["metric"] for m in a["metrics"]] == list(METRICS) and a["metrics"][0]["label"] == "이익수익률 E/P"
    vol = next(m for m in a["metrics"] if m["metric"] == "volatility")
    assert vol["direction"] == -1 and vol["raw_value"] is not None and vol["z_adj"] is not None
    # 국가 내 순위: KR에서 점수가 있는 종목(1, 2, 5, 6, 7) 중
    assert a["rank"]["country"] == "KR" and a["rank"]["total"] == 5 and 1 <= a["rank"]["position"] <= 5
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
