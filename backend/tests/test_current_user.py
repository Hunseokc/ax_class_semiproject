"""요청 사용자: 기본은 DEFAULT_USER_ID 설정값, GUEST_SESSION_ENABLED면 브라우저(세션 쿠키)별 게스트, 로그인하면 계정(test_auth).

게스트는 관심종목만 저장하고(포트폴리오는 데모 보기만), 마지막 접속 후 3일이 지나면 정리된다."""
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
    monkeypatch.setattr(deps, "get_settings", lambda: Settings(guest_session_enabled=True, session_secret="test",
                                                               jwt_secret="test-key-0123456789abcdef0123456789"))
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


def test_first_write_creates_guest_with_demo_watchlist(guest, engine):
    assert guest.post(API, json={"market": "NASDAQ", "ticker": "AAPL"}).status_code == 201
    assert "stockmind_session" in guest.cookies
    r = guest.get(API).json()
    assert r["user_id"] == 3 and [c["ticker"] for c in r["items"]] == ["005930", "AAPL"]
    assert scalar(engine, "SELECT nickname LIKE 'guest-%' FROM users WHERE user_id = 3")
    assert scalar(engine, "SELECT COUNT(*) FROM watchlist_items WHERE user_id = 1") == 1   # 데모 원본은 그대로
    assert scalar(engine, "SELECT COUNT(*) FROM portfolios WHERE user_id = 3") == 0       # 포트폴리오는 복사하지 않는다


def test_guest_sees_demo_portfolio_but_cannot_save(guest, engine):
    guest.post(API, json={"market": "NASDAQ", "ticker": "AAPL"})                        # 게스트 3
    pf = guest.get("/api/v1/portfolios").json()
    assert [(p["user_id"], p["name"]) for p in pf] == [(1, "데모")]                     # 데모 포트폴리오를 보기만
    r = guest.post("/api/v1/portfolios", json={"name": "내 것", "seed_krw": 1000000})
    assert (r.status_code, r.json()["error"]["code"]) == (401, "AUTH_REQUIRED")
    assert scalar(engine, "SELECT COUNT(*) FROM portfolios") == 1


def test_guest_last_seen_is_touched_hourly_and_old_guests_are_removed(guest, engine):
    from app.services.guest import cleanup_guests
    guest.post(API, json={"market": "NASDAQ", "ticker": "AAPL"})
    with engine.begin() as conn:
        conn.execute(text("UPDATE users SET last_seen_at = now() - interval '2 days' WHERE user_id = 3"))
    guest.get(API)                                                       # 방금 기록했으니(1시간 안) 다시 쓰지 않는다
    assert scalar(engine, "SELECT last_seen_at < now() - interval '1 day' FROM users WHERE user_id = 3")
    with engine.begin() as conn:
        conn.execute(text("UPDATE users SET last_seen_at = now() - interval '4 days' WHERE user_id = 3"))
    assert cleanup_guests(engine, 3) == 1
    assert scalar(engine, "SELECT COUNT(*) FROM users") == 2             # demo·other는 남는다
    assert scalar(engine, "SELECT COUNT(*) FROM watchlist_items WHERE user_id = 3") == 0
    assert guest.get(API).json()["user_id"] == 1                          # 정리된 게스트 쿠키는 데모 조회로


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
