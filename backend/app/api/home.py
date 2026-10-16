"""대시보드 홈 전용 API: 시장 주목 종목 순위(거래량 급증·매력도), 섹터 히트맵, 시장 심리 지수.

모두 외부 호출 없이 DB만 쓴다(섹터 등락률은 갱신 작업이 수집, 심리 지수는 저장된 지수 일봉으로 계산·저장).

공유 파일: B는 [S6-B] 구역(/ranking), C는 [S6-C] 구역(/sectors·/sentiment)만 고친다. 구역에서 필요한 import는 맨 위에 추가한다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db, get_engine_dep, get_preset
from app.schemas.api import HomeRankingOut, SectorsOut, SentimentOut

router = APIRouter(prefix="/home", tags=["home"])


# ── [S6-B] 시장 주목 종목 순위 ──
# TODO(껍데기): B — 본문을 원본대로 교체(services/home_ranking.py의 get_volume_surge_ranking·get_attractiveness_ranking,
#   queries/home_volume_surge.sql·home_attractiveness.sql). 주소·인자·응답 모델은 원본 그대로다.
#   지금은 docs/06 3-7 예시 값(kind별 2개)을 limit만큼 잘라 돌려준다(country를 바꿔도 같은 종목).
@router.get("/ranking", response_model=HomeRankingOut,
            summary="시장 주목 종목 TOP N — 거래량 급증(20거래일 평균 대비 배수) 또는 매력도 순위 (노출 종목 + 관심종목)")
def ranking(kind: Literal["volume_surge", "attractiveness"] = Query(description="volume_surge·attractiveness"),
            country: Literal["KR", "US"] = "KR",
            limit: int = Query(5, ge=1, le=20),
            user_id: int = Depends(get_current_user_id),
            preset: dict = Depends(get_preset),
            db: Session = Depends(get_db)):
    if kind == "volume_surge":
        items = [
            {"rank": 1, "stock_id": 7, "market": "KOSPI", "country": "KR", "currency": "KRW", "ticker": "373220",
             "name": "LG에너지솔루션", "value": Decimal("3.181"), "as_of": date(2026, 10, 8), "is_watched": True},
            {"rank": 2, "stock_id": 14, "market": "KOSPI", "country": "KR", "currency": "KRW", "ticker": "012450",
             "name": "한화에어로스페이스", "value": Decimal("2.4753"), "as_of": date(2026, 10, 8), "is_watched": False},
        ][:limit]
    else:
        items = [
            {"rank": 1, "stock_id": 21, "market": "NASDAQ", "country": "US", "currency": "USD", "ticker": "NVDA",
             "name": "NVIDIA", "value": Decimal("95.28"), "as_of": date(2026, 10, 12), "is_watched": True},
            {"rank": 2, "stock_id": 19, "market": "NASDAQ", "country": "US", "currency": "USD", "ticker": "GOOGL",
             "name": "Alphabet", "value": Decimal("92.39"), "as_of": date(2026, 10, 12), "is_watched": False},
        ][:limit]
    return {"kind": kind, "country": country, "preset": preset["code"] if kind == "attractiveness" else None,
            "items": items}


# ── [S6-C] 섹터 히트맵·시장 심리 지수 ──
# TODO(껍데기): C — 본문을 원본대로 교체(services/sectors.py의 read_sectors). 주소·인자·응답 모델은 원본 그대로다.
#   지금은 docs/06 3-7 예시 값(정보기술·금융 2개)을 돌려준다(country만 실제 값).
@router.get("/sectors", response_model=SectorsOut,
            summary="섹터 히트맵 — 저장된 섹터 등락률만 읽는다(수집은 갱신 작업 SECTORS_US·SECTORS_KR, 외부 호출 없음)")
def sectors(country: Literal["KR", "US"] = "KR", db: Session = Depends(get_db)):
    return {"country": country, "available": True, "as_of": date(2026, 10, 8), "session_status": "previous_session",
            "fetched_at": datetime(2026, 10, 12, 15, 8, 17, tzinfo=timezone(timedelta(hours=9))),
            "sectors": [{"code": "1155", "name": "정보기술", "weight": 35.0, "change_pct": Decimal("-3.4975")},
                        {"code": "1156", "name": "금융", "weight": 12.0, "change_pct": Decimal("-3.1413")}]}


# TODO(껍데기): C — 본문을 원본대로 교체(services/sentiment.py의 get_sentiment). 주소·인자·응답 모델은 원본 그대로다.
#   지금은 docs/06 3-7 예시 값(S&P 500 + VIX)을 돌려준다(market·index_code만 country에 맞춤, KR은 vix_score null).
@router.get("/sentiment", response_model=SentimentOut,
            summary="시장 심리 지수(StockMind 간이 계산, CNN Fear & Greed 아님) — 저장된 지수·VIX 일봉으로 계산, 외부 호출 없음")
def sentiment(country: Literal["KR", "US"] = "KR", engine: Engine = Depends(get_engine_dep)):
    return {"market": country, "index_code": "SPX" if country == "US" else "KOSPI", "formula_version": 1,
            "as_of": date(2026, 10, 9), "session_status": "previous_session", "score": Decimal("79.25"), "label": "탐욕",
            "components": {"price_position": Decimal("99.5"), "ma_gap_score": Decimal("69.91"),
                           "rsi_score": Decimal("59.93"), "vix_score": Decimal("87.65") if country == "US" else None},
            "previous": {"trade_date": date(2026, 10, 8), "score": Decimal("76.27"), "label": "탐욕"},
            "week_ago": {"trade_date": date(2026, 10, 2), "score": Decimal("75.49"), "label": "탐욕"}}
