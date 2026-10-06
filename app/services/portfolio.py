"""모의 포트폴리오 = 시드 안에서 종목을 담아보는 장바구니 + 계산기 (체결 기록 아님).

- 통화는 원화 통합. 담을 때 그 시점 종가(ref_price)·환율(ref_fx_rate)을 항목에 고정 저장한다.
- 입력 모드: quantity(수량) / amount(금액, 원) / weight(시드 대비 %) → 서버가 정수 수량으로 환산
- "원가 합계 ≤ 시드"는 행 간 제약 → 포트폴리오 행을 SELECT … FOR UPDATE로 잠근 한 트랜잭션에서 검증
- 모든 계산은 Decimal (float 사용 안 함)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, Unprocessable
from app.models import Market, Portfolio, PortfolioItem, Stock, User
from app.queries import sql
from app.services.fx import FxQuote, FxService

CENT = Decimal("0.01")
WON = Decimal("1")
PRICE_Q = Decimal("0.0001")     # NUMERIC(18,4) / NUMERIC(12,4)
MODES = ("quantity", "amount", "weight")


def q(v: Decimal, unit: Decimal = CENT) -> Decimal:
    return v.quantize(unit, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class RefQuote:
    """담기 기준 가격 정보."""
    stock: Stock
    price: Decimal          # 종목 통화 종가
    price_date: date
    fx_rate: Decimal        # KRW 종목은 1
    fx: FxQuote | None

    @property
    def unit_cost_krw(self) -> Decimal:
        return self.price * self.fx_rate


def quantity_for(mode: str, value: Decimal, seed: Decimal, unit_cost: Decimal) -> int:
    if mode == "quantity":
        if value != value.to_integral_value():
            raise Unprocessable("수량은 정수여야 합니다", code="INVALID_QUANTITY")
        return int(value)
    if mode == "amount":
        amount = value
    elif mode == "weight":
        amount = seed * value / Decimal(100)
    else:
        raise Unprocessable(f"지원하지 않는 모드: {mode}", detail={"modes": MODES}, code="INVALID_MODE")
    return int((amount / unit_cost).to_integral_value(rounding=ROUND_FLOOR))


class PortfolioService:
    def __init__(self, db: Session, fx: FxService):
        self.db = db
        self.fx = fx

    # ------------------------------------------------------------ 조회 도우미
    def _user(self, user_id: int) -> User:
        user = self.db.get(User, user_id)
        if user is None:
            raise NotFound(f"사용자(ID {user_id})를 찾을 수 없습니다", code="USER_NOT_FOUND")
        return user

    def get(self, portfolio_id: int, *, lock: bool = False) -> Portfolio:
        stmt = select(Portfolio).where(Portfolio.portfolio_id == portfolio_id)
        if lock:
            # 잠금 후 최신 값으로 다시 읽는다(앞서 identity map에 올라온 객체도 덮어씀)
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        pf = self.db.execute(stmt).scalar_one_or_none()
        if pf is None:
            raise NotFound(f"포트폴리오(ID {portfolio_id})를 찾을 수 없습니다", code="PORTFOLIO_NOT_FOUND")
        return pf

    def used_krw(self, portfolio_id: int, exclude_item: int | None = None) -> Decimal:
        stmt = select(func.coalesce(func.sum(PortfolioItem.cost_krw), 0)).where(PortfolioItem.portfolio_id == portfolio_id)
        if exclude_item is not None:
            stmt = stmt.where(PortfolioItem.item_id != exclude_item)
        return Decimal(self.db.execute(stmt).scalar_one())

    def find_stock(self, market: str, ticker: str) -> Stock:
        stock = self.db.execute(select(Stock).join(Market).where(Market.code == market.upper(),
                                                                  Stock.ticker == ticker.upper())).scalar_one_or_none()
        if stock is None:
            raise NotFound(f"종목 {market}/{ticker}을(를) 찾을 수 없습니다", code="STOCK_NOT_FOUND")
        return stock

    def ref_quote(self, stock: Stock) -> RefQuote:
        row = self.db.execute(text("SELECT trade_date, close FROM v_latest_price WHERE stock_id = :s"),
                              {"s": stock.stock_id}).first()
        if row is None:
            raise Unprocessable("시세가 없어 담을 수 없습니다", code="NO_PRICE")
        if stock.market.currency == "KRW":
            return RefQuote(stock, q(row.close, PRICE_Q), row.trade_date, Decimal(1), None)
        fx = self.fx.get_current_rate()
        return RefQuote(stock, q(row.close, PRICE_Q), row.trade_date, q(fx.usd_krw, PRICE_Q), fx)

    # ------------------------------------------------------------ 포트폴리오 CRUD
    def list(self, user_id: int) -> list[Portfolio]:
        self._user(user_id)
        return list(self.db.execute(select(Portfolio).where(Portfolio.user_id == user_id)
                                    .order_by(Portfolio.portfolio_id)).scalars())

    def create(self, user_id: int, name: str, seed_krw: Decimal) -> Portfolio:
        self._user(user_id)
        pf = Portfolio(user_id=user_id, name=name.strip(), seed_krw=seed_krw)
        self.db.add(pf)
        self._commit_unique(f"같은 이름의 포트폴리오가 이미 있습니다: {name}", "DUPLICATE_PORTFOLIO_NAME")
        self.db.refresh(pf)
        return pf

    def update(self, portfolio_id: int, name: str, seed_krw: Decimal) -> Portfolio:
        pf = self.get(portfolio_id, lock=True)
        used = self.used_krw(portfolio_id)
        if seed_krw < used:
            self.db.rollback()
            raise Conflict("시드를 현재 담은 원가 합계보다 작게 줄일 수 없습니다",
                           detail={"used_krw": used, "requested_seed_krw": seed_krw}, code="SEED_BELOW_USED")
        pf.name, pf.seed_krw = name.strip(), seed_krw
        self._commit_unique(f"같은 이름의 포트폴리오가 이미 있습니다: {name}", "DUPLICATE_PORTFOLIO_NAME")
        self.db.refresh(pf)
        return pf

    def delete(self, portfolio_id: int) -> None:
        pf = self.get(portfolio_id)
        self.db.delete(pf)
        self.db.commit()

    # ------------------------------------------------------------ 항목 CRUD
    def _check_and_quantity(self, pf: Portfolio, quote: RefQuote, mode: str, value: Decimal,
                            exclude_item: int | None = None) -> tuple[int, Decimal]:
        unit = quote.unit_cost_krw
        qty = quantity_for(mode, value, pf.seed_krw, unit)
        if qty <= 0:
            raise Unprocessable("계산된 수량이 0주입니다. 금액이나 비중을 늘려 주세요",
                                detail={"min_amount_krw": unit.to_integral_value(rounding=ROUND_CEILING),
                                        "min_weight_pct": q(unit / pf.seed_krw * 100, Decimal("0.0001")),
                                        "unit_cost_krw": q(unit)}, code="QUANTITY_ZERO")
        cost = q(qty * quote.price * quote.fx_rate)
        used = self.used_krw(pf.portfolio_id, exclude_item)
        remaining = pf.seed_krw - used
        if cost > remaining:
            max_qty = int((remaining / unit).to_integral_value(rounding=ROUND_FLOOR)) if remaining > 0 else 0
            raise Conflict("담은 원가 합계가 시드를 넘습니다",
                           detail={"seed_krw": pf.seed_krw, "used_krw": used, "remaining_krw": remaining,
                                   "requested_quantity": qty, "requested_cost_krw": cost,
                                   "max_quantity": max_qty, "unit_cost_krw": q(unit)}, code="SEED_EXCEEDED")
        return qty, cost

    def add_item(self, portfolio_id: int, market: str, ticker: str, mode: str, value: Decimal,
                 memo: str | None) -> PortfolioItem:
        self.get(portfolio_id)                       # 404 먼저 (환율 조회 전)
        stock = self.find_stock(market, ticker)
        quote = self.ref_quote(stock)                # 외부 호출 가능성 → 잠그기 전에 수행
        try:
            pf = self.get(portfolio_id, lock=True)
            existing = self.db.execute(select(PortfolioItem.item_id).where(
                PortfolioItem.portfolio_id == portfolio_id, PortfolioItem.stock_id == stock.stock_id)).scalar()
            if existing:
                raise Conflict("이미 담은 종목입니다. 수량을 바꾸려면 수정(PUT)을 사용하세요",
                               detail={"item_id": existing,
                                       "hint": f"PUT /api/v1/portfolios/{portfolio_id}/items/{existing}"},
                               code="DUPLICATE_ITEM")
            qty, _ = self._check_and_quantity(pf, quote, mode, value)
            item = PortfolioItem(portfolio_id=portfolio_id, stock_id=stock.stock_id, quantity=qty,
                                 ref_price=quote.price, ref_fx_rate=quote.fx_rate, ref_date=quote.price_date,
                                 memo=memo)
            self.db.add(item)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(item)
        return item

    def get_item(self, portfolio_id: int, item_id: int) -> PortfolioItem:
        item = self.db.get(PortfolioItem, item_id)
        if item is None or item.portfolio_id != portfolio_id:
            raise NotFound(f"포트폴리오(ID {portfolio_id})에 항목(ID {item_id})이 없습니다", code="ITEM_NOT_FOUND")
        return item

    def update_item(self, portfolio_id: int, item_id: int, mode: str, value: Decimal, memo: str | None) -> PortfolioItem:
        """수정 시 기준가·환율도 현재값으로 갱신한다(명세)."""
        self.get(portfolio_id)
        item = self.get_item(portfolio_id, item_id)
        quote = self.ref_quote(item.stock)
        try:
            pf = self.get(portfolio_id, lock=True)
            qty, _ = self._check_and_quantity(pf, quote, mode, value, exclude_item=item_id)
            item.quantity, item.ref_price, item.ref_fx_rate, item.ref_date = qty, quote.price, quote.fx_rate, quote.price_date
            if memo is not None:
                item.memo = memo
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(item)
        return item

    def delete_item(self, portfolio_id: int, item_id: int) -> None:
        item = self.get_item(portfolio_id, item_id)
        self.db.delete(item)
        self.db.commit()

    # ------------------------------------------------------------ 평가·요약
    def valued_items(self, portfolio_id: int) -> tuple[list[dict], FxQuote | None]:
        rows = self.db.execute(sql("portfolio_items_valued"), {"pid": portfolio_id}).mappings().all()
        fx = self.fx.get_current_rate() if any(r["currency"] == "USD" for r in rows) else None
        out = []
        for r in rows:
            fx_now = fx.usd_krw if r["currency"] == "USD" else Decimal(1)
            qty, ref_p, ref_fx, cost = r["quantity"], r["ref_price"], r["ref_fx_rate"], r["cost_krw"]
            close = r["close"]
            value = q(qty * close * fx_now, WON) if close is not None else None
            pnl = value - cost if value is not None else None
            local_ret = close / ref_p - 1 if close is not None else None
            out.append({
                **{k: r[k] for k in ("item_id", "stock_id", "market", "ticker", "name", "currency", "country",
                                     "quantity", "ref_price", "ref_fx_rate", "ref_date", "memo", "score")},
                "cost_krw": cost,
                "current_price": close, "price_date": r["trade_date"], "current_fx_rate": fx_now,
                "value_krw": value, "pnl_krw": q(pnl, WON) if pnl is not None else None,
                "pnl_rate": q(pnl / cost, Decimal("0.000001")) if pnl is not None else None,
                # 환 효과 분리: 원화 손익 = 가격 효과(기준 환율로 환산) + 환율 효과(현재가 × 환율 변화)
                "local_return": q(local_ret, Decimal("0.000001")) if local_ret is not None else None,
                "fx_return": q(fx_now / ref_fx - 1, Decimal("0.000001")),
                "price_effect_krw": q(qty * (close - ref_p) * ref_fx, WON) if close is not None else None,
                "fx_effect_krw": q(qty * close * (fx_now - ref_fx), WON) if close is not None else None,
                "groups": r["groups"] or [],
            })
        return out, fx

    def summary(self, portfolio_id: int) -> dict:
        pf = self.get(portfolio_id)
        items, fx = self.valued_items(portfolio_id)
        seed = pf.seed_krw
        used = sum((i["cost_krw"] for i in items), Decimal(0))
        remaining = seed - used

        def ratio(a: Decimal, b: Decimal) -> Decimal | None:
            return q(a / b, Decimal("0.000001")) if b else None

        for i in items:
            i["weight"] = ratio(i["cost_krw"], used)
        by_market: dict[str, Decimal] = {}
        by_group: dict[str, Decimal] = {}
        for i in items:
            by_market[i["country"]] = by_market.get(i["country"], Decimal(0)) + i["cost_krw"]
            for g in i["groups"]:                  # 여러 그룹 소속이면 각 그룹에 모두 반영
                by_group[g] = by_group.get(g, Decimal(0)) + i["cost_krw"]
        scored = [i for i in items if i["score"] is not None]
        scored_cost = sum((i["cost_krw"] for i in scored), Decimal(0))
        valued = [i for i in items if i["value_krw"] is not None]
        total_value = sum((i["value_krw"] for i in valued), Decimal(0))
        valued_cost = sum((i["cost_krw"] for i in valued), Decimal(0))
        total_pnl = total_value - valued_cost
        return {
            "portfolio_id": pf.portfolio_id, "name": pf.name, "currency": "KRW",
            "seed_krw": seed, "used_krw": used, "remaining_krw": remaining, "usage_rate": ratio(used, seed),
            "items": items,
            "market_weights": [{"country": k, "cost_krw": v, "weight": ratio(v, used)} for k, v in sorted(by_market.items())],
            "group_weights": [{"group": k, "cost_krw": v, "weight": ratio(v, used)}
                              for k, v in sorted(by_group.items(), key=lambda kv: -kv[1])],
            "weighted_score": q(sum((i["cost_krw"] * i["score"] for i in scored), Decimal(0)) / scored_cost)
                              if scored_cost else None,
            "total_value_krw": total_value, "total_pnl_krw": q(total_pnl, WON),
            "total_pnl_rate": ratio(total_pnl, valued_cost),
            "price_effect_krw": sum((i["price_effect_krw"] for i in valued), Decimal(0)),
            "fx_effect_krw": sum((i["fx_effect_krw"] for i in valued), Decimal(0)),
            "fx_rate": fx.usd_krw if fx else None, "fx_rate_at": fx.rate_at if fx else None,
            "fx_stale": fx.stale if fx else False,
            "as_of": max((i["price_date"] for i in items if i["price_date"]), default=None),
            "disclaimer": "모의 계산이며 투자 권유가 아닙니다.",
        }

    # ------------------------------------------------------------ 내부
    def _commit_unique(self, message: str, code: str) -> None:
        try:
            self.db.commit()
        except IntegrityError as e:
            self.db.rollback()
            if "unique" in str(e.orig).lower():
                raise Conflict(message, code=code) from e
            raise
