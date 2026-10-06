"""외부 호출 공통: 호출 간격 제한 + 지수 백오프 재시도."""
from __future__ import annotations

import logging
import threading
import time
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


def call_with_retry(fn: Callable[[], T], *, throttle: Throttle, what: str,
                    retry_if: Callable[[T], bool] | None = None) -> T:
    """fn을 호출하고 예외(또는 retry_if가 True인 결과)면 지수 백오프로 재시도한다."""
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        throttle.wait()
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
