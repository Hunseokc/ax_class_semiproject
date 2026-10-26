"""로그인(2차): 계정(이메일·비밀번호 / Google), JWT access token, Redis refresh token, 로그인 시도 제한, 사용자별 설정.

- 비밀번호: argon2id(argon2-cffi 기본값). 로그인할 때 기본값이 바뀌었으면 다시 해시한다.
- access token: JWT(HS256, JWT_SECRET) 15분. sub = user_id. 서명·만료로만 검증하고 DB·Redis를 보지 않는다.
- refresh token: 임의 문자열 14일, httpOnly 쿠키. Redis에는 SHA-256만 둔다. 쓸 때마다 새 토큰으로 바꾼다(rotation).
  · 바꾼 지 30초 안에 옛 토큰이 다시 오면 동시 요청(탭 두 개)으로 보고 401 REFRESH_RETRY → 화면이 새 쿠키로 다시 시도한다.
  · 그 뒤에 옛 토큰이 오면 탈취로 보고 그 기기(family)의 토큰을 모두 지운다.
- 시도 제한: 15분 동안 실패가 이메일당 5회·IP당 20회를 넘으면 429 (Redis 카운터).
- 가입: 이 브라우저의 게스트 행에 계정 정보를 채운다 → 게스트로 담은 관심종목이 그대로 계정 것이 된다. 게스트가 없으면 빈 계정.

Redis 키 (모두 refresh 기간 TTL)
  auth:rt:<hash>      → {"uid", "fam"}   지금 쓸 수 있는 refresh token
  auth:used:<hash>    → {"fam", "at"}    이미 바꾼 토큰(재사용 감지)
  auth:fam:<fam>      → <hash>           기기(family)의 지금 토큰
  auth:user:<uid>     → {fam, …}         사용자의 기기 목록(모든 기기 로그아웃·탈퇴)
  auth:fail:e:<email> / auth:fail:ip:<ip> → 실패 횟수(15분 TTL)
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import jwt
import redis
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict, ServiceUnavailable, TooManyRequests, Unauthorized

FAIL_WINDOW_SECONDS = 15 * 60
MAX_FAILS_PER_EMAIL, MAX_FAILS_PER_IP = 5, 20
ROTATE_GRACE_SECONDS = 30
PREF_KEYS = {"theme", "preset", "metrics", "watch_view", "home_portfolio"}   # 화면 localStorage 키와 1:1 (frontend/js/prefs.js)
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash(secrets.token_hex(8))   # 없는 이메일도 같은 시간 동안 검사 → 응답 시간으로 가입 여부를 알 수 없게


def normalize_email(email: str) -> str:
    return email.strip().lower()


# ------------------------------------------------------------------ 비밀번호
def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored: str | None) -> bool:
    try:
        return _hasher.verify(stored or _DUMMY_HASH, password) and stored is not None
    except (VerificationError, InvalidHashError):
        return False


# ------------------------------------------------------------------ access token (JWT)
def issue_access_token(user_id: int, secret: str, minutes: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user_id), "typ": "access", "iat": now, "exp": now + timedelta(minutes=minutes)},
                      secret, algorithm="HS256")


def read_access_token(token: str, secret: str) -> int:
    """유효한 access token의 user_id. 만료 → 401 TOKEN_EXPIRED, 그 밖의 문제 → 401 INVALID_TOKEN."""
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["sub", "exp", "iat"]}, leeway=10)
    except jwt.ExpiredSignatureError as e:
        raise Unauthorized("로그인이 만료됐어요", code="TOKEN_EXPIRED") from e
    except jwt.InvalidTokenError as e:
        raise Unauthorized("로그인 정보가 올바르지 않아요", code="INVALID_TOKEN") from e
    if claims.get("typ") != "access" or not str(claims["sub"]).isdigit():
        raise Unauthorized("로그인 정보가 올바르지 않아요", code="INVALID_TOKEN")
    return int(claims["sub"])


# ------------------------------------------------------------------ refresh token (Redis)
def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class RefreshStore:
    """refresh token 발급·교체·폐기. Redis에 연결할 수 없으면 503."""

    def __init__(self, r: redis.Redis, days: int, clock: Callable[[], float] = time.time):
        self.r, self.ttl, self.clock = r, days * 86400, clock

    def _guard(self, fn):
        try:
            return fn()
        except redis.RedisError as e:
            raise ServiceUnavailable("로그인 서버에 잠시 연결할 수 없어요. 잠시 후 다시 시도해 주세요",
                                     code="AUTH_STORE_UNAVAILABLE") from e

    def issue(self, user_id: int, fam: str | None = None) -> str:
        token, fam = secrets.token_urlsafe(32), fam or secrets.token_hex(8)

        def run():
            p = self.r.pipeline()
            p.set(f"auth:rt:{_h(token)}", json.dumps({"uid": user_id, "fam": fam}), ex=self.ttl)
            p.set(f"auth:fam:{fam}", _h(token), ex=self.ttl)
            p.sadd(f"auth:user:{user_id}", fam)
            p.expire(f"auth:user:{user_id}", self.ttl)
            p.execute()
        self._guard(run)
        return token

    def rotate(self, token: str) -> tuple[int, str]:
        """옛 토큰을 쓰고 새 토큰을 돌려준다 → (user_id, 새 토큰)."""
        h = _h(token)
        raw = self._guard(lambda: self.r.getdel(f"auth:rt:{h}"))
        if raw is None:
            used = self._guard(lambda: self.r.get(f"auth:used:{h}"))
            if used is None:
                raise Unauthorized("다시 로그인해 주세요", code="REFRESH_INVALID")
            u = json.loads(used)
            if self.clock() - u["at"] <= ROTATE_GRACE_SECONDS:
                raise Unauthorized("잠시 후 다시 시도해 주세요", code="REFRESH_RETRY")
            self.revoke_family(u["fam"])
            raise Unauthorized("보안을 위해 이 기기는 로그아웃됐어요. 다시 로그인해 주세요", code="REFRESH_REUSED")
        data = json.loads(raw)
        self._guard(lambda: self.r.set(f"auth:used:{h}", json.dumps({"fam": data["fam"], "at": self.clock()}), ex=self.ttl))
        return data["uid"], self.issue(data["uid"], data["fam"])

    def revoke(self, token: str) -> None:
        raw = self._guard(lambda: self.r.getdel(f"auth:rt:{_h(token)}"))
        if raw:
            data = json.loads(raw)
            self._guard(lambda: (self.r.delete(f"auth:fam:{data['fam']}"), self.r.srem(f"auth:user:{data['uid']}", data["fam"])))

    def revoke_family(self, fam: str) -> None:
        def run():
            cur = self.r.getdel(f"auth:fam:{fam}")
            if cur:
                raw = self.r.getdel(f"auth:rt:{cur}")
                if raw:
                    self.r.srem(f"auth:user:{json.loads(raw)['uid']}", fam)
        self._guard(run)

    def revoke_user(self, user_id: int, keep_token: str | None = None) -> None:
        """사용자의 모든 기기를 로그아웃한다(keep_token의 기기는 남긴다)."""
        keep = None
        if keep_token:
            raw = self._guard(lambda: self.r.get(f"auth:rt:{_h(keep_token)}"))
            keep = json.loads(raw)["fam"] if raw else None
        for fam in self._guard(lambda: self.r.smembers(f"auth:user:{user_id}")):
            if fam != keep:
                self.revoke_family(fam)

    # -------------------------------------------------------------- 시도 제한
    def check_rate_limit(self, email: str, ip: str | None) -> None:
        keys = [f"auth:fail:e:{email}"] + ([f"auth:fail:ip:{ip}"] if ip else [])
        counts = self._guard(lambda: self.r.mget(keys))
        if int(counts[0] or 0) >= MAX_FAILS_PER_EMAIL or (ip and int(counts[1] or 0) >= MAX_FAILS_PER_IP):
            raise TooManyRequests("로그인 시도가 너무 많아요. 15분 뒤에 다시 시도해 주세요",
                                  detail={"retry_after_minutes": FAIL_WINDOW_SECONDS // 60}, code="TOO_MANY_LOGIN_ATTEMPTS")

    def record_failure(self, email: str, ip: str | None) -> None:
        def run():
            p = self.r.pipeline()
            for k in [f"auth:fail:e:{email}"] + ([f"auth:fail:ip:{ip}"] if ip else []):
                p.incr(k)
                p.expire(k, FAIL_WINDOW_SECONDS, nx=True)
            p.execute()
        self._guard(run)

    def clear_failures(self, email: str) -> None:
        self._guard(lambda: self.r.delete(f"auth:fail:e:{email}"))


# ------------------------------------------------------------------ 계정
def account(db: Session, user_id: int) -> dict | None:
    row = db.execute(text("""SELECT user_id, nickname, email, password_hash IS NOT NULL AS has_password,
                                    google_sub IS NOT NULL AS has_google
                             FROM users WHERE user_id = :u AND email IS NOT NULL"""), {"u": user_id}).mappings().first()
    return dict(row) if row else None


def _guest_id(db: Session, user_id: int | None) -> int | None:
    """user_id가 게스트(계정 정보 없음, guest- 닉네임)면 그대로, 아니면 None."""
    if user_id is None:
        return None
    ok = db.execute(text("SELECT 1 FROM users WHERE user_id = :u AND email IS NULL AND nickname LIKE 'guest-%'"),
                    {"u": user_id}).first()
    return user_id if ok else None


def _save_account(db: Session, guest_user_id: int | None, fields: dict) -> int:
    """게스트 행을 계정으로 바꾸거나(관심종목 유지) 새 사용자 행을 만든다. 커밋까지 한다."""
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    try:
        if guest_user_id is not None:
            db.execute(text(f"UPDATE users SET {sets}, last_login_at = now() WHERE user_id = :uid"),
                       {**fields, "uid": guest_user_id})
            uid = guest_user_id
        else:
            cols = ", ".join(fields)
            uid = db.execute(text(f"INSERT INTO users ({cols}, last_login_at) VALUES ({', '.join(':' + k for k in fields)}, now()) "
                                  "RETURNING user_id"), fields).scalar_one()
        db.commit()
    except IntegrityError as e:        # 동시에 같은 이메일·닉네임으로 가입한 경우
        db.rollback()
        raise Conflict("이미 가입된 이메일이나 쓰고 있는 닉네임이에요", code="ACCOUNT_TAKEN") from e
    return uid


def signup(db: Session, email: str, password: str, nickname: str, guest_user_id: int | None) -> int:
    email = normalize_email(email)
    if db.execute(text("SELECT 1 FROM users WHERE email = :e"), {"e": email}).first():
        raise Conflict("이미 가입된 이메일이에요", code="EMAIL_TAKEN")
    if db.execute(text("SELECT 1 FROM users WHERE nickname = :n"), {"n": nickname}).first():
        raise Conflict("이미 쓰고 있는 닉네임이에요", code="NICKNAME_TAKEN")
    return _save_account(db, _guest_id(db, guest_user_id),
                         {"email": email, "password_hash": hash_password(password), "nickname": nickname})


def login(db: Session, store: RefreshStore, email: str, password: str, ip: str | None) -> int:
    """이메일·비밀번호가 맞으면 user_id. 틀리면 어느 쪽이 틀렸는지 알리지 않고 401."""
    email = normalize_email(email)
    store.check_rate_limit(email, ip)
    row = db.execute(text("SELECT user_id, password_hash FROM users WHERE email = :e"), {"e": email}).first()
    ok = verify_password(password, row.password_hash if row else None)    # 없는 이메일·Google 전용 계정도 해시 검사 시간을 쓴다
    if row is None or not ok:
        store.record_failure(email, ip)
        raise Unauthorized("이메일 또는 비밀번호가 맞지 않아요", code="INVALID_CREDENTIALS")
    store.clear_failures(email)
    new_hash = hash_password(password) if _hasher.check_needs_rehash(row.password_hash) else row.password_hash
    db.execute(text("UPDATE users SET last_login_at = now(), password_hash = :p WHERE user_id = :u"),
               {"u": row.user_id, "p": new_hash})
    db.commit()
    return row.user_id


# ------------------------------------------------------------------ Google 로그인
def verify_google_credential(credential: str, client_id: str, signing_key: Callable[[str], object]) -> dict:
    """Google Identity Services의 ID token(JWT)을 검증하고 claims를 돌려준다. signing_key(token) → 공개키."""
    try:
        claims = jwt.decode(credential, signing_key(credential), algorithms=["RS256"], audience=client_id,
                            options={"require": ["sub", "email", "exp", "iss"]}, leeway=10)
    except jwt.PyJWTError as e:
        raise Unauthorized("Google 로그인 정보를 확인하지 못했어요", code="INVALID_GOOGLE_TOKEN") from e
    if claims["iss"] not in GOOGLE_ISSUERS or claims.get("email_verified") is not True:
        raise Unauthorized("Google 로그인 정보를 확인하지 못했어요", code="INVALID_GOOGLE_TOKEN")
    return claims


def _free_nickname(db: Session, base: str) -> str:
    base = re.sub(r"[^0-9A-Za-z가-힣_.-]", "", base)[:14] or "user"
    if base.lower().startswith("guest-") or base.lower() in {"demo", "other"} or len(base) < 2:
        base = f"user{base}"[:14]
    name = base
    while db.execute(text("SELECT 1 FROM users WHERE nickname = :n"), {"n": name}).first():
        name = f"{base}{secrets.randbelow(10 ** 6):06d}"
    return name


def google_login(db: Session, claims: dict, guest_user_id: int | None) -> int:
    """Google 계정으로 로그인한다. 처음이면 같은 이메일 계정에 연결하거나 새로 만든다(게스트 관심종목 유지)."""
    sub, email = claims["sub"], normalize_email(claims["email"])
    row = db.execute(text("SELECT user_id FROM users WHERE google_sub = :s"), {"s": sub}).first()
    if row is None:
        row = db.execute(text("SELECT user_id FROM users WHERE email = :e"), {"e": email}).first()
        if row is not None:        # 이메일 계정에 Google 연결 (Google이 이메일 소유를 확인했다)
            db.execute(text("UPDATE users SET google_sub = :s WHERE user_id = :u"), {"s": sub, "u": row.user_id})
    if row is not None:
        db.execute(text("UPDATE users SET last_login_at = now() WHERE user_id = :u"), {"u": row.user_id})
        db.commit()
        return row.user_id
    nickname = _free_nickname(db, claims.get("name") or email.split("@")[0])
    return _save_account(db, _guest_id(db, guest_user_id), {"email": email, "google_sub": sub, "nickname": nickname})


# ------------------------------------------------------------------ 비밀번호 변경 · 탈퇴
def _check_password(db: Session, user_id: int, password: str) -> None:
    stored = db.execute(text("SELECT password_hash FROM users WHERE user_id = :u"), {"u": user_id}).scalar_one_or_none()
    if stored is None or not verify_password(password, stored):
        raise Unauthorized("비밀번호가 맞지 않아요", code="INVALID_PASSWORD")


def change_password(db: Session, user_id: int, current: str | None, new: str) -> None:
    """비밀번호를 바꾼다. Google로만 가입해 비밀번호가 없으면 current 없이 새로 정할 수 있다."""
    has_pw = db.execute(text("SELECT password_hash IS NOT NULL FROM users WHERE user_id = :u"), {"u": user_id}).scalar_one()
    if has_pw:
        _check_password(db, user_id, current or "")
    db.execute(text("UPDATE users SET password_hash = :p WHERE user_id = :u"), {"p": hash_password(new), "u": user_id})
    db.commit()


def withdraw(db: Session, user_id: int, password: str | None) -> None:
    """탈퇴: 사용자 행을 지운다 → 관심종목·포트폴리오·설정이 함께 지워진다(ON DELETE CASCADE).
    비밀번호가 있는 계정은 비밀번호를 확인한다. Google로만 가입한 계정은 로그인 상태만으로 지운다."""
    has_pw = db.execute(text("SELECT password_hash IS NOT NULL FROM users WHERE user_id = :u"), {"u": user_id}).scalar_one()
    if has_pw:
        _check_password(db, user_id, password or "")
    db.execute(text("DELETE FROM users WHERE user_id = :u"), {"u": user_id})
    db.commit()


# ------------------------------------------------------------------ 사용자별 설정
def get_prefs(db: Session, user_id: int) -> dict:
    prefs = db.execute(text("SELECT prefs FROM user_preferences WHERE user_id = :u"), {"u": user_id}).scalar_one_or_none()
    return {k: v for k, v in (prefs or {}).items() if k in PREF_KEYS}


def save_prefs(db: Session, user_id: int, prefs: dict) -> dict:
    """보낸 키만 덮어쓴다(None이면 그 키를 지운다)."""
    merged = {**get_prefs(db, user_id), **{k: v for k, v in prefs.items() if k in PREF_KEYS}}
    merged = {k: v for k, v in merged.items() if v is not None}
    db.execute(text("""INSERT INTO user_preferences (user_id, prefs) VALUES (:u, CAST(:p AS jsonb))
                       ON CONFLICT (user_id) DO UPDATE SET prefs = EXCLUDED.prefs, updated_at = now()"""),
               {"u": user_id, "p": json.dumps(merged)})
    db.commit()
    return merged
