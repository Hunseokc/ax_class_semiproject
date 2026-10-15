"""분석 API: 종목 수치 분석·매력도, 경쟁 그룹 비교·기준일=100 차트, DB 통계.

TODO(껍데기): B — 엔드포인트 본문을 원본대로 교체(queries/analysis·peers·peers_chart·stock_groups·stats_*.sql,
  deps.get_preset, services.scoring의 FACTORS·METRICS·default_preset). 주소·인자·응답 모델은 원본 그대로다.
  지금은 없는 종목만 404로 막고, 나머지는 docs/06 3-3·3-6 예시 값을 돌려준다(DB의 점수를 읽지 않음 → 프리셋을 바꿔도 점수가 같다).
  이번 단계에서 뺀 것: 응답의 reference·reference_note(listed 참고 점수), metrics의 dps·dividend_yield,
  통계 monthly·ranking·data-quality(Stage 5).
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import MarketPath, TickerPath, get_db
from app.api.stocks import resolve_stock
from app.schemas.common import INT_MAX, Num, Schema
from app.services.scoring import FACTORS, METRICS, load_config

router = APIRouter(prefix="/stocks", tags=["analysis"])
stats_router = APIRouter(prefix="/statistics", tags=["statistics"])
scoring_router = APIRouter(prefix="/scoring", tags=["analysis"])

SCORE_DISCLAIMER = ("매력도는 노출 종목과 매력도 비교군 안에서 같은 시장끼리 비교한 상대적 위치를 나타내는 팩터 점수이며, "
                    "수익률 예측이나 투자 권유가 아닙니다.")
PRESET_NOTE = "공개된 일반적 투자 스타일을 단순화한 가중치이며 특정 인물의 판단이 아닙니다."
SCORE_METHOD = ("지표별로 같은 시장 안 로버스트 Z(중앙값·MAD)를 구해 ±3으로 자르고, 주 경쟁 그룹 평균을 축소 추정으로 빼 섹터 중립화한 뒤 "
                "팩터 평균 → 프리셋 가중 평균 → 시장 안에서 다시 표준화해 100·Φ(z)로 0~100 변환합니다.")
ACCOUNTING_NOTE = ("국내 종목 재무는 K-IFRS 연결(DART), 미국 종목은 US-GAAP(SEC)이며 PER·PBR은 국내 KRX 제공값, 미국은 SEC 발행주식수·FY 순이익·자본으로 계산한 값입니다. "
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


class PeerAverageOut(Schema):
    group_name: str
    size: int                         # 같은 국가 주 그룹 구성원 중 점수가 있는 종목 수(대상 포함)
    factors: dict[str, Num | None]    # 팩터 점수(Z) 평균


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
    peer_average: PeerAverageOut | None = None   # 레이더 비교용 주 그룹 평균


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


# ------------------------------------------------------------------ 껍데기 예시 값 (docs/06 3-3·3-6, 삼성전자 기준)
_EXAMPLE_METRICS = {"return_1w": -0.007273, "return_1m": 0.068493, "return_3m": -0.141509}
_EXAMPLE_FACTORS = {
    "value":    {"score": -0.0134, "weight": 0.1, "effective_weight": 0.1, "contribution": -0.0013, "available": True},
    "quality":  {"score": 0.0025, "weight": 0.2, "effective_weight": 0.2, "contribution": 0.0005, "available": True},
    "growth":   {"score": -0.1287, "weight": 0.4, "effective_weight": 0.4, "contribution": -0.0515, "available": True},
    "safety":   {"score": 0.2022, "weight": 0.05, "effective_weight": 0.05, "contribution": 0.0101, "available": True},
    "momentum": {"score": 2.1149, "weight": 0.25, "effective_weight": 0.25, "contribution": 0.5287, "available": True},
}
_EXAMPLE_METRIC_VALUES = {"earnings_yield": (0.024194139194139194, -0.0649, 0.1315),
                          "book_yield": (0.23442124542124543, -0.3197, -0.1582)}
_EXAMPLE_PEER_MEMBERS = [
    {"stock_id": 21, "ticker": "NVDA", "name": "NVIDIA", "market": "NASDAQ", "country": "US", "currency": "USD",
     "is_target": False, "accounting_std": "US-GAAP",
     "values": {"return_1m": 0.038233, "return_3m": 0.227569, "return_1y": 0.276369, "per": 30.2023, "pbr": 25.1924,
                "roe": 0.763333, "operating_margin": 0.603817, "revenue_yoy": 0.654735,
                "market_cap_krw": 7724774625367818, "score": 68.44},
     "ranks": {"return_1m": 4, "return_3m": 1, "return_1y": 4, "per": 2, "pbr": 5, "roe": 1, "operating_margin": 1,
               "revenue_yoy": 1, "market_cap_krw": 1, "score": 1}},
    {"stock_id": 24, "ticker": "AVGO", "name": "Broadcom", "market": "NASDAQ", "country": "US", "currency": "USD",
     "is_target": False, "accounting_std": "US-GAAP",
     "values": {"return_1m": 0.014725, "return_3m": 0.007547, "return_1y": 0.079308, "per": 46.2976, "pbr": 17.3599,
                "roe": 0.284481, "operating_margin": 0.398892, "revenue_yoy": 0.238744,
                "market_cap_krw": 2317262804153795, "score": 44.38},
     "ranks": {"return_1m": 5, "return_3m": 3, "return_1y": 5, "per": 4, "pbr": 4, "roe": 3, "operating_margin": 3,
               "revenue_yoy": 4, "market_cap_krw": 2, "score": 5}},
]
_EXAMPLE_PEER_AVERAGES = {"return_1m": 0.105495, "return_3m": 0.015009, "return_1y": 1.75406, "per": 61.4841,
                          "pbr": 14.4919, "roe": 0.315413, "operating_margin": 0.345195, "revenue_yoy": 0.362657,
                          "market_cap_krw": 2861680590488512, "score": 56.39}


def _preset_ref(code: str | None) -> dict:
    """요청한 프리셋의 이름표만 맞춘다(점수는 예시 그대로). 없는 code는 기본 프리셋 — 422는 B의 get_preset."""
    presets = {p["code"]: p for p in load_config()["presets"]}
    p = presets.get(code or "") or presets[load_config()["default_preset"]]
    return {k: p[k] for k in ("code", "name", "description")}


# ------------------------------------------------------------------ 종목 분석
@router.get("/{market}/{ticker}/analysis", response_model=AnalysisOut,
            summary="수치 분석(v_stock_metrics) + 매력도(프리셋별 점수·팩터 기여도·지표 원값/Z·국가 내 순위)")
def analysis(market: MarketPath, ticker: TickerPath,
             preset: str | None = Query(None, description="aggressive·growth·balanced·value, 비우면 기본 프리셋"),
             db: Session = Depends(get_db)):
    s = resolve_stock(db, market, ticker)
    metrics = [{"metric": k, "label": d.label, "factor": d.factor, "direction": d.direction,
                **dict(zip(("raw_value", "z_raw", "z_adj"), _EXAMPLE_METRIC_VALUES.get(k, (None, None, None))))}
               for k, d in METRICS.items()]
    return {
        "market": s["market"], "ticker": s["ticker"], "currency": s["currency"], "as_of": "2026-10-06",
        "valuation_as_of": "2026-10-07", "fin_period_end": "2025-12-31", "accounting_std": "K-IFRS",
        "fx_usd_krw": 1339.83, "fx_rate_at": "2026-10-07T02:18:55.125990Z",
        "metrics": {k: _EXAMPLE_METRICS.get(k) for k in METRIC_FIELDS},
        "attractiveness": {"as_of": "2026-10-07", "preset": _preset_ref(preset), "score": 73.13, "composite": 0.4865,
                           "factor_coverage": 5, "rank": {"country": "KR", "position": 5, "total": 16, "percentile": 73.3},
                           "factors": _EXAMPLE_FACTORS, "metrics": metrics, "data_quality": {"partition": "KR"}},
        "disclaimer": SCORE_DISCLAIMER,
    }


@scoring_router.get("/presets", response_model=PresetsOut, summary="투자 성향 프리셋(sort_order 순)과 팩터별 가중치")
def presets():
    cfg = load_config()
    return {"note": PRESET_NOTE, "presets": [
        {**{k: p[k] for k in ("code", "name", "description", "sort_order")},
         "is_default": p["code"] == cfg["default_preset"], "weights": {f: p["weights"][f] for f in FACTORS}}
        for p in sorted(cfg["presets"], key=lambda p: p["sort_order"])]}


# ------------------------------------------------------------------ 경쟁 비교
@router.get("/{market}/{ticker}/peers", response_model=PeersOut,
            summary="경쟁 그룹별 비교 표 (그룹 내 RANK·AVG, 구성원 1명 그룹은 비교 대상 없음)")
def peers(market: MarketPath, ticker: TickerPath, db: Session = Depends(get_db)):
    s = resolve_stock(db, market, ticker)
    return {"market": s["market"], "ticker": s["ticker"], "accounting_note": ACCOUNTING_NOTE,
            "rank_rule": "값이 있는 구성원끼리 RANK. PER·PBR은 낮을수록(양수만), 나머지는 높을수록 1위",
            "groups": [{"group_id": 1, "name": "반도체", "size": 5, "has_peers": True, "message": None,
                        "averages": _EXAMPLE_PEER_AVERAGES, "members": _EXAMPLE_PEER_MEMBERS}]}


@router.get("/{market}/{ticker}/peers/chart", response_model=PeersChartOut,
            summary="경쟁 그룹 기준일=100 가격 추이 (합집합 날짜 + 휴장일 null)")
def peers_chart(market: MarketPath, ticker: TickerPath, range: Literal["1m", "3m", "6m", "1y"] = "3m",
                group_id: int | None = Query(None, ge=1, le=INT_MAX, description="비우면 종목의 첫 번째 그룹"),
                db: Session = Depends(get_db)):
    s = resolve_stock(db, market, ticker)
    return {"market": s["market"], "ticker": s["ticker"], "group_id": 1, "group_name": "반도체",
            "groups": [{"group_id": 1, "name": "반도체", "size": 5}], "range": range,
            "dates": ["2026-09-07", "2026-09-08", "2026-09-09"],
            "series": [
                {"stock_id": 1, "ticker": "005930", "name": "삼성전자", "market": "KOSPI", "is_target": True,
                 "values": [100, 99.8148, 99.8148]},
                {"stock_id": 2, "ticker": "000660", "name": "SK하이닉스", "market": "KOSPI", "is_target": False,
                 "values": [100, 100.5609, 104.0942]},
                {"stock_id": 25, "ticker": "AMD", "name": "AMD", "market": "NASDAQ", "is_target": False,
                 "values": [None, 100, 103.0371]},
            ],
            "note": "각 종목의 구간 첫 거래일 종가 = 100. 시장별 휴장일이 달라 해당 날짜 값은 null(선 연결 표시)."}


# ------------------------------------------------------------------ 통계
@stats_router.get("/overview", summary="데이터 개요: 행 수·기간·마지막 갱신")
def stats_overview():
    return {"stocks": 25, "peer_groups": 8, "daily_prices": 12276, "price_from": "2024-10-07", "price_to": "2026-10-06",
            "index_daily_prices": 2472, "fx_daily": 517, "fx_snapshots": 1, "valuation_snapshots": 3881,
            "financial_fy": 125, "disclosures": 1349, "stock_scores": 25, "scores_as_of": "2026-10-06",
            "last_refreshed_at": "2026-10-06T12:45:18.945590+00:00", "failed_jobs": 1}


@stats_router.get("/market-valuation", summary="시장별 평균 PER/PBR/ROE (HAVING 표본 수 이상)")
def stats_market_valuation(min_samples: int = Query(3, ge=1, le=25)):
    return {"min_samples": min_samples,
            "markets": [
                {"market": "NASDAQ", "country": "US", "currency": "USD", "stocks": 9, "per_samples": 9, "avg_per": 80.1,
                 "min_per": 17.38, "max_per": 350.68, "avg_pbr": 16.46, "avg_roe": 0.4189,
                 "total_market_cap_krw": 36989834635994727},
                {"market": "KOSPI", "country": "KR", "currency": "KRW", "stocks": 15, "per_samples": 12, "avg_per": 31.38,
                 "min_per": 5.81, "max_per": 67.75, "avg_pbr": 3.51, "avg_roe": 0.1003,
                 "total_market_cap_krw": 3391496760067950}],
            "excluded": [{"market": "KOSDAQ", "stocks": 1}],
            "note": "PER·PBR은 양수만 평균. 시총 합계는 원화 환산"}


@stats_router.get("/peer-group-valuation", summary="경쟁 그룹별 평균·최고·최저 지표")
def stats_peer_group_valuation():
    return {"groups": [
        {"group_id": 4, "group_name": "빅테크", "members": 3, "kr_members": 0, "us_members": 3, "avg_per": 29.08,
         "min_per": 20.23, "max_per": 38.18, "avg_pbr": 19.65, "avg_roe": 0.6701, "min_roe": 0.1889, "max_roe": 1.5191,
         "avg_operating_margin": 0.2997, "avg_revenue_yoy": 0.122, "avg_return_1y": 0.1546, "min_return_1y": 0.0235,
         "max_return_1y": 0.2949, "total_market_cap_krw": 15358824734219305}]}


@stats_router.get("/disclosure-frequency", summary="기간별 공시 빈도 (월·분기·주)")
def stats_disclosure_frequency(period: Literal["week", "month", "quarter"] = "month",
                               days: int = Query(365, ge=7, le=1095)):
    return {"period": period, "days": days, "items": [
        {"period_start": "2025-10-01", "total": 277, "dart": 245, "sec": 32, "periodic_reports": 25, "share": 0.2055,
         "cumulative": 277},
        {"period_start": "2026-01-01", "total": 416, "dart": 375, "sec": 41, "periodic_reports": 25, "share": 0.3086,
         "cumulative": 693}]}
