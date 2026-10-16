"""관심종목 CRUD. (매력도, 비교군 상세 수집 예약은 이후 단계)

사용자는 요청 본문·경로로 받지 않고 항상 get_current_user_id로 정한다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import MarketPath, TickerPath, get_current_user_id, get_db, resolve_stock
from app.core.errors import Conflict, NotFound
from app.models import User, WatchlistItem
from app.queries import sql
from app.schemas.api import WatchlistCard, WatchlistCreate, WatchlistOrder, WatchlistOut, WatchlistUpdate

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
    except IntegrityError as e:       # PK(user_id, stock_id) 위반 = 이미 담은 종목
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
    _require_user(db, user_id)
    s = resolve_stock(db, market, ticker)
    w = db.get(WatchlistItem, (user_id, s["stock_id"]))
    if w is None:
        raise NotFound(f"관심종목에 {market}/{ticker}이(가) 없습니다", code="WATCHLIST_ITEM_NOT_FOUND")
    db.delete(w)
    db.commit()
    return Response(status_code=204)


# TODO(껍데기): B — 본문을 원본대로 교체(보낸 필드만 w.memo·w.target_price에 저장 → commit → _cards에서 그 카드).
#   주소·인자·응답 모델(WatchlistCard)·404 두 가지는 원본 그대로다. 지금은 저장하지 않고, 지금 카드에 보낸 값만 얹어 돌려준다
#   (target_gap은 null — GET /watchlist의 memo·target_price·target_gap은 B가 watchlist.sql에 추가).
@router.put("/{market}/{ticker}", response_model=WatchlistCard,
            summary="관심종목 메모·목표가 수정 (보낸 필드만 변경, null이면 지움). 응답에 목표가 대비 괴리율 target_gap")
def update_watchlist(market: MarketPath, ticker: TickerPath, body: WatchlistUpdate,
                     user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    _require_user(db, user_id)
    s = resolve_stock(db, market, ticker)
    w = db.get(WatchlistItem, (user_id, s["stock_id"]))          # 다른 사용자 것이면 없는 것과 같은 404
    if w is None:
        raise NotFound(f"관심종목에 {market}/{ticker}이(가) 없습니다", code="WATCHLIST_ITEM_NOT_FOUND")
    card = next(c for c in _cards(db, user_id) if c["stock_id"] == s["stock_id"])
    return {**card, **body.model_dump(exclude_unset=True), "target_gap": None}
