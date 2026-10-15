"""외부 호출 공통: 호출 간격 제한 + 지수 백오프 재시도."""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import TypeVar

from app.providers.base import ProviderError

log = logging.getLogger(__name__)
T = TypeVar("T")

MAX_RETRIES = 3          # 최초 시도 후 최대 3회 재시도
BACKOFF_BASE = 1.0       # 1s → 2s → 4s


class Throttle:
    """같은 소스에 대한 연속 호출 사이에 최소 간격을 둔다."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            gap = time.monotonic() - self._last
            if gap < self.min_interval:
                time.sleep(self.min_interval - gap)
            self._last = time.monotonic()


class WindowLimiter:
    """최근 period초 동안의 호출을 max_calls회 이하로 제한한다(재시도 포함, 프로세스 안 스레드 공유).
    가득 차면 가장 오래된 호출이 창을 벗어날 때까지 기다린다."""

    def __init__(self, max_calls: int, period: float = 60.0, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.max_calls, self.period = max_calls, period
        self.clock, self.sleep = clock, sleep
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = self.clock()
            while self._calls and self._calls[0] <= now - self.period:
                self._calls.popleft()
            if len(self._calls) >= self.max_calls:
                delay = self._calls[0] + self.period - now
                log.info("호출 한도(%d회/%.0f초) 도달 — %.1fs 대기", self.max_calls, self.period, delay)
                self.sleep(delay)
                now = self.clock()
                while self._calls and self._calls[0] <= now - self.period:
                    self._calls.popleft()
            self._calls.append(now)


def call_with_retry(fn: Callable[[], T], *, throttle: Throttle, what: str,
                    retry_if: Callable[[T], bool] | None = None, limiter: WindowLimiter | None = None) -> T:
    """fn을 호출하고 예외(또는 retry_if가 True인 결과)면 지수 백오프로 재시도한다."""
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        throttle.wait()
        if limiter is not None:
            limiter.wait()
        try:
            result = fn()
            if retry_if is not None and retry_if(result):
                raise ProviderError(f"{what}: 유효하지 않은 응답")
            return result
        except Exception as e:  # noqa: BLE001 - 외부 라이브러리 예외 형태가 제각각
            last_err = e
            if attempt < MAX_RETRIES:
                delay = BACKOFF_BASE * 2 ** attempt
                log.warning("%s 실패(%d/%d): %s — %.0fs 후 재시도", what, attempt + 1, MAX_RETRIES + 1, e, delay)
                time.sleep(delay)
    raise ProviderError(f"{what}: {type(last_err).__name__}: {last_err}") from last_err
