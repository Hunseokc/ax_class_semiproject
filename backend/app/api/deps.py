"""FastAPI 의존성. 테스트는 get_engine_dep·get_providers를 override해 테스트 DB·fake provider를 주입한다."""
from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Path, Query
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_engine, session_factory
from app.core.errors import Unprocessable
from app.ingest.benchmark import config as benchmark_config
from app.providers.factory import Providers, default_providers
from app.schemas.common import INT_MAX, MARKET_PATTERN, TICKER_PATTERN
from app.services.fx import FxService
from app.services.hydration import Hydrator
from app.services.portfolio import PortfolioService
from app.services.refresh import RefreshService
from app.services.scoring import default_preset


# 경로 파라미터 형식 — 형식이 틀리면 DB 조회 전에 422 VALIDATION_ERROR (근거: ASSUMPTIONS A-112)
MarketPath = Annotated[str, Path(pattern=MARKET_PATTERN, description="시장 코드 (KOSPI·KOSDAQ·NASDAQ·NYSE)", examples=["KOSPI"])]
TickerPath = Annotated[str, Path(pattern=TICKER_PATTERN, description="종목 코드 (005930·AAPL)", examples=["005930"])]
IdPath = Annotated[int, Path(ge=1, le=INT_MAX, description="1 이상 PostgreSQL INT 범위")]


def get_engine_dep() -> Engine:
    return get_engine()


def get_current_user_id() -> int:
    """1차는 단일 사용자(데모) 모드라 설정값을 그대로 쓴다. 2차에서 JWT 검증으로 교체한다."""
    return get_settings().default_user_id


def get_db(engine: Engine = Depends(get_engine_dep)) -> Iterator[Session]:
    db = session_factory(engine)()
    try:
        yield db
    finally:
        db.close()


def get_preset(preset: str | None = Query(None, max_length=20, description="투자 성향 프리셋 코드(aggressive·growth·balanced·value). 비우면 balanced, 그 외 값은 422"),
               db: Session = Depends(get_db)) -> dict:
    code = preset or default_preset()
    row = db.execute(text("SELECT preset_id, code, name, description FROM scoring_presets WHERE code = :c"),
                     {"c": code}).mappings().first()
    if row is None:
        codes = list(db.execute(text("SELECT code FROM scoring_presets ORDER BY sort_order")).scalars())
        raise Unprocessable(f"알 수 없는 매력도 프리셋입니다: {code}", detail={"presets": codes}, code="UNKNOWN_PRESET")
    return dict(row)


@lru_cache
def _providers() -> Providers:
    return default_providers()


def get_providers() -> Providers:
    return _providers()


def get_fx_service(engine: Engine = Depends(get_engine_dep), providers: Providers = Depends(get_providers)) -> FxService:
    return FxService(engine, providers.fx, get_settings().refresh_ttl_hours)


def get_scorer():
    """5단계에서 점수 계산기를 연결한다."""
    if importlib.util.find_spec("app.services.scoring") is None:
        return None
    from app.services.scoring import compute_scores
    return compute_scores


def get_refresh_service(engine: Engine = Depends(get_engine_dep), providers: Providers = Depends(get_providers),
                        fx: FxService = Depends(get_fx_service), scorer=Depends(get_scorer)) -> RefreshService:
    return RefreshService(engine, providers, fx, get_settings().refresh_ttl_hours, scorer=scorer)


@lru_cache
def get_hydrator() -> Hydrator:
    """비교군 종목 상세 데이터를 요청 시 받는 작업자 (프로세스당 1개)."""
    return Hydrator(get_engine, _providers, benchmark_config()["detail_ttl_hours"])


def get_portfolio_service(db: Session = Depends(get_db), fx: FxService = Depends(get_fx_service),
                          user_id: int = Depends(get_current_user_id)) -> PortfolioService:
    return PortfolioService(db, fx, user_id)
