"""소유자 확인: 다른 사용자의 포트폴리오·항목·관심종목은 존재 여부를 드러내지 않고 404로 응답한다."""
import pytest

API = "/api/v1"


@pytest.fixture
def others(client, as_user):
    """사용자 2의 포트폴리오(항목 1개)와 관심종목을 만든 뒤 사용자 1로 돌아온다."""
    as_user(2)
    pid = client.post(f"{API}/portfolios", json={"name": "남의 것", "seed_krw": 10_000_000}).json()["portfolio_id"]
    iid = client.post(f"{API}/portfolios/{pid}/items",
                      json={"market": "KOSPI", "ticker": "005930", "mode": "quantity", "value": 1}).json()["item_id"]
    assert client.post(f"{API}/watchlist", json={"market": "KOSPI", "ticker": "005930"}).status_code == 201
    as_user(1)
    return {"pid": pid, "iid": iid}


ITEM = {"mode": "quantity", "value": 2}
CROSS_REQUESTS = [
    ("GET", "/portfolios/{pid}", None, "PORTFOLIO_NOT_FOUND"),
    ("PUT", "/portfolios/{pid}", {"name": "탈취", "seed_krw": 1}, "PORTFOLIO_NOT_FOUND"),
    ("DELETE", "/portfolios/{pid}", None, "PORTFOLIO_NOT_FOUND"),
    ("GET", "/portfolios/{pid}/summary", None, "PORTFOLIO_NOT_FOUND"),
    ("GET", "/portfolios/{pid}/items", None, "PORTFOLIO_NOT_FOUND"),
    ("POST", "/portfolios/{pid}/items", {"market": "KOSPI", "ticker": "000660", **ITEM}, "PORTFOLIO_NOT_FOUND"),
    ("PUT", "/portfolios/{pid}/items/{iid}", ITEM, "PORTFOLIO_NOT_FOUND"),
    ("DELETE", "/portfolios/{pid}/items/{iid}", None, "PORTFOLIO_NOT_FOUND"),
    ("DELETE", "/watchlist/KOSPI/005930", None, "WATCHLIST_ITEM_NOT_FOUND"),
    ("PATCH", "/watchlist/order", {"items": [{"market": "KOSPI", "ticker": "005930", "sort_order": 9}]},
     "WATCHLIST_ITEM_NOT_FOUND"),
    ("PUT", "/watchlist/KOSPI/005930", {"memo": "탈취", "target_price": 1}, "WATCHLIST_ITEM_NOT_FOUND"),
]


@pytest.mark.parametrize("method,path,body,code", CROSS_REQUESTS, ids=[f"{m} {p}" for m, p, *_ in CROSS_REQUESTS])
def test_cross_user_access_is_404_and_changes_nothing(client, as_user, others, method, path, body, code):
    r = client.request(method, API + path.format(**others), json=body)
    assert r.status_code == 404 and r.json()["error"]["code"] == code

    as_user(2)
    pf = client.get(f"{API}/portfolios/{others['pid']}").json()
    assert (pf["name"], pf["seed_krw"], pf["item_count"]) == ("남의 것", 10_000_000, 1)
    items = client.get(f"{API}/portfolios/{others['pid']}/items").json()["items"]
    assert [(i["item_id"], i["quantity"]) for i in items] == [(others["iid"], 1)]
    assert [(w["ticker"], w["sort_order"], w["memo"], w["target_price"])
            for w in client.get(f"{API}/watchlist").json()["items"]] == [("005930", 1, None, None)]


def test_others_resources_are_not_listed(client, others):
    assert client.get(f"{API}/portfolios").json() == []
    assert client.get(f"{API}/watchlist").json()["count"] == 0


def test_others_item_via_own_portfolio_is_404(client, others):
    own = client.post(f"{API}/portfolios", json={"name": "내 것", "seed_krw": 10_000_000}).json()["portfolio_id"]
    r = client.delete(f"{API}/portfolios/{own}/items/{others['iid']}")
    assert r.status_code == 404 and r.json()["error"]["code"] == "ITEM_NOT_FOUND"
    r = client.put(f"{API}/portfolios/{own}/items/{others['iid']}", json=ITEM)
    assert r.status_code == 404 and r.json()["error"]["code"] == "ITEM_NOT_FOUND"


def test_same_name_per_user_is_independent(client, as_user, others):
    assert client.post(f"{API}/portfolios", json={"name": "남의 것", "seed_krw": 100}).status_code == 201
