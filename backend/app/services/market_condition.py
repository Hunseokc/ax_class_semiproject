"""시장·섹터 점수 — 종목 상세 '투자 매력도' 카드의 위험 표시(0~100). 매력도와 별개이며 투자 권유가 아니다.

  시장       그 국가 시장 심리 지수 최신 저장값(market_sentiment_daily) — 계산·저장은 홈·4시간 갱신이 한다
  섹터 흐름   같은 stocks.sector 표본 종목의 5거래일 수익률 중앙값 → clamp(50 + r × 100 × 5)
  점수       0.7 × 시장 + 0.3 × 섹터 흐름 (섹터가 없거나 표본 5개 미만이면 시장만)
외부 호출·DB 쓰기가 없다. 정의는 개발산출물/09 '시장·섹터 점수' 절.
"""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Connection, Engine, text

from app.queries import sql
from app.services import sentiment
from app.services.market_calendar import last_closed_session, sessions_between

log = logging.getLogger(__name__)

MARKET_WEIGHT = Decimal("0.7")
SECTOR_WEIGHT = Decimal("0.3")
SECTOR_DAYS = 5                    # 수익률 기간(거래일) — sector_flow.sql의 rn = 6과 짝
SECTOR_SCALE = 5                   # 시장 심리 이동평균 괴리 점수와 같은 배율 → 50이 중립
MIN_SECTOR_SAMPLE = 5
MAX_SENTIMENT_LAG = 5              # 거래일 — 이보다 오래된 시장 심리는 쓰지 않는다
CALENDAR_LAG_DAYS = 7              # 거래소 달력을 못 쓸 때의 달력일 기준
CACHE_TTL = timedelta(hours=1)
BAND_LABELS = ("매우 낮음", "낮음", "보통", "높음", "매우 높음")   # frontend/js/components/charts.js BANDS와 같아야 한다
INSUFFICIENT = sentiment.INSUFFICIENT   # "데이터 부족"

STOCK_R5 = text("""
    SELECT MAX(x.close) FILTER (WHERE x.rn = 1) / NULLIF(MAX(x.close) FILTER (WHERE x.rn = 6), 0) - 1
    FROM (SELECT d.trade_date, d.close, ROW_NUMBER() OVER (ORDER BY d.trade_date DESC) AS rn
          FROM daily_prices d WHERE d.stock_id = :s AND d.trade_date <= :d) x
    WHERE x.rn <= 6
    HAVING MAX(x.trade_date) FILTER (WHERE x.rn = 1) = :d AND COUNT(*) FILTER (WHERE x.rn = 6) = 1""")

INDEX_R5 = text("""
    SELECT MAX(x.close) FILTER (WHERE x.rn = 1) / NULLIF(MAX(x.close) FILTER (WHERE x.rn = 6), 0) - 1
    FROM (SELECT p.trade_date, p.close, ROW_NUMBER() OVER (ORDER BY p.trade_date DESC) AS rn
          FROM index_daily_prices p JOIN indices i ON i.index_id = p.index_id
          WHERE i.code = :c AND p.trade_date <= :d) x
    WHERE x.rn <= 6
    HAVING MAX(x.trade_date) FILTER (WHERE x.rn = 1) = :d AND COUNT(*) FILTER (WHERE x.rn = 6) = 1""")

INDEX_LATEST = text("""SELECT MAX(p.trade_date) FROM index_daily_prices p JOIN indices i ON i.index_id = p.index_id
                       WHERE i.code = :c""")

_cache: dict[tuple[str, str, date], tuple[datetime, tuple[Decimal | None, int, date | None]]] = {}
_cache_lock = threading.Lock()


def _q(x, places: str) -> Decimal | None:
    return None if x is None else Decimal(str(x)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def band_label(score: int | None) -> str:
    """None → "데이터 부족", 0~19 매우 낮음, 20~39 낮음, 40~59 보통, 60~79 높음, 80~100 매우 높음."""
    return INSUFFICIENT if score is None else BAND_LABELS[min(4, max(0, score) // 20)]


def sector_flow_score(r: Decimal | float | None) -> Decimal | None:
    """5거래일 수익률 → 0~100. clamp(50 + r × 100 × 5), 소수 둘째 자리 HALF_UP. None → None."""
    if r is None:
        return None
    v = Decimal(50) + Decimal(str(r)) * 100 * SECTOR_SCALE
    return _q(min(Decimal(100), max(Decimal(0), v)), "0.01")


def compute_condition(sentiment_score: Decimal | float | None, sector_r: Decimal | float | None) -> dict:
    """순수 계산. 반환 {"score": int | None, "label": str, "sector_flow": Decimal | None}.
    sentiment_score None → score None·"데이터 부족"(sector_flow는 그대로 계산). sector_r None → 시장만."""
    flow = sector_flow_score(sector_r)
    if sentiment_score is None:
        return {"score": None, "label": INSUFFICIENT, "sector_flow": flow}
    s = Decimal(str(sentiment_score))
    raw = s if flow is None else MARKET_WEIGHT * s + SECTOR_WEIGHT * flow
    score = int(raw.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return {"score": score, "label": band_label(score), "sector_flow": flow}


def read_sector_flow(conn: Connection, country: str, sector: str, as_of: date) -> tuple[Decimal | None, int, date | None]:
    """sector_flow.sql 실행(캐시 없음). 반환 (sector_r5 — 소수 여섯째 자리 HALF_UP, n, ref_date)."""
    r = conn.execute(sql("sector_flow"), {"country": country, "sector": sector, "as_of": as_of,
                                          "min_n": MIN_SECTOR_SAMPLE}).mappings().one()
    return _q(r["sector_r5"], "0.000001"), int(r["n"]), r["ref_date"]


def _cached_sector_flow(conn: Connection, country: str, sector: str, base: date, now: datetime):
    key = (country, sector, base)
    with _cache_lock:
        hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]
    value = read_sector_flow(conn, country, sector, base)
    if value[1] >= MIN_SECTOR_SAMPLE:              # 표본이 모자란 결과는 저장하지 않는다(07:00 일봉이 들어오면 채워짐)
        with _cache_lock:
            _cache[key] = (now, value)
    return value


def clear_cache() -> None:
    """섹터 흐름 캐시 비우기 (테스트용)."""
    with _cache_lock:
        _cache.clear()


def empty_condition(country: str, sector: str | None) -> dict:
    """모든 값 null·"데이터 부족"·sector_sample 0."""
    return {"score": None, "label": INSUFFICIENT, "sentiment": None, "sector_name": sector, "sector_flow": None,
            "sector_sample": 0, "sector_as_of": None, "index_code": sentiment.INDEX_CODE[country],
            "stock_r5": None, "sector_r5": None, "index_r5": None, "as_of": None}


def _is_stale(country: str, sentiment_day: date, base: date) -> bool:
    lag = sessions_between(country, sentiment_day, base)
    if lag is None:                                 # 달력 판정 불가 → 달력일 기준
        return (base - sentiment_day).days > CALENDAR_LAG_DAYS
    return lag > MAX_SENTIMENT_LAG


def get_condition(engine: Engine, *, stock_id: int, country: str, sector: str | None,
                  now: datetime | None = None) -> dict:
    """상세 응답 market_condition. 항상 MarketConditionOut 모양의 dict, 예외를 올리지 않는다."""
    try:
        index_code = sentiment.INDEX_CODE[country]
        now = now or datetime.now(timezone.utc)
        with engine.connect() as conn:
            base = last_closed_session(country, now) or conn.execute(INDEX_LATEST, {"c": index_code}).scalar()
            if base is None:
                return empty_condition(country, sector)
            s_row = sentiment.latest_stored(engine, country)
            stale = s_row is not None and _is_stale(country, s_row["trade_date"], base)
            sector_r5, n, ref_date = (_cached_sector_flow(conn, country, sector, base, now) if sector
                                      else (None, 0, None))
            use = n >= MIN_SECTOR_SAMPLE and sector_r5 is not None
            compare = ref_date if use else (s_row["trade_date"] if s_row else base)
            stock_r5 = _q(conn.execute(STOCK_R5, {"s": stock_id, "d": compare}).scalar(), "0.000001")
            index_r5 = _q(conn.execute(INDEX_R5, {"c": index_code, "d": compare}).scalar(), "0.000001")
        cond = compute_condition(None if (s_row is None or stale) else s_row["score"], sector_r5 if use else None)
        return {"score": cond["score"], "label": cond["label"],
                "sentiment": s_row["score"] if s_row else None, "sector_name": sector,
                "sector_flow": cond["sector_flow"] if use else None, "sector_sample": n,
                "sector_as_of": ref_date if use else None, "index_code": index_code,
                "stock_r5": stock_r5, "sector_r5": sector_r5 if use else None, "index_r5": index_r5,
                "as_of": s_row["trade_date"] if s_row else None}
    except Exception:  # noqa: BLE001 — 위험 표시 계산 실패가 상세 화면 전체를 막지 않는다
        log.exception("시장·섹터 점수 계산 실패(stock_id=%s)", stock_id)
        return empty_condition(country, sector)
