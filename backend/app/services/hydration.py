"""비교군·상장 목록 종목의 상세 데이터 요청 시 수집 (상세 화면 열기·관심종목 추가).

비교군(benchmark) 종목은 평시에 점수 계산용 데이터만, 상장 목록(listed) 종목은 이름·티커만 있으므로
사용자가 상세를 요구하면 그때 백그라운드에서 받는다. 순서: 일봉 → FY 재무(5개년) → 밸류에이션 → 공시(1년).
일봉을 먼저 받아 화면이 가격 차트부터 채울 수 있게 한다. 같은 종목은 detail_ttl_hours(24시간) 안에 다시 확인하지 않는다.
가격 외 데이터는 유효기간(data_freshness) 안이면 받지 않는다 → 다시 열 때는 보통 일봉 증분만 받는다.
  - 일봉: 2년 백필은 price_history 유효기간(1년)이 지났을 때만, 그 밖에는 빠진 날짜만
  - 재무: 공시 일정 기반 + 90일 상한 / 공시: 1일 / 밸류에이션: 국내는 최신 거래일 값이 없을 때만, 미국은 기초값 × 종가(호출 없음)
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
from app.ingest.benchmark import map_ids
from app.ingest.store import job_log
from app.providers.factory import Providers
from app.services import freshness

log = logging.getLogger(__name__)
FAILED_BACKOFF = timedelta(minutes=10)   # 실패하면 이 시간 동안은 다시 시도하지 않는다
ON_DEMAND = ("benchmark", "listed")      # 상세 데이터를 요청 시 받는 계층 (featured는 평시에 모두 있음)


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
        if coverage not in ON_DEMAND:
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
    """유효기간이 지난 데이터만 받고 detail_synced_at을 기록한다. 반환: 작업별 결과(건너뛴 작업은 'FRESH')."""
    ids = [stock_id]
    out: dict = {}
    with job_log(engine, source="INTERNAL", job_type="HYDRATE", stock_id=stock_id, label=str(stock_id)) as res:
        with engine.connect() as conn:
            backfill = bool(freshness.due(conn, "price_history", ids))
            fin_due = bool(freshness.due(conn, "financials", ids))
            disc_due = bool(freshness.due(conn, "disclosures", ids))
        out["prices"] = jobs.load_prices(engine, providers, stock_ids=ids, full=backfill)
        if backfill and "FAILED" not in out["prices"].values():
            with engine.begin() as conn:
                freshness.mark(conn, "price_history", stock_id, True)
        if fin_due:
            map_ids(engine, providers, ids, res.notes)        # 상장 목록 종목은 DART 고유번호가 아직 없을 수 있다
            out["financials"] = jobs.load_financials(engine, providers, stock_ids=ids)
        else:
            out["financials"] = "FRESH"
        out["valuation"] = _valuation_if_stale(engine, providers, stock_id)
        out["disclosures"] = jobs.load_disclosures(engine, providers, stock_ids=ids) if disc_due else "FRESH"
        ran = {k: v for k, v in out.items() if v != "FRESH"}
        failed = [k for k, v in ran.items() if "FAILED" in v.values()]
        if ran and len(failed) == len(ran):
            raise RuntimeError("상세 데이터를 하나도 받지 못함")
        with engine.begin() as conn:
            conn.execute(text("UPDATE stocks SET detail_synced_at = now() WHERE stock_id = :s"), {"s": stock_id})
        res.rows = 1
        res.notes.append("유효기간 안: " + (", ".join(k for k, v in out.items() if v == "FRESH") or "없음"))
        if failed:
            res.notes.append(f"일부 실패: {', '.join(failed)}")
    if res.status != "SUCCESS":
        raise RuntimeError("상세 수집 실패 — ingestion_logs 참고")
    return out


def _valuation_if_stale(engine: Engine, providers: Providers, stock_id: int) -> dict | str:
    """확정된 최근 거래일(장 마감·KRX 공표 뒤)의 밸류에이션이 이미 있으면 받지 않는다(국내 KRX 값은 거래일마다 1행)."""
    with engine.connect() as conn:
        country = conn.execute(text("""SELECT m.country FROM stocks s JOIN markets m ON m.market_id = s.market_id
                                       WHERE s.stock_id = :s"""), {"s": stock_id}).scalar_one()
        fresh = conn.execute(text("""
            SELECT EXISTS (SELECT 1 FROM valuation_snapshots v
                           WHERE v.stock_id = :s
                             AND v.as_of >= LEAST(CAST(:closed AS date),
                                                  (SELECT MAX(trade_date) FROM daily_prices WHERE stock_id = :s)))
        """), {"s": stock_id, "closed": jobs.last_closed_day(country)}).scalar()
    if fresh:
        return "FRESH"
    return jobs.load_valuations(engine, providers, stock_ids=[stock_id], history_days=10)
