"""전처리: 결측·형변환·중복 제거·현지 날짜·이상 행 격리.

격리한 행은 버리지 않고 (행, 사유)로 돌려주며, 적재 단계에서 ingestion_logs와
data/quarantine/*.csv에 기록한다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from decimal import Decimal
from statistics import median
from zoneinfo import ZoneInfo

from app.providers.base import Bar, FxPoint

MARKET_CLOSE = {"Asia/Seoul": time(15, 30), "America/New_York": time(16, 0)}


@dataclass
class Quarantined:
    row: dict
    reason: str


def _dedupe(rows: list, key) -> list:
    """같은 키는 마지막 값 유지(원본 순서상 나중 값이 최신)."""
    seen = {}
    for r in rows:
        seen[key(r)] = r
    return sorted(seen.values(), key=key)


def unfinished_session_date(tz: str, now: datetime | None = None) -> date | None:
    """현지 시각이 장 마감 전이면 오늘 날짜(=미확정 봉)를 반환 (ASSUMPTIONS A-07)."""
    zone = ZoneInfo(tz)
    now = (now or datetime.now(zone)).astimezone(zone)
    close = MARKET_CLOSE.get(tz, time(23, 59))
    return now.date() if now.time() < close else None


def clean_bars(bars: list[Bar], tz: str, *, require_volume: bool, now: datetime | None = None
               ) -> tuple[list[Bar], list[Quarantined]]:
    ok, bad = [], []
    skip_date = unfinished_session_date(tz, now)
    for b in _dedupe(bars, key=lambda x: x.trade_date):
        if b.trade_date == skip_date:
            bad.append(Quarantined(asdict(b), "장 마감 전 미확정 봉"))
            continue
        reason = None
        if b.close is None:
            reason = "종가 결측"
        elif require_volume and (b.open is None or b.high is None or b.low is None or b.volume is None):
            reason = "OHLCV 결측"
        elif b.close <= 0 or (b.low is not None and b.low <= 0):
            reason = "가격 0 이하(거래정지 등)"
        elif b.high is not None and b.low is not None and b.high < b.low:
            reason = "고가 < 저가"
        elif b.volume is not None and b.volume < 0:
            reason = "음수 거래량"
        if reason:
            bad.append(Quarantined(asdict(b), reason))
        else:
            ok.append(b)
    return ok, bad


def clean_fx(points: list[FxPoint], window: int = 5, max_dev: Decimal = Decimal("0.05")
             ) -> tuple[list[FxPoint], list[Quarantined]]:
    """결측·0 이하 제거, 전후 window개 중앙값 대비 5% 넘게 튀는 값 격리(yfinance 환율 튐 방지)."""
    pts = _dedupe([p for p in points], key=lambda p: p.rate_at)
    ok, bad = [], []
    valid = [p for p in pts if p.usd_krw is not None and p.usd_krw > 0]
    for p in pts:
        if p.usd_krw is None or p.usd_krw <= 0:
            bad.append(Quarantined(asdict(p), "환율 결측/0 이하"))
    for i, p in enumerate(valid):
        neighbors = [q.usd_krw for q in valid[max(0, i - window): i] + valid[i + 1: i + 1 + window]]
        if neighbors:
            m = median(neighbors)
            if abs(p.usd_krw / m - 1) > max_dev:
                bad.append(Quarantined(asdict(p), f"주변 중앙값 {m} 대비 {max_dev:.0%} 초과 이탈"))
                continue
        ok.append(p)
    return ok, bad
