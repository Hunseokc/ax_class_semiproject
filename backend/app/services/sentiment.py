"""시장 심리 지수 — StockMind 간이 계산(0~100, 높을수록 탐욕). CNN Fear & Greed 지수가 아니다.

기준 지수(국내 KOSPI, 미국 S&P 500)의 일봉 종가로 구성요소를 각각 0~100 점수로 바꿔 단순 평균한다.
  가격 위치    (현재 − 52주 저점) / (52주 고점 − 52주 저점) × 100          최근 252거래일 종가
  이동평균 괴리 clamp(50 + (현재 / 125일 이동평균 − 1) × 100 × 5)
  RSI(14)     Wilder 방식 RSI 값 그대로
  변동성(미국)  clamp((35 − VIX) / (35 − 12) × 100)                        VIX 종가
계산할 수 없는 구성요소는 빼고 평균하며, 남은 구성요소가 2개 미만이면 '데이터 부족'.

외부 호출이 없다: 지수·VIX 일봉은 갱신 작업(INDICES)이 이미 index_daily_prices에 쌓아 둔 것을 읽는다.
계산(compute_sentiment)은 DB와 무관한 순수 함수, 저장·조회는 아래 함수들로 분리한다.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import Connection, Engine, text

from app.ingest.store import upsert
from app.services.market_calendar import session_status

log = logging.getLogger(__name__)

FORMULA_VERSION = 1          # 계산식을 바꾸면 올린다 → 저장된 행의 버전이 다르면 다시 계산해 덮어쓴다
INDEX_CODE = {"KR": "KOSPI", "US": "SPX"}
VIX_CODE = "VIX"
RANGE_DAYS, MA_DAYS, RSI_DAYS = 252, 125, 14
VIX_HIGH, VIX_LOW = 35.0, 12.0
VIX_MAX_LAG = timedelta(days=5)       # 기준일보다 이만큼 넘게 오래된 VIX는 쓰지 않는다(변동성 요소 제외)
LOOKBACK = RANGE_DAYS + 10            # 5거래일 전까지 계산하는 데 필요한 종가 수(여유 포함)
MIN_COMPONENTS = 2
# 구간 라벨: [하한, 상한) — 0~20 극단적 공포, 20~40 공포, 40~60 중립, 60~80 탐욕, 80~100 극단적 탐욕
LABELS = ((20, "극단적 공포"), (40, "공포"), (60, "중립"), (80, "탐욕"), (float("inf"), "극단적 탐욕"))
INSUFFICIENT = "데이터 부족"


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def label_for(score: float | None) -> str:
    if score is None:
        return INSUFFICIENT
    return next(name for upper, name in LABELS if score < upper)


def _rsi(closes: Sequence[float], period: int = RSI_DAYS) -> float | None:
    """Wilder 방식 RSI. 종가가 period+1개 미만이면 None."""
    if len(closes) < period + 1:
        return None
    diffs = [b - a for a, b in zip(closes, closes[1:])]
    gain = sum(max(d, 0) for d in diffs[:period]) / period
    loss = sum(max(-d, 0) for d in diffs[:period]) / period
    for d in diffs[period:]:
        gain = (gain * (period - 1) + max(d, 0)) / period
        loss = (loss * (period - 1) + max(-d, 0)) / period
    if loss == 0:
        return 50.0 if gain == 0 else 100.0
    return 100 - 100 / (1 + gain / loss)


def compute_sentiment(closes: Sequence[float], vix_closes: Sequence[float] | None = None) -> dict:
    """종가(오래된 → 최근)와 선택적 VIX 종가로 심리 점수. 구성요소는 0~100, 계산 못 하면 None.

    반환: {score, label, price_position, ma_gap_score, rsi_score, vix_score}
    """
    c = [float(x) for x in closes]
    cur = c[-1] if c else None
    price_position = ma_gap_score = None
    if len(c) >= RANGE_DAYS:
        window = c[-RANGE_DAYS:]
        lo, hi = min(window), max(window)
        price_position = (cur - lo) / (hi - lo) * 100 if hi > lo else None
    if len(c) >= MA_DAYS:
        ma = sum(c[-MA_DAYS:]) / MA_DAYS
        ma_gap_score = clamp(50 + (cur / ma - 1) * 100 * 5)
    rsi_score = _rsi(c)
    vix_score = None
    if vix_closes:
        vix_score = clamp((VIX_HIGH - float(vix_closes[-1])) / (VIX_HIGH - VIX_LOW) * 100)
    parts = {"price_position": price_position, "ma_gap_score": ma_gap_score, "rsi_score": rsi_score, "vix_score": vix_score}
    valid = [v for v in parts.values() if v is not None]
    score = round(sum(valid) / len(valid), 2) if len(valid) >= MIN_COMPONENTS else None
    return {"score": score, "label": label_for(score), **{k: (round(v, 2) if v is not None else None) for k, v in parts.items()}}


# ------------------------------------------------------------------ 저장·조회 (DB)
def _series(conn: Connection, code: str, limit: int) -> list[tuple[date, float]]:
    rows = conn.execute(text("""
        SELECT p.trade_date, p.close FROM index_daily_prices p JOIN indices i ON i.index_id = p.index_id
        WHERE i.code = :c ORDER BY p.trade_date DESC LIMIT :n"""), {"c": code, "n": limit}).all()
    return [(d, float(c)) for d, c in reversed(rows)]


def _stored(conn: Connection, market: str, days: list[date]) -> dict[date, dict]:
    rows = conn.execute(text("""
        SELECT trade_date, score, label, price_position, ma_gap_score, rsi_score, vix_score, formula_version
        FROM market_sentiment_daily WHERE market = :m AND trade_date = ANY(:d)"""), {"m": market, "d": days}).mappings()
    return {r["trade_date"]: dict(r) for r in rows}


def _compute_at(series: list[tuple[date, float]], vix: list[tuple[date, float]] | None, day: date) -> dict:
    """day까지 자른 시계열로 계산(백필). VIX는 day 이하 최근 값이 VIX_MAX_LAG 안에 있을 때만."""
    closes = [c for d, c in series if d <= day]
    vix_closes = None
    if vix:
        upto = [(d, c) for d, c in vix if d <= day]
        if upto and day - upto[-1][0] <= VIX_MAX_LAG:
            vix_closes = [c for _, c in upto]
    return compute_sentiment(closes, vix_closes)


POINTS = {"current": -1, "previous": -2, "week_ago": -6}     # 기준일·직전 거래일·5거래일 전 (시계열 끝에서의 위치)


def ensure_sentiment(engine: Engine, market: str, now: datetime | None = None) -> dict[str, dict]:
    """기준일·직전 거래일·5거래일 전 행을 보장한다. 없거나 계산식 버전이 다르면 그 시점까지 자른 시계열로 계산해 upsert.

    반환: {"current"|"previous"|"week_ago": 행} — 시계열이 짧아 없는 시점은 빠진다. 지수 일봉이 없으면 빈 dict.
    """
    now = now or datetime.now(timezone.utc)
    with engine.connect() as conn:
        series = _series(conn, INDEX_CODE[market], LOOKBACK)
        vix = _series(conn, VIX_CODE, LOOKBACK) if market == "US" else None
        days = {role: series[i][0] for role, i in POINTS.items() if len(series) >= -i}
        stored = _stored(conn, market, list(days.values())) if days else {}
    out, fresh = {}, []
    for role, day in days.items():
        row = stored.get(day)
        if row is None or row["formula_version"] != FORMULA_VERSION:
            row = {"trade_date": day, **_compute_at(series, vix, day), "formula_version": FORMULA_VERSION}
            if row["score"] is not None:              # '데이터 부족'은 저장하지 않는다
                fresh.append({"market": market, **row, "computed_at": now})
        out[role] = row
    if fresh:
        with engine.begin() as conn:
            upsert(conn, "market_sentiment_daily", fresh, ["market", "trade_date"])
    return out


def _latest_stored(engine: Engine, market: str) -> dict | None:
    with engine.connect() as conn:
        r = conn.execute(text("""
            SELECT trade_date, score, label, price_position, ma_gap_score, rsi_score, vix_score, formula_version
            FROM market_sentiment_daily WHERE market = :m ORDER BY trade_date DESC LIMIT 1"""), {"m": market}).mappings().first()
    return dict(r) if r else None


def _point(row: dict | None) -> dict | None:
    if row is None or row.get("score") is None:
        return None
    return {"trade_date": row["trade_date"], "score": row["score"], "label": row["label"]}


def get_sentiment(engine: Engine, market: str, now: datetime | None = None) -> dict:
    """홈 화면용 — 기준일 값 + 어제(직전 거래일)·지난주(5거래일 전) 값과 라벨.

    계산할 지수 일봉이 없거나 계산·저장이 실패하면 가장 최근 저장 행을 그 기준일과 함께 쓴다. 저장 행도 없으면 '데이터 부족'.
    """
    try:
        points = ensure_sentiment(engine, market, now)
    except Exception:  # noqa: BLE001
        log.exception("시장 심리 지수 계산 실패(%s) — 마지막 저장값으로 대체", market)
        points = {}
    cur = points.get("current") or _latest_stored(engine, market)
    as_of = cur["trade_date"] if cur else None
    return {
        "market": market,
        "index_code": INDEX_CODE[market],
        "formula_version": FORMULA_VERSION,
        "as_of": as_of,
        "session_status": session_status(market, as_of, now),
        "score": cur["score"] if cur else None,
        "label": cur["label"] if cur else INSUFFICIENT,
        "components": {k: (cur or {}).get(k) for k in ("price_position", "ma_gap_score", "rsi_score", "vix_score")},
        "previous": _point(points.get("previous")),
        "week_ago": _point(points.get("week_ago")),
    }
