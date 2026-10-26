"""로그인(2차): JWT access + Redis refresh(교체·재사용 감지), 가입(게스트 관심종목 이어 쓰기), 시도 제한,
로그아웃·모든 기기 로그아웃, 비밀번호 변경, 탈퇴, Google 로그인, 사용자별 설정.

refresh 쿠키는 Secure라 base_url을 https로 둔다. 비밀번호 해시는 argon2라 가입·로그인마다 수십 ms가 든다.
"""
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.api import auth as auth_api
from app.api import deps
from app.core.config import Settings
from app.main import app
from app.services import auth as svc
from app.services.auth import ROTATE_GRACE_SECONDS, RefreshStore
from tests.conftest import scalar

ME, WL, REFRESH = "/api/v1/auth/me", "/api/v1/watchlist", "/api/v1/auth/refresh"
RT = auth_api.REFRESH_COOKIE
KEY = "test-key-0123456789abcdef0123456789"                 # HS256 권장 길이(32바이트) 이상
ACC = {"email": "Me@Example.com", "password": "correct-horse", "nickname": "주니어"}


@pytest.fixture
def web(client):
    client.base_url = "https://testserver"
    return client


@pytest.fixture
def guest_mode(web, monkeypatch):
    monkeypatch.setattr(deps, "get_settings", lambda: Settings(guest_session_enabled=True, session_secret="test",
                                                               jwt_secret="test-key-0123456789abcdef0123456789"))
    return web


@pytest.fixture
def clock(redis_client):
    """refresh 교체 시각을 조절할 수 있는 저장소."""
    now = [1_000_000.0]
    store = RefreshStore(redis_client, 14, clock=lambda: now[0])
    app.dependency_overrides[deps.get_refresh_store] = lambda: store
    return now


def bearer(r) -> dict:
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def signup(c, **over):
    return c.post("/api/v1/auth/signup", json={**ACC, **over})


def login(c, email="me@example.com", password=ACC["password"]):
    return c.post("/api/v1/auth/login", json={"email": email, "password": password})


def err(r) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


# ------------------------------------------------------------------ 토큰·해시
def test_password_hash_is_argon2():
    h = svc.hash_password("pw-12345")
    assert h.startswith("$argon2id$") and svc.verify_password("pw-12345", h)
    assert not svc.verify_password("pw-12346", h) and not svc.verify_password("x", "not-a-hash")
    assert not svc.verify_password("pw-12345", None)


def test_access_token_checks():
    t = svc.issue_access_token(7, KEY, 15)
    assert svc.read_access_token(t, KEY) == 7
    with pytest.raises(svc.Unauthorized) as e:
        svc.read_access_token(t, "other-key-0123456789abcdef01234567")
    assert e.value.code == "INVALID_TOKEN"
    with pytest.raises(svc.Unauthorized) as e:
        svc.read_access_token(svc.issue_access_token(7, KEY, -1), KEY)
    assert e.value.code == "TOKEN_EXPIRED"


def test_me_without_token_and_bad_header(web):
    assert web.get(ME).json()["logged_in"] is False
    assert err(web.get(ME, headers={"Authorization": "Basic abc"})) == (401, "INVALID_TOKEN")


# ------------------------------------------------------------------ 가입·로그인
def test_signup_turns_current_guest_into_account(guest_mode, engine):
    guest_mode.post(WL, json={"market": "NASDAQ", "ticker": "AAPL"})          # 첫 쓰기 → 게스트 3
    r = signup(guest_mode)
    assert r.status_code == 201 and r.json()["token_type"] == "bearer" and r.json()["expires_in"] == 15 * 60
    assert r.json()["user"] == {"logged_in": True, "user_id": 3, "nickname": "주니어", "email": "me@example.com",
                              "has_password": True, "has_google": False}
    assert RT in guest_mode.cookies
    assert [c["ticker"] for c in guest_mode.get(WL, headers=bearer(r)).json()["items"]] == ["AAPL"]   # 게스트로 담은 것 그대로
    assert scalar(engine, "SELECT COUNT(*) FROM users") == 3                  # 새 사용자를 만들지 않았다
    assert guest_mode.get(WL).json()["user_id"] == 1                          # 토큰 없이는 게스트 칸이 비어 데모 조회


def test_signup_without_guest_starts_empty(web, engine):
    r = signup(web)
    assert r.json()["user"]["user_id"] == 3
    assert web.get(WL, headers=bearer(r)).json()["items"] == []
    assert web.post(WL, json={"market": "KOSPI", "ticker": "005930"}, headers=bearer(r)).status_code == 201
    assert scalar(engine, "SELECT COUNT(*) FROM watchlist_items WHERE user_id = 1") == 0   # demo는 그대로


@pytest.mark.parametrize("over, expected", [
    ({"email": "ME@example.com", "nickname": "다른이"}, (409, "EMAIL_TAKEN")),   # 대소문자만 다른 이메일
    ({"email": "b@example.com"}, (409, "NICKNAME_TAKEN")),
    ({"email": "c@example.com", "nickname": "guest-1"}, (422, "VALIDATION_ERROR")),
    ({"email": "d@example.com", "nickname": "짧은비번", "password": "1234567"}, (422, "VALIDATION_ERROR")),
    ({"email": "not-an-email", "nickname": "형식"}, (422, "VALIDATION_ERROR")),
])
def test_signup_rejects(web, over, expected):
    assert signup(web).status_code == 201
    assert err(signup(web, **over)) == expected


def test_login(web):
    signup(web)
    for email, pw in [("me@example.com", "wrong-password"), ("nobody@example.com", ACC["password"])]:
        assert err(login(web, email, pw)) == (401, "INVALID_CREDENTIALS")      # 어느 쪽이 틀렸는지 같은 답
    r = login(web, " ME@example.com ")
    assert r.status_code == 200 and web.get(ME, headers=bearer(r)).json()["user_id"] == 3


def test_login_attempts_are_limited(web, redis_client):
    signup(web)
    for _ in range(svc.MAX_FAILS_PER_EMAIL):
        assert login(web, password="wrong-password").status_code == 401
    assert err(login(web)) == (429, "TOO_MANY_LOGIN_ATTEMPTS")                # 맞는 비밀번호도 15분 동안 막힌다
    assert redis_client.ttl("auth:fail:e:me@example.com") > 800
    redis_client.delete("auth:fail:e:me@example.com")                         # 15분이 지난 것과 같다
    assert login(web).status_code == 200


def test_expired_or_deleted_user_token_is_rejected(web, engine):
    signup(web)
    expired = svc.issue_access_token(3, deps.jwt_secret(), -1)
    assert err(web.get(ME, headers={"Authorization": f"Bearer {expired}"})) == (401, "TOKEN_EXPIRED")
    ghost = svc.issue_access_token(999, deps.jwt_secret(), 15)
    assert err(web.get(WL, headers={"Authorization": f"Bearer {ghost}"})) == (401, "INVALID_TOKEN")


# ------------------------------------------------------------------ refresh 교체
def test_refresh_rotates_and_detects_reuse(web, clock):
    signup(web)
    old = web.cookies[RT]
    r = web.post(REFRESH)
    assert r.status_code == 200 and web.get(ME, headers=bearer(r)).json()["user_id"] == 3
    new = web.cookies[RT]
    assert new != old

    web.cookies.set(RT, old, path=auth_api.REFRESH_PATH)                      # 다른 탭이 옛 쿠키로 동시에 부름
    assert err(web.post(REFRESH)) == (401, "REFRESH_RETRY")
    clock[0] += ROTATE_GRACE_SECONDS + 1                                      # 유예가 지난 뒤 옛 토큰 = 탈취로 본다
    assert err(web.post(REFRESH)) == (401, "REFRESH_REUSED")
    web.cookies.set(RT, new, path=auth_api.REFRESH_PATH)
    assert err(web.post(REFRESH)) == (401, "REFRESH_INVALID")                 # 그 기기의 새 토큰도 함께 폐기


def test_refresh_without_cookie(web):
    assert err(web.post(REFRESH)) == (401, "REFRESH_INVALID")


def test_logout_revokes_refresh(web):
    signup(web)
    token = web.cookies[RT]
    assert web.post("/api/v1/auth/logout").status_code == 204
    web.cookies.set(RT, token, path=auth_api.REFRESH_PATH)
    assert err(web.post(REFRESH)) == (401, "REFRESH_INVALID")


def _two_devices(web) -> tuple[str, str, dict]:
    signup(web)
    first = web.cookies[RT]
    web.cookies.clear()
    r = login(web)
    return first, web.cookies[RT], bearer(r)


def _use(web, token):
    web.cookies.clear()
    web.cookies.set(RT, token, path=auth_api.REFRESH_PATH)


def test_logout_all_logs_out_every_device(web):
    first, second, auth = _two_devices(web)
    assert web.post("/api/v1/auth/logout-all", headers=auth).status_code == 204
    for t in (first, second):
        _use(web, t)
        assert err(web.post(REFRESH)) == (401, "REFRESH_INVALID")


def test_login_required_endpoints(web):
    assert err(web.post("/api/v1/auth/logout-all")) == (401, "AUTH_REQUIRED")
    assert err(web.get("/api/v1/auth/me/preferences")) == (401, "AUTH_REQUIRED")


def test_change_password_keeps_this_device_only(web):
    first, second, auth = _two_devices(web)
    body = {"current_password": "wrong-password", "new_password": "new-password-1"}
    assert err(web.put("/api/v1/auth/password", json=body, headers=auth)) == (401, "INVALID_PASSWORD")
    body["current_password"] = ACC["password"]
    assert web.put("/api/v1/auth/password", json=body, headers=auth).status_code == 204
    assert web.post(REFRESH).status_code == 200                              # 바꾼 기기(second)는 그대로
    _use(web, first)
    assert err(web.post(REFRESH)) == (401, "REFRESH_INVALID")                 # 다른 기기는 로그아웃
    assert login(web).status_code == 401 and login(web, password="new-password-1").status_code == 200


def test_withdraw_deletes_everything(web, engine):
    r = signup(web)
    web.post(WL, json={"market": "KOSPI", "ticker": "005930"}, headers=bearer(r))
    web.put("/api/v1/auth/me/preferences", json={"theme": "dark"}, headers=bearer(r))
    assert err(web.request("DELETE", ME, json={"password": "wrong-password"}, headers=bearer(r))) == (401, "INVALID_PASSWORD")
    assert web.request("DELETE", ME, json={"password": ACC["password"]}, headers=bearer(r)).status_code == 204
    for t in ("users WHERE user_id = 3", "watchlist_items WHERE user_id = 3", "user_preferences"):
        assert scalar(engine, f"SELECT COUNT(*) FROM {t}") == 0
    assert err(web.get(ME, headers=bearer(r))) == (401, "INVALID_TOKEN")      # 남은 access token도 거절
    assert err(web.post(REFRESH)) == (401, "REFRESH_INVALID")


# ------------------------------------------------------------------ 설정
def test_preferences(web):
    auth = bearer(signup(web))
    url = "/api/v1/auth/me/preferences"
    assert web.get(url, headers=auth).json() == {"theme": None, "preset": None, "metrics": None, "watch_view": None,
                                                 "home_portfolio": None}
    r = web.put(url, json={"theme": "dark", "metrics": ["per", "roe"]}, headers=auth)
    assert r.json()["theme"] == "dark" and r.json()["metrics"] == ["per", "roe"]
    r = web.put(url, json={"theme": None, "watch_view": "card"}, headers=auth)   # null은 지우고, 안 보낸 칸은 그대로
    assert (r.json()["theme"], r.json()["watch_view"], r.json()["metrics"]) == (None, "card", ["per", "roe"])
    assert err(web.put(url, json={"theme": "blue"}, headers=auth)) == (422, "VALIDATION_ERROR")


# ------------------------------------------------------------------ Google
@pytest.fixture
def google(web, monkeypatch):
    """가짜 Google 서명 키 + GOOGLE_CLIENT_ID 설정. make(**claims)로 ID token을 만든다."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(auth_api, "get_settings", lambda: Settings(google_client_id="cid"))
    app.dependency_overrides[auth_api.get_google_key_resolver] = lambda: (lambda token: key.public_key())

    def make(**over):
        now = datetime.now(timezone.utc)
        claims = {"iss": "https://accounts.google.com", "aud": "cid", "sub": "g-123", "email": "Me@Example.com",
                  "email_verified": True, "name": "홍 길동", "iat": now, "exp": now + timedelta(minutes=5), **over}
        return web.post("/api/v1/auth/google", json={"credential": jwt.encode(claims, key, algorithm="RS256")})
    return make


def test_google_creates_then_logs_in_same_account(google, web, engine):
    r = google()
    assert r.status_code == 200 and r.json()["user"]["has_google"] and not r.json()["user"]["has_password"]
    assert r.json()["user"]["nickname"] == "홍길동"
    assert google().json()["user"]["user_id"] == r.json()["user"]["user_id"]
    assert scalar(engine, "SELECT COUNT(*) FROM users WHERE google_sub = 'g-123'") == 1


def test_google_links_existing_email_account(google, web):
    uid = signup(web).json()["user"]["user_id"]
    r = google()
    assert r.json()["user"]["user_id"] == uid and r.json()["user"]["has_google"] and r.json()["user"]["has_password"]


@pytest.mark.parametrize("over", [{"aud": "other"}, {"email_verified": False}, {"iss": "evil.example.com"}])
def test_google_rejects_bad_tokens(google, over):
    assert err(google(**over)) == (401, "INVALID_GOOGLE_TOKEN")


def test_google_disabled_without_client_id(web):
    assert err(web.post("/api/v1/auth/google", json={"credential": "x"})) == (503, "GOOGLE_LOGIN_DISABLED")
    assert web.get("/api/v1/auth/config").json() == {"google_client_id": None}


def test_google_only_account_sets_password_and_withdraws_without_one(google, web, engine):
    auth = bearer(google())
    assert web.put("/api/v1/auth/password", json={"new_password": "first-password"}, headers=auth).status_code == 204
    assert login(web, "me@example.com", "first-password").status_code == 200
    auth = bearer(google(sub="g-999", email="only@example.com"))
    assert web.request("DELETE", ME, json={}, headers=auth).status_code == 204
    assert scalar(engine, "SELECT COUNT(*) FROM users WHERE google_sub = 'g-999'") == 0
