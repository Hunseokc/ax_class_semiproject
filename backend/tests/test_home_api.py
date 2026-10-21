"""대시보드 홈: 시장 주목 종목(거래량 급증·매력도 순위), 지수·환율 52주 범위, 관심종목 스파크라인."""
from datetime import timedelta

from sqlalchemy import text

from tests.conftest import D, DAYS

API = "/api/v1"


def _add_history(conn, stock_id: int, days: int, volume: int) -> None:
    """픽스처 3일 앞에 거래일 days개를 더 넣는다 (종가는 마지막 픽스처 종가와 같게)."""
    first = DAYS[0]
    conn.execute(text("""INSERT INTO daily_prices (stock_id, trade_date, open, high, low, close, volume)
                         SELECT :s, CAST(:d AS date), close, close, close, close, :v
                         FROM daily_prices WHERE stock_id = :s AND trade_date = :first"""),
                 [{"s": stock_id, "d": first - timedelta(days=i), "v": volume, "first": first} for i in range(1, days + 1)])


def _ranking(client, kind, country="KR", **params):
    r = client.get(f"{API}/home/ranking", params={"kind": kind, "country": country, **params})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ 거래량 급증
def test_volume_surge_ratio_against_previous_20_days(client, engine):
    with engine.begin() as conn:
        _add_history(conn, 1, 18, 1000)                       # 삼성전자: 직전 20거래일 평균 1,000
        conn.execute(text("UPDATE daily_prices SET volume = 2400 WHERE stock_id = 1 AND trade_date = :d"), {"d": D})
    items = _ranking(client, "volume_surge")["items"]
    assert [(i["ticker"], i["value"], i["rank"]) for i in items] == [("005930", 2.4, 1)]
    assert items[0]["as_of"] == D.isoformat() and items[0]["is_watched"] is False


def test_volume_surge_excludes_short_history_and_zero_volume(client, engine):
    with engine.begin() as conn:
        _add_history(conn, 1, 17, 1000)                       # 직전 19거래일 → 부족해서 제외
        _add_history(conn, 2, 18, 3000)
        conn.execute(text("UPDATE daily_prices SET volume = 0 WHERE stock_id = 2 AND trade_date = :d"), {"d": D})
    assert _ranking(client, "volume_surge")["items"] == []


def test_volume_surge_targets_featured_benchmark_and_watchlist(client, engine):
    with engine.begin() as conn:
        _add_history(conn, 1, 18, 1000)
        _add_history(conn, 2, 18, 1000)
        _add_history(conn, 3, 18, 1000)
        conn.execute(text("UPDATE stocks SET coverage = 'benchmark' WHERE stock_id IN (1, 2)"))
        conn.execute(text("UPDATE stocks SET coverage = 'listed' WHERE stock_id = 3"))
        conn.execute(text("INSERT INTO watchlist_items (user_id, stock_id, sort_order) VALUES (1, 2, 1)"))
    items = _ranking(client, "volume_surge")["items"]
    watched = {i["ticker"]: i["is_watched"] for i in items}
    assert watched["005930"] is False and watched["000660"] is True      # 비교군도 대상, 관심 표시는 따로
    assert all(i["stock_id"] != 3 for i in items)                        # listed는 관심종목이 아니면 제외
    assert _ranking(client, "volume_surge", "US")["items"] == []                          # 시장 필터


# ------------------------------------------------------------------ 매력도 순위
def test_attractiveness_reads_latest_stored_score(client, engine):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO stock_scores (stock_id, as_of, preset_id, score, factor_coverage)
            SELECT s, d, (SELECT preset_id FROM scoring_presets WHERE code = 'balanced'), sc, 5
            FROM (VALUES (1, CAST(:old AS date), 90.0), (1, CAST(:d AS date), 55.5),
                         (2, CAST(:d AS date), 80.0), (3, CAST(:d AS date), 99.0)) v(s, d, sc)"""),
                     {"d": D, "old": D - timedelta(days=1)})
        conn.execute(text("INSERT INTO stock_scores (stock_id, as_of, preset_id, score, factor_coverage) "
                          "SELECT 4, :d, preset_id, NULL, 2 FROM scoring_presets WHERE code = 'balanced'"), {"d": D})
        conn.execute(text("INSERT INTO watchlist_items (user_id, stock_id, sort_order) VALUES (1, 1, 1)"))
    kr = _ranking(client, "attractiveness")
    assert kr["preset"] == "balanced"
    assert [(i["ticker"], i["value"], i["is_watched"]) for i in kr["items"]] == [("000660", 80, False), ("005930", 55.5, True)]
    us = _ranking(client, "attractiveness", "US")["items"]
    assert [i["ticker"] for i in us] == ["AAPL"]                                          # 점수 NULL(NVDA)은 제외
    assert _ranking(client, "attractiveness", preset="growth")["items"] == []            # 프리셋별 점수


def test_ranking_validates_params(client):
    assert client.get(f"{API}/home/ranking", params={"kind": "volume"}).status_code == 422
    assert client.get(f"{API}/home/ranking", params={"kind": "attractiveness", "country": "JP"}).status_code == 422
    assert client.get(f"{API}/home/ranking", params={"kind": "attractiveness", "limit": 0}).status_code == 422


# ------------------------------------------------------------------ 52주 범위·스파크라인
def test_index_52w_range_needs_a_full_year(client, engine):
    idx = client.get(f"{API}/market/indices").json()["indices"][0]
    assert idx["high_52w"] is None and idx["position_52w"] is None                       # 3일치뿐
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO index_daily_prices (index_id, trade_date, close) VALUES (1, :d, :c)"),
                     [{"d": D - timedelta(days=400), "c": 9999}, {"d": D - timedelta(days=200), "c": 2000},
                      {"d": D - timedelta(days=100), "c": 3000}])
    idx = client.get(f"{API}/market/indices").json()["indices"][0]
    assert idx["low_52w"] == 2000 and idx["high_52w"] == 3000                            # 1년 넘은 9,999는 범위 밖
    assert idx["position_52w"] == 0.52                                                   # (2520 − 2000) / 1000
    assert [p["close"] for p in idx["sparkline"]] == [2000, 3000, 2500, 2510, 2520]      # 1년치


def test_fx_52w_range_and_history(client, engine):
    fx = client.get(f"{API}/market/fx").json()
    assert fx["position_52w"] is None and len(fx["history"]) == 3
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO fx_rates (rate_at, usd_krw, granularity) VALUES (CAST(:d AS date) + time '00:00', :v, 'DAILY')"),
                     [{"d": D - timedelta(days=400), "v": 1500}, {"d": D - timedelta(days=100), "v": 1400}])
    fx = client.get(f"{API}/market/fx").json()
    assert fx["low_52w"] == 1300 and fx["high_52w"] == 1400 and fx["position_52w"] == 0
    assert len(fx["history"]) == 4 and fx["change_rate"] == 0                           # 전일 대비 계산은 그대로


# ------------------------------------------------------------------ 장 상태(거래소 달력)
def test_session_status_uses_exchange_calendar():
    from datetime import date, datetime, timezone

    from app.services.market_calendar import session_status

    def at(y, m, d, hour_utc=3):
        return datetime(y, m, d, hour_utc, tzinfo=timezone.utc)

    assert session_status("KR", date(2026, 10, 8), at(2026, 10, 9)) == "holiday"           # 한글날(금)
    assert session_status("US", date(2026, 10, 8), at(2026, 10, 9, 15)) == "previous_session"   # 미국은 개장
    assert session_status("KR", date(2026, 9, 23), at(2026, 9, 25)) == "holiday"           # 추석 연휴
    assert session_status("US", date(2026, 11, 25), at(2026, 11, 26, 15)) == "holiday"     # 추수감사절
    assert session_status("KR", date(2026, 10, 8), at(2026, 10, 10)) == "holiday"          # 토요일
    assert session_status("KR", date(2026, 10, 8), at(2026, 10, 12)) == "previous_session"
    assert session_status("KR", date(2026, 10, 12), at(2026, 10, 12)) == "today"
    assert session_status("JP", date(2026, 10, 8)) is None and session_status("KR", None) is None
    assert session_status("KR", date(2020, 1, 1), at(2099, 1, 2)) is None                   # 달력 범위 밖 → 판정 포기


def test_indices_include_session_status(client):
    idx = client.get(f"{API}/market/indices").json()["indices"][0]
    assert idx["session_status"] in {"holiday", "previous_session"}                        # 픽스처 기준일은 4일 전
