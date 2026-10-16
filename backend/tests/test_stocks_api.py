"""종목·시장 조회 API: 리스트(정렬·필터·검색·페이지·is_watched), 상세, 캔들, 경쟁 그룹, 지수, 환율.

데이터는 conftest의 고정 픽스처를 쓰고(기준일 D = today - 4일), 필요한 경우에만 테스트 안에서 행을 추가·수정한다.
"""
from datetime import timedelta

import pytest
from sqlalchemy import text

from tests.conftest import D, DAYS

API = "/api/v1"
LIST_KEYS = {"rank", "stock_id", "market", "country", "currency", "ticker", "name", "name_en", "as_of",
             "close", "change", "change_rate", "volume", "market_cap", "market_cap_krw", "score", "is_watched"}


def get(client, path):
    r = client.get(API + path)
    return r, r.json()


def tickers(body):
    return [i["ticker"] for i in body["items"]]


def code(body):
    return body["error"]["code"]


# ---------------------------------------------------------------- 리스트: 정렬
def test_list_kr_sorted_by_volume(client):
    r, b = get(client, "/stocks?country=KR&sort=volume&limit=2")
    assert r.status_code == 200
    assert tickers(b) == ["000660", "005930"]                       # 거래량 3000 > 1000
    assert [i["rank"] for i in b["items"]] == [1, 2] and b["total"] == 2
    assert set(b) == {"total", "limit", "offset", "sort", "order", "preset", "fx_rate_at", "items"}
    assert b["sort"] == "volume" and b["order"] == "desc" and b["limit"] == 2 and b["offset"] == 0


def test_list_default_is_market_cap_in_krw_desc(client):
    r, b = get(client, "/stocks")
    assert tickers(b) == ["AAPL", "NVDA", "005930", "000660"]       # 미국 종목은 환율(1300)을 곱한 원화 시총으로 비교
    assert b["items"][0]["market_cap_krw"] == 3_900_000_000_000_000
    assert b["items"][0]["market_cap"] == 3_000_000_000_000         # 종목 통화 그대로
    assert b["sort"] == "market_cap" and b["fx_rate_at"] is not None


def test_is_watched_flag(client, engine, as_user):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO watchlist_items (user_id, stock_id) VALUES (1, 3)"))
    items = {x["ticker"]: x["is_watched"] for x in client.get(f"{API}/stocks").json()["items"]}
    assert items == {"AAPL": True, "NVDA": False, "005930": False, "000660": False}
    as_user(2)
    other = {x["ticker"]: x["is_watched"] for x in client.get(f"{API}/stocks").json()["items"]}
    assert not any(other.values())
    assert client.get(f"{API}/stocks/NASDAQ/AAPL").json()["is_watched"] is False


def test_list_ascending(client):
    r, b = get(client, "/stocks?order=asc")
    assert tickers(b) == ["000660", "005930", "NVDA", "AAPL"] and b["order"] == "asc"


def test_list_item_shape_and_change_rate(client):
    r, b = get(client, "/stocks?country=KR&sort=volume&order=asc&limit=1")
    item = b["items"][0]                                             # 거래량 오름차순 첫 줄 = 삼성전자
    assert set(item) == LIST_KEYS
    assert item["ticker"] == "005930" and item["close"] == 70000 and item["change"] == 1000
    assert item["change_rate"] == pytest.approx(0.014493)            # 1000 / 69000
    assert item["as_of"] == D.isoformat() and item["name_en"] == "Samsung Electronics"


# ---------------------------------------------------------------- 리스트: 전체 개수와 동점
def test_total_is_full_count_when_limit_is_smaller(client):
    r, b = get(client, "/stocks?limit=2")
    assert len(b["items"]) == 2                                      # 한 페이지는 2개
    assert b["total"] == 4 and b["limit"] == 2                       # 하지만 total은 전체 4개
    r, b = get(client, "/stocks?country=US&limit=1")
    assert len(b["items"]) == 1 and b["total"] == 2                  # 필터가 걸려도 필터 결과 전체 개수


@pytest.mark.parametrize("order", ["desc", "asc"])
def test_volume_tie_is_ordered_by_stock_id(client, engine, order):
    with engine.begin() as conn:                                     # 삼성전자(stock_id 1)의 거래량을 SK하이닉스(2)와 같게 만든다
        conn.execute(text("UPDATE daily_prices SET volume = 3000 WHERE stock_id = 1 AND trade_date = :d"), {"d": D})
    path = f"/stocks?country=KR&sort=volume&order={order}"
    r1, first = get(client, path)
    r2, second = get(client, path)
    assert tickers(first) == ["005930", "000660"]                    # 동점이면 방향과 상관없이 stock_id 작은 쪽이 먼저
    assert [i["rank"] for i in first["items"]] == [1, 1]             # 순위는 공동 1위
    assert tickers(second) == tickers(first)                         # 여러 번 불러도 순서가 같다


def test_tie_stays_stable_across_pages(client, engine):
    with engine.begin() as conn:
        conn.execute(text("UPDATE daily_prices SET volume = 3000 WHERE stock_id = 1 AND trade_date = :d"), {"d": D})
    _, page1 = get(client, "/stocks?country=KR&sort=volume&limit=1&offset=0")
    _, page2 = get(client, "/stocks?country=KR&sort=volume&limit=1&offset=1")
    assert tickers(page1) + tickers(page2) == ["005930", "000660"]  # 동점이어도 페이지 사이에 겹치거나 빠지지 않는다


def test_pages_do_not_overlap(client):
    _, p1 = get(client, "/stocks?limit=2&offset=0")
    _, p2 = get(client, "/stocks?limit=2&offset=2")
    assert tickers(p1) + tickers(p2) == ["AAPL", "NVDA", "005930", "000660"]
    _, p3 = get(client, "/stocks?limit=2&offset=4")
    assert p3["items"] == [] and p3["total"] == 4                  # 끝을 넘은 페이지도 전체 개수는 그대로
    _, p4 = get(client, "/stocks?group=없는그룹&offset=2")
    assert p4["items"] == [] and p4["total"] == 0


# ---------------------------------------------------------------- 리스트: 필터·검색
def test_list_filter_by_country(client):
    _, b = get(client, "/stocks?country=US")
    assert tickers(b) == ["AAPL", "NVDA"] and b["total"] == 2


@pytest.mark.parametrize("group, expected", [("반도체", ["NVDA", "005930", "000660"]), ("빅테크", ["AAPL"]), ("없는그룹", [])])
def test_list_filter_by_group(client, group, expected):
    r, b = get(client, f"/stocks?group={group}")
    assert r.status_code == 200 and tickers(b) == expected and b["total"] == len(expected)


@pytest.mark.parametrize("q, expected", [("삼성", ["005930"]), ("aapl", ["AAPL"]), ("HYNIX", ["000660"]), ("00", ["005930", "000660"])])
def test_list_search(client, q, expected):
    _, b = get(client, f"/stocks?q={q}&sort=market_cap")
    assert tickers(b) == expected                                    # 이름·영문명·티커 일부, 대소문자 무시


def test_inactive_stock_is_excluded(client, engine):
    with engine.begin() as conn:
        conn.execute(text("UPDATE stocks SET is_active = false WHERE ticker = 'NVDA'"))
    _, b = get(client, "/stocks")
    assert "NVDA" not in tickers(b) and b["total"] == 3


def test_stock_without_prices_is_listed_last(client, engine):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO stocks (market_id, ticker, name) VALUES (1, '111111', '무가격')"))
    _, b = get(client, "/stocks?country=KR")
    assert tickers(b) == ["005930", "000660", "111111"]
    assert b["items"][-1]["close"] is None and b["items"][-1]["market_cap_krw"] is None


# ---------------------------------------------------------------- 리스트: 잘못된 요청
def test_volume_sort_requires_market(client):
    r, b = get(client, "/stocks?sort=volume")
    assert r.status_code == 422 and code(b) == "VOLUME_SORT_REQUIRES_MARKET"
    assert b["error"]["detail"] == {"allowed_sort_for_all": ["market_cap"]}


@pytest.mark.parametrize("query", ["sort=price", "order=up", "country=JP", "limit=0", "limit=101", "offset=-1",
                                   "offset=10001", "q=", "q=" + "a" * 51, "group=" + "g" * 65])
def test_list_validation_422(client, query):
    r, b = get(client, f"/stocks?{query}")
    assert r.status_code == 422 and code(b) == "VALIDATION_ERROR"


# ---------------------------------------------------------------- 상세
def test_detail_krw_stock(client):
    r, b = get(client, "/stocks/KOSPI/005930")
    assert r.status_code == 200
    assert (b["stock_id"], b["market"], b["country"], b["currency"], b["name"]) == (1, "KOSPI", "KR", "KRW", "삼성전자")
    assert (b["close"], b["prev_close"], b["change"]) == (70000, 69000, 1000)
    assert b["change_rate"] == pytest.approx(0.014493)
    assert (b["per"], b["pbr"], b["market_cap"], b["valuation_source"]) == (12, 1.2, 400_000_000_000_000, "PYKRX")
    assert b["market_cap_krw"] == 400_000_000_000_000 and b["close_krw"] == 70000
    assert b["fx_rate"] is None and b["fx_rate_at"] is None and b["fx_stale"] is False
    assert b["groups"] == [{"group_id": 1, "name": "반도체"}]
    assert b["score"] is None and b["score_as_of"] is None and b["preset"] == "balanced"   # 테스트 DB에는 점수 행이 없다
    assert b["is_watched"] is False


def test_detail_usd_stock_converts_to_krw(client):
    _, b = get(client, "/stocks/NASDAQ/AAPL")
    assert b["currency"] == "USD" and b["close"] == 200
    assert b["fx_rate"] == 1300 and b["close_krw"] == 260000 and b["fx_rate_at"] is not None
    assert b["market_cap_krw"] == 3_900_000_000_000_000 and b["fx_stale"] is False
    assert b["groups"] == [{"group_id": 2, "name": "빅테크"}]


def test_detail_accepts_lowercase_path(client):
    r, b = get(client, "/stocks/kospi/005930")
    assert r.status_code == 200 and b["ticker"] == "005930"
    r, b = get(client, "/stocks/nasdaq/aapl")
    assert r.status_code == 200 and b["ticker"] == "AAPL"


def test_detail_stock_without_data_returns_nulls(client, engine):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO stocks (market_id, ticker, name) VALUES (1, '111111', '무가격')"))
    r, b = get(client, "/stocks/KOSPI/111111")
    assert r.status_code == 200                                      # 종목은 있으니 404가 아니다
    assert b["close"] is None and b["per"] is None and b["market_cap"] is None and b["groups"] == []


@pytest.mark.parametrize("path", ["/stocks/KOSPI/999999", "/stocks/NASDAQ/005930", "/stocks/NYSE/AAPL"])
def test_detail_not_found(client, path):
    r, b = get(client, path)
    assert r.status_code == 404 and code(b) == "STOCK_NOT_FOUND"     # 시장이 다르면 다른 종목


@pytest.mark.parametrize("path", ["/stocks/KOSPI/ABC!", "/stocks/K/005930", "/stocks/KOSPI/-bad", "/stocks/KOSPI123/005930"])
def test_detail_bad_path_422(client, path):
    r, b = get(client, path)
    assert r.status_code == 422 and code(b) == "VALIDATION_ERROR"    # 모양이 틀리면 DB에 가기 전에 막는다


# ---------------------------------------------------------------- 캔들
def test_candles_default_range(client):
    r, b = get(client, "/stocks/KOSPI/005930/candles")
    assert r.status_code == 200
    assert (b["market"], b["ticker"], b["currency"], b["range"]) == ("KOSPI", "005930", "KRW", "3m")
    assert b["as_of"] == D.isoformat()
    assert [c["date"] for c in b["candles"]] == [d.isoformat() for d in DAYS]       # 오래된 날짜부터
    assert [c["close"] for c in b["candles"]] == [68000, 69000, 70000]
    assert set(b["candles"][0]) == {"date", "open", "high", "low", "close", "volume"}


@pytest.mark.parametrize("rng", ["1m", "3m", "6m", "1y"])
def test_candles_ranges(client, rng):
    r, b = get(client, f"/stocks/NASDAQ/AAPL/candles?range={rng}")
    assert r.status_code == 200 and b["range"] == rng and len(b["candles"]) == 3 and b["currency"] == "USD"


def test_candles_window_is_counted_from_latest_trading_day(client, engine):
    old = D - timedelta(days=40)                                     # 한 달보다 오래, 석 달보다는 최근
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO daily_prices VALUES (1, :d, 1, 1, 1, 1, 1)"), {"d": old})
    _, one = get(client, "/stocks/KOSPI/005930/candles?range=1m")
    _, three = get(client, "/stocks/KOSPI/005930/candles?range=3m")
    assert old.isoformat() not in [c["date"] for c in one["candles"]] and len(one["candles"]) == 3
    assert [c["date"] for c in three["candles"]][0] == old.isoformat() and len(three["candles"]) == 4


def test_candles_invalid_range_422(client):
    r, b = get(client, "/stocks/KOSPI/005930/candles?range=2y")
    assert r.status_code == 422 and code(b) == "VALIDATION_ERROR"


def test_candles_unknown_stock_404(client):
    r, b = get(client, "/stocks/KOSPI/999999/candles")
    assert r.status_code == 404 and code(b) == "STOCK_NOT_FOUND"


def test_candles_empty_for_stock_without_prices(client, engine):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO stocks (market_id, ticker, name) VALUES (1, '111111', '무가격')"))
    r, b = get(client, "/stocks/KOSPI/111111/candles")
    assert r.status_code == 200 and b["as_of"] is None and b["candles"] == []


# ---------------------------------------------------------------- 경쟁 그룹
def test_peer_groups(client):
    r, b = get(client, "/peer-groups")
    assert r.status_code == 200 and set(b) == {"groups"}
    assert {g["name"]: (g["group_id"], g["size"]) for g in b["groups"]} == {"반도체": (1, 3), "빅테크": (2, 1)}


# ---------------------------------------------------------------- 지수
def test_indices(client):
    r, b = get(client, "/market/indices")
    assert r.status_code == 200 and b["as_of"] == D.isoformat()
    kospi = b["indices"][0]
    assert (kospi["code"], kospi["country"], kospi["currency"]) == ("KOSPI", "KR", "KRW")
    assert (kospi["close"], kospi["prev_close"], kospi["change"]) == (2520, 2510, 10)
    assert kospi["change_rate"] == pytest.approx(0.003984)           # 10 / 2510
    assert kospi["sparkline"] == [{"date": d.isoformat(), "close": 2500 + i * 10} for i, d in enumerate(DAYS)]
    assert set(kospi) == {"code", "name", "country", "currency", "as_of", "close", "prev_close", "change",
                          "change_rate", "sparkline",
                          "high_52w", "low_52w", "position_52w", "session_status"}   # 52주 범위·장 상태는 Stage 6


def test_index_without_prices_keeps_card(client, engine):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO indices (code, name, market_id, source_symbol, display_order) "
                          "VALUES ('EMPTY', '일봉없음', 1, 'x', 2)"))
    _, b = get(client, "/market/indices")
    empty = next(i for i in b["indices"] if i["code"] == "EMPTY")
    assert empty["close"] is None and empty["change"] is None and empty["sparkline"] == []


def test_sparkline_and_fx_history_cover_one_year(client, engine):
    """홈 카드가 1개월·3개월·1년으로 자를 수 있게 최신일 기준 1년치를 준다 (1년보다 오래된 점은 제외)."""
    old = [D - timedelta(days=n) for n in (40, 200, 364, 366)]      # 366일 전은 1년 밖
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO index_daily_prices (index_id, trade_date, close) VALUES (1, :d, 2000)"),
                     [{"d": d} for d in old])
        conn.execute(text("INSERT INTO fx_rates (rate_at, usd_krw, granularity) VALUES (CAST(:d AS date) + time '00:00', 1200, 'DAILY')"),
                     [{"d": d} for d in old])
    _, b = get(client, "/market/indices")
    spark = [p["date"] for p in b["indices"][0]["sparkline"]]
    assert spark[0] == old[2].isoformat() and old[3].isoformat() not in spark and len(spark) == 3 + 3
    _, f = get(client, "/market/fx")
    hist = [h["date"] for h in f["history"]]
    assert hist[0] == old[2].isoformat() and old[3].isoformat() not in hist and len(hist) == 3 + 3


# ---------------------------------------------------------------- 환율
def test_fx_change_uses_previous_daily(client, engine):
    with engine.begin() as conn:                                     # 지금 시각 SNAPSHOT을 1313으로, 이전 날짜 DAILY는 1300
        conn.execute(text("UPDATE fx_rates SET usd_krw = 1313 WHERE granularity = 'SNAPSHOT'"))
    r, b = get(client, "/market/fx")
    assert r.status_code == 200 and b["granularity"] == "SNAPSHOT" and b["usd_krw"] == 1313
    assert (b["prev_close"], b["change"]) == (1300, 13)
    assert b["change_rate"] == pytest.approx(0.01)
    assert [h["date"] for h in b["history"]] == [d.isoformat() for d in DAYS]       # DAILY 3개, 오래된 순
    assert b["pair"] == "USD/KRW" and b["currency"] == "KRW" and b["fx_stale"] is False
    assert set(b) == {"pair", "currency", "usd_krw", "rate_at", "granularity", "fx_stale", "prev_close", "change",
                      "change_rate", "history", "as_of"}


def test_fx_same_day_daily_is_not_the_comparison(client, engine, fake_fx):
    fake_fx.fail = True                                              # TTL이 지난 SNAPSHOT을 그대로 쓰게 조회 실패
    with engine.begin() as conn:                                     # 같은 날(D) DAILY 1310과 낮 1시 SNAPSHOT 1320
        conn.execute(text("DELETE FROM fx_rates"))
        for d, v in zip(DAYS, (1290, 1300, 1310)):
            conn.execute(text("INSERT INTO fx_rates (rate_at, usd_krw, granularity) VALUES "
                              "((CAST(:d AS date) + time '00:00') AT TIME ZONE 'Asia/Seoul', :v, 'DAILY')"), {"d": d, "v": v})
        conn.execute(text("INSERT INTO fx_rates (rate_at, usd_krw, granularity) VALUES "
                          "((CAST(:d AS date) + time '13:00') AT TIME ZONE 'Asia/Seoul', 1320, 'SNAPSHOT')"), {"d": D})
    _, b = get(client, "/market/fx")
    assert b["usd_krw"] == 1320 and b["prev_close"] == 1300          # 같은 날 DAILY(1310)가 아니라 전날(1300)과 비교
    assert b["change"] == 20 and b["change_rate"] == pytest.approx(0.015385)


def test_fx_without_previous_daily(client, engine):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM fx_rates WHERE granularity = 'DAILY'"))
    r, b = get(client, "/market/fx")
    assert r.status_code == 200 and b["prev_close"] is None and b["change"] is None and b["change_rate"] is None
    assert b["history"] == []


def test_fx_unavailable_503(client, engine, fake_fx):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM fx_rates"))
    fake_fx.fail = True
    r, b = get(client, "/market/fx")
    assert r.status_code == 503 and code(b) == "FX_UNAVAILABLE"


# ---------------------------------------------------------------- 문서
def test_openapi_lists_the_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("/stocks", "/stocks/{market}/{ticker}", "/stocks/{market}/{ticker}/candles", "/peer-groups",
              "/market/indices", "/market/fx"):
        assert API + p in paths


# ── [S3-B] 재무·공시 ──
def _insert_financials(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO financial_statements (stock_id, period_end, period_type, revenue, operating_income, net_income,
                                              total_assets, total_equity, total_debt, data_source, accounting_std)
            VALUES (1, '2023-12-31', 'FY', 800, 100, 80, 2000, 400, 900, 'DART', 'K-IFRS'),
                   (1, '2024-12-31', 'FY', 1000, 200, 100, 2500, 500, 1000, 'DART', 'K-IFRS'),
                   (1, '2025-12-31', 'FY', 1200, 300, 150, 3000, 0, 1200, 'DART', 'K-IFRS')"""))


def test_financials_endpoint_returns_latest_n_oldest_first(client, engine):
    _insert_financials(engine)
    r, b = get(client, "/stocks/KOSPI/005930/financials?limit=2")
    assert r.status_code == 200
    assert set(b) == {"market", "ticker", "currency", "as_of", "items"} and b["currency"] == "KRW"
    assert [i["period_end"] for i in b["items"]] == ["2024-12-31", "2025-12-31"]     # 최근 2개를 오래된 순으로
    assert b["as_of"] == "2025-12-31"
    first = b["items"][0]
    assert first["revenue"] == 1000 and first["data_source"] == "DART" and first["accounting_std"] == "K-IFRS"
    assert first["operating_margin"] == 0.2 and first["roe"] == 0.2              # 200/1000, 100/500
    assert b["items"][1]["roe"] is None                                         # 자본 0 → ROE 계산 안 함
    assert len(get(client, "/stocks/KOSPI/005930/financials")[1]["items"]) == 3   # 기본 limit 5 ≥ 3행


def test_financials_empty_and_unknown_stock(client):
    r, b = get(client, "/stocks/KOSPI/000660/financials")
    assert r.status_code == 200 and b["items"] == [] and b["as_of"] is None      # 종목은 있고 데이터만 없음
    r, b = get(client, "/stocks/KOSPI/999999/financials")
    assert r.status_code == 404 and code(b) == "STOCK_NOT_FOUND"
    assert get(client, "/stocks/KOSPI/005930/financials?limit=0")[0].status_code == 422
    assert get(client, "/stocks/KOSPI/005930/disclosures?limit=51")[0].status_code == 422


def test_disclosures_endpoint_returns_newest_first_with_limit(client, engine):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO disclosures (stock_id, rcept_no, title, report_type, filed_at, url, data_source) VALUES
              (1, 'r1', '오래된 공시', '정기공시', '2026-01-01T00:00:00+09', 'https://dart.example/r1', 'DART'),
              (1, 'r2', '중간 공시',  '거래소공시', '2026-02-01T00:00:00+09', NULL, 'DART'),
              (1, 'r3', '최신 공시',  '기타공시',   '2026-03-01T00:00:00+09', 'https://dart.example/r3', 'DART'),
              (3, 'a1', '애플 공시',  '8-K',        '2026-03-02T00:00:00Z',   'https://sec.example/a1', 'SEC')"""))
    r, b = get(client, "/stocks/KOSPI/005930/disclosures?limit=2")
    assert r.status_code == 200 and set(b) == {"market", "ticker", "as_of", "items"}
    assert [i["rcept_no"] for i in b["items"]] == ["r3", "r2"]                   # 최신순, limit 2건
    assert set(b["items"][0]) == {"rcept_no", "title", "report_type", "filed_at", "url", "data_source"}
    assert b["items"][1]["url"] is None and b["as_of"] == b["items"][0]["filed_at"]
    assert [i["rcept_no"] for i in get(client, "/stocks/NASDAQ/AAPL/disclosures")[1]["items"]] == ["a1"]   # 종목별로 분리
