"""비교군 종목 상세 데이터 요청 시 수집 (상세 화면 열기·관심종목 추가).

비교군 종목은 평시에 점수 계산용 데이터만 있으므로, 사용자가 상세를 요구하면 그때
공시(1년)·일봉(2년)·FY 재무(5개년)를 백그라운드로 받는다. 같은 종목은 detail_ttl_hours(24시간) 안에 다시 받지 않는다.
- 작업은 프로세스 안 단일 작업자 스레드에서 순서대로 실행(동시 요청은 한 번만) → DART 분당 호출 제한 보호
- 재무·공시 수집은 jobs가 DART 잠금을 잡으므로 다른 프로세스의 DART 작업과도 겹치지 않는다
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from sqlalchemy import Engine, text

from app.ingest import jobs
from app.ingest.store import job_log
from app.providers.factory import Providers

log = logging.getLogger(__name__)
FAILED_BACKOFF = timedelta(minutes=10)   # 실패하면 이 시간 동안은 다시 시도하지 않는다


class Hydrator:
    def __init__(self, engine: Callable[[], Engine], providers: Callable[[], Providers], ttl_hours: float,
                 executor: Executor | None = None):
        self._engine, self._providers = engine, providers
        self.ttl = timedelta(hours=ttl_hours)
        self.executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="hydrate")
        self._inflight: set[int] = set()
        self._failed: dict[int, datetime] = {}
        self._lock = threading.Lock()

    def status(self, stock_id: int, coverage: str, synced_at: datetime | None) -> str:
        """ready: 상세 데이터 있음 / loading: 받는 중 / failed: 최근 실패(잠시 뒤 다시 시도)."""
        if coverage != "benchmark":
            return "ready"
        with self._lock:
            if stock_id in self._inflight:
                return "loading"
            failed_at = self._failed.get(stock_id)
        if synced_at and datetime.now(timezone.utc) - synced_at < self.ttl:
            return "ready"
        if failed_at and datetime.now(timezone.utc) - failed_at < FAILED_BACKOFF:
            return "failed"
        return "stale"

    def request(self, stock_id: int, coverage: str, synced_at: datetime | None) -> str:
        """필요하면 수집을 예약하고 상태를 돌려준다."""
        st = self.status(stock_id, coverage, synced_at)
        if st != "stale":
            return st
        with self._lock:
            if stock_id in self._inflight:
                return "loading"
            self._inflight.add(stock_id)
        self.executor.submit(self._run, stock_id)
        return "ready" if self.status(stock_id, coverage, self._synced_at(stock_id)) == "ready" else "loading"

    def _synced_at(self, stock_id: int) -> datetime | None:
        with self._engine().connect() as conn:
            return conn.execute(text("SELECT detail_synced_at FROM stocks WHERE stock_id = :s"), {"s": stock_id}).scalar()

    def _run(self, stock_id: int) -> None:
        engine, providers = self._engine(), self._providers()
        try:
            hydrate(engine, providers, stock_id)
            with self._lock:
                self._failed.pop(stock_id, None)
        except Exception:  # noqa: BLE001 — 백그라운드 작업 실패는 기록만
            log.exception("상세 수집 실패 stock_id=%s", stock_id)
            with self._lock:
                self._failed[stock_id] = datetime.now(timezone.utc)
        finally:
            with self._lock:
                self._inflight.discard(stock_id)


def hydrate(engine: Engine, providers: Providers, stock_id: int) -> dict:
    """공시(1년)·일봉(2년)·FY 재무(5개년)를 받고 detail_synced_at을 기록한다."""
    ids = [stock_id]
    out: dict = {}
    with job_log(engine, source="INTERNAL", job_type="HYDRATE", stock_id=stock_id, label=str(stock_id)) as res:
        out["prices"] = jobs.load_prices(engine, providers, stock_ids=ids, full=True)
        out["financials"] = jobs.load_financials(engine, providers, stock_ids=ids)
        out["disclosures"] = jobs.load_disclosures(engine, providers, stock_ids=ids)
        failed = [k for k, v in out.items() if "FAILED" in v.values()]
        if len(failed) == len(out):
            raise RuntimeError("상세 데이터를 하나도 받지 못함")
        with engine.begin() as conn:
            conn.execute(text("UPDATE stocks SET detail_synced_at = now() WHERE stock_id = :s"), {"s": stock_id})
        res.rows = 1
        if failed:
            res.notes.append(f"일부 실패: {', '.join(failed)}")
    if res.status != "SUCCESS":
        raise RuntimeError("상세 수집 실패 — ingestion_logs 참고")
    return out
