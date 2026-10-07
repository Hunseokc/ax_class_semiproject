"""관심종목 CRUD."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.api.stocks import resolve_stock
from app.core.errors import Conflict, NotFound
from app.models import User, WatchlistItem
from app.queries import sql
from app.schemas.api import WatchlistCard, WatchlistCreate, WatchlistOrder, WatchlistOut

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


def _require_user(db: Session, user_id: int) -> None:
    if db.get(User, user_id) is None:
        raise NotFound(f"사용자(ID {user_id})를 찾을 수 없습니다", code="USER_NOT_FOUND")


def _cards(db: Session, user_id: int) -> list[dict]:
    return [dict(r) for r in db.execute(sql("watchlist"), {"user_id": user_id}).mappings().all()]


@router.get("", response_model=WatchlistOut, summary="관심종목 카드 목록 (정렬순)")
def list_watchlist(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _require_user(db, user_id)
    items = _cards(db, user_id)
    return {"user_id": user_id, "count": len(items), "items": items}


@router.post("", response_model=WatchlistCard, status_code=201, summary="관심종목 추가")
def add_watchlist(body: WatchlistCreate, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _require_user(db, user_id)
    s = resolve_stock(db, body.market, body.ticker)
    next_order = db.execute(select(func.coalesce(func.max(WatchlistItem.sort_order), 0) + 1)
                            .where(WatchlistItem.user_id == user_id)).scalar_one()
    db.add(WatchlistItem(user_id=user_id, stock_id=s["stock_id"], sort_order=next_order))
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise Conflict("이미 관심종목에 있습니다", detail={"market": s["market"], "ticker": s["ticker"]},
                       code="DUPLICATE_WATCHLIST") from e
    return next(c for c in _cards(db, user_id) if c["stock_id"] == s["stock_id"])


@router.patch("/order", response_model=WatchlistOut, summary="관심종목 정렬 순서 변경")
def reorder_watchlist(body: WatchlistOrder, user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _require_user(db, user_id)
    for it in body.items:
        s = resolve_stock(db, it.market, it.ticker)
        w = db.get(WatchlistItem, (user_id, s["stock_id"]))
        if w is None:
            db.rollback()
            raise NotFound(f"관심종목에 {it.market}/{it.ticker}이(가) 없습니다", code="WATCHLIST_ITEM_NOT_FOUND")
        w.sort_order = it.sort_order
    db.commit()
    items = _cards(db, user_id)
    return {"user_id": user_id, "count": len(items), "items": items}


@router.delete("/{market}/{ticker}", status_code=204, summary="관심종목 삭제")
def delete_watchlist(market: str, ticker: str, user_id: int = Depends(get_current_user_id),
                     db: Session = Depends(get_db)):
    _require_user(db, user_id)
    s = resolve_stock(db, market, ticker)
    w = db.get(WatchlistItem, (user_id, s["stock_id"]))
    if w is None:
        raise NotFound(f"관심종목에 {market}/{ticker}이(가) 없습니다", code="WATCHLIST_ITEM_NOT_FOUND")
    db.delete(w)
    db.commit()
    return Response(status_code=204)
