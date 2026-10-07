"""FastAPI 의존성. 테스트는 get_engine_dep·get_providers를 override해 테스트 DB·fake provider를 주입한다."""
from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from functools import lru_cache

from fastapi import Depends
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_engine, session_factory
from app.providers.factory import Providers, default_providers
from app.services.fx import FxService
from app.services.portfolio import PortfolioService
from app.services.refresh import RefreshService


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


def get_portfolio_service(db: Session = Depends(get_db), fx: FxService = Depends(get_fx_service)) -> PortfolioService:
    return PortfolioService(db, fx)
