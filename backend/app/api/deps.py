"""FastAPI 의존성. 테스트는 get_engine_dep를 override해 테스트 DB를 주입한다.

이후 단계에서 추가: get_providers·서비스 팩토리(Stage 2~3)
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Annotated

from fastapi import Depends, Path
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_engine, session_factory
from app.core.errors import NotFound
from app.providers.base import FxPoint, ProviderError
from app.schemas.common import INT_MAX, MARKET_PATTERN, TICKER_PATTERN
from app.services.fx import FxService
from app.services.portfolio import PortfolioService


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


# ── [S2-D] 현재 사용자·경로 id ──
def get_current_user_id() -> int:
    """1차는 단일 사용자(데모) 모드라 설정값을 그대로 쓴다. 2차에서 JWT 검증으로 교체한다."""
    return get_settings().default_user_id


# 정수 id 경로 파라미터(portfolio_id·item_id 등) — 범위 밖이면 DB 조회 전에 422 VALIDATION_ERROR
IdPath = Annotated[int, Path(ge=1, le=INT_MAX, description="1 이상 PostgreSQL INT 범위")]


# ── [S2-C] 환율·포트폴리오 서비스 ──
class _UnavailableFxProvider:
    """항상 실패하는 환율 provider. Stage 2에는 실제 환율 소스 연결이 없어 FxService가 저장된 마지막 값(+stale)으로 동작한다.

    TODO(Stage 3): get_providers().fx 주입으로 교체하고 이 클래스를 제거한다.
    """
    source = "INTERNAL"

    def get_daily_rates(self, start: date, end: date) -> list[FxPoint]:
        raise ProviderError("환율 provider가 아직 연결되지 않았습니다 (Stage 3)")

    def get_current_rate(self) -> FxPoint:
        raise ProviderError("환율 provider가 아직 연결되지 않았습니다 (Stage 3)")


def get_fx_service(engine: Engine = Depends(get_engine_dep)) -> FxService:
    return FxService(engine, _UnavailableFxProvider(), get_settings().refresh_ttl_hours)


def get_portfolio_service(db: Session = Depends(get_db), fx: FxService = Depends(get_fx_service),
                          user_id: int = Depends(get_current_user_id)) -> PortfolioService:
    return PortfolioService(db, fx, user_id)
