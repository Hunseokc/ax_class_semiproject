"""FastAPI 의존성. 테스트는 get_engine_dep를 override해 테스트 DB를 주입한다.

이후 단계에서 추가: MarketPath·TickerPath(Stage 1-B), get_current_user_id(Stage 2-D), get_providers·서비스 팩토리(Stage 2~3)
"""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.db import get_engine, session_factory


def get_engine_dep() -> Engine:
    return get_engine()


def get_db(engine: Engine = Depends(get_engine_dep)) -> Iterator[Session]:
    db = session_factory(engine)()
    try:
        yield db
    finally:
        db.close()
