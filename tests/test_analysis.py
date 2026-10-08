"""분석 SQL을 손계산(파이썬)과 비교: v_stock_metrics, 경쟁 비교, 통계. (매력도는 test_scoring.py)"""
from __future__ import annotations

import math
import statistics
from datetime import date, timedelta
from decimal import Decimal as Dec

import pytest
from sqlalchemy import text

from tests.conftest import D

API = "/api/v1"


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


# ------------------------------------------------------------------ 월별 집계 (/statistics/monthly)
def _month_start(d: date, back: int) -> date:
    y, m = divmod(d.month - 1 - back, 12)
    return date(d.year + y, m + 1, 1)


@pytest.fixture
def monthly_stock(engine):
    """카카오(5, KOSPI): 3개월 전 1봉(범위 밖) · 2개월 전 3봉 · 지난달 2봉 · 이번 달 1봉 (시장 현지 날짜 기준)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    m3, m2, m1, m0 = (_month_start(today, k) for k in (3, 2, 1, 0))
    bars = [  # (날짜, 시가, 고가, 저가, 종가, 거래량)
        (m3, 50, 60, 40, 55, 9999),
        (m2, 100, 110, 95, 105, 1000), (m2.replace(day=2), 106, 120, 100, 115, 2000), (m2.replace(day=3), 114, 118, 90, 98, 3000),
        (m1, 200, 210, 190, 200, 500), (m1.replace(day=2), 202, 230, 201, 220, 1500),
        (m0, 300, 305, 295, 303, 700),
    ]
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO stocks (stock_id, market_id, ticker, name) VALUES (5, 1, '035720', '카카오')"))
        conn.execute(text("INSERT INTO daily_prices VALUES (5, :d, :o, :h, :l, :c, :v)"),
                     [dict(zip("dohlcv", b)) for b in bars])
    return {"m2": m2, "m1": m1, "m0": m0}


def test_monthly_statistics_match_hand_calculation(client, monthly_stock):
    r = client.get(f"{API}/statistics/monthly", params={"market": "KOSPI", "ticker": "035720", "months": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["currency"], body["months"], body["name"]) == ("KRW", 3, "카카오")
    items = body["items"]
    assert [i["month"] for i in items] == [monthly_stock[k].strftime("%Y-%m") for k in ("m2", "m1", "m0")]  # 3개월 전 제외
    m2, m1, m0 = items
    # 2개월 전: 종가 105·115·98 → 평균 318/3 = 106, 고가 최대 120, 저가 최소 90, 월초 105 → 월말 98
    assert (m2["trading_days"], m2["avg_close"], m2["max_high"], m2["min_low"]) == (3, 106, 120, 90)
    assert (m2["first_close"], m2["last_close"], m2["total_volume"], m2["avg_volume"]) == (105, 98, 6000, 2000)
    assert m2["monthly_return"] == pytest.approx(round(98 / 105 - 1, 6))            # -0.066667
    assert m2["first_date"] == monthly_stock["m2"].isoformat() and m2["is_partial"] is False
    # 지난달: 종가 200·220 → 평균 210, 수익률 +10%, 거래량 2000 / 평균 1000
    assert (m1["trading_days"], m1["avg_close"], m1["max_high"], m1["min_low"], m1["monthly_return"]) == (2, 210, 230, 190, 0.1)
    assert (m1["total_volume"], m1["avg_volume"], m1["is_partial"]) == (2000, 1000, False)
    # 이번 달: 진행 중 1봉 → 수익률 0, is_partial
    assert (m0["trading_days"], m0["first_close"], m0["last_close"], m0["monthly_return"], m0["is_partial"]) == (1, 303, 303, 0, True)


def test_monthly_statistics_months_window(client, monthly_stock):
    def months(n):
        return [i["month"] for i in client.get(f"{API}/statistics/monthly",
                                                params={"market": "KOSPI", "ticker": "035720", "months": n}).json()["items"]]
    assert months(1) == [monthly_stock["m0"].strftime("%Y-%m")]
    assert months(2) == [monthly_stock[k].strftime("%Y-%m") for k in ("m1", "m0")]
    assert len(months(24)) == 4                                         # 3개월 전 봉까지 포함


@pytest.mark.parametrize("params, status, code", [
    ({"market": "KOSPI", "ticker": "999999"}, 404, "STOCK_NOT_FOUND"),
    ({"market": "KOSPI", "ticker": "005930", "months": 0}, 422, "VALIDATION_ERROR"),
    ({"market": "KOSPI", "ticker": "005930", "months": 25}, 422, "VALIDATION_ERROR"),
    ({"market": "KOSPI"}, 422, "VALIDATION_ERROR"),                     # ticker 필수
    ({"market": "KOSPI1", "ticker": "005930"}, 422, "VALIDATION_ERROR"),
])
def test_monthly_statistics_errors(client, params, status, code):
    r = client.get(f"{API}/statistics/monthly", params=params)
    assert r.status_code == status and r.json()["error"]["code"] == code


def test_monthly_statistics_empty_when_no_prices(client, engine):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO stocks (stock_id, market_id, ticker, name) VALUES (5, 1, '035720', '카카오')"))
    r = client.get(f"{API}/statistics/monthly", params={"market": "KOSPI", "ticker": "035720"})
    assert r.status_code == 200 and r.json()["items"] == [] and r.json()["months"] == 12
