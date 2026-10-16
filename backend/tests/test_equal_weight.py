"""관심종목 균등 배분 미리보기: POST /portfolios/{id}/preview/equal-weight (저장하지 않는 계산 전용).

픽스처 시세: 삼성 70,000원 · SK하이닉스 150,000원 · AAPL $200 · NVDA $110, 환율 1,300 (SNAPSHOT, TTL 이내)
"""
import pytest

from tests.conftest import scalar

API = "/api/v1"
ALL4 = [("KOSPI", "005930"), ("KOSPI", "000660"), ("NASDAQ", "AAPL"), ("NASDAQ", "NVDA")]


def new_pf(client, seed=10_000_000, name="균등"):
    return client.post(f"{API}/portfolios", json={"name": name, "seed_krw": seed}).json()["portfolio_id"]


def watch(client, *keys):
    for m, t in keys:
        assert client.post(f"{API}/watchlist", json={"market": m, "ticker": t}).status_code == 201


def preview(client, pid, body=None, status=200):
    r = client.post(f"{API}/portfolios/{pid}/preview/equal-weight", json=body)
    assert r.status_code == status, r.text
    return r.json()


def test_hand_calculated_scenario_mixed_currency(client):
    """시드 1천만 = 잔여 1천만 → 4종목 균등 몫 2,500,000원
    삼성 70,000 × 35 = 2,450,000 / SK 150,000 × 16 = 2,400,000 / AAPL $200×1,300 = 260,000 × 9 = 2,340,000 /
    NVDA $110×1,300 = 143,000 × 17 = 2,431,000 → 합계 9,621,000, 남는 금액 379,000"""
    pid = new_pf(client)
    watch(client, *ALL4)
    d = preview(client, pid)                                            # 본문 생략 → 관심종목 전체, 잔여 시드
    assert (d["budget_krw"], d["target_count"], d["share_krw"]) == (10_000_000, 4, 2_500_000)
    got = {i["ticker"]: (i["quantity"], i["unit_cost_krw"], i["cost_krw"], i["fx_rate"]) for i in d["items"]}
    assert got == {"005930": (35, 70_000, 2_450_000, 1), "000660": (16, 150_000, 2_400_000, 1),
                   "AAPL": (9, 260_000, 2_340_000, 1300), "NVDA": (17, 143_000, 2_431_000, 1300)}
    assert (d["total_cost_krw"], d["leftover_krw"], d["skipped"], d["saved"]) == (9_621_000, 379_000, [], False)
    assert {i["ticker"]: i["weight"] for i in d["items"]}["005930"] == pytest.approx(round(2_450_000 / 9_621_000, 6))
    assert d["fx_rate"] == 1300 and [i["ticker"] for i in d["items"]] == ["005930", "000660", "AAPL", "NVDA"]  # 관심종목 순서


def test_price_above_share_is_skipped_with_reason(client):
    """예산 500,000 → 몫 125,000: 삼성만 1주(70,000), SK 150,000·AAPL 260,000·NVDA 143,000은 1주가 몫보다 비쌈."""
    pid = new_pf(client)
    watch(client, *ALL4)
    d = preview(client, pid, {"budget_krw": 500_000})
    assert [(i["ticker"], i["quantity"], i["cost_krw"]) for i in d["items"]] == [("005930", 1, 70_000)]
    assert {s["ticker"]: (s["reason"], s["unit_cost_krw"], s["share_krw"]) for s in d["skipped"]} == {
        "000660": ("PRICE_ABOVE_SHARE", 150_000, 125_000), "AAPL": ("PRICE_ABOVE_SHARE", 260_000, 125_000),
        "NVDA": ("PRICE_ABOVE_SHARE", 143_000, 125_000)}
    assert (d["total_cost_krw"], d["leftover_krw"]) == (70_000, 430_000)


def test_explicit_stocks_held_and_unpriced_are_excluded(client, engine):
    from sqlalchemy import text
    with engine.begin() as conn:                                        # 시세 없는 종목
        conn.execute(text("INSERT INTO stocks (stock_id, market_id, ticker, name) VALUES (5, 1, '035720', '카카오')"))
    pid = new_pf(client)
    client.post(f"{API}/portfolios/{pid}/items", json={"market": "KOSPI", "ticker": "005930", "mode": "quantity", "value": 10})
    # 잔여 = 10,000,000 − 700,000 = 9,300,000 → 대상은 SK·NVDA 2종목, 몫 4,650,000
    d = preview(client, pid, {"stocks": [{"market": "KOSPI", "ticker": "005930"}, {"market": "KOSPI", "ticker": "000660"},
                                         {"market": "KOSPI", "ticker": "035720"}, {"market": "NASDAQ", "ticker": "NVDA"}]})
    assert (d["remaining_krw"], d["target_count"], d["share_krw"]) == (9_300_000, 2, 4_650_000)
    assert [(i["ticker"], i["quantity"]) for i in d["items"]] == [("000660", 31), ("NVDA", 32)]   # 4,650,000/150,000, /143,000
    assert {s["ticker"]: s["reason"] for s in d["skipped"]} == {"005930": "ALREADY_IN_PORTFOLIO", "035720": "NO_PRICE"}


def test_preview_does_not_save(client, engine):
    pid = new_pf(client)
    watch(client, *ALL4)
    before = (scalar(engine, "SELECT count(*) FROM portfolio_items"), scalar(engine, "SELECT count(*) FROM watchlist_items"))
    preview(client, pid)
    preview(client, pid, {"budget_krw": 1_000_000})
    assert (scalar(engine, "SELECT count(*) FROM portfolio_items"), scalar(engine, "SELECT count(*) FROM watchlist_items")) == before
    assert client.get(f"{API}/portfolios/{pid}").json()["used_krw"] == 0


def test_budget_over_remaining_or_no_remaining_is_409(client):
    pid = new_pf(client, seed=1_000_000)
    watch(client, ("KOSPI", "005930"))
    r = client.post(f"{API}/portfolios/{pid}/preview/equal-weight", json={"budget_krw": 1_000_001})
    assert r.status_code == 409 and r.json()["error"]["code"] == "SEED_EXCEEDED"
    assert r.json()["error"]["detail"]["remaining_krw"] == 1_000_000
    client.post(f"{API}/portfolios/{pid}/items", json={"market": "KOSPI", "ticker": "005930", "mode": "amount", "value": 1_000_000})
    pid2 = new_pf(client, seed=70_000, name="꽉 참")                   # 70,000원 시드에 삼성 1주 → 잔여 0
    client.post(f"{API}/portfolios/{pid2}/items", json={"market": "KOSPI", "ticker": "005930", "mode": "quantity", "value": 1})
    r = client.post(f"{API}/portfolios/{pid2}/preview/equal-weight")
    assert r.status_code == 409 and r.json()["error"]["message"] == "잔여 시드가 없습니다"


@pytest.mark.parametrize("body, status, code", [
    ({"budget_krw": 0}, 422, "VALIDATION_ERROR"),
    ({"budget_krw": -1}, 422, "VALIDATION_ERROR"),
    ({"stocks": []}, 422, "VALIDATION_ERROR"),
    ({"stocks": [{"market": "KOSPI", "ticker": "005930"}, {"market": "kospi", "ticker": "005930"}]}, 422, "VALIDATION_ERROR"),
    ({"stocks": [{"market": "KOSPI", "ticker": "999999"}]}, 404, "STOCK_NOT_FOUND"),
    (None, 422, "EMPTY_WATCHLIST"),                                     # 관심종목 0개 + 종목 지정 없음
])
def test_invalid_requests(client, body, status, code):
    pid = new_pf(client)
    r = client.post(f"{API}/portfolios/{pid}/preview/equal-weight", json=body)
    assert r.status_code == status and r.json()["error"]["code"] == code, r.text


def test_other_users_or_missing_portfolio_is_404(client, as_user):
    as_user(2)
    other = new_pf(client, name="남의 것")
    as_user(1)
    for pid in (other, 999_999):
        r = client.post(f"{API}/portfolios/{pid}/preview/equal-weight")
        assert r.status_code == 404 and r.json()["error"]["code"] == "PORTFOLIO_NOT_FOUND"
