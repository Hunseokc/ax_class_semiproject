"""오류 응답: 에러 코드별 재현, 입력 검증 경계값, 예상하지 못한 예외(500)의 형식·로그."""
import logging
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import deps
from app.core.errors import Unprocessable
from app.main import app
from app.schemas.common import INT_MAX
from app.services.portfolio import quantity_for

API = "/api/v1"
MONEY_MAX = 10**15


def code(r):
    return r.json()["error"]["code"]


def new_portfolio(client, seed=10_000_000, name="오류 테스트"):
    r = client.post(f"{API}/portfolios", json={"name": name, "seed_krw": seed})
    assert r.status_code == 201, r.text
    return r.json()["portfolio_id"]


# ---------------------------------------------------------------- 에러 코드 재현 (기존 테스트에 없던 코드)
def test_group_not_found_and_no_peer_group(client, engine):
    r = client.get(f"{API}/stocks/KOSPI/005930/peers/chart?group_id=2")     # 삼성전자는 반도체(1)만
    assert r.status_code == 404 and code(r) == "GROUP_NOT_FOUND"
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO stocks (stock_id, market_id, ticker, name) VALUES (5, 1, '035720', '카카오')"))
    r = client.get(f"{API}/stocks/KOSPI/035720/peers/chart")
    assert r.status_code == 404 and code(r) == "NO_PEER_GROUP"


def test_no_price_for_analysis_and_portfolio(client, engine):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO stocks (stock_id, market_id, ticker, name) VALUES (5, 1, '035720', '카카오')"))
    r = client.get(f"{API}/stocks/KOSPI/035720/analysis")
    assert r.status_code == 404 and code(r) == "NO_PRICE"
    pid = new_portfolio(client)
    r = client.post(f"{API}/portfolios/{pid}/items", json={"market": "KOSPI", "ticker": "035720", "mode": "quantity", "value": 1})
    assert r.status_code == 422 and code(r) == "NO_PRICE"


def test_duplicate_item_and_seed_below_used(client):
    pid = new_portfolio(client)
    body = {"market": "KOSPI", "ticker": "005930", "mode": "quantity", "value": 10}    # 70,000 × 10 = 700,000원
    assert client.post(f"{API}/portfolios/{pid}/items", json=body).status_code == 201
    r = client.post(f"{API}/portfolios/{pid}/items", json=body)
    assert r.status_code == 409 and code(r) == "DUPLICATE_ITEM" and r.json()["error"]["detail"]["item_id"]
    r = client.put(f"{API}/portfolios/{pid}", json={"name": "오류 테스트", "seed_krw": 699_999})
    assert r.status_code == 409 and code(r) == "SEED_BELOW_USED"
    assert r.json()["error"]["detail"]["used_krw"] == 700_000


def test_invalid_quantity_and_mode_are_rejected_by_service():
    """API에서는 스키마 검증이 먼저 422 VALIDATION_ERROR로 막는다. 서비스를 직접 부르는 경로의 방어."""
    with pytest.raises(Unprocessable) as e:
        quantity_for("quantity", Decimal("1.5"), Decimal(1_000_000), Decimal(70_000))
    assert e.value.code == "INVALID_QUANTITY"
    with pytest.raises(Unprocessable) as e:
        quantity_for("shares", Decimal(1), Decimal(1_000_000), Decimal(70_000))
    assert e.value.code == "INVALID_MODE"


def test_fx_unavailable_when_lookup_fails_and_nothing_stored(client, engine, fake_fx):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM fx_rates"))
    fake_fx.fail = True
    r = client.get(f"{API}/market/fx")
    assert r.status_code == 503 and code(r) == "FX_UNAVAILABLE"


def test_not_found_and_method_not_allowed(client):
    r = client.get(f"{API}/no-such-path")
    assert r.status_code == 404 and code(r) == "NOT_FOUND"
    r = client.delete(f"{API}/stocks")
    assert r.status_code == 405 and code(r) == "METHOD_NOT_ALLOWED"


def test_other_http_exception_is_http_error(client):
    def teapot():
        raise StarletteHTTPException(status_code=418, detail="teapot")
    app.dependency_overrides[deps.get_db] = teapot
    r = client.get(f"{API}/stocks")
    assert r.status_code == 418 and code(r) == "HTTP_ERROR"


# ---------------------------------------------------------------- 500: 형식·정보 노출·로그
def test_unexpected_error_is_internal_error_without_leak(client, caplog):
    secret = "SELECT password FROM users -- /srv/app/secret.py"

    def boom():
        raise RuntimeError(secret)
    app.dependency_overrides[deps.get_db] = boom
    plain = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR):
        r = plain.get(f"{API}/stocks", headers={"X-Request-ID": "req-500-test"})
    assert r.status_code == 500
    assert r.json() == {"error": {"code": "INTERNAL_ERROR", "message": "서버 오류가 발생했습니다", "detail": None}}
    assert "password" not in r.text and "/srv/" not in r.text and "Traceback" not in r.text
    assert r.headers["X-Request-ID"] == "req-500-test"                 # 500에도 요청 ID 헤더
    rec = next(x for x in caplog.records if x.levelno == logging.ERROR)
    assert rec.request_id == "req-500-test" and rec.exc_info is not None   # 서버 로그엔 요청 ID와 스택


# ---------------------------------------------------------------- 입력 검증 경계값
@pytest.mark.parametrize("path, expected", [
    ("/stocks/KOSPI/005930", 200),
    ("/stocks/KOSPI/ABCDEFGHIJKLMNOP", 404),                 # 16자: 형식 통과 → 없는 종목
    ("/stocks/KOSPI/ABCDEFGHIJKLMNOPQ", 422),                # 17자
    ("/stocks/KOSPI/005930%20", 422),                        # 공백
    ("/stocks/KOSPI/.5930", 422),                            # 첫 글자는 영숫자
    ("/stocks/KOSPI1/005930", 422),                          # 시장 코드는 영문만
    ("/stocks/K/005930", 422),                               # 시장 코드 2자 이상
    ("/stocks/KOSPIKOSPIK/005930", 422),                     # 11자
    ("/stocks/kospi/005930", 200),                           # 대소문자 무관(기존 동작)
])
def test_market_ticker_path_format(client, path, expected):
    r = client.get(API + path)
    assert r.status_code == expected, r.text
    if expected == 422:
        assert code(r) == "VALIDATION_ERROR"


@pytest.mark.parametrize("bad_id, expected_status, expected_code", [
    (INT_MAX, 404, None),                     # 형식 통과 → 없는 대상
    (INT_MAX + 1, 422, "VALIDATION_ERROR"),   # 예전에는 DB 정수 범위 오류가 500으로 샜다
    (0, 422, "VALIDATION_ERROR"),
    (-1, 422, "VALIDATION_ERROR"),
])
def test_id_path_range(client, bad_id, expected_status, expected_code):
    pid = new_portfolio(client)
    cases = [
        (client.get, f"/portfolios/{bad_id}", "PORTFOLIO_NOT_FOUND"),
        (client.get, f"/portfolios/{bad_id}/summary", "PORTFOLIO_NOT_FOUND"),
        (client.delete, f"/portfolios/{pid}/items/{bad_id}", "ITEM_NOT_FOUND"),
    ]
    for method, path, not_found_code in cases:
        r = method(API + path)
        assert r.status_code == expected_status, (path, r.text)
        assert code(r) == (expected_code or not_found_code), (path, r.text)


@pytest.mark.parametrize("name, expected", [
    ("가" * 100, 201), ("가" * 101, 422), ("", 422), ("   ", 422),
])
def test_portfolio_name_length(client, name, expected):
    r = client.post(f"{API}/portfolios", json={"name": name, "seed_krw": 1_000_000})
    assert r.status_code == expected, r.text


@pytest.mark.parametrize("seed, expected", [(MONEY_MAX, 201), (MONEY_MAX + 1, 422), (0, 422), (-1, 422), (1.5, 422)])
def test_portfolio_seed_range(client, seed, expected):
    r = client.post(f"{API}/portfolios", json={"name": f"시드 {seed}", "seed_krw": seed})
    assert r.status_code == expected, r.text
    pid = new_portfolio(client, name="수정 대상")
    r = client.put(f"{API}/portfolios/{pid}", json={"name": "수정 대상", "seed_krw": seed})
    assert r.status_code == (200 if expected == 201 else 422), r.text


@pytest.mark.parametrize("mode, value, expected_status, expected_code", [
    ("quantity", INT_MAX, 409, "SEED_EXCEEDED"),              # 형식은 통과, 시드 초과
    ("quantity", INT_MAX + 1, 422, "VALIDATION_ERROR"),
    ("amount", MONEY_MAX, 409, "SEED_EXCEEDED"),
    ("amount", MONEY_MAX + 1, 422, "VALIDATION_ERROR"),
    ("weight", 100, 201, None),
    ("weight", 100.01, 422, "VALIDATION_ERROR"),
    ("quantity", 0, 422, "VALIDATION_ERROR"),
    ("amount", -1, 422, "VALIDATION_ERROR"),
])
def test_item_value_range(client, mode, value, expected_status, expected_code):
    pid = new_portfolio(client, seed=10_000_000)
    r = client.post(f"{API}/portfolios/{pid}/items", json={"market": "KOSPI", "ticker": "005930", "mode": mode, "value": value})
    assert r.status_code == expected_status, r.text
    if expected_code:
        assert code(r) == expected_code


@pytest.mark.parametrize("memo, expected", [("가" * 500, 201), ("가" * 501, 422), ("", 201), (None, 201)])
def test_item_memo_length(client, memo, expected):
    pid = new_portfolio(client)
    r = client.post(f"{API}/portfolios/{pid}/items",
                    json={"market": "KOSPI", "ticker": "005930", "mode": "quantity", "value": 1, "memo": memo})
    assert r.status_code == expected, r.text


@pytest.mark.parametrize("body, expected", [
    ({"market": "KOSPI", "ticker": "005930"}, 201),
    ({"market": "KOSPI", "ticker": "005 930"}, 422),
    ({"market": "", "ticker": "005930"}, 422),
    ({"market": "KOSPI", "ticker": "A" * 17}, 422),
])
def test_watchlist_body_format(client, body, expected):
    r = client.post(f"{API}/watchlist", json=body)
    assert r.status_code == expected, r.text
    r = client.post(f"{API}/portfolios/{new_portfolio(client, name=str(body))}/items",
                    json={**body, "mode": "quantity", "value": 1})
    assert r.status_code == (201 if expected == 201 else 422), r.text


@pytest.mark.parametrize("sort_order, expected", [(9999, 200), (10_000, 422), (-1, 422)])
def test_watchlist_order_range(client, sort_order, expected):
    client.post(f"{API}/watchlist", json={"market": "KOSPI", "ticker": "005930"})
    r = client.patch(f"{API}/watchlist/order", json={"items": [{"market": "KOSPI", "ticker": "005930", "sort_order": sort_order}]})
    assert r.status_code == expected, r.text


def test_watchlist_order_item_count(client):
    item = {"market": "KOSPI", "ticker": "005930", "sort_order": 0}
    assert client.patch(f"{API}/watchlist/order", json={"items": []}).status_code == 422
    r = client.patch(f"{API}/watchlist/order", json={"items": [item] * 501})
    assert r.status_code == 422 and code(r) == "VALIDATION_ERROR"


@pytest.mark.parametrize("query, expected", [
    ("group=" + "가" * 64, 200), ("group=" + "가" * 65, 422),
    ("offset=10000", 200), ("offset=10001", 422), ("offset=-1", 422),
    ("limit=100", 200), ("limit=101", 422), ("limit=0", 422),
    ("preset=" + "x" * 21, 422),
])
def test_stock_list_query_range(client, query, expected):
    r = client.get(f"{API}/stocks?{query}")
    assert r.status_code == expected, r.text


def test_preset_length_and_unknown_preset(client):
    r = client.get(f"{API}/stocks?preset=" + "x" * 21)
    assert code(r) == "VALIDATION_ERROR"
    r = client.get(f"{API}/stocks?preset=" + "x" * 20)                  # 길이는 통과, 없는 프리셋
    assert r.status_code == 422 and code(r) == "UNKNOWN_PRESET"


@pytest.mark.parametrize("group_id, expected", [(1, 200), (0, 422), (INT_MAX + 1, 422)])
def test_peers_chart_group_id_range(client, group_id, expected):
    r = client.get(f"{API}/stocks/KOSPI/005930/peers/chart?group_id={group_id}")
    assert r.status_code == expected, r.text
