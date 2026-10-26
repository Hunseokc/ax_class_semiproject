"""게스트 사용자: 로그인 없이 브라우저마다 사용자를 나눈다 (GUEST_SESSION_ENABLED=true일 때만 쓰인다).

게스트는 비로그인 상태의 사용성을 위한 것이라 관심종목만 저장한다. 포트폴리오 저장은 로그인해야 한다(deps.get_portfolio_user_id).
새 게스트는 기본 사용자(demo)의 관심종목을 복사해 시작한다 → 처음 쓰기 전까지 보던 화면 그대로 이어진다.
마지막 접속(last_seen_at, 1시간에 한 번 갱신) 후 GUEST_RETENTION_DAYS(3일)가 지나면 cleanup_guests가 지운다.
가입하면 게스트 행이 그대로 계정이 된다(app/services/auth.py) → 정리 대상에서 빠진다.
"""
from __future__ import annotations

import secrets

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

GUEST_PREFIX = "guest-"
TOUCH_SECONDS = 3600


def user_exists(db: Session, user_id: int) -> bool:
    return db.execute(text("SELECT 1 FROM users WHERE user_id = :u"), {"u": user_id}).first() is not None


def create_guest(db: Session, template_user_id: int) -> int:
    """게스트 사용자 1명을 만들고 template 사용자의 관심종목을 복사한다. 커밋까지 하고 새 user_id를 돌려준다."""
    uid = db.execute(text("INSERT INTO users (nickname) VALUES (:n) RETURNING user_id"),
                     {"n": f"{GUEST_PREFIX}{secrets.token_hex(8)}"}).scalar_one()
    db.execute(text("""
        INSERT INTO watchlist_items (user_id, stock_id, sort_order, memo, target_price)
        SELECT :uid, stock_id, sort_order, memo, target_price FROM watchlist_items WHERE user_id = :src"""),
               {"uid": uid, "src": template_user_id})
    db.commit()
    return uid


def touch_guest(db: Session, user_id: int) -> None:
    db.execute(text("UPDATE users SET last_seen_at = now() WHERE user_id = :u"), {"u": user_id})
    db.commit()


def cleanup_guests(engine: Engine, retention_days: int) -> int:
    """마지막 접속 후 retention_days가 지난 게스트를 지운다(관심종목 등은 ON DELETE CASCADE). 지운 수를 돌려준다."""
    with engine.begin() as conn:
        return conn.execute(text("""
            DELETE FROM users
            WHERE email IS NULL AND nickname LIKE :p AND last_seen_at < now() - make_interval(days => :d)"""),
                            {"p": GUEST_PREFIX + "%", "d": retention_days}).rowcount
