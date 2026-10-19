"""시장·섹터 점수(market_condition) — 순수 계산 경계값, 섹터 흐름 SQL, 상세 응답 조립 (추가기능 API 정의서 5절)."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.services import market_condition as MC
from tests.conftest import D

SECTOR = "반도체·전자"


@pytest.fixture(autouse=True)
def _fresh_cache():
    MC.clear_cache()
    yield
    MC.clear_cache()


# ------------------------------------------------------------------ 순수 계산
@pytest.mark.parametrize("r, expected", [(-0.20, "0.00"), (-0.10, "0.00"), (-0.034, "33.00"), (0, "50.00"),
                                         (0.02, "60.00"), (0.10, "100.00"), (None, None)])
def test_sector_flow_score_bounds(r, expected):
    assert MC.sector_flow_score(r) == (None if expected is None else Decimal(expected))


def test_compute_condition_weights_and_half_up():
    assert MC.compute_condition(28, -0.024) == {"score": 31, "label": "낮음", "sector_flow": Decimal("38.00")}
    assert MC.compute_condition(Decimal("50.50"), None)["score"] == 51            # 짝수 반올림이면 50
    assert MC.compute_condition(Decimal("49.50"), None) == {"score": 50, "label": "보통", "sector_flow": None}


@pytest.mark.parametrize("score, label", [(None, "데이터 부족"), (0, "매우 낮음"), (19, "매우 낮음"), (20, "낮음"),
                                          (39, "낮음"), (40, "보통"), (59, "보통"), (60, "높음"), (79, "높음"),
                                          (80, "매우 높음"), (100, "매우 높음")])
def test_band_label_boundaries(score, label):
    assert MC.band_label(score) == label


def test_compute_condition_without_sentiment():
    assert MC.compute_condition(None, 0.0) == {"score": None, "label": "데이터 부족", "sector_flow": Decimal("50.00")}


# ------------------------------------------------------------------ 섹터 흐름 SQL
def _days(n: int, end=D) -> list:
    return [end - timedelta(days=n - 1 - i) for i in range(n)]


def _bars(conn, sid: int, days: list, r5: float) -> None:
    """마지막 날 종가가 6번째 전 종가의 (1 + r5)배가 되도록 일봉을 넣는다."""
    closes = [100.0] * (len(days) - 1) + [100.0 * (1 + r5)]
    conn.execute(text("INSERT INTO daily_prices VALUES (:s, :d, :c, :c, :c, :c, 1000)"),
                 [{"s": sid, "d": d, "c": c} for d, c in zip(days, closes)])


def _sector_stocks(conn, rows: list[tuple[int, int, str]]) -> None:
    conn.execute(text("""INSERT INTO stocks (stock_id, market_id, ticker, name, sector, coverage)
                         VALUES (:i, :m, :t, :t, :sec, :cov)"""),
                 [{"i": i, "m": m, "t": f"9{i:05d}", "sec": SECTOR, "cov": cov} for i, m, cov in rows])


@pytest.fixture
def sector_peers(engine):
    """KR 101~106(featured 3·benchmark 3) 5일 수익률 −5%·−2%·0·1%·3%·4% → 중앙값 0.5%.
    제외: 107 listed(+50%), 108 featured인데 기준일 일봉 없음, 109 미국 같은 섹터 이름."""
    with engine.begin() as conn:
        _sector_stocks(conn, [(101, 1, "featured"), (102, 1, "featured"), (103, 1, "featured"), (104, 1, "benchmark"),
                              (105, 1, "benchmark"), (106, 1, "benchmark"), (107, 1, "listed"), (108, 1, "featured"),
                              (109, 2, "featured")])
        for sid, r in zip(range(101, 107), (-0.05, -0.02, 0.0, 0.01, 0.03, 0.04)):
            _bars(conn, sid, _days(6), r)
        _bars(conn, 107, _days(6), 0.50)
        _bars(conn, 108, _days(6, D - timedelta(days=1)), 0.30)
        _bars(conn, 109, _days(6), 0.50)


def test_sector_flow_sql_median_sample_and_exclusions(engine, sector_peers):
    with engine.connect() as conn:
        r5, n, ref = MC.read_sector_flow(conn, "KR", SECTOR, D)
    assert r5 == Decimal("0.005000") and n == 6 and ref == D


def test_sector_flow_sql_falls_back_to_previous_day(engine):
    with engine.begin() as conn:
        _sector_stocks(conn, [(i, 1, "featured") for i in range(101, 107)])
        for sid in range(101, 107):                                         # 전 거래일까지는 6종목 모두
            _bars(conn, sid, _days(7, D - timedelta(days=1)), 0.02)
        conn.execute(text("INSERT INTO daily_prices VALUES (:s, :d, 1, 1, 1, 1, 1)"),   # 기준일 일봉은 4종목만
                     [{"s": s, "d": D} for s in range(101, 105)])
    with engine.connect() as conn:
        r5, n, ref = MC.read_sector_flow(conn, "KR", SECTOR, D)
    assert ref == D - timedelta(days=1) and n == 6 and r5 == Decimal("0.020000")


# ------------------------------------------------------------------ 상세 응답 조립
@pytest.fixture
def at_d(monkeypatch):
    monkeypatch.setattr(MC, "last_closed_session", lambda country, now=None: D)


def _sentiment(engine, day, score) -> None:
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO market_sentiment_daily (market, trade_date, score, label, formula_version)
                             VALUES ('KR', :d, :s, '중립', 1)"""), {"d": day, "s": score})


def test_get_condition_without_sector_uses_market_only(engine, at_d):
    _sentiment(engine, D, Decimal("61.50"))
    c = MC.get_condition(engine, stock_id=1, country="KR", sector=None)
    assert c["score"] == 62 and c["label"] == "높음" and c["sentiment"] == Decimal("61.50")
    assert (c["sector_name"], c["sector_flow"], c["sector_sample"], c["sector_as_of"], c["sector_r5"]) == (None, None, 0, None, None)
    assert c["index_code"] == "KOSPI" and c["as_of"] == D


def test_get_condition_with_sector(engine, at_d, sector_peers):
    _sentiment(engine, D, Decimal("28"))
    c = MC.get_condition(engine, stock_id=101, country="KR", sector=SECTOR)
    # 섹터 흐름 = 50 + 0.005 × 500 = 52.5 → 0.7 × 28 + 0.3 × 52.5 = 35.35 → 35
    assert c["sector_flow"] == Decimal("52.50") and c["score"] == 35 and c["label"] == "낮음"
    assert c["sector_sample"] == 6 and c["sector_as_of"] == D and c["stock_r5"] == Decimal("-0.050000")


def test_get_condition_small_sector_uses_market_only(engine, at_d):
    with engine.begin() as conn:
        _sector_stocks(conn, [(i, 1, "featured") for i in (101, 102, 103)])
        for sid in (101, 102, 103):
            _bars(conn, sid, _days(6), 0.02)
    _sentiment(engine, D, Decimal("40"))
    c = MC.get_condition(engine, stock_id=101, country="KR", sector=SECTOR)
    assert c["sector_name"] == SECTOR and c["sector_flow"] is None and c["sector_sample"] == 3
    assert c["score"] == 40 and c["sector_r5"] is None


def test_get_condition_stale_sentiment_is_insufficient(engine, at_d, monkeypatch):
    _sentiment(engine, D - timedelta(days=14), Decimal("70"))
    monkeypatch.setattr(MC, "sessions_between", lambda country, start, end: 10)
    c = MC.get_condition(engine, stock_id=1, country="KR", sector=None)
    assert c["score"] is None and c["label"] == "데이터 부족" and c["sentiment"] == Decimal("70")


def test_get_condition_never_raises(engine, at_d, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("SQL 실패")
    monkeypatch.setattr(MC, "read_sector_flow", boom)
    c = MC.get_condition(engine, stock_id=1, country="KR", sector=SECTOR)
    assert c == MC.empty_condition("KR", SECTOR)


def test_sector_flow_cache_skips_small_samples(engine, at_d, monkeypatch):
    calls = []
    real = MC.read_sector_flow
    monkeypatch.setattr(MC, "read_sector_flow", lambda *a: calls.append(1) or real(*a))
    MC.get_condition(engine, stock_id=1, country="KR", sector=SECTOR)      # 표본 0 → 캐시하지 않음
    MC.get_condition(engine, stock_id=1, country="KR", sector=SECTOR)
    assert len(calls) == 2
