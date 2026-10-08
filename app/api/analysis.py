"""분석 API: 종목 수치 분석·매력도, 경쟁 그룹 비교·기준일=100 차트, DB 통계."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import MarketPath, TickerPath, get_db, get_preset
from app.api.stocks import RANGE_MONTHS, resolve_stock
from app.core.errors import NotFound, Unprocessable
from app.queries import sql
from app.schemas.common import INT_MAX, MARKET_PATTERN, TICKER_PATTERN, Num, Schema
from app.services.scoring import FACTORS, METRICS, default_preset

router = APIRouter(prefix="/stocks", tags=["analysis"])
stats_router = APIRouter(prefix="/statistics", tags=["statistics"])
scoring_router = APIRouter(prefix="/scoring", tags=["analysis"])

SCORE_DISCLAIMER = ("매력도는 유니버스(25종목) 안에서 같은 시장끼리 비교한 상대적 위치를 나타내는 팩터 점수이며, "
                    "수익률 예측이나 투자 권유가 아닙니다.")
PRESET_NOTE = "공개된 일반적 투자 스타일을 단순화한 가중치이며 특정 인물의 판단이 아닙니다."
SCORE_METHOD = ("지표별로 같은 시장 안 로버스트 Z(중앙값·MAD)를 구해 ±3으로 자르고, 주 경쟁 그룹 평균을 축소 추정으로 빼 섹터 중립화한 뒤 "
                "팩터 평균 → 프리셋 가중 평균 → 시장 안에서 다시 표준화해 100·Φ(z)로 0~100 변환합니다.")
ACCOUNTING_NOTE = ("국내 종목 재무는 K-IFRS 연결(DART), 미국 종목은 US-GAAP(SEC)이며 PER·PBR은 각각 KRX·Yahoo 제공값입니다. "
                   "회계기준·산정 방식이 달라 국가 간 수치 비교에는 한계가 있습니다.")
PEER_METRICS = ["return_1m", "return_3m", "return_1y", "per", "pbr", "roe", "operating_margin", "revenue_yoy",
                "market_cap_krw", "score"]
METRIC_FIELDS = ["return_1w", "return_1m", "return_3m", "return_6m", "return_1y", "volatility_1y", "max_drawdown_1y",
                 "ma20", "ma60", "ma120", "ma120_gap", "high_52w", "low_52w", "position_52w", "volume",
                 "avg_volume_20d", "volume_ratio_20d", "per", "pbr", "eps", "bps", "market_cap", "market_cap_krw",
                 "operating_margin", "roe", "debt_ratio", "revenue_yoy", "operating_income_yoy"]


# ------------------------------------------------------------------ 스키마 (Swagger 문서용)
class PresetRef(Schema):
    code: str
    name: str
    description: str | None


class FactorOut(Schema):
    score: Num | None                 # 유효 지표 z_adj 평균 (Z 단위)
    weight: Num                       # 프리셋 가중치
    effective_weight: Num | None      # 유효 팩터만으로 재정규화한 가중치
    contribution: Num | None          # effective_weight × score (합 = composite)
    available: bool


class MetricOut(Schema):
    metric: str
    label: str
    factor: str
    direction: int
    raw_value: Num | None
    z_raw: Num | None
    z_adj: Num | None


class RankOut(Schema):
    country: str
    position: int
    total: int
    percentile: Num


class ScoreOut(Schema):
    as_of: Any = None
    preset: PresetRef
    score: Num | None = None
    composite: Num | None = None
    factor_coverage: int = 0
    factor_total: int = len(FACTORS)
    rank: RankOut | None = None
    factors: dict[str, FactorOut] = {}
    metrics: list[MetricOut] = []
    data_quality: dict = {}
    method: str = SCORE_METHOD


class PresetOut(PresetRef):
    sort_order: int
    is_default: bool
    weights: dict[str, Num]


class PresetsOut(Schema):
    note: str
    presets: list[PresetOut]


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
def _attractiveness(db: Session, stock_id: int, country: str, preset: dict, row) -> dict:
    out = {"preset": {k: preset[k] for k in ("code", "name", "description")}}
    if row["score_as_of"] is None:
        return out
    weights = dict(db.execute(text("SELECT factor, weight FROM scoring_weights WHERE preset_id = :p"),
                              {"p": preset["preset_id"]}).all())
    scores = {f: row[f"{f}_score"] for f in FACTORS}
    valid_w = sum((weights[f] for f in FACTORS if scores[f] is not None), Decimal(0))
    use = row["composite"] is not None and valid_w > 0
    factors = {}
    for f in FACTORS:
        ew = (weights[f] / valid_w).quantize(Decimal("0.0001")) if use and scores[f] is not None else None
        factors[f] = {"score": scores[f], "weight": weights[f], "effective_weight": ew,
                      "contribution": (weights[f] / valid_w * scores[f]).quantize(Decimal("0.0001")) if ew is not None else None,
                      "available": scores[f] is not None}
    mv = db.execute(text("SELECT metric, raw_value, z_raw, z_adj FROM stock_metric_values WHERE stock_id = :s AND as_of = :d"),
                    {"s": stock_id, "d": row["score_as_of"]}).mappings().all()
    by_metric = {m["metric"]: m for m in mv}
    metrics = [{"metric": k, "label": d.label, "factor": d.factor, "direction": d.direction,
                **{c: by_metric[k][c] if k in by_metric else None for c in ("raw_value", "z_raw", "z_adj")}}
               for k, d in METRICS.items()]
    rank = ({"country": country, "position": row["rank_position"], "total": row["rank_total"],
             "percentile": row["percentile"]} if row["rank_position"] is not None else None)
    return {**out, "as_of": row["score_as_of"], "score": row["score"], "composite": row["composite"],
            "factor_coverage": row["factor_coverage"], "rank": rank, "factors": factors, "metrics": metrics,
            "data_quality": row["data_quality"] or {}}


@router.get("/{market}/{ticker}/analysis", response_model=AnalysisOut,
            summary="수치 분석(v_stock_metrics) + 매력도(프리셋별 점수·팩터 기여도·지표 원값/Z·국가 내 순위)")
def analysis(market: MarketPath, ticker: TickerPath, preset: dict = Depends(get_preset), db: Session = Depends(get_db)):
    s = resolve_stock(db, market, ticker)
    row = db.execute(sql("analysis"), {"stock_id": s["stock_id"], "preset_id": preset["preset_id"]}).mappings().first()
    if row is None:
        raise NotFound("시세가 없어 분석할 수 없습니다", code="NO_PRICE")
    return {
        "market": s["market"], "ticker": s["ticker"], "currency": s["currency"], "as_of": row["as_of"],
        "valuation_as_of": row["valuation_as_of"], "fin_period_end": row["fin_period_end"],
        "accounting_std": row["accounting_std"], "fx_usd_krw": row["fx_usd_krw"], "fx_rate_at": row["fx_rate_at"],
        "metrics": {k: row[k] for k in METRIC_FIELDS},
        "attractiveness": _attractiveness(db, s["stock_id"], s["country"], preset, row),
        "disclaimer": SCORE_DISCLAIMER,
    }


@scoring_router.get("/presets", response_model=PresetsOut, summary="투자 성향 프리셋(sort_order 순)과 팩터별 가중치")
def presets(db: Session = Depends(get_db)):
    rows = db.execute(text("""SELECT p.preset_id, p.code, p.name, p.description, p.sort_order, w.factor, w.weight
                              FROM scoring_presets p JOIN scoring_weights w ON w.preset_id = p.preset_id
                              ORDER BY p.sort_order, p.preset_id""")).mappings().all()
    out: dict[int, dict] = {}
    for r in rows:
        p = out.setdefault(r["preset_id"], {"code": r["code"], "name": r["name"], "description": r["description"],
                                            "sort_order": r["sort_order"],
                                            "is_default": r["code"] == default_preset(), "weights": {}})
        p["weights"][r["factor"]] = r["weight"]
    for p in out.values():
        p["weights"] = {f: p["weights"][f] for f in FACTORS}
    return {"note": PRESET_NOTE, "presets": list(out.values())}


# ------------------------------------------------------------------ 경쟁 비교
@router.get("/{market}/{ticker}/peers", response_model=PeersOut,
            summary="경쟁 그룹별 비교 표 (그룹 내 RANK·AVG, 구성원 1명 그룹은 비교 대상 없음)")
def peers(market: MarketPath, ticker: TickerPath, db: Session = Depends(get_db)):
    s = resolve_stock(db, market, ticker)
    rows = db.execute(sql("peers"), {"stock_id": s["stock_id"], "preset": default_preset()}).mappings().all()
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
def peers_chart(market: MarketPath, ticker: TickerPath, range: Literal["1m", "3m", "6m", "1y"] = "3m",
                group_id: int | None = Query(None, ge=1, le=INT_MAX, description="비우면 종목의 첫 번째 그룹"),
                db: Session = Depends(get_db)):
    s = resolve_stock(db, market, ticker)
    my_groups = [dict(r) for r in db.execute(sql("stock_groups"), {"stock_id": s["stock_id"]}).mappings()]
    if not my_groups:
        raise NotFound("이 종목은 경쟁 그룹에 속해 있지 않습니다", code="NO_PEER_GROUP")
    target = next((g for g in my_groups if g["group_id"] == group_id), None) if group_id else my_groups[0]
    if target is None:
        raise NotFound(f"이 종목은 그룹(ID {group_id})에 속해 있지 않습니다", code="GROUP_NOT_FOUND")
    rows = db.execute(sql("peers_chart"), {"group_id": target["group_id"], "stock_id": s["stock_id"],
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


class MonthlyItem(Schema):
    month: str                       # YYYY-MM
    trading_days: int
    first_date: date
    last_date: date
    avg_close: Num
    max_high: Num
    min_low: Num
    first_close: Num
    last_close: Num
    monthly_return: Num | None       # 월초(첫 거래일) 종가 대비 월말(마지막 거래일) 종가
    total_volume: int
    avg_volume: int
    is_partial: bool                 # 아직 끝나지 않은 달


class MonthlyOut(Schema):
    market: str
    ticker: str
    name: str
    currency: str
    months: int
    today: date                      # 시장 현지 날짜(이 달이 is_partial)
    items: list[MonthlyItem]


@stats_router.get("/monthly", response_model=MonthlyOut,
                  summary="종목 월별 집계: 거래일 수·평균 종가·최고/최저·월초 대비 월말 수익률·거래량 (진행 중인 달은 is_partial)")
def stats_monthly(market: str = Query(pattern=MARKET_PATTERN, examples=["KOSPI"]),
                  ticker: str = Query(pattern=TICKER_PATTERN, examples=["005930"]),
                  months: int = Query(12, ge=1, le=24, description="이번 달 포함 최근 N개월"),
                  db: Session = Depends(get_db)):
    s = resolve_stock(db, market, ticker)
    tz = db.execute(text("SELECT timezone FROM markets WHERE code = :m"), {"m": s["market"]}).scalar_one()
    today = datetime.now(ZoneInfo(tz)).date()
    rows = db.execute(sql("stats_monthly"), {"stock_id": s["stock_id"], "today": today, "months": months}).mappings().all()
    return {"market": s["market"], "ticker": s["ticker"], "name": s["name"], "currency": s["currency"],
            "months": months, "today": today, "items": [dict(r) for r in rows]}


RankingMetric = Literal["return_1m", "return_3m", "return_1y", "volume", "market_cap_krw"]


class RankingItem(Schema):
    rank: int
    stock_id: int
    market: str
    country: str
    currency: str
    ticker: str
    name: str
    value: Num                       # 수익률은 소수(0.05 = 5%), 거래량은 주, 시총은 원화 환산
    as_of: date


class RankingOut(Schema):
    metric: str
    country: str | None
    order: str
    limit: int
    total: int                       # 지표값이 있는 종목 수(순위 대상)
    items: list[RankingItem]


@stats_router.get("/ranking", response_model=RankingOut,
                  summary="지표별 TOP N 랭킹 (노출 종목, RANK() — 같은 값은 같은 순위, 지표값 없는 종목 제외)")
def stats_ranking(metric: RankingMetric = Query(description="return_1m·return_3m·return_1y·volume·market_cap_krw"),
                  country: Literal["KR", "US"] | None = Query(None, description="비우면 전체 (volume은 시장 지정 필수)"),
                  order: Literal["desc", "asc"] = "desc",
                  limit: int = Query(10, ge=1, le=50),
                  db: Session = Depends(get_db)):
    if metric == "volume" and country is None:
        raise Unprocessable("시장마다 거래량 단위가 달라 '전체'에서는 거래량 순위를 낼 수 없습니다. country를 지정하세요",
                            detail={"allowed_metrics_for_all": ["return_1m", "return_3m", "return_1y", "market_cap_krw"]},
                            code="VOLUME_SORT_REQUIRES_MARKET")
    rows = db.execute(sql("stats_ranking"), {"metric": metric, "country": country, "order_dir": order,
                                             "limit": limit}).mappings().all()
    return {"metric": metric, "country": country, "order": order, "limit": limit,
            "total": rows[0]["total"] if rows else 0, "items": [dict(r) for r in rows]}


@stats_router.get("/disclosure-frequency", summary="기간별 공시 빈도 (월·분기·주)")
def stats_disclosure_frequency(period: Literal["week", "month", "quarter"] = "month",
                               days: int = Query(365, ge=7, le=1095), db: Session = Depends(get_db)):
    rows = db.execute(sql("stats_disclosure_frequency"), {"period": period, "days": days}).mappings().all()
    return {"period": period, "days": days, "items": [dict(r) for r in rows]}
