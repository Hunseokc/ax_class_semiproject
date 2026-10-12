"""시장·갱신 API: 지수, 환율, 갱신."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_fx_service, get_refresh_service
from app.core.config import get_settings
from app.queries import sql
from app.schemas.api import FxOut, IndicesOut, RefreshJobOut, RefreshOut
from app.services.fx import FxService
from app.services.refresh import RefreshResult, RefreshService

router = APIRouter(prefix="/market", tags=["market"])
SEOUL = ZoneInfo("Asia/Seoul")


@router.get("/indices", response_model=IndicesOut, summary="지수별 최신값·등락·최근 30거래일 스파크라인")
def indices(db: Session = Depends(get_db)):
    rows = db.execute(sql("market_indices")).mappings().all()
    items = [{**r, "sparkline": r["sparkline"] or []} for r in rows]
    return {"as_of": max((r["as_of"] for r in rows if r["as_of"]), default=None), "indices": items}


@router.get("/fx", response_model=FxOut, summary="USD/KRW 최신값·전일 대비·최근 30일 (TTL 내에는 외부 호출 없음)")
def fx(db: Session = Depends(get_db), fx_service: FxService = Depends(get_fx_service)):
    quote = fx_service.get_current_rate()
    history = list(reversed(db.execute(sql("fx_daily_recent")).mappings().all()))
    # 전일 대비: 현재 값의 기준일(서울) 이전 마지막 DAILY 종가
    quote_day = quote.rate_at.astimezone(SEOUL).date()
    prev = next((h["usd_krw"] for h in reversed(history) if h["date"] < quote_day), None)
    change = quote.usd_krw - prev if prev is not None else None
    return {
        "usd_krw": quote.usd_krw, "rate_at": quote.rate_at, "granularity": quote.granularity, "fx_stale": quote.stale,
        "prev_close": prev, "change": change,
        "change_rate": round(change / prev, 6) if change is not None and prev else None,
        "history": history, "as_of": quote.rate_at,
    }


def _refresh_out(r: RefreshResult) -> RefreshOut:
    return RefreshOut(refreshed_at=r.refreshed_at, next_refresh_available_at=r.next_refresh_available_at,
                      ttl_hours=get_settings().refresh_ttl_hours,
                      jobs=[RefreshJobOut(**j.__dict__) for j in r.jobs])


@router.post("/refresh", response_model=RefreshOut,
             summary="환율·지수·증분 일봉·밸류에이션·점수 갱신 (작업별 TTL 이내면 SKIPPED)")
def refresh(service: RefreshService = Depends(get_refresh_service)):
    return _refresh_out(service.refresh())


@router.get("/refresh/status", response_model=RefreshOut,
            summary="갱신 상태 조회 — 외부 호출 없음 (사이드바 '마지막 갱신 시각' 표시용)")
def refresh_status(service: RefreshService = Depends(get_refresh_service)):
    return _refresh_out(service.status())
