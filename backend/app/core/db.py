"""DB 엔진·세션 (SQLAlchemy 2.x, 동기)."""
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine(url: str | None = None) -> Engine:
    # connect_timeout: DB가 응답하지 않을 때 요청·헬스체크가 무한정 멈추지 않도록(A-114)
    return create_engine(url or get_settings().database_url, pool_pre_ping=True, connect_args={"connect_timeout": 10})


def session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=engine or get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI 의존성."""
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()
