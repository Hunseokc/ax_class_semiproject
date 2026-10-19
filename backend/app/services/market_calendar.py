"""거래소 휴장 달력 — 지수 카드의 장 상태 배지(휴장·직전 거래일) 판정.

exchange_calendars 라이브러리에 들어 있는 거래소 달력(XKRX·XNYS)을 쓴다. 네트워크 호출은 없다.
음력 공휴일·연말 휴장·Good Friday 등은 포함되지만, 임시공휴일처럼 뒤늦게 정해지는 휴장은 라이브러리 버전을 올려야 반영된다.
달력 범위를 벗어나거나 판정할 수 없으면 None을 돌려주고 화면은 주말 여부로만 판단한다.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

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


def last_closed_session(country: str, now: datetime | None = None) -> date | None:
    """그 시장에서 가장 최근에 마감된 거래일(현지 날짜). 장중이면 직전 거래일. 판정할 수 없으면 None.

    갱신 작업이 '마감 이후 값이 이미 있으면 다음 거래일까지 다시 받지 않는다'를 판단할 때 쓴다(주말·휴장 포함).
    """
    if country not in CALENDARS:
        return None
    try:
        close = _calendar(CALENDARS[country]).previous_close(pd.Timestamp(now or datetime.now(timezone.utc)))
    except Exception as e:  # noqa: BLE001 — 달력 범위 밖 등: 판정을 포기하면 호출 측은 평소대로 받는다
        log.warning("거래소 달력 마감 판정 실패(%s): %s", country, e)
        return None
    return close.tz_convert(TIMEZONES[country]).date()


def sessions_between(country: str, start: date, end: date) -> int | None:
    """start 다음 날부터 end까지(end 포함)의 거래일 수. start >= end면 0. 판정할 수 없으면 None.

    시장·섹터 점수가 '시장 심리 저장값이 몇 거래일 묵었나'를 셀 때 쓴다(휴장일은 세지 않음).
    """
    if country not in CALENDARS:
        return None
    if start >= end:
        return 0
    try:
        return len(_calendar(CALENDARS[country]).sessions_in_range(pd.Timestamp(start + timedelta(days=1)), pd.Timestamp(end)))
    except Exception as e:  # noqa: BLE001 — 달력 범위 밖 등
        log.warning("거래소 달력 거래일 수 판정 실패(%s %s~%s): %s", country, start, end, e)
        return None
