"""종목 조회 API: 리스트, 상세, 캔들, 재무, 공시, 경쟁 그룹 목록, 상단 검색."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.api.deps import (MarketPath, TickerPath, get_current_user_id, get_db, get_engine_dep, get_hydrator, get_preset,
                          resolve_stock)
from app.core.errors import NotFound, Unprocessable
from app.ingest.sectors import sectors
from app.queries import raw, sql
from app.schemas.api import CandlesOut, DisclosuresOut, FinancialsOut, SearchOut, StockDetailOut, StockListOut
from app.services.hydration import Hydrator
from app.services.market_condition import get_condition

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
    sector: str | None = Query(None, min_length=1, max_length=32, description="업종 섹터(config/universe.yaml sectors 이름)"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10_000),
    user_id: int = Depends(get_current_user_id),
    preset: dict = Depends(get_preset),
    db: Session = Depends(get_db),
):
    if sort == "volume" and country is None:
        raise Unprocessable("시장마다 거래량 단위가 달라 '전체'에서는 거래량 정렬을 할 수 없습니다. 국내/미국 탭을 선택하세요",
                            detail={"allowed_sort_for_all": ["market_cap"]}, code="VOLUME_SORT_REQUIRES_MARKET")
    if sector is not None and sector not in {s.name for s in sectors()}:
        raise Unprocessable("알 수 없는 섹터입니다", detail={"allowed": [s.name for s in sectors()]}, code="VALIDATION_ERROR")
    # order_col·order_dir은 위 화이트리스트(SORT_COLUMNS, Literal)에서만 나오므로 문자열 치환해도 안전하다
    stmt = text(raw("stock_list").format(order_col=SORT_COLUMNS[sort], order_dir=order.upper()))
    params = {"user_id": user_id, "country": country, "grp": group, "q": q, "sector": sector, "preset": preset["code"],
              "limit": limit, "offset": offset}
    rows = db.execute(stmt, params).mappings().all()
    # total은 COUNT(*) OVER()라 돌려줄 행이 없으면 읽을 곳이 없다 → offset이 끝을 넘었을 때만 첫 행으로 한 번 더 센다
    total_row = rows[0] if rows else (db.execute(stmt, {**params, "limit": 1, "offset": 0}).mappings().first() if offset else None)
    fx_at = db.execute(text("SELECT rate_at FROM v_fx_latest")).scalar()
    return {"total": total_row["total"] if total_row else 0, "limit": limit, "offset": offset, "sort": sort, "order": order,
            "preset": preset["code"], "fx_rate_at": fx_at, "items": [dict(r) for r in rows]}


# ── [S6-B] 상단 검색 ──
def like_escape(q: str) -> str:
    """LIKE 특수문자를 글자 그대로 찾도록 이스케이프(PostgreSQL 기본 ESCAPE는 백슬래시)."""
    return q.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


@router.get("/search", response_model=SearchOut, summary="상단 검색 자동완성 (상장 보통주 전체 · 이름·영문명·티커)")
def search_stocks(q: str = Query(min_length=1, max_length=50, description="이름·영문명·티커 일부"),
                  limit: int = Query(8, ge=1, le=20), db: Session = Depends(get_db)):
    q = q.strip()
    if not q:
        return {"q": q, "items": []}
    rows = db.execute(sql("stock_search"), {"q": like_escape(q), "limit": limit}).mappings().all()
    return {"q": q, "items": [dict(r) for r in rows]}


@router.get("/{market}/{ticker}", response_model=StockDetailOut, summary="종목 기본 정보 + 최신 시세·밸류에이션")
def stock_detail(market: MarketPath, ticker: TickerPath, user_id: int = Depends(get_current_user_id),
                 preset: dict = Depends(get_preset), db: Session = Depends(get_db),
                 hydrator: Hydrator = Depends(get_hydrator), engine: Engine = Depends(get_engine_dep)):
    row = db.execute(sql("stock_detail"), {"market": market.upper(), "ticker": ticker.upper(),
                                           "user_id": user_id, "preset": preset["code"]}).mappings().first()
    if row is None:
        raise NotFound(f"종목 {market}/{ticker}을(를) 찾을 수 없습니다", code="STOCK_NOT_FOUND")
    out = dict(row)
    out["groups"] = out["groups"] or []
    out["preset"] = preset["code"]
    # 매력도 비교군 종목은 상세를 열 때 공시·2년 일봉·5개년 재무를 받는다(백그라운드)
    out["detail_status"] = hydrator.request(out["stock_id"], out["coverage"], out.pop("detail_synced_at"))
    # 시장·섹터 점수 — 매력 점수 아래 위험 표시(매력도와 별개). 섹터는 이 계산에만 쓰고 응답 최상위에는 내지 않는다
    out["market_condition"] = get_condition(engine, stock_id=out["stock_id"], country=out["country"],
                                            sector=out.pop("sector"))
    out["fx_stale"] = False          # Stage 1은 DB 값만 읽는다. TTL 외부 호출(FxService)은 Stage 2에서 교체
    return out


@router.get("/{market}/{ticker}/candles", response_model=CandlesOut, summary="기간 일봉")
def candles(market: MarketPath, ticker: TickerPath, range: Literal["1m", "3m", "6m", "1y"] = "3m", db: Session = Depends(get_db)):
    s = resolve_stock(db, market, ticker)
    rows = db.execute(sql("candles"), {"stock_id": s["stock_id"], "months": RANGE_MONTHS[range]}).mappings().all()
    return {"market": s["market"], "ticker": s["ticker"], "currency": s["currency"], "range": range,
            "as_of": rows[-1]["date"] if rows else None, "candles": rows}


# ── [S3-B] 재무·공시 ──
@router.get("/{market}/{ticker}/financials", response_model=FinancialsOut, summary="FY 재무 추이")
def financials(market: MarketPath, ticker: TickerPath, limit: int = Query(5, ge=1, le=10), db: Session = Depends(get_db)):
    s = resolve_stock(db, market, ticker)
    rows = db.execute(sql("financials"), {"stock_id": s["stock_id"], "limit": limit}).mappings().all()
    return {"market": s["market"], "ticker": s["ticker"], "currency": s["currency"],
            "as_of": rows[-1]["period_end"] if rows else None, "items": rows}


@router.get("/{market}/{ticker}/disclosures", response_model=DisclosuresOut, summary="최근 공시")
def disclosures(market: MarketPath, ticker: TickerPath, limit: int = Query(5, ge=1, le=50), db: Session = Depends(get_db)):
    s = resolve_stock(db, market, ticker)
    rows = db.execute(sql("disclosures"), {"stock_id": s["stock_id"], "limit": limit}).mappings().all()
    return {"market": s["market"], "ticker": s["ticker"],
            "as_of": rows[0]["filed_at"] if rows else None, "items": rows}


groups_router = APIRouter(prefix="/peer-groups", tags=["stocks"])


@groups_router.get("", summary="경쟁 그룹 목록 (리스트 필터용)")
def list_groups(db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT g.group_id, g.name, COUNT(gm.stock_id) AS size
        FROM peer_groups g LEFT JOIN peer_group_members gm ON gm.group_id = g.group_id
        GROUP BY g.group_id, g.name ORDER BY g.name""")).mappings().all()
    return {"groups": [dict(r) for r in rows]}
