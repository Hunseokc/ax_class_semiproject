"""시장·갱신 API: 지수, 환율, 갱신. 지수·환율 조회는 DB 값(+FxService TTL)만, 외부 수집은 갱신(refresh)에서만."""
from __future__ import annotations

from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_fx_service
from app.core.config import get_settings
from app.queries import sql
from app.schemas.api import FxOut, IndicesOut, RefreshOut
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


# ── [S3-D] 갱신 ──
# TODO(껍데기): D — RefreshService(services/refresh.py)·deps.get_refresh_service로 교체.
#   지금은 외부 호출도 DB 조회도 하지 않고 docs/06 3-1 예시 값을 돌려준다(Stage 3 작업 4개: FX·INDICES·PRICES·VALUATION)
_EXAMPLE_LAST_SUCCESS = {"FX": "2026-10-12T13:18:25.035205+09:00", "INDICES": "2026-10-12T13:18:39.418969+09:00",
                         "PRICES": "2026-10-12T13:18:55.994997+09:00", "VALUATION": "2026-10-12T13:19:22.821645+09:00"}


def _example_refresh(status: str, refreshed_at: str) -> dict:
    return {
        "refreshed_at": refreshed_at, "next_refresh_available_at": "2026-10-12T17:18:25.035205+09:00",
        "ttl_hours": get_settings().refresh_ttl_hours,
        "jobs": [{"job_type": j, "status": status,
                  "detail": f"TTL 이내 — 마지막 성공 {at}" if status == "SKIPPED" else None,
                  "last_success_at": at, "counts": {}} for j, at in _EXAMPLE_LAST_SUCCESS.items()],
    }


@router.post("/refresh", response_model=RefreshOut,
             summary="환율·지수·증분 일봉·밸류에이션 갱신 (작업별 TTL 이내면 SKIPPED)")
def refresh():
    return _example_refresh("SKIPPED", "2026-10-12T06:27:31.141007Z")


@router.get("/refresh/status", response_model=RefreshOut,
            summary="갱신 상태 조회 — 외부 호출 없음 (사이드바 '마지막 갱신 시각' 표시용)")
def refresh_status():
    return _example_refresh("FRESH", "2026-10-12T13:19:22.821645+09:00")
