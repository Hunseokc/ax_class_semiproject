"""대시보드 홈 전용 API: 시장 주목 종목 순위(거래량 급증·매력도)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db, get_preset
from app.schemas.api import HomeRankingOut
from app.services.home_ranking import get_attractiveness_ranking, get_volume_surge_ranking

router = APIRouter(prefix="/home", tags=["home"])


@router.get("/ranking", response_model=HomeRankingOut,
            summary="시장 주목 종목 TOP N — 거래량 급증(20거래일 평균 대비 배수) 또는 매력도 순위 (노출 종목 + 관심종목)")
def ranking(kind: Literal["volume_surge", "attractiveness"] = Query(description="volume_surge·attractiveness"),
            country: Literal["KR", "US"] = "KR",
            limit: int = Query(5, ge=1, le=20),
            user_id: int = Depends(get_current_user_id),
            preset: dict = Depends(get_preset),
            db: Session = Depends(get_db)):
    if kind == "volume_surge":
        items = get_volume_surge_ranking(db, country, limit, user_id=user_id)
    else:
        items = get_attractiveness_ranking(db, country, limit, preset=preset["code"], user_id=user_id)
    return {"kind": kind, "country": country, "preset": preset["code"] if kind == "attractiveness" else None,
            "items": items}
