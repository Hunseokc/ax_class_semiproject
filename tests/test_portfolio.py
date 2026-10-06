"""모의 포트폴리오: 명세 고정 시나리오, 시드 초과·축소 409, 입력 검증, 동시 담기, CRUD."""
import threading
from datetime import timedelta

import pytest
from sqlalchemy import text

from tests.conftest import D

API = "/api/v1/portfolios"


def create(client, name="테스트", seed=10_000_000, user_id=1):
    r = client.post(API, json={"user_id": user_id, "name": name, "seed_krw": seed})
    assert r.status_code == 201, r.text
    return r.json()["portfolio_id"]


def add(client, pid, ticker, mode, value, market=None):
    market = market or ("NASDAQ" if ticker.isalpha() else "KOSPI")
    return client.post(f"{API}/{pid}/items", json={"market": market, "ticker": ticker, "mode": mode, "value": value})


# ------------------------------------------------------------------ 명세 10절 고정 시나리오
def test_spec_scenario(client, engine):
    pid = create(client)
    # 삼성전자 종가 70,000원을 금액 3,000,000원으로 → 42주, 원가 2,940,000원
    r = add(client, pid, "005930", "amount", 3_000_000)
    assert r.status_code == 201
    assert (r.json()["quantity"], r.json()["cost_krw"], r.json()["ref_fx_rate"]) == (42, 2_940_000, 1)
    # AAPL 종가 $200, 환율 1,300을 비중 30%로 → 11주, 원가 2,860,000원
    r = add(client, pid, "AAPL", "weight", 30)
    assert (r.json()["quantity"], r.json()["cost_krw"], r.json()["ref_price"], r.json()["ref_fx_rate"]) == (11, 2_860_000, 200, 1300)
    s = client.get(f"{API}/{pid}/summary").json()
    assert (s["used_krw"], s["remaining_krw"], s["usage_rate"]) == (5_800_000, 4_200_000, 0.58)

    # 이후 AAPL $210, 환율 1,400
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO daily_prices VALUES (3, :d, 210, 210, 210, 210, 500)"), {"d": D + timedelta(days=1)})
        conn.execute(text("INSERT INTO fx_rates (rate_at, usd_krw, granularity) VALUES (now() + interval '1 minute', 1400, 'SNAPSHOT')"))
    s = client.get(f"{API}/{pid}/summary").json()
    aapl = next(i for i in s["items"] if i["ticker"] == "AAPL")
    assert aapl["value_krw"] == 3_234_000
    assert aapl["pnl_krw"] == 374_000
    assert aapl["pnl_rate"] == pytest.approx(0.1308, abs=5e-5)            # 약 +13.08%
    assert aapl["local_return"] == pytest.approx(0.05)                     # 종목통화 기준 +5.0%
    assert aapl["fx_return"] == pytest.approx(1400 / 1300 - 1, abs=1e-6)
    # 환 효과 분리: 가격 효과 11×(210−200)×1,300 + 환율 효과 11×210×(1,400−1,300) = 손익
    assert (aapl["price_effect_krw"], aapl["fx_effect_krw"]) == (143_000, 231_000)
    assert aapl["price_effect_krw"] + aapl["fx_effect_krw"] == aapl["pnl_krw"]
    # 담은 시점 기준가·환율은 시세·환율이 바뀌어도 그대로 (의도적 비정규화)
    assert (aapl["ref_price"], aapl["ref_fx_rate"], aapl["cost_krw"]) == (200, 1300, 2_860_000)
    assert s["total_value_krw"] == 2_940_000 + 3_234_000 and s["total_pnl_krw"] == 374_000
    assert s["fx_rate"] == 1400 and s["fx_stale"] is False
    assert {m["country"]: m["weight"] for m in s["market_weights"]} == {"KR": pytest.approx(2.94 / 5.8, abs=1e-6),
                                                                        "US": pytest.approx(2.86 / 5.8, abs=1e-6)}
    assert {g["group"] for g in s["group_weights"]} == {"반도체", "빅테크"}


def test_seed_exceeded_returns_409_with_max_quantity(client):
    pid = create(client)
    add(client, pid, "005930", "amount", 3_000_000)
    add(client, pid, "AAPL", "weight", 30)
    r = add(client, pid, "NVDA", "quantity", 100)                          # 100 × $110 × 1,300 = 14,300,000원
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "SEED_EXCEEDED"
    assert err["detail"]["remaining_krw"] == 4_200_000
    assert err["detail"]["max_quantity"] == 29                              # floor(4,200,000 / 143,000)
    assert add(client, pid, "NVDA", "quantity", 29).status_code == 201      # 안내된 최대 수량은 담김


def test_seed_cannot_drop_below_used(client):
    pid = create(client)
    add(client, pid, "005930", "amount", 3_000_000)
    r = client.put(f"{API}/{pid}", json={"name": "테스트", "seed_krw": 2_000_000})
    assert r.status_code == 409 and r.json()["error"]["detail"]["used_krw"] == 2_940_000
    ok = client.put(f"{API}/{pid}", json={"name": "새 이름", "seed_krw": 2_940_000})
    assert ok.status_code == 200 and ok.json()["remaining_krw"] == 0 and ok.json()["name"] == "새 이름"


def test_quantity_zero_returns_min_amount(client):
    pid = create(client)
    r = add(client, pid, "005930", "amount", 50_000)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "QUANTITY_ZERO" and r.json()["error"]["detail"]["min_amount_krw"] == 70_000


@pytest.mark.parametrize("body", [
    {"mode": "quantity", "value": 0}, {"mode": "quantity", "value": -3}, {"mode": "quantity", "value": 1.5},
    {"mode": "weight", "value": 101}, {"mode": "ratio", "value": 1}, {"mode": "amount"},
])
def test_invalid_item_input(client, body):
    pid = create(client)
    r = client.post(f"{API}/{pid}/items", json={"market": "KOSPI", "ticker": "005930", **body})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_duplicate_item_and_not_found(client):
    pid = create(client)
    first = add(client, pid, "005930", "quantity", 1).json()
    dup = add(client, pid, "005930", "quantity", 1)
    assert dup.status_code == 409 and dup.json()["error"]["detail"]["item_id"] == first["item_id"]
    assert add(client, pid, "999999", "quantity", 1).status_code == 404
    assert add(client, 999, "005930", "quantity", 1).status_code == 404
    assert client.get(f"{API}/999/summary").status_code == 404
    assert client.put(f"{API}/{pid}/items/999", json={"mode": "quantity", "value": 1}).status_code == 404
    other = create(client, name="다른")
    # 다른 포트폴리오의 항목 ID로 접근 → 404
    assert client.delete(f"{API}/{other}/items/{first['item_id']}").status_code == 404


def test_portfolio_validation_and_duplicate_name(client):
    assert client.post(API, json={"name": "x", "seed_krw": 0}).status_code == 422
    assert client.post(API, json={"name": "x", "seed_krw": -1}).status_code == 422
    assert client.post(API, json={"name": "", "seed_krw": 100}).status_code == 422
    assert client.post(API, json={"user_id": 99, "name": "x", "seed_krw": 100}).status_code == 404
    create(client, name="같은이름")
    r = client.post(API, json={"name": "같은이름", "seed_krw": 100})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_PORTFOLIO_NAME"
    create(client, name="같은이름", user_id=2)                              # 사용자가 다르면 허용


def test_empty_summary(client):
    pid = create(client)
    s = client.get(f"{API}/{pid}/summary").json()
    assert (s["used_krw"], s["remaining_krw"], s["usage_rate"], s["total_value_krw"]) == (0, 10_000_000, 0, 0)
    assert s["items"] == [] and s["weighted_score"] is None and s["fx_stale"] is False and s["as_of"] is None


def test_update_item_refreshes_reference_price_and_fx(client, engine):
    pid = create(client)
    item = add(client, pid, "AAPL", "quantity", 10).json()
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO daily_prices VALUES (3, :d, 220, 220, 220, 220, 500)"), {"d": D + timedelta(days=1)})
        conn.execute(text("INSERT INTO fx_rates (rate_at, usd_krw, granularity) VALUES (now() + interval '1 minute', 1400, 'SNAPSHOT')"))
    r = client.put(f"{API}/{pid}/items/{item['item_id']}", json={"mode": "amount", "value": 3_100_000, "memo": "수정"})
    body = r.json()
    assert r.status_code == 200
    assert (body["ref_price"], body["ref_fx_rate"], body["quantity"], body["memo"]) == (220, 1400, 10, "수정")
    assert body["ref_date"] == (D + timedelta(days=1)).isoformat()


def test_update_item_excludes_itself_from_used(client):
    pid = create(client, seed=1_000_000)
    item = add(client, pid, "005930", "quantity", 14).json()                # 980,000원
    r = client.put(f"{API}/{pid}/items/{item['item_id']}", json={"mode": "weight", "value": 100})
    assert r.status_code == 200 and r.json()["quantity"] == 14              # 자기 원가는 빼고 검증
    r = client.put(f"{API}/{pid}/items/{item['item_id']}", json={"mode": "quantity", "value": 15})
    assert r.status_code == 409 and r.json()["error"]["detail"]["max_quantity"] == 14


def test_delete_item_and_portfolio_cascade(client, engine):
    pid = create(client)
    item = add(client, pid, "005930", "quantity", 1).json()
    assert client.delete(f"{API}/{pid}/items/{item['item_id']}").status_code == 204
    add(client, pid, "005930", "quantity", 1)
    assert client.delete(f"{API}/{pid}").status_code == 204
    assert client.get(f"{API}/{pid}").status_code == 404
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM portfolio_items")).scalar() == 0


def test_concurrent_adds_never_exceed_seed(client, engine):
    """두 종목이 각각은 시드 안이지만 합치면 초과 → 동시에 담아도 정확히 하나만 성공해야 한다."""
    for round_ in range(5):
        pid = create(client, name=f"동시성{round_}", seed=1_000_000)
        barrier, codes = threading.Barrier(2), []

        def worker(ticker, qty):
            barrier.wait()
            codes.append(add(client, pid, ticker, "quantity", qty).status_code)

        threads = [threading.Thread(target=worker, args=("005930", 8)),     # 560,000원
                   threading.Thread(target=worker, args=("000660", 4))]     # 600,000원
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert sorted(codes) == [201, 409]
        with engine.connect() as conn:
            used = conn.execute(text("SELECT sum(cost_krw) FROM portfolio_items WHERE portfolio_id = :p"), {"p": pid}).scalar()
        assert used <= 1_000_000
