"""시장 API: 지수, 환율. DB에 저장된 최신 값만 돌려준다(외부 호출 없음). 갱신·TTL 외부 호출은 Stage 2 이후."""
from __future__ import annotations

from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_fx_service
from app.queries import sql
from app.schemas.api import FxOut, IndicesOut
from app.services.fx import FxService

router = APIRouter(prefix="/market", tags=["market"])
SEOUL = ZoneInfo("Asia/Seoul")


@router.get("/indices", response_model=IndicesOut, summary="지수별 최신값·등락·최근 1년 스파크라인")
def indices(db: Session = Depends(get_db)):
    rows = db.execute(sql("market_indices")).mappings().all()
    items = [{**r, "sparkline": r["sparkline"] or []} for r in rows]
    return {"as_of": max((r["as_of"] for r in rows if r["as_of"]), default=None), "indices": items}


# ── [S2-C] 환율: FxService로 교체 ──
@router.get("/fx", response_model=FxOut, summary="USD/KRW 최신값·전일 대비·최근 1년 (TTL 내에는 외부 호출 없음)")
def fx(db: Session = Depends(get_db), fx_service: FxService = Depends(get_fx_service)):
    quote = fx_service.get_current_rate()                               # 저장값도 없으면 503 FX_UNAVAILABLE
    rows = db.execute(sql("fx_daily_recent")).mappings().all()          # 최신순
    history = [{"date": r["date"], "usd_krw": r["usd_krw"]} for r in reversed(rows)]   # 그래프용 오래된 순
    # 전일 대비: 현재 값의 기준일(서울) 이전 마지막 DAILY 종가. 같은 날 DAILY와 비교하면 변화가 0으로 나올 수 있다
    quote_day = quote.rate_at.astimezone(SEOUL).date()
    prev = next((h["usd_krw"] for h in reversed(history) if h["date"] < quote_day), None)
    change = quote.usd_krw - prev if prev is not None else None
    return {
        "usd_krw": quote.usd_krw, "rate_at": quote.rate_at, "granularity": quote.granularity, "fx_stale": quote.stale,
        "prev_close": prev, "change": change,
        "change_rate": round(change / prev, 6) if change is not None and prev else None,
        "history": history, "as_of": quote.rate_at,
    }
