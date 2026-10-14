"""관심종목 CRUD: 빈 목록·추가·중복 409·404·정렬 변경·삭제·사용자 분리. (메모·목표가 PUT은 Stage 5)"""
import pytest
from sqlalchemy import text

from app.api import deps
from app.main import app

API = "/api/v1/watchlist"


@pytest.fixture
def as_user(engine):
    """다른 사용자인 척하는 도구. 사용자 2번을 만들고, 이후 요청의 get_current_user_id를 지정한 번호로 바꾼다.
    (override는 client 픽스처가 끝날 때 dependency_overrides.clear()로 정리된다)"""
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (user_id, username, display_name) VALUES (2, 'other', '다른 사용자')"))

    def _set(user_id: int) -> None:
        app.dependency_overrides[deps.get_current_user_id] = lambda: user_id

    return _set


def tickers(client) -> list[str]:
    return [c["ticker"] for c in client.get(API).json()["items"]]


def test_empty_watchlist(client):
    assert client.get(API).json() == {"user_id": 1, "count": 0, "items": []}


def test_crud_flow(client):
    r = client.post(API, json={"market": "KOSPI", "ticker": "005930"})
    assert r.status_code == 201 and r.json()["sort_order"] == 1 and r.json()["close"] == 70000
    assert client.post(API, json={"market": "nasdaq", "ticker": "aapl"}).json()["sort_order"] == 2   # 대소문자 무관, 맨 뒤 번호

    dup = client.post(API, json={"market": "KOSPI", "ticker": "005930"})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "DUPLICATE_WATCHLIST"
    assert tickers(client) == ["005930", "AAPL"]                      # 중복 요청은 목록을 바꾸지 않는다

    r = client.patch(f"{API}/order", json={"items": [{"market": "NASDAQ", "ticker": "AAPL", "sort_order": 0}]})
    assert [c["ticker"] for c in r.json()["items"]] == ["AAPL", "005930"]

    assert client.delete(f"{API}/KOSPI/005930").status_code == 204
    assert client.delete(f"{API}/KOSPI/005930").status_code == 404
    assert tickers(client) == ["AAPL"]


def test_not_found_and_validation(client):
    r = client.post(API, json={"market": "KOSPI", "ticker": "999999"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "STOCK_NOT_FOUND"
    assert client.post(API, json={"market": "KOSPI"}).status_code == 422
    assert client.patch(f"{API}/order", json={"items": []}).status_code == 422
    # 종목은 있지만 내 관심종목이 아님
    r = client.patch(f"{API}/order", json={"items": [{"market": "KOSPI", "ticker": "000660", "sort_order": 1}]})
    assert r.status_code == 404 and r.json()["error"]["code"] == "WATCHLIST_ITEM_NOT_FOUND"
    r = client.delete(f"{API}/KOSPI/000660")
    assert r.status_code == 404 and r.json()["error"]["code"] == "WATCHLIST_ITEM_NOT_FOUND"


def test_reorder_all_or_nothing(client):
    client.post(API, json={"market": "KOSPI", "ticker": "005930"})
    client.post(API, json={"market": "NASDAQ", "ticker": "AAPL"})
    r = client.patch(f"{API}/order", json={"items": [
        {"market": "NASDAQ", "ticker": "AAPL", "sort_order": 0},          # 이건 유효하지만
        {"market": "KOSPI", "ticker": "000660", "sort_order": 5},         # 이건 내 목록에 없다 → 전체 취소
    ]})
    assert r.status_code == 404
    assert tickers(client) == ["005930", "AAPL"]                          # AAPL의 순번도 바뀌지 않았다


def test_user_id_in_request_is_ignored(client):
    client.post(API, json={"user_id": 2, "market": "KOSPI", "ticker": "005930"})
    assert client.get(f"{API}?user_id=2").json()["user_id"] == 1
    assert client.get(API).json()["count"] == 1


def test_watchlists_are_per_user(client, as_user):
    as_user(2)
    client.post(API, json={"market": "KOSPI", "ticker": "005930"})
    assert client.get(API).json()["count"] == 1
    as_user(1)
    assert client.get(API).json()["count"] == 0
