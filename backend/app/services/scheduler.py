"""앱 안 스케줄러 — 서버가 떠 있는 동안 주기 작업을 실행한다(SCHEDULER_ENABLED=false로 끌 수 있음).

- 활성 종목 갱신: REFRESH_TTL_HOURS(4시간)마다 POST /market/refresh와 같은 작업
- check_minutes(5분)마다 할 일이 있는지만 확인한다. 실제 작업은 별도 스레드에서 돌아 API 응답을 막지 않는다.
- 같은 작업이 여러 프로세스(워커 여러 개, CLI 수동 실행)에서 겹치지 않도록 PostgreSQL advisory lock을 쓴다.
서버를 띄우지 않는 환경이면 같은 작업을 cron·작업 스케줄러로 `python -m app.ingest refresh`로 돌린다.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import Engine

from app.core.config import get_settings

log = logging.getLogger(__name__)
# 작업이 실패하면 성공 기록이 없어 매 확인마다 '해야 할 일'이 된다 → 시도 사이 최소 간격으로 외부 호출 폭주를 막는다
MIN_RETRY = {"refresh": timedelta(minutes=30)}


class Scheduler:
    def __init__(self, engine: Engine, refresh_service_factory):
        self.engine = engine
        self.refresh_service = refresh_service_factory
        self._attempted: dict[str, datetime] = {}

    def _may_try(self, job: str, now: datetime) -> bool:
        last = self._attempted.get(job)
        if last and now - last < MIN_RETRY[job]:
            return False
        self._attempted[job] = now
        return True

    def tick(self, now: datetime | None = None) -> list[str]:
        """할 일이 있으면 실행하고 실행한 작업 이름을 돌려준다."""
        now = now or datetime.now(timezone.utc)
        ran = []
        svc = self.refresh_service()
        if svc.next_available() <= svc.clock() and self._may_try("refresh", now):   # next_available은 svc 시계 기준
            svc.refresh()                                   # TTL·재시도 간격이 남은 작업은 내부에서 SKIPPED
            ran.append("refresh")
        return ran

    async def run_forever(self) -> None:
        interval = get_settings().scheduler_check_minutes * 60
        log.info("스케줄러 시작: %d분마다 확인", interval // 60)
        while True:
            try:
                ran = await asyncio.to_thread(self.tick)
                if ran:
                    log.info("스케줄러 실행: %s", ", ".join(ran))
            except Exception:  # noqa: BLE001 — 한 번 실패해도 다음 주기에 다시 시도
                log.exception("스케줄러 작업 실패")
            await asyncio.sleep(interval)
