"""분석 API: 종목 수치 분석·매력도, 경쟁 그룹 비교·기준일=100 차트, DB 통계."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.stocks import RANGE_MONTHS, resolve_stock
from app.core.errors import NotFound
from app.queries import sql
from app.schemas.common import Num, Schema
from app.services.scoring import load_weights

router = APIRouter(prefix="/stocks", tags=["analysis"])
stats_router = APIRouter(prefix="/statistics", tags=["statistics"])

SCORE_DISCLAIMER = "유니버스(25종목) 안에서 같은 시장끼리 비교한 상대 평가이며 투자 권유가 아닙니다."
ACCOUNTING_NOTE = ("국내 종목 재무는 K-IFRS 연결(DART), 미국 종목은 US-GAAP(SEC)이며 PER·PBR은 각각 KRX·Yahoo 제공값입니다. "
                   "회계기준·산정 방식이 달라 국가 간 수치 비교에는 한계가 있습니다.")
PEER_METRICS = ["return_1m", "return_3m", "return_1y", "per", "pbr", "roe", "operating_margin", "revenue_yoy",
                "market_cap_krw", "score"]
METRIC_FIELDS = ["return_1w", "return_1m", "return_3m", "return_6m", "return_1y", "volatility_1y", "max_drawdown_1y",
                 "ma20", "ma60", "ma120", "ma120_gap", "high_52w", "low_52w", "position_52w", "volume",
                 "avg_volume_20d", "volume_ratio_20d", "per", "pbr", "eps", "bps", "market_cap", "market_cap_krw",
                 "operating_margin", "roe", "debt_ratio", "revenue_yoy", "operating_income_yoy"]


# ------------------------------------------------------------------ 스키마 (Swagger 문서용)
class FactorOut(Schema):
    score: Num | None
    weight: int
    available: bool


class ScoreOut(Schema):
    as_of: Any = None
    score: Num | None = None
    factors: dict[str, FactorOut] = {}
    data_quality: dict = {}
    weights_version: str | None = None


class AnalysisOut(Schema):
    market: str
    ticker: str
    currency: str
    as_of: Any
    valuation_as_of: Any
    fin_period_end: Any
    accounting_std: str | None
    fx_usd_krw: Num | None
    fx_rate_at: Any
    metrics: dict[str, Num | int | None]
    attractiveness: ScoreOut
    disclaimer: str


class PeerMember(Schema):
    stock_id: int
    ticker: str
    name: str
    market: str
    country: str
    currency: str
    is_target: bool
    accounting_std: str | None
    values: dict[str, Num | None]
    ranks: dict[str, int | None]


class PeerGroupOut(Schema):
    group_id: int
    name: str
    size: int
    has_peers: bool
    message: str | None
    averages: dict[str, Num | None]
    members: list[PeerMember]


class PeersOut(Schema):
    market: str
    ticker: str
    accounting_note: str
    rank_rule: str
    groups: list[PeerGroupOut]


class ChartSeries(Schema):
    stock_id: int
    ticker: str
    name: str
    market: str
    is_target: bool
    values: list[Num | None]


class PeersChartOut(Schema):
    market: str
    ticker: str
    group_id: int
    group_name: str
    groups: list[dict]
    range: str
    base: int = 100
    dates: list[Any]
    series: list[ChartSeries]
    note: str


# ------------------------------------------------------------------ 종목 분석
@router.get("/{market}/{ticker}/analysis", response_model=AnalysisOut,
            summary="수치 분석(v_stock_metrics) + 매력도(팩터별·data_quality)")
def analysis(market: str, ticker: str, db: Session = Depends(get_db)):
    s = resolve_stock(db, market, ticker)
    row = db.execute(sql("analysis"), {"stock_id": s["stock_id"]}).mappings().first()
    if row is None:
        raise NotFound("시세가 없어 분석할 수 없습니다", code="NO_PRICE")
    w = load_weights()
    weights = {"valuation": w["w_val"], "growth": w["w_gro"], "profitability": w["w_pro"], "momentum": w["w_mom"]}
    factors = {k: {"score": row[f"{k}_score"], "weight": v, "available": row[f"{k}_score"] is not None}
               for k, v in weights.items()}
    return {
        "market": s["market"], "ticker": s["ticker"], "currency": s["currency"], "as_of": row["as_of"],
        "valuation_as_of": row["valuation_as_of"], "fin_period_end": row["fin_period_end"],
        "accounting_std": row["accounting_std"], "fx_usd_krw": row["fx_usd_krw"], "fx_rate_at": row["fx_rate_at"],
        "metrics": {k: row[k] for k in METRIC_FIELDS},
        "attractiveness": {"as_of": row["score_as_of"], "score": row["score"],
                           "factors": factors if row["score_as_of"] else {},
                           "data_quality": row["data_quality"] or {}, "weights_version": row["weights_version"]},
        "disclaimer": SCORE_DISCLAIMER,
    }


# ------------------------------------------------------------------ 경쟁 비교
@router.get("/{market}/{ticker}/peers", response_model=PeersOut,
            summary="경쟁 그룹별 비교 표 (그룹 내 RANK·AVG, 구성원 1명 그룹은 비교 대상 없음)")
def peers(market: str, ticker: str, db: Session = Depends(get_db)):
    s = resolve_stock(db, market, ticker)
    rows = db.execute(sql("peers"), {"stock_id": s["stock_id"]}).mappings().all()
    groups: dict[int, dict] = {}
    for r in rows:
        g = groups.setdefault(r["group_id"], {
            "group_id": r["group_id"], "name": r["group_name"], "size": r["group_size"],
            "has_peers": r["group_size"] > 1,
            "message": None if r["group_size"] > 1 else "이 그룹에는 비교할 경쟁 종목이 없습니다",
            "averages": {m: r[f"{m}_avg"] for m in PEER_METRICS}, "members": []})
        g["members"].append({
            **{k: r[k] for k in ("stock_id", "ticker", "name", "market", "country", "currency", "is_target",
                                 "accounting_std")},
            "values": {m: r[m] for m in PEER_METRICS},
            "ranks": {m: r[f"{m}_rank"] for m in PEER_METRICS}})
    return {"market": s["market"], "ticker": s["ticker"], "accounting_note": ACCOUNTING_NOTE,
            "rank_rule": "값이 있는 구성원끼리 RANK. PER·PBR은 낮을수록(양수만), 나머지는 높을수록 1위",
            "groups": list(groups.values())}


@router.get("/{market}/{ticker}/peers/chart", response_model=PeersChartOut,
            summary="경쟁 그룹 기준일=100 가격 추이 (합집합 날짜 + 휴장일 null)")
def peers_chart(market: str, ticker: str, range: Literal["1m", "3m", "6m", "1y"] = "3m",
                group_id: int | None = Query(None, description="비우면 종목의 첫 번째 그룹"),
                db: Session = Depends(get_db)):
    s = resolve_stock(db, market, ticker)
    my_groups = [dict(r) for r in db.execute(sql("stock_groups"), {"stock_id": s["stock_id"]}).mappings()]
    if not my_groups:
        raise NotFound("이 종목은 경쟁 그룹에 속해 있지 않습니다", code="NO_PEER_GROUP")
    target = next((g for g in my_groups if g["group_id"] == group_id), None) if group_id else my_groups[0]
    if target is None:
        raise NotFound(f"이 종목은 그룹(ID {group_id})에 속해 있지 않습니다", code="GROUP_NOT_FOUND")
    rows = db.execute(sql("peers_chart"), {"group_id": target["group_id"],
                                           "months": RANGE_MONTHS[range]}).mappings().all()
    dates = sorted({r["trade_date"] for r in rows})
    pos = {d: i for i, d in enumerate(dates)}
    series: dict[int, dict] = {}
    for r in rows:
        sr = series.setdefault(r["stock_id"], {"stock_id": r["stock_id"], "ticker": r["ticker"], "name": r["name"],
                                               "market": r["market"], "is_target": r["stock_id"] == s["stock_id"],
                                               "values": [None] * len(dates)})
        sr["values"][pos[r["trade_date"]]] = r["indexed"]
    return {"market": s["market"], "ticker": s["ticker"], "group_id": target["group_id"],
            "group_name": target["name"], "groups": my_groups, "range": range, "dates": dates,
            "series": sorted(series.values(), key=lambda x: (not x["is_target"], x["ticker"])),
            "note": "각 종목의 구간 첫 거래일 종가 = 100. 시장별 휴장일이 달라 해당 날짜 값은 null(선 연결 표시)."}


# ------------------------------------------------------------------ 통계
@stats_router.get("/overview", summary="데이터 개요: 행 수·기간·마지막 갱신")
def stats_overview(db: Session = Depends(get_db)):
    return dict(db.execute(sql("stats_overview")).mappings().one())


@stats_router.get("/market-valuation", summary="시장별 평균 PER/PBR/ROE (HAVING 표본 수 이상)")
def stats_market_valuation(min_samples: int = Query(3, ge=1, le=25), db: Session = Depends(get_db)):
    p = {"min_samples": min_samples}
    return {"min_samples": min_samples,
            "markets": [dict(r) for r in db.execute(sql("stats_market_valuation"), p).mappings()],
            "excluded": [dict(r) for r in db.execute(sql("stats_market_excluded"), p).mappings()],
            "note": "PER·PBR은 양수만 평균. 시총 합계는 원화 환산"}


@stats_router.get("/peer-group-valuation", summary="경쟁 그룹별 평균·최고·최저 지표")
def stats_peer_group_valuation(db: Session = Depends(get_db)):
    return {"groups": [dict(r) for r in db.execute(sql("stats_peer_group_valuation")).mappings()]}


@stats_router.get("/disclosure-frequency", summary="기간별 공시 빈도 (월·분기·주)")
def stats_disclosure_frequency(period: Literal["week", "month", "quarter"] = "month",
                               days: int = Query(365, ge=7, le=1095), db: Session = Depends(get_db)):
    rows = db.execute(sql("stats_disclosure_frequency"), {"period": period, "days": days}).mappings().all()
    return {"period": period, "days": days, "items": [dict(r) for r in rows]}
