"""시장 API: 지수, 환율. DB에 저장된 최신 값만 돌려준다(외부 호출 없음). 갱신·TTL 외부 호출은 Stage 2 이후."""
from __future__ import annotations

from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.errors import ServiceUnavailable
from app.queries import sql
from app.schemas.api import FxOut, IndicesOut

router = APIRouter(prefix="/market", tags=["market"])
SEOUL = ZoneInfo("Asia/Seoul")


@router.get("/indices", response_model=IndicesOut, summary="지수별 최신값·등락·최근 1년 스파크라인")
def indices(db: Session = Depends(get_db)):
    rows = db.execute(sql("market_indices")).mappings().all()
    items = [{**r, "sparkline": r["sparkline"] or []} for r in rows]
    return {"as_of": max((r["as_of"] for r in rows if r["as_of"]), default=None), "indices": items}


@router.get("/fx", response_model=FxOut, summary="USD/KRW 최신값·전일 대비·최근 1년 (DB 값만, 외부 호출 없음)")
def fx(db: Session = Depends(get_db)):
    latest = db.execute(text("SELECT rate_at, usd_krw, granularity FROM v_fx_latest")).mappings().first()
    if latest is None:
        raise ServiceUnavailable("환율 데이터가 없습니다", code="FX_UNAVAILABLE")
    rows = db.execute(sql("fx_daily_recent")).mappings().all()          # 최신순
    history = [{"date": r["date"], "usd_krw": r["usd_krw"]} for r in reversed(rows)]   # 그래프용 오래된 순
    # 전일 대비: 현재 값의 기준일(서울) 이전 마지막 DAILY 종가. 같은 날 DAILY와 비교하면 변화가 0으로 나올 수 있다
    quote_day = latest["rate_at"].astimezone(SEOUL).date()
    prev = next((h["usd_krw"] for h in reversed(history) if h["date"] < quote_day), None)
    change = latest["usd_krw"] - prev if prev is not None else None
    return {
        "usd_krw": latest["usd_krw"], "rate_at": latest["rate_at"], "granularity": latest["granularity"],
        "fx_stale": False,           # Stage 1은 DB 값만 읽는다. TTL 외부 호출(FxService)은 Stage 2에서 교체
        "prev_close": prev, "change": change,
        "change_rate": round(change / prev, 6) if change is not None and prev else None,
        "history": history, "as_of": latest["rate_at"],
    }
