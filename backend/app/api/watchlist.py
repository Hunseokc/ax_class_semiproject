"""관심종목 CRUD. (메모·목표가 수정 PUT, 매력도, 비교군 상세 수집 예약은 이후 단계)

사용자는 요청 본문·경로로 받지 않고 항상 get_current_user_id로 정한다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import MarketPath, TickerPath, get_current_user_id, get_db, resolve_stock
from app.core.errors import Conflict, NotFound
from app.models import WatchlistItem
from app.queries import sql
from app.schemas.api import WatchlistAddIn, WatchlistItemOut, WatchlistOrderIn, WatchlistOut

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


def _cards(db: Session, user_id: int) -> list[dict]:
    return [dict(r) for r in db.execute(sql("watchlist"), {"user_id": user_id}).mappings().all()]


@router.get("", response_model=WatchlistOut, summary="관심종목 카드 목록 (정렬순)")
def list_watchlist(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    items = _cards(db, user_id)
    return {"user_id": user_id, "count": len(items), "items": items}


@router.post("", response_model=WatchlistItemOut, status_code=201, summary="관심종목 추가")
def add_watchlist(body: WatchlistAddIn, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    s = resolve_stock(db, body.market, body.ticker)
    next_order = db.execute(select(func.coalesce(func.max(WatchlistItem.sort_order), 0) + 1)
                            .where(WatchlistItem.user_id == user_id)).scalar_one()
    db.add(WatchlistItem(user_id=user_id, stock_id=s["stock_id"], sort_order=next_order))
    try:
        db.commit()
    except IntegrityError as e:       # PK(user_id, stock_id) 위반 = 이미 담은 종목
        db.rollback()
        raise Conflict("이미 관심종목에 있습니다", detail={"market": s["market"], "ticker": s["ticker"]},
                       code="DUPLICATE_WATCHLIST") from e
    return next(c for c in _cards(db, user_id) if c["stock_id"] == s["stock_id"])


@router.patch("/order", response_model=WatchlistOut, summary="관심종목 정렬 순서 변경")
def reorder_watchlist(body: WatchlistOrderIn, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    for it in body.items:
        s = resolve_stock(db, it.market, it.ticker)
        w = db.get(WatchlistItem, (user_id, s["stock_id"]))
        if w is None:                 # 하나라도 목록에 없으면 전체를 취소한다
            db.rollback()
            raise NotFound(f"관심종목에 {it.market}/{it.ticker}이(가) 없습니다", code="WATCHLIST_ITEM_NOT_FOUND")
        w.sort_order = it.sort_order
    db.commit()
    items = _cards(db, user_id)
    return {"user_id": user_id, "count": len(items), "items": items}


@router.delete("/{market}/{ticker}", status_code=204, summary="관심종목 삭제")
def delete_watchlist(market: MarketPath, ticker: TickerPath, user_id: int = Depends(get_current_user_id),
                     db: Session = Depends(get_db)):
    s = resolve_stock(db, market, ticker)
    w = db.get(WatchlistItem, (user_id, s["stock_id"]))
    if w is None:
        raise NotFound(f"관심종목에 {market}/{ticker}이(가) 없습니다", code="WATCHLIST_ITEM_NOT_FOUND")
    db.delete(w)
    db.commit()
    return Response(status_code=204)
