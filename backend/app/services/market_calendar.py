"""거래소 휴장 달력 — 지수 카드의 장 상태 배지(휴장·직전 거래일) 판정.

exchange_calendars 라이브러리에 들어 있는 거래소 달력(XKRX·XNYS)을 쓴다. 네트워크 호출은 없다.
음력 공휴일·연말 휴장·Good Friday 등은 포함되지만, 임시공휴일처럼 뒤늦게 정해지는 휴장은 라이브러리 버전을 올려야 반영된다.
달력 범위를 벗어나거나 판정할 수 없으면 None을 돌려주고 화면은 주말 여부로만 판단한다.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

log = logging.getLogger(__name__)

CALENDARS = {"KR": "XKRX", "US": "XNYS"}
TIMEZONES = {"KR": ZoneInfo("Asia/Seoul"), "US": ZoneInfo("America/New_York")}
SessionStatus = Literal["today", "holiday", "previous_session"]


@lru_cache
def _calendar(code: str):
    return xcals.get_calendar(code)          # 만들 때 1년 남짓 앞까지 계산해 두므로 프로세스당 한 번만


def session_status(country: str | None, as_of: date | None, now: datetime | None = None) -> SessionStatus | None:
    """today: 최신 일봉이 그 시장의 오늘 / holiday: 오늘이 휴장일 / previous_session: 오늘은 거래일이지만 오늘 일봉이 아직 없음."""
    if as_of is None or country not in CALENDARS:
        return None
    today = (now or datetime.now(timezone.utc)).astimezone(TIMEZONES[country]).date()
    if as_of >= today:
        return "today"
    try:
        open_today = _calendar(CALENDARS[country]).is_session(today.isoformat())
    except Exception as e:  # noqa: BLE001 — 달력 범위 밖 등: 배지 판정만 포기하고 응답은 정상
        log.warning("거래소 달력 판정 실패(%s %s): %s", country, today, e)
        return None
    return "previous_session" if open_today else "holiday"
