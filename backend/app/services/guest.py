"""게스트 사용자: 로그인 없이 브라우저마다 사용자를 나눈다 (GUEST_SESSION_ENABLED=true일 때만 쓰인다).

새 게스트는 기본 사용자(demo)의 관심종목·포트폴리오를 복사해 시작한다 → 처음 쓰기 전까지 보던 화면 그대로 이어진다.
포트폴리오 항목의 ref_*(담은 시점 가격·환율)도 그대로 복사한다 — 다시 담으면 기준가가 오늘 값으로 바뀌기 때문.
"""
from __future__ import annotations

import secrets

from sqlalchemy import text
from sqlalchemy.orm import Session


def user_exists(db: Session, user_id: int) -> bool:
    return db.execute(text("SELECT 1 FROM users WHERE user_id = :u"), {"u": user_id}).first() is not None


def create_guest(db: Session, template_user_id: int) -> int:
    """게스트 사용자 1명을 만들고 template 사용자의 관심종목·포트폴리오를 복사한다. 커밋까지 하고 새 user_id를 돌려준다."""
    uid = db.execute(text("INSERT INTO users (nickname) VALUES (:n) RETURNING user_id"),
                     {"n": f"guest-{secrets.token_hex(8)}"}).scalar_one()
    p = {"uid": uid, "src": template_user_id}
    db.execute(text("""
        INSERT INTO watchlist_items (user_id, stock_id, sort_order, memo, target_price)
        SELECT :uid, stock_id, sort_order, memo, target_price FROM watchlist_items WHERE user_id = :src"""), p)
    # 포트폴리오 이름은 사용자 안에서 유일하다 → 새 포트폴리오와 원본을 이름으로 짝지어 항목을 옮긴다
    db.execute(text("""
        WITH src AS (
            SELECT portfolio_id, name, seed_krw FROM portfolios WHERE user_id = :src
        ), dst AS (
            INSERT INTO portfolios (user_id, name, seed_krw)
            SELECT :uid, name, seed_krw FROM src
            RETURNING portfolio_id, name
        )
        INSERT INTO portfolio_items (portfolio_id, stock_id, quantity, ref_price, ref_fx_rate, ref_date, memo)
        SELECT dst.portfolio_id, i.stock_id, i.quantity, i.ref_price, i.ref_fx_rate, i.ref_date, i.memo
        FROM dst
        JOIN src ON src.name = dst.name
        JOIN portfolio_items i ON i.portfolio_id = src.portfolio_id"""), p)
    db.commit()
    return uid
