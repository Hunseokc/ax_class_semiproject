"""앱 안 스케줄러 — 서버가 떠 있는 동안 주기 작업을 실행한다(SCHEDULER_ENABLED=false로 끌 수 있음).

- 노출 종목(+관심종목·포트폴리오 종목) 갱신: REFRESH_TTL_HOURS(4시간)마다 POST /market/refresh와 같은 작업
- 비교군 갱신: 매일 daily_at_kst(07:00 KST) 이후 1회 — 선정(30일마다)·평시 데이터·점수
- check_minutes(5분)마다 할 일이 있는지만 확인한다. 실제 작업은 별도 스레드에서 돌아 API 응답을 막지 않는다.
- 같은 작업이 여러 프로세스(워커 여러 개, CLI 수동 실행)에서 겹치지 않도록 PostgreSQL advisory lock을 쓴다.
서버를 띄우지 않는 환경이면 같은 작업을 cron·작업 스케줄러로 `python -m app.ingest refresh` / `benchmark`로 돌린다.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, text

from app.core.config import get_settings
from app.ingest import benchmark

log = logging.getLogger(__name__)
SEOUL = ZoneInfo("Asia/Seoul")
# 작업이 실패하면 성공 기록이 없어 매 확인마다 '해야 할 일'이 된다 → 시도 사이 최소 간격으로 외부 호출 폭주를 막는다
MIN_RETRY = {"refresh": timedelta(minutes=30), "benchmark": timedelta(minutes=60)}


def daily_boundary(now: datetime, at: time) -> datetime:
    """now 기준 가장 최근의 '매일 at(KST)' 시각."""
    local = now.astimezone(SEOUL)
    today_at = datetime.combine(local.date(), at, SEOUL)
    return today_at if local >= today_at else today_at - timedelta(days=1)


def benchmark_due(last_success: datetime | None, now: datetime, at: time) -> bool:
    return last_success is None or last_success < daily_boundary(now, at)


def last_benchmark_success(engine: Engine) -> datetime | None:
    with engine.connect() as conn:
        return conn.execute(text("""SELECT MAX(finished_at) FROM ingestion_logs
                                    WHERE job_type = 'BENCHMARK' AND status = 'SUCCESS' AND error LIKE '일일:%'""")).scalar()


class Scheduler:
    def __init__(self, engine: Engine, refresh_service_factory, providers_factory, scorer):
        self.engine = engine
        self.refresh_service = refresh_service_factory
        self.providers = providers_factory
        self.scorer = scorer
        hh, mm = benchmark.config()["daily_at_kst"].split(":")
        self.daily_at = time(int(hh), int(mm))
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
        if benchmark_due(last_benchmark_success(self.engine), now, self.daily_at) and self._may_try("benchmark", now):
            if benchmark.run_benchmark(self.engine, self.providers(), self.scorer) is not None:
                ran.append("benchmark")
        return ran

    async def run_forever(self) -> None:
        interval = get_settings().scheduler_check_minutes * 60
        log.info("스케줄러 시작: %d분마다 확인, 비교군은 매일 %s KST 이후", interval // 60, self.daily_at.strftime("%H:%M"))
        while True:
            try:
                ran = await asyncio.to_thread(self.tick)
                if ran:
                    log.info("스케줄러 실행: %s", ", ".join(ran))
            except Exception:  # noqa: BLE001 — 한 번 실패해도 다음 주기에 다시 시도
                log.exception("스케줄러 작업 실패")
            await asyncio.sleep(interval)
