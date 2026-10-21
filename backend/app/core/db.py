"""DB 엔진·세션 (SQLAlchemy 2.x, 동기)."""
import os
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine(url: str | None = None) -> Engine:
    # connect_timeout: DB가 응답하지 않을 때 요청·헬스체크가 무한정 멈추지 않도록(A-114)
    # 풀 크기: Supabase 세션 풀러 한도(15)를 서비스+Jobs가 함께 넘지 않도록 기본 5+3, Jobs는 환경변수로 더 줄인다
    return create_engine(
        url or get_settings().database_url,
        pool_pre_ping=True,
        pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "3")),
        connect_args={"connect_timeout": 10},
    )


def session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=engine or get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI 의존성."""
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()
