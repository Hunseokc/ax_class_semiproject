"""대시보드 홈: 시장 주목 종목(거래량 급증·매력도 순위).

Stage 6-B에서 뺀 것: 지수·환율 52주 범위, 장 상태(session_status) — Stage 6-D(market_calendar) 몫."""
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


def test_volume_surge_targets_featured_and_watchlist_only(client, engine):
    with engine.begin() as conn:
        _add_history(conn, 1, 18, 1000)
        _add_history(conn, 2, 18, 1000)
        conn.execute(text("UPDATE stocks SET coverage = 'benchmark' WHERE stock_id IN (1, 2)"))
        conn.execute(text("INSERT INTO watchlist_items (user_id, stock_id, sort_order) VALUES (1, 2, 1)"))
    items = _ranking(client, "volume_surge")["items"]
    assert [i["ticker"] for i in items] == ["000660"] and items[0]["is_watched"] is True   # 비교군은 관심종목일 때만
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
