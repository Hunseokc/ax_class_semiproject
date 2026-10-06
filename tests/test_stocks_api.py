"""시장·종목 조회 API: 정렬·필터·is_watched·전체 탭 거래량 정렬 거부·404."""
from sqlalchemy import text

API = "/api/v1"


def tickers(resp):
    return [r["ticker"] for r in resp.json()["items"]]


def test_market_cap_sort_converts_usd_to_krw(client):
    r = client.get(f"{API}/stocks")
    assert r.status_code == 200
    body = r.json()
    # 시총(원화): AAPL 3조$×1300=3,900조, NVDA 1,300조, 삼성 400조, SK 100조
    assert tickers(r) == ["AAPL", "NVDA", "005930", "000660"]
    assert [x["rank"] for x in body["items"]] == [1, 2, 3, 4]
    assert body["items"][0]["market_cap_krw"] == 3_000_000_000_000 * 1300
    assert body["total"] == 4


def test_volume_sort_within_market(client):
    assert tickers(client.get(f"{API}/stocks?country=KR&sort=volume")) == ["000660", "005930"]
    assert tickers(client.get(f"{API}/stocks?country=US&sort=volume")) == ["NVDA", "AAPL"]
    assert tickers(client.get(f"{API}/stocks?country=US&sort=volume&order=asc")) == ["AAPL", "NVDA"]


def test_volume_sort_rejected_for_all_markets(client):
    r = client.get(f"{API}/stocks?sort=volume")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VOLUME_SORT_REQUIRES_MARKET"


def test_filters_and_pagination(client):
    assert tickers(client.get(f"{API}/stocks?group=빅테크")) == ["AAPL"]
    assert tickers(client.get(f"{API}/stocks?q=삼성")) == ["005930"]
    assert tickers(client.get(f"{API}/stocks?q=nvidia")) == ["NVDA"]
    page = client.get(f"{API}/stocks?limit=2&offset=2").json()
    assert [x["ticker"] for x in page["items"]] == ["005930", "000660"] and page["total"] == 4
    empty = client.get(f"{API}/stocks?group=없는그룹").json()
    assert empty["items"] == [] and empty["total"] == 0


def test_is_watched_flag(client, engine):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO watchlist_items (user_id, stock_id) VALUES (1, 3)"))
    items = {x["ticker"]: x["is_watched"] for x in client.get(f"{API}/stocks").json()["items"]}
    assert items == {"AAPL": True, "NVDA": False, "005930": False, "000660": False}
    other = {x["ticker"]: x["is_watched"] for x in client.get(f"{API}/stocks?user_id=2").json()["items"]}
    assert not any(other.values())


def test_stock_detail_and_404(client):
    d = client.get(f"{API}/stocks/nasdaq/aapl").json()
    assert d["close"] == 200 and d["close_krw"] == 260_000 and d["fx_rate"] == 1300 and d["fx_stale"] is False
    assert d["groups"] == [{"group_id": 2, "name": "빅테크"}]
    kr = client.get(f"{API}/stocks/KOSPI/005930").json()
    assert kr["close_krw"] == 70000 and kr["change"] == 1000
    r = client.get(f"{API}/stocks/KOSPI/AAPL")
    assert r.status_code == 404 and r.json()["error"]["code"] == "STOCK_NOT_FOUND"


def test_candles_financials_disclosures(client):
    c = client.get(f"{API}/stocks/KOSPI/005930/candles?range=1m").json()
    assert [x["close"] for x in c["candles"]] == [68000, 69000, 70000] and c["currency"] == "KRW"
    assert client.get(f"{API}/stocks/KOSPI/005930/candles?range=5y").status_code == 422
    assert client.get(f"{API}/stocks/KOSPI/005930/financials").json()["items"] == []     # 빈 데이터
    assert client.get(f"{API}/stocks/KOSPI/005930/disclosures").json()["items"] == []


def test_indices_and_fx(client, fake_fx):
    idx = client.get(f"{API}/market/indices").json()["indices"][0]
    assert idx["code"] == "KOSPI" and idx["close"] == 2520 and idx["change"] == 10 and len(idx["sparkline"]) == 3
    fx = client.get(f"{API}/market/fx").json()
    assert fx["usd_krw"] == 1300 and fx["fx_stale"] is False and len(fx["history"]) == 3
    assert fake_fx.current.count == 0                                   # TTL 이내 → 외부 호출 없음


def test_error_format(client):
    r = client.get(f"{API}/stocks?limit=0")
    assert r.status_code == 422
    assert set(r.json()["error"]) == {"code", "message", "detail"}
    assert r.headers["X-Request-ID"]
