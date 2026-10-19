"""대시보드 홈 전용 API: 시장 주목 종목 순위(거래량 급증·매력도), 섹터 히트맵, 시장 심리 지수.

모두 외부 호출 없이 DB만 쓴다(섹터 등락률은 갱신 작업이 수집, 심리 지수는 저장된 지수 일봉으로 계산·저장).

공유 파일: B는 [S6-B] 구역(/ranking), C는 [S6-C] 구역(/sectors·/sentiment)만 고친다. 구역에서 필요한 import는 맨 위에 추가한다.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db, get_engine_dep, get_preset
from app.queries import sql
from app.schemas.api import HomeRankingOut, SectorsOut, SentimentOut
from app.services.sectors import read_sectors
from app.services.sentiment import get_sentiment

router = APIRouter(prefix="/home", tags=["home"])


# ── [S6-B] 시장 주목 종목 순위 ──
@router.get("/ranking", response_model=HomeRankingOut,
            summary="시장 주목 종목 TOP N — 거래량 급증(20거래일 평균 대비 배수) 또는 매력도 순위 (노출 종목 + 관심종목)")
def ranking(kind: Literal["volume_surge", "attractiveness"] = Query(description="volume_surge·attractiveness"),
            country: Literal["KR", "US"] = "KR",
            limit: int = Query(5, ge=1, le=20),
            user_id: int = Depends(get_current_user_id),
            preset: dict = Depends(get_preset),
            db: Session = Depends(get_db)):
    # TODO(연결): C의 services/home_ranking.py — 연결 시 원본처럼 맨 위 import로 옮기고 아래 except 대체 경로를 지운다
    try:
        from app.services.home_ranking import get_attractiveness_ranking, get_volume_surge_ranking
    except ImportError:          # C의 파일이 stage6에 들어오기 전: 같은 SQL을 직접 실행(원본 함수 본문과 같음)
        def get_volume_surge_ranking(db, country, limit=5, *, user_id):
            rows = db.execute(sql("home_volume_surge"), {"country": country, "limit": limit, "user_id": user_id})
            return [dict(r) for r in rows.mappings().all()]

        def get_attractiveness_ranking(db, country, limit=5, *, preset, user_id):
            rows = db.execute(sql("home_attractiveness"),
                              {"country": country, "limit": limit, "preset": preset, "user_id": user_id})
            return [dict(r) for r in rows.mappings().all()]
    if kind == "volume_surge":
        items = get_volume_surge_ranking(db, country, limit, user_id=user_id)
    else:
        items = get_attractiveness_ranking(db, country, limit, preset=preset["code"], user_id=user_id)
    return {"kind": kind, "country": country, "preset": preset["code"] if kind == "attractiveness" else None,
            "items": items}


# ── [S6-C] 섹터 히트맵·시장 심리 지수 ──
@router.get("/sectors", response_model=SectorsOut,
            summary="섹터 히트맵 — 저장된 섹터 등락률만 읽는다(수집은 갱신 작업 SECTORS_US·SECTORS_KR, 외부 호출 없음)")
def sectors(country: Literal["KR", "US"] = "KR", db: Session = Depends(get_db)):
    return read_sectors(db, country)


@router.get("/sentiment", response_model=SentimentOut,
            summary="시장 심리 지수(StockMind 간이 계산, CNN Fear & Greed 아님) — 저장된 지수·VIX 일봉으로 계산, 외부 호출 없음")
def sentiment(country: Literal["KR", "US"] = "KR", engine: Engine = Depends(get_engine_dep)):
    return get_sentiment(engine, country)
