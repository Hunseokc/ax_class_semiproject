"""분석 SQL을 손계산(파이썬)과 비교: v_stock_metrics, 매력도(PERCENT_RANK·가중 재정규화), 경쟁 비교, 통계."""
from __future__ import annotations

import math
import statistics
from datetime import date, timedelta
from decimal import Decimal as Dec

import pytest
from sqlalchemy import text

from app.services.fx import FxService
from app.services.refresh import RefreshService
from app.services.scoring import compute_scores
from tests.conftest import D
from tests.fakes import make_providers

API = "/api/v1"
WEIGHTS = {"version": "test", "w_val": 30, "w_gro": 25, "w_pro": 25, "w_mom": 20}


# ------------------------------------------------------------------ v_stock_metrics 손계산
def _path(n: int, phase: float, slope: float, base: float = 100) -> list[Dec]:
    return [Dec(str(round(base + 10 * math.sin(i / 15 + phase) + i * slope, 4))) for i in range(n)]


def _replace_prices(engine, stock_id: int, closes: list[Dec], end: date) -> list[date]:
    dates = [end - timedelta(days=len(closes) - 1 - i) for i in range(len(closes))]
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_prices WHERE stock_id = :s"), {"s": stock_id})
        conn.execute(text("INSERT INTO daily_prices VALUES (:s, :d, :c, :c + 1, :c - 1, :c, :v)"),
                     [{"s": stock_id, "d": d, "c": c, "v": 1000 + (i % 7) * 100} for i, (d, c) in enumerate(zip(dates, closes))])
    return dates


def _before(dates, closes, target):
    c = [x for d, x in zip(dates, closes) if d <= target]
    return c[-1] if c else None


def _months_ago(d: date, m: int) -> date:
    y, mo = divmod(d.month - 1 - m, 12)
    import calendar
    return date(d.year + y, mo + 1, min(d.day, calendar.monthrange(d.year + y, mo + 1)[1]))


def test_stock_metrics_match_hand_calculation(engine):
    closes = _path(420, 0, 0.05)                 # 달력일 420일 → 1년 전 기준가 존재
    dates = _replace_prices(engine, 1, closes, D)
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO financial_statements (stock_id, period_end, period_type, revenue, operating_income,
                             net_income, total_equity, total_debt, data_source) VALUES
                             (1, '2023-12-31', 'FY', 1000, 100, 50, 500, 200, 'DART'),
                             (1, '2024-12-31', 'FY', 1200, 90, 60, 400, 200, 'DART')"""))
    with engine.connect() as conn:
        m = conn.execute(text("SELECT * FROM v_stock_metrics WHERE stock_id = 1")).mappings().one()
    last = closes[-1]
    exp = {
        "return_1w": last / _before(dates, closes, D - timedelta(days=7)) - 1,
        "return_1m": last / _before(dates, closes, _months_ago(D, 1)) - 1,
        "return_3m": last / _before(dates, closes, _months_ago(D, 3)) - 1,
        "return_6m": last / _before(dates, closes, _months_ago(D, 6)) - 1,
        "return_1y": last / _before(dates, closes, _months_ago(D, 12)) - 1,
    }
    r253 = closes[-253:]
    exp["volatility_1y"] = statistics.stdev([float(r253[i] / r253[i - 1] - 1) for i in range(1, 253)]) * math.sqrt(252)
    peak, mdd = closes[-252], 0.0
    for c in closes[-252:]:
        peak = max(peak, c)
        mdd = min(mdd, float(c / peak - 1))
    exp["max_drawdown_1y"] = mdd
    for n in (20, 60, 120):
        exp[f"ma{n}"] = sum(closes[-n:]) / n
    exp["ma120_gap"] = last / exp["ma120"] - 1
    year = [c for d, c in zip(dates, closes) if d > _months_ago(D, 12)]
    hi, lo = max(year) + 1, min(year) - 1
    exp.update(high_52w=hi, low_52w=lo, position_52w=(last - lo) / (hi - lo))
    vols = [1000 + (i % 7) * 100 for i in range(420)]
    exp["volume_ratio_20d"] = Dec(vols[-1]) / (Dec(sum(vols[-21:-1])) / 20)
    exp.update(operating_margin=Dec(90) / Dec(1200), roe=Dec(60) / Dec(400), debt_ratio=Dec(200) / Dec(400),
               revenue_yoy=Dec("0.2"), operating_income_yoy=Dec("-0.1"))
    for k, v in exp.items():
        assert m[k] is not None, k
        assert float(m[k]) == pytest.approx(float(v), abs=1e-4), k


def test_stock_metrics_are_null_when_data_is_insufficient(engine):
    # 픽스처는 3거래일뿐 → 기간 지표 NULL, 재무 없음 → 재무 지표 NULL (거짓 값을 만들지 않음)
    with engine.connect() as conn:
        m = conn.execute(text("SELECT * FROM v_stock_metrics WHERE stock_id = 3")).mappings().one()
    for k in ("return_1m", "return_1y", "volatility_1y", "max_drawdown_1y", "ma20", "ma120_gap", "high_52w",
              "position_52w", "volume_ratio_20d", "roe", "operating_margin", "revenue_yoy"):
        assert m[k] is None, k
    assert m["market_cap_krw"] == 3_000_000_000_000 * 1300


def test_yoy_requires_consecutive_fiscal_years(engine):
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO financial_statements (stock_id, period_end, period_type, revenue, operating_income,
                             net_income, total_equity, data_source) VALUES
                             (2, '2022-12-31', 'FY', 100, 10, 5, 0, 'DART'), (2, '2024-12-31', 'FY', 150, 20, 8, -5, 'DART')"""))
    with engine.connect() as conn:
        m = conn.execute(text("SELECT revenue_yoy, roe, operating_margin FROM v_stock_metrics WHERE stock_id = 2")).one()
    assert m.revenue_yoy is None and m.roe is None              # 2023 누락 → YoY NULL, 자본 ≤ 0 → ROE NULL
    assert float(m.operating_margin) == pytest.approx(20 / 150, abs=1e-6)


# ------------------------------------------------------------------ 매력도 손계산
@pytest.fixture
def scoring_data(engine):
    """KR 3종목(1, 2, 5) · US 2종목(3, 4), 130일 시세, 일부 팩터 계산 불가."""
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO stocks (stock_id, market_id, ticker, name) VALUES (5, 1, '035420', 'NAVER')"))
        conn.execute(text("DELETE FROM valuation_snapshots"))
        conn.execute(text("""INSERT INTO valuation_snapshots (stock_id, as_of, per, pbr, market_cap, source) VALUES
            (1, :d, 12, 1.2, 4e14, 'PYKRX'), (2, :d, -5, 1.5, 1e14, 'PYKRX'), (5, :d, NULL, NULL, 3e13, 'PYKRX'),
            (3, :d, 30, 40, 3e12, 'YFINANCE'), (4, :d, 50, 30, 1e12, 'YFINANCE')"""), {"d": D})
        conn.execute(text("""INSERT INTO financial_statements (stock_id, period_end, period_type, revenue, operating_income,
                             net_income, total_equity, data_source) VALUES
            (1, '2023-12-31', 'FY', 100, 10, 8, 100, 'DART'), (1, '2024-12-31', 'FY', 120, 15, 12, 110, 'DART'),
            (2, '2023-12-31', 'FY', 200, 40, 30, 150, 'DART'), (2, '2024-12-31', 'FY', 210, 30, 20, 160, 'DART'),
            (3, '2023-09-30', 'FY', 300, 90, 80, 60, 'SEC'),   (3, '2024-09-30', 'FY', 330, 99, 90, 70, 'SEC'),
            (4, '2024-01-31', 'FY', 50, 20, 15, 40, 'SEC'),    (4, '2025-01-31', 'FY', 120, 70, 60, 80, 'SEC')"""))
    for sid, (phase, slope) in {1: (0, .1), 2: (1, -.05), 5: (2, .02), 3: (.5, .2), 4: (3, .3)}.items():
        _replace_prices(engine, sid, _path(130, phase, slope), D)


def _pr(values: dict[int, float | None], sid: int, lower_is_better: bool) -> float | None:
    vals = {k: v for k, v in values.items() if v is not None}
    if sid not in vals or len(vals) < 2:
        return None
    x = vals[sid]
    better = sum(1 for v in vals.values() if (v > x if lower_is_better else v < x))
    return better / (len(vals) - 1)


def test_scores_match_hand_calculation(engine, scoring_data):
    with engine.connect() as conn:
        rows = {r["stock_id"]: r for r in conn.execute(text("SELECT * FROM v_stock_metrics")).mappings()}
    n = compute_scores(engine, as_of=D, weights=WEIGHTS)
    assert n == 5
    with engine.connect() as conn:
        got = {r["stock_id"]: r for r in conn.execute(text("SELECT * FROM stock_scores WHERE as_of = :d"), {"d": D}).mappings()}

    def f(v):
        return float(v) if v is not None else None

    inputs = {sid: {"per": f(r["per"]) if r["per"] and r["per"] > 0 else None,
                    "pbr": f(r["pbr"]) if r["pbr"] and r["pbr"] > 0 else None,
                    "rev": f(r["revenue_yoy"]), "op": f(r["operating_income_yoy"]), "opm": f(r["operating_margin"]),
                    "roe": f(r["roe"]), "r3": f(r["return_3m"]), "gap": f(r["ma120_gap"]), "country": r["country"]}
              for sid, r in rows.items()}
    factors = {"valuation": [("per", True), ("pbr", True)], "growth": [("rev", False), ("op", False)],
               "profitability": [("opm", False), ("roe", False)], "momentum": [("r3", False), ("gap", False)]}
    weights = {"valuation": 30, "growth": 25, "profitability": 25, "momentum": 20}
    for sid, inp in inputs.items():
        same = {k: v for k, v in inputs.items() if v["country"] == inp["country"]}
        fac = {}
        for name, subs in factors.items():
            ranks = [_pr({k: v[key] for k, v in same.items()}, sid, low) for key, low in subs]
            ranks = [x for x in ranks if x is not None]
            fac[name] = sum(ranks) / len(ranks) * 100 if ranks else None
            assert (got[sid][f"{name}_score"] is None) == (fac[name] is None), (sid, name)
            if fac[name] is not None:
                assert float(got[sid][f"{name}_score"]) == pytest.approx(fac[name], abs=0.01), (sid, name)
        avail = {k: v for k, v in fac.items() if v is not None}
        expected = sum(weights[k] * v for k, v in avail.items()) / sum(weights[k] for k in avail) if avail else None
        assert float(got[sid]["score"]) == pytest.approx(expected, abs=0.01), sid

    # NAVER(5): PER·PBR·재무 없음 → valuation·growth·profitability 불가, momentum만으로 재정규화
    naver = got[5]
    assert set(naver["data_quality"]["unavailable"]) == {"valuation", "growth", "profitability"}
    assert naver["score"] == naver["momentum_score"]
    # SK하이닉스(2): 음수 PER은 제외되고 PBR만으로 valuation 계산
    assert "per" in got[2]["data_quality"]["missing_inputs"] and got[2]["valuation_score"] is not None
    assert {r["weights_version"] for r in got.values()} == {"test"}


def test_scores_are_regenerated_for_same_as_of(engine, scoring_data):
    compute_scores(engine, as_of=D, weights=WEIGHTS)
    compute_scores(engine, as_of=D, weights={**WEIGHTS, "version": "v2"})
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT count(*), max(weights_version) FROM stock_scores")).one()
    assert tuple(rows) == (5, "v2")                                  # DELETE 후 INSERT → 중복 없음


def test_all_factors_unavailable_gives_null_score(engine):
    compute_scores(engine, as_of=D, weights=WEIGHTS)                  # 기본 픽스처: 3일 시세, 재무 없음
    with engine.connect() as conn:
        aapl = conn.execute(text("SELECT score, valuation_score, data_quality FROM stock_scores WHERE stock_id = 3")).one()
    # US 2종목 PER·PBR은 있으므로 valuation만 계산되고 나머지는 불가
    assert aapl.valuation_score is not None and aapl.score == aapl.valuation_score
    with engine.begin() as conn:
        conn.execute(text("UPDATE valuation_snapshots SET per = NULL, pbr = NULL"))
    compute_scores(engine, as_of=D, weights=WEIGHTS)
    with engine.connect() as conn:
        aapl = conn.execute(text("SELECT score, data_quality FROM stock_scores WHERE stock_id = 3")).one()
    assert aapl.score is None and len(aapl.data_quality["unavailable"]) == 4


def test_refresh_runs_scorer_and_analysis_api(client, engine, scoring_data):
    p = make_providers()
    svc = RefreshService(engine, p, FxService(engine, p.fx, 4), 4, scorer=lambda e: compute_scores(e, weights=WEIGHTS))
    scores_job = next(j for j in svc.refresh().jobs if j.job_type == "SCORES")
    assert scores_job.status == "SUCCESS"
    body = client.get(f"{API}/stocks/KOSPI/035420/analysis").json()
    assert body["attractiveness"]["score"] is not None
    # 갱신의 VALUATION 작업이 fake PER·PBR을 넣으므로 valuation은 계산되고, 재무가 없는 growth는 불가
    assert body["attractiveness"]["factors"]["growth"] == {"score": None, "weight": 25, "available": False}
    assert body["attractiveness"]["factors"]["valuation"]["available"] is True
    assert body["metrics"]["return_3m"] is not None and "투자 권유가 아닙니다" in body["disclaimer"]


# ------------------------------------------------------------------ 경쟁 비교
def test_peers_rank_and_average(client):
    body = client.get(f"{API}/stocks/KOSPI/005930/peers").json()
    assert "K-IFRS" in body["accounting_note"] and "US-GAAP" in body["accounting_note"]
    g = body["groups"][0]
    assert g["name"] == "반도체" and g["size"] == 3 and g["has_peers"] is True
    m = {x["ticker"]: x for x in g["members"]}
    # PER 낮을수록 1위: SK 8 → 삼성 12 → NVDA 50
    assert {t: x["ranks"]["per"] for t, x in m.items()} == {"000660": 1, "005930": 2, "NVDA": 3}
    assert g["averages"]["per"] == pytest.approx((8 + 12 + 50) / 3, abs=1e-4)
    # 시총(원화) 높을수록 1위: NVDA 1조$×1300 > 삼성 400조 > SK 100조
    assert {t: x["ranks"]["market_cap_krw"] for t, x in m.items()} == {"NVDA": 1, "005930": 2, "000660": 3}
    assert m["005930"]["is_target"] and not m["NVDA"]["is_target"]
    assert m["005930"]["ranks"]["return_1y"] is None                 # 값 없는 지표는 순위 없음


def test_single_member_group_has_no_peers(client):
    g = client.get(f"{API}/stocks/NASDAQ/AAPL/peers").json()["groups"][0]
    assert g["name"] == "빅테크" and g["has_peers"] is False and "없습니다" in g["message"]


def test_peers_chart_uses_union_dates_with_nulls(client, engine):
    with engine.begin() as conn:                                     # 한국만 거래한 날 (미국 휴장)
        conn.execute(text("INSERT INTO daily_prices VALUES (1, :d, 71400, 71400, 71400, 71400, 1), "
                          "(2, :d, 150000, 150000, 150000, 150000, 1)"), {"d": D + timedelta(days=1)})
    c = client.get(f"{API}/stocks/KOSPI/005930/peers/chart?range=1m").json()
    assert c["group_name"] == "반도체" and len(c["dates"]) == 4
    s = {x["ticker"]: x["values"] for x in c["series"]}
    assert s["005930"] == [100, pytest.approx(69000 / 68000 * 100, abs=1e-4), pytest.approx(70000 / 68000 * 100, abs=1e-4), 105]
    assert s["NVDA"][-1] is None and s["NVDA"][0] == 100
    assert c["series"][0]["is_target"] is True
    assert client.get(f"{API}/stocks/KOSPI/005930/peers/chart?group_id=2").status_code == 404


# ------------------------------------------------------------------ 통계
def test_statistics(client, engine):
    o = client.get(f"{API}/statistics/overview").json()
    assert (o["stocks"], o["daily_prices"], o["fx_daily"]) == (4, 12, 3)
    mv = client.get(f"{API}/statistics/market-valuation").json()     # 시장당 2종목 → HAVING 3 이상에서 모두 제외
    assert mv["markets"] == [] and {x["market"] for x in mv["excluded"]} == {"KOSPI", "NASDAQ"}
    mv2 = {x["market"]: x for x in client.get(f"{API}/statistics/market-valuation?min_samples=2").json()["markets"]}
    assert mv2["KOSPI"]["avg_per"] == 10 and mv2["KOSPI"]["total_market_cap_krw"] == 500_000_000_000_000
    groups = {x["group_name"]: x for x in client.get(f"{API}/statistics/peer-group-valuation").json()["groups"]}
    assert (groups["반도체"]["members"], groups["반도체"]["kr_members"], groups["반도체"]["min_per"], groups["반도체"]["max_per"]) == (3, 2, 8, 50)
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO disclosures (stock_id, rcept_no, title, report_type, filed_at, data_source) VALUES
            (1, 'a', 't', '정기공시', now() - interval '40 days', 'DART'), (1, 'b', 't', '거래소공시', now() - interval '40 days', 'DART'),
            (3, 'c', 't', '10-Q', now() - interval '1 day', 'SEC')"""))
    items = client.get(f"{API}/statistics/disclosure-frequency?period=month").json()["items"]
    assert sum(i["total"] for i in items) == 3 and items[-1]["cumulative"] == 3
    assert sum(i["periodic_reports"] for i in items) == 2 and sum(i["share"] for i in items) == pytest.approx(1)
