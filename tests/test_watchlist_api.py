"""관심종목 CRUD: 빈 목록·추가·중복 409·404·정렬 변경·삭제."""
API = "/api/v1/watchlist"


def test_empty_watchlist(client):
    assert client.get(API).json() == {"user_id": 1, "preset": "balanced", "count": 0, "items": []}


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


def test_not_found_and_validation(client, as_user):
    assert client.post(API, json={"market": "KOSPI", "ticker": "999999"}).status_code == 404
    assert client.post(API, json={"market": "KOSPI"}).status_code == 422
    r = client.patch(f"{API}/order", json={"items": [{"market": "KOSPI", "ticker": "000660", "sort_order": 1}]})
    assert r.status_code == 404 and r.json()["error"]["code"] == "WATCHLIST_ITEM_NOT_FOUND"
    as_user(99)
    assert client.post(API, json={"market": "KOSPI", "ticker": "005930"}).status_code == 404
    assert client.get(API).json()["error"]["code"] == "USER_NOT_FOUND"


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


# ------------------------------------------------------------------ 메모·목표가 수정 (PUT /watchlist/{market}/{ticker})
import time  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402


def put(client, ticker, body, market="KOSPI"):
    return client.put(f"{API}/{market}/{ticker}", json=body)


def test_update_memo_and_target_price_with_gap(client):
    assert client.post(f"{API}", json={"market": "KOSPI", "ticker": "005930"}).status_code == 201
    r = put(client, "005930", {"memo": "  실적 발표 확인  ", "target_price": 84000})
    assert r.status_code == 200, r.text
    c = r.json()
    # 현재가 70,000 → (84,000 − 70,000) / 70,000 = 0.2
    assert (c["memo"], c["target_price"], c["target_gap"], c["currency"]) == ("실적 발표 확인", 84000, 0.2, "KRW")
    card = client.get(f"{API}").json()["items"][0]
    assert (card["memo"], card["target_price"], card["target_gap"]) == ("실적 발표 확인", 84000, 0.2)


def test_target_gap_uses_stock_currency(client):
    client.post(f"{API}", json={"market": "NASDAQ", "ticker": "AAPL"})
    c = put(client, "AAPL", {"target_price": 250}, market="NASDAQ").json()      # $200 → $250
    assert (c["currency"], c["target_price"], c["target_gap"]) == ("USD", 250, 0.25)
    c = put(client, "AAPL", {"target_price": "199.1234"}, market="NASDAQ").json()  # 소수 4자리
    assert c["target_gap"] == pytest.approx(round((199.1234 - 200) / 200, 6))


def test_partial_update_and_clear_with_null(client):
    client.post(f"{API}", json={"market": "KOSPI", "ticker": "005930"})
    put(client, "005930", {"memo": "처음", "target_price": 84000})
    c = put(client, "005930", {"memo": "바꿈"}).json()                  # 보내지 않은 목표가는 유지
    assert (c["memo"], c["target_price"]) == ("바꿈", 84000)
    c = put(client, "005930", {"target_price": None}).json()            # null → 지움
    assert (c["memo"], c["target_price"], c["target_gap"]) == ("바꿈", None, None)
    c = put(client, "005930", {"memo": "   "}).json()                   # 공백만 → 지움
    assert c["memo"] is None


def test_update_refreshes_updated_at(client, engine):
    client.post(f"{API}", json={"market": "KOSPI", "ticker": "005930"})
    sql = "SELECT updated_at FROM watchlist_items WHERE stock_id = 1"
    with engine.connect() as conn:                                   # 닫지 않으면 열린 트랜잭션이 다음 테스트의 TRUNCATE를 막는다
        before = conn.execute(text(sql)).scalar()
    time.sleep(0.05)
    c = put(client, "005930", {"memo": "갱신"}).json()
    with engine.connect() as conn:
        after = conn.execute(text(sql)).scalar()
    assert after > before and c["updated_at"]


def test_target_price_check_constraint(client, engine):
    client.post(f"{API}", json={"market": "KOSPI", "ticker": "005930"})
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("UPDATE watchlist_items SET target_price = 0 WHERE stock_id = 1"))


@pytest.mark.parametrize("body, status, code", [
    ({"target_price": 0}, 422, "VALIDATION_ERROR"),
    ({"target_price": -1}, 422, "VALIDATION_ERROR"),
    ({"target_price": "1.12345"}, 422, "VALIDATION_ERROR"),             # NUMERIC(20,4)
    ({"memo": "가" * 201}, 422, "VALIDATION_ERROR"),
    ({"memo": "가" * 200}, 200, None),
    ({}, 422, "VALIDATION_ERROR"),                                       # 바꿀 값 없음
])
def test_update_validation(client, body, status, code):
    client.post(f"{API}", json={"market": "KOSPI", "ticker": "005930"})
    r = put(client, "005930", body)
    assert r.status_code == status, r.text
    if code:
        assert r.json()["error"]["code"] == code


def test_update_not_found(client):
    r = put(client, "000660", {"memo": "x"})                            # 종목은 있지만 관심종목이 아님
    assert r.status_code == 404 and r.json()["error"]["code"] == "WATCHLIST_ITEM_NOT_FOUND"
    r = put(client, "999999", {"memo": "x"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "STOCK_NOT_FOUND"


def test_new_fields_are_null_by_default(client):
    client.post(f"{API}", json={"market": "KOSPI", "ticker": "005930"})
    card = client.get(f"{API}").json()["items"][0]
    assert (card["memo"], card["target_price"], card["target_gap"]) == (None, None, None) and card["updated_at"]
