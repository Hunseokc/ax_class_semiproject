"""모의 포트폴리오 CRUD + 요약."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.api.deps import IdPath, get_portfolio_service
from app.models import Portfolio, PortfolioItem
from app.schemas.api import (ItemCreate, ItemInput, ItemOut, ItemsOut, PortfolioCreate, PortfolioOut,
                             PortfolioUpdate, SummaryOut)
from app.services.portfolio import PortfolioService

router = APIRouter(prefix="/portfolios", tags=["portfolios"])


def _pf_out(svc: PortfolioService, pf: Portfolio) -> dict:
    used = svc.used_krw(pf.portfolio_id)
    count = len(pf.items)
    return {"portfolio_id": pf.portfolio_id, "user_id": pf.user_id, "name": pf.name, "seed_krw": pf.seed_krw,
            "used_krw": used, "remaining_krw": pf.seed_krw - used, "item_count": count,
            "created_at": pf.created_at, "updated_at": pf.updated_at}


def _item_out(item: PortfolioItem) -> dict:
    s = item.stock
    return {"item_id": item.item_id, "portfolio_id": item.portfolio_id, "stock_id": s.stock_id,
            "market": s.market.code, "ticker": s.ticker, "name": s.name, "currency": s.market.currency,
            "quantity": item.quantity, "ref_price": item.ref_price, "ref_fx_rate": item.ref_fx_rate,
            "ref_date": item.ref_date, "cost_krw": item.cost_krw, "memo": item.memo,
            "created_at": item.created_at, "updated_at": item.updated_at}


@router.post("", response_model=PortfolioOut, status_code=201, summary="포트폴리오 생성")
def create_portfolio(body: PortfolioCreate, svc: PortfolioService = Depends(get_portfolio_service)):
    return _pf_out(svc, svc.create(body.name, body.seed_krw))


@router.get("", response_model=list[PortfolioOut], summary="사용자의 포트폴리오 목록")
def list_portfolios(svc: PortfolioService = Depends(get_portfolio_service)):
    return [_pf_out(svc, pf) for pf in svc.list()]


@router.get("/{portfolio_id}", response_model=PortfolioOut, summary="포트폴리오 단건")
def get_portfolio(portfolio_id: IdPath, svc: PortfolioService = Depends(get_portfolio_service)):
    return _pf_out(svc, svc.get(portfolio_id))


@router.put("/{portfolio_id}", response_model=PortfolioOut, summary="이름·시드 수정 (원가 합계 미만 시드는 409)")
def update_portfolio(portfolio_id: IdPath, body: PortfolioUpdate, svc: PortfolioService = Depends(get_portfolio_service)):
    return _pf_out(svc, svc.update(portfolio_id, body.name, body.seed_krw))


@router.delete("/{portfolio_id}", status_code=204, summary="포트폴리오 삭제 (담은 항목 함께 삭제)")
def delete_portfolio(portfolio_id: IdPath, svc: PortfolioService = Depends(get_portfolio_service)):
    svc.delete(portfolio_id)
    return Response(status_code=204)


@router.post("/{portfolio_id}/items", response_model=ItemOut, status_code=201,
             summary="종목 담기 (quantity/amount/weight 모드, 시드 초과 409, 수량 0이면 422)")
def add_item(portfolio_id: IdPath, body: ItemCreate, svc: PortfolioService = Depends(get_portfolio_service)):
    return _item_out(svc.add_item(portfolio_id, body.market, body.ticker, body.mode, body.value, body.memo))


@router.get("/{portfolio_id}/items", response_model=ItemsOut, summary="담은 종목과 현재 평가")
def list_items(portfolio_id: IdPath, svc: PortfolioService = Depends(get_portfolio_service)):
    items, fx = svc.valued_items(portfolio_id)
    return {"portfolio_id": portfolio_id, "fx_rate": fx.usd_krw if fx else None,
            "fx_rate_at": fx.rate_at if fx else None, "fx_stale": fx.stale if fx else False, "items": items}


@router.put("/{portfolio_id}/items/{item_id}", response_model=ItemOut,
            summary="담은 종목 수정 (기준가·환율을 현재값으로 갱신)")
def update_item(portfolio_id: IdPath, item_id: IdPath, body: ItemInput, svc: PortfolioService = Depends(get_portfolio_service)):
    return _item_out(svc.update_item(portfolio_id, item_id, body.mode, body.value, body.memo))


@router.delete("/{portfolio_id}/items/{item_id}", status_code=204, summary="담은 종목 삭제")
def delete_item(portfolio_id: IdPath, item_id: IdPath, svc: PortfolioService = Depends(get_portfolio_service)):
    svc.delete_item(portfolio_id, item_id)
    return Response(status_code=204)


@router.get("/{portfolio_id}/summary", response_model=SummaryOut,
            summary="요약: 사용·잔여·비중·가중 매력도·평가손익(환 효과 분리)")
def summary(portfolio_id: IdPath, svc: PortfolioService = Depends(get_portfolio_service)):
    return svc.summary(portfolio_id)
