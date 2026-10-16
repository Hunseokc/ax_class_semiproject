"""요청 사용자: 기본은 DEFAULT_USER_ID 설정값, GUEST_SESSION_ENABLED면 브라우저(세션 쿠키)별 게스트 (2차에서 JWT 검증으로 교체)."""
import pytest
from sqlalchemy import text

from app.api import deps
from app.core.config import Settings
from tests.conftest import D, scalar

API = "/api/v1/watchlist"


def test_current_user_comes_from_default_user_id(client, monkeypatch):
    assert client.get(API).json()["user_id"] == 1
    monkeypatch.setattr(deps, "get_settings", lambda: Settings(default_user_id=2))
    assert client.get(API).json()["user_id"] == 2
    assert client.post(API, json={"market": "KOSPI", "ticker": "005930"}).status_code == 201
    assert "stockmind_session" not in client.cookies          # 기본 모드는 쿠키를 쓰지 않는다


@pytest.fixture
def guest(client, engine, monkeypatch):
    """게스트 세션 모드 + 데모 사용자(1)의 관심종목 1건·포트폴리오 1개(항목 1개). 세션 쿠키는 HTTPS에서만 오간다."""
    monkeypatch.setattr(deps, "get_settings", lambda: Settings(guest_session_enabled=True, session_secret="test"))
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO watchlist_items (user_id, stock_id, sort_order) VALUES (1, 1, 1);
            INSERT INTO portfolios (user_id, name, seed_krw) VALUES (1, '데모', 10000000)"""))
        conn.execute(text("""
            INSERT INTO portfolio_items (portfolio_id, stock_id, quantity, ref_price, ref_fx_rate, ref_date, memo)
              VALUES (currval('portfolios_portfolio_id_seq'), 3, 2, 195, 1300, :d, '메모')"""), {"d": D})
    client.base_url = "https://testserver"
    return client


def test_guest_reads_demo_until_first_write(guest):
    r = guest.get(API)
    assert r.json()["user_id"] == 1 and [c["ticker"] for c in r.json()["items"]] == ["005930"]
    assert "stockmind_session" not in guest.cookies           # 조회만으로는 게스트를 만들지 않는다


def test_first_write_creates_guest_with_demo_copy(guest, engine):
    assert guest.post(API, json={"market": "NASDAQ", "ticker": "AAPL"}).status_code == 201
    assert "stockmind_session" in guest.cookies
    r = guest.get(API).json()
    assert r["user_id"] == 3 and [c["ticker"] for c in r["items"]] == ["005930", "AAPL"]
    assert scalar(engine, "SELECT nickname LIKE 'guest-%' FROM users WHERE user_id = 3")
    assert scalar(engine, "SELECT COUNT(*) FROM watchlist_items WHERE user_id = 1") == 1   # 데모 원본은 그대로

    pf = guest.get("/api/v1/portfolios").json()
    assert [p["name"] for p in pf] == ["데모"]
    assert scalar(engine, """SELECT i.cost_krw FROM portfolio_items i JOIN portfolios p USING (portfolio_id)
                             WHERE p.user_id = 3 AND i.memo = '메모'""") == 507000      # 2주 × 195 × 1,300 — 담은 시점 값 그대로


def test_browsers_are_separate_users(guest):
    guest.post(API, json={"market": "NASDAQ", "ticker": "AAPL"})
    guest.cookies.clear()                                       # 다른 브라우저
    assert guest.get(API).json()["user_id"] == 1
    guest.post(API, json={"market": "NASDAQ", "ticker": "NVDA"})
    r = guest.get(API).json()
    assert r["user_id"] == 4 and [c["ticker"] for c in r["items"]] == ["005930", "NVDA"]


def test_stale_cookie_falls_back_to_demo(guest, engine):
    guest.post(API, json={"market": "NASDAQ", "ticker": "AAPL"})
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE user_id = 3"))
    assert guest.get(API).json()["user_id"] == 1
