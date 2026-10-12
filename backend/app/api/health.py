"""헬스체크: 프로세스 생존(/health)과 DB 연결(/health/db). `/api/v1` 밖(루트)에 둔다(ASSUMPTIONS A-114)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.errors import ServiceUnavailable
from app.schemas.api import ErrorOut, HealthDbOut, HealthOut

log = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut, summary="프로세스 생존 확인 (DB에 접근하지 않음)")
def health():
    return {"status": "ok"}


@router.get("/health/db", response_model=HealthDbOut, responses={503: {"model": ErrorOut}},
            summary="DB 연결 확인 (SELECT 1). 실패하면 503 DB_UNAVAILABLE — 컨테이너 HEALTHCHECK가 사용")
def health_db(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1")).scalar_one()
    except SQLAlchemyError as e:
        # 접속 문자열·내부 메시지는 응답에 넣지 않고 로그에만 남긴다
        log.warning("DB 헬스체크 실패: %s", type(e).__name__)
        raise ServiceUnavailable("DB에 연결할 수 없습니다", code="DB_UNAVAILABLE") from e
    return {"status": "ok", "db": "ok"}
