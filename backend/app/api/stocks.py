"""종목 조회 API: 리스트, 상세, 캔들, 경쟁 그룹 목록. (재무·공시·검색은 이후 단계)"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import MarketPath, TickerPath, get_db, resolve_stock
from app.core.errors import NotFound, Unprocessable
from app.queries import raw, sql
from app.schemas.api import CandlesOut, StockDetailOut, StockListOut

router = APIRouter(prefix="/stocks", tags=["stocks"])

SORT_COLUMNS = {"volume": "volume", "market_cap": "market_cap_krw"}
RANGE_MONTHS = {"1m": 1, "3m": 3, "6m": 6, "1y": 12}


@router.get("", response_model=StockListOut, summary="주식 리스트 (거래량/시총 순위, 시장·그룹 필터, 검색)")
def list_stocks(
    country: Literal["KR", "US"] | None = Query(None, description="시장 탭. 비우면 전체"),
    sort: Literal["volume", "market_cap"] = Query("market_cap", description="전체 탭은 시총만 허용"),
    order: Literal["desc", "asc"] = "desc",
    group: str | None = Query(None, max_length=64, description="경쟁 그룹 이름"),
    q: str | None = Query(None, min_length=1, max_length=50, description="이름·티커 검색"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10_000),
    db: Session = Depends(get_db),
):
    if sort == "volume" and country is None:
        raise Unprocessable("시장마다 거래량 단위가 달라 '전체'에서는 거래량 정렬을 할 수 없습니다. 국내/미국 탭을 선택하세요",
                            detail={"allowed_sort_for_all": ["market_cap"]}, code="VOLUME_SORT_REQUIRES_MARKET")
    # order_col·order_dir은 위 화이트리스트(SORT_COLUMNS, Literal)에서만 나오므로 문자열 치환해도 안전하다
    stmt = text(raw("stock_list").format(order_col=SORT_COLUMNS[sort], order_dir=order.upper()))
    rows = db.execute(stmt, {"country": country, "grp": group, "q": q, "limit": limit, "offset": offset}).mappings().all()
    fx_at = db.execute(text("SELECT rate_at FROM v_fx_latest")).scalar()
    return {"total": rows[0]["total"] if rows else 0, "limit": limit, "offset": offset, "sort": sort, "order": order,
            "fx_rate_at": fx_at, "items": [dict(r) for r in rows]}


@router.get("/{market}/{ticker}", response_model=StockDetailOut, summary="종목 기본 정보 + 최신 시세·밸류에이션")
def stock_detail(market: MarketPath, ticker: TickerPath, db: Session = Depends(get_db)):
    row = db.execute(sql("stock_detail"), {"market": market.upper(), "ticker": ticker.upper()}).mappings().first()
    if row is None:
        raise NotFound(f"종목 {market}/{ticker}을(를) 찾을 수 없습니다", code="STOCK_NOT_FOUND")
    out = dict(row)
    out["groups"] = out["groups"] or []
    out["fx_stale"] = False          # Stage 1은 DB 값만 읽는다. TTL 외부 호출(FxService)은 Stage 2에서 교체
    return out


@router.get("/{market}/{ticker}/candles", response_model=CandlesOut, summary="기간 일봉")
def candles(market: MarketPath, ticker: TickerPath, range: Literal["1m", "3m", "6m", "1y"] = "3m", db: Session = Depends(get_db)):
    s = resolve_stock(db, market, ticker)
    rows = db.execute(sql("candles"), {"stock_id": s["stock_id"], "months": RANGE_MONTHS[range]}).mappings().all()
    return {"market": s["market"], "ticker": s["ticker"], "currency": s["currency"], "range": range,
            "as_of": rows[-1]["date"] if rows else None, "candles": rows}


groups_router = APIRouter(prefix="/peer-groups", tags=["stocks"])


@groups_router.get("", summary="경쟁 그룹 목록 (리스트 필터용)")
def list_groups(db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT g.group_id, g.name, COUNT(gm.stock_id) AS size
        FROM peer_groups g LEFT JOIN peer_group_members gm ON gm.group_id = g.group_id
        GROUP BY g.group_id, g.name ORDER BY g.name""")).mappings().all()
    return {"groups": [dict(r) for r in rows]}
