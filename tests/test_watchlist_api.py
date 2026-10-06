"""관심종목 CRUD: 빈 목록·추가·중복 409·404·정렬 변경·삭제."""
API = "/api/v1/watchlist"


def test_empty_watchlist(client):
    assert client.get(API).json() == {"user_id": 1, "count": 0, "items": []}


def test_crud_flow(client):
    r = client.post(API, json={"market": "KOSPI", "ticker": "005930"})
    assert r.status_code == 201 and r.json()["sort_order"] == 1 and r.json()["close"] == 70000
    assert client.post(API, json={"market": "nasdaq", "ticker": "aapl"}).json()["sort_order"] == 2

    dup = client.post(API, json={"market": "KOSPI", "ticker": "005930"})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "DUPLICATE_WATCHLIST"

    r = client.patch(f"{API}/order", json={"items": [{"market": "NASDAQ", "ticker": "AAPL", "sort_order": 0}]})
    assert [c["ticker"] for c in r.json()["items"]] == ["AAPL", "005930"]

    assert client.delete(f"{API}/KOSPI/005930").status_code == 204
    assert client.delete(f"{API}/KOSPI/005930").status_code == 404
    assert [c["ticker"] for c in client.get(API).json()["items"]] == ["AAPL"]


def test_not_found_and_validation(client):
    assert client.post(API, json={"market": "KOSPI", "ticker": "999999"}).status_code == 404
    assert client.post(API, json={"user_id": 99, "market": "KOSPI", "ticker": "005930"}).status_code == 404
    assert client.get(f"{API}?user_id=99").status_code == 404
    assert client.post(API, json={"market": "KOSPI"}).status_code == 422
    r = client.patch(f"{API}/order", json={"items": [{"market": "KOSPI", "ticker": "000660", "sort_order": 1}]})
    assert r.status_code == 404 and r.json()["error"]["code"] == "WATCHLIST_ITEM_NOT_FOUND"


def test_watchlists_are_per_user(client):
    client.post(API, json={"user_id": 2, "market": "KOSPI", "ticker": "005930"})
    assert client.get(API).json()["count"] == 0
    assert client.get(f"{API}?user_id=2").json()["count"] == 1
