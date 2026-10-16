"""FastAPI 의존성. 테스트는 get_engine_dep·get_providers를 override해 테스트 DB·fake provider를 주입한다."""
from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Path, Query, Request
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_engine, session_factory
from app.core.errors import NotFound, Unprocessable
from app.providers.factory import Providers, default_providers
from app.schemas.common import INT_MAX, MARKET_PATTERN, TICKER_PATTERN
from app.services.fx import FxService
from app.services.guest import create_guest, user_exists
from app.services.portfolio import PortfolioService
from app.services.refresh import RefreshService
from app.services.scoring import default_preset


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
READ_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_current_user_id(request: Request, db: Session = Depends(get_db)) -> int:
    """요청 사용자. 기본은 단일 사용자(데모) 모드라 설정값을 그대로 쓴다. 2차에서 JWT 검증으로 교체한다.

    GUEST_SESSION_ENABLED면 브라우저마다 세션 쿠키로 게스트를 나눈다.
    쿠키가 없을 때 조회는 데모 사용자를 보여 주고, 첫 쓰기 요청에서 데모 데이터를 복사한 게스트를 만들어 쿠키에 담는다
    (조회만 하는 봇·미리보기 요청마다 사용자가 생기지 않게).
    """
    settings = get_settings()
    if not settings.guest_session_enabled:
        return settings.default_user_id
    uid = request.session.get("user_id")
    if isinstance(uid, int) and user_exists(db, uid):     # DB를 비운 뒤 남은 옛 쿠키는 없는 것으로 본다
        return uid
    if request.method in READ_METHODS:
        return settings.default_user_id
    uid = create_guest(db, settings.default_user_id)
    request.session["user_id"] = uid
    return uid


# 정수 id 경로 파라미터(portfolio_id·item_id 등) — 범위 밖이면 DB 조회 전에 422 VALIDATION_ERROR
IdPath = Annotated[int, Path(ge=1, le=INT_MAX, description="1 이상 PostgreSQL INT 범위")]


# ── [S3-D] 외부 소스 provider ──
@lru_cache
def _providers() -> Providers:
    return default_providers()


def get_providers() -> Providers:
    return _providers()


# ── [S2-C] 환율·포트폴리오 서비스 ──
def get_fx_service(engine: Engine = Depends(get_engine_dep), providers: Providers = Depends(get_providers)) -> FxService:
    return FxService(engine, providers.fx, get_settings().refresh_ttl_hours)


def get_portfolio_service(db: Session = Depends(get_db), fx: FxService = Depends(get_fx_service),
                          user_id: int = Depends(get_current_user_id)) -> PortfolioService:
    return PortfolioService(db, fx, user_id)


# ── [S3-D] 갱신 서비스 ──
def get_refresh_service(engine: Engine = Depends(get_engine_dep), providers: Providers = Depends(get_providers),
                        fx: FxService = Depends(get_fx_service)) -> RefreshService:
    return RefreshService(engine, providers, fx, get_settings().refresh_ttl_hours)


# ── [S4-B] 투자 성향 프리셋 ──
def get_preset(preset: str | None = Query(None, max_length=20, description="투자 성향 프리셋 코드(aggressive·growth·balanced·value). 비우면 balanced, 그 외 값은 422"),
               db: Session = Depends(get_db)) -> dict:
    code = preset or default_preset()
    row = db.execute(text("SELECT preset_id, code, name, description FROM scoring_presets WHERE code = :c"),
                     {"c": code}).mappings().first()
    if row is None:
        codes = list(db.execute(text("SELECT code FROM scoring_presets ORDER BY sort_order")).scalars())
        raise Unprocessable(f"알 수 없는 매력도 프리셋입니다: {code}", detail={"presets": codes}, code="UNKNOWN_PRESET")
    return dict(row)
