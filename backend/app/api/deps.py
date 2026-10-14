"""FastAPI 의존성. 테스트는 get_engine_dep를 override해 테스트 DB를 주입한다.

이후 단계에서 추가: get_providers·서비스 팩토리(Stage 2~3)
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Path
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_engine, session_factory
from app.core.errors import NotFound, ServiceUnavailable
from app.schemas.common import INT_MAX, MARKET_PATTERN, TICKER_PATTERN


def get_engine_dep() -> Engine:
    return get_engine()


def get_db(engine: Engine = Depends(get_engine_dep)) -> Iterator[Session]:
    db = session_factory(engine)()
    try:
        yield db
    finally:
        db.close()


# ── [S1-B] 경로 검증·종목 찾기 ──
# 경로 파라미터 형식 — 형식이 틀리면 DB 조회 전에 422 VALIDATION_ERROR
MarketPath = Annotated[str, Path(pattern=MARKET_PATTERN, description="시장 코드 (KOSPI·KOSDAQ·NASDAQ·NYSE)", examples=["KOSPI"])]
TickerPath = Annotated[str, Path(pattern=TICKER_PATTERN, description="종목 코드 (005930·AAPL)", examples=["005930"])]


def resolve_stock(db: Session, market: str, ticker: str) -> dict:
    """시장 코드 + 종목 코드로 종목을 찾는다. 없으면 404 STOCK_NOT_FOUND. (형식 검사는 대소문자를 가리지 않아 여기서 대문자로 맞춘다)"""
    row = db.execute(text("""
        SELECT s.stock_id, s.ticker, s.name, m.code AS market, m.country, m.currency
        FROM stocks s JOIN markets m ON m.market_id = s.market_id
        WHERE m.code = :m AND s.ticker = :t"""), {"m": market.upper(), "t": ticker.upper()}).mappings().first()
    if row is None:
        raise NotFound(f"종목 {market}/{ticker}을(를) 찾을 수 없습니다", code="STOCK_NOT_FOUND")
    return dict(row)


# ── [S2-D] 현재 사용자 ──
def get_current_user_id(db: Session = Depends(get_db)) -> int:
    """요청을 보낸 사용자의 user_id. 인증이 없는 단일 데모 사용자 모드라 설정의 demo_username 행을 쓴다.

    관심종목·포트폴리오 API는 요청 본문·경로로 user_id를 받지 않고 항상 이 함수로 정한다
    (나중에 로그인이 생기면 이 함수만 바꾸면 된다). 사용자 행이 없으면 init-db/seed-demo가 안 된 상태 → 503.
    """
    username = get_settings().demo_username
    user_id = db.execute(text("SELECT user_id FROM users WHERE username = :u"), {"u": username}).scalar()
    if user_id is None:
        raise ServiceUnavailable(f"사용자 '{username}'이(가) 없습니다. init-db(또는 seed-demo)를 실행하세요", code="USER_NOT_FOUND")
    return user_id


CurrentUserId = Annotated[int, Depends(get_current_user_id)]

# 정수 id 경로 파라미터(portfolio_id·item_id 등) — 범위 밖이면 DB 조회 전에 422 VALIDATION_ERROR
IdPath = Annotated[int, Path(ge=1, le=INT_MAX, description="1 이상 PostgreSQL INT 범위")]
