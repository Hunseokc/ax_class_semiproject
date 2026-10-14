"""환율 서비스 — 외부 호출을 TTL당 최대 1회로 제한한다.

get_current_rate():
  1) 최신 SNAPSHOT의 rate_at이 TTL 이내 → DB 값 반환 (외부 호출 0회)
  2) TTL 초과 → advisory lock을 잡고 다시 확인한 뒤 한 번만 조회해 SNAPSHOT 저장
     (동시 요청은 lock에서 기다렸다가 방금 저장된 값을 읽으므로 중복 호출하지 않는다)
  3) 조회 실패 → 마지막 값(v_fx_latest) + stale=True. 저장값이 전혀 없을 때만 오류
  실패 직후 요청마다 재시도하지 않도록 실패 후 FAILURE_COOLDOWN 동안은 외부 호출을 하지 않는다.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import Connection, Engine, text

from app.core.errors import ServiceUnavailable
from app.providers.base import FxProvider

log = logging.getLogger(__name__)

FX_LOCK_KEY = 7_301_001            # pg_advisory_xact_lock 키 (환율 SNAPSHOT 갱신)
FAILURE_COOLDOWN = timedelta(minutes=15)


@dataclass(frozen=True)
class FxQuote:
    usd_krw: Decimal
    rate_at: datetime
    granularity: str
    stale: bool


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FxService:
    def __init__(self, engine: Engine, provider: FxProvider, ttl_hours: float,
                 clock: Callable[[], datetime] = utcnow):
        self.engine = engine
        self.provider = provider
        self.ttl = timedelta(hours=ttl_hours)
        self.clock = clock

    # ------------------------------------------------------------ 조회
    @staticmethod
    def _latest_snapshot(conn: Connection):
        return conn.execute(text("""
            SELECT usd_krw, rate_at FROM fx_rates WHERE granularity = 'SNAPSHOT'
            ORDER BY rate_at DESC LIMIT 1""")).first()

    @staticmethod
    def _latest_any(conn: Connection):
        return conn.execute(text("SELECT usd_krw, rate_at, granularity FROM v_fx_latest")).first()

    @staticmethod
    def _last_failure(conn: Connection):
        return conn.execute(text("""
            SELECT max(finished_at) FROM ingestion_logs
            WHERE job_type = 'FX' AND status = 'FAILED' AND error LIKE 'SNAPSHOT%'""")).scalar()

    def _fresh(self, row) -> bool:
        return row is not None and self.clock() - row.rate_at < self.ttl

    # ------------------------------------------------------------ 공개 API
    def get_current_rate(self, force: bool = False) -> FxQuote:
        if not force:
            with self.engine.connect() as conn:
                snap = self._latest_snapshot(conn)
            if self._fresh(snap):
                return FxQuote(snap.usd_krw, snap.rate_at, "SNAPSHOT", stale=False)

        with self.engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": FX_LOCK_KEY})
            snap = self._latest_snapshot(conn)          # lock을 기다리는 사이 다른 요청이 저장했을 수 있음
            if self._fresh(snap) and not force:
                return FxQuote(snap.usd_krw, snap.rate_at, "SNAPSHOT", stale=False)
            failed_at = self._last_failure(conn)
            if not force and failed_at and self.clock() - failed_at < FAILURE_COOLDOWN:
                return self._fallback(conn, "최근 조회 실패 후 대기 중")
            started = self.clock()
            try:
                p = self.provider.get_current_rate()
                if p.usd_krw is None or p.usd_krw <= 0:
                    raise ValueError(f"유효하지 않은 환율 {p.usd_krw}")
            except Exception as e:  # noqa: BLE001 — 실패해도 마지막 값으로 응답
                with self.engine.begin() as log_conn:      # 별도 트랜잭션: 아래에서 503으로 롤백돼도 실패 기록 유지
                    self._log(log_conn, "FAILED", 0, f"SNAPSHOT {type(e).__name__}: {e}", started)
                log.warning("환율 조회 실패 → 저장된 마지막 값으로 대체 시도: %s", e)
                return self._fallback(conn, str(e))
            conn.execute(text("""
                INSERT INTO fx_rates (rate_at, usd_krw, granularity, source)
                VALUES (:rate_at, :usd_krw, 'SNAPSHOT', :source)
                ON CONFLICT (granularity, rate_at) DO UPDATE SET usd_krw = EXCLUDED.usd_krw"""),
                {"rate_at": p.rate_at, "usd_krw": p.usd_krw, "source": self.provider.source})
            self._log(conn, "SUCCESS", 1, "SNAPSHOT", started)
            return FxQuote(p.usd_krw, p.rate_at, "SNAPSHOT", stale=False)

    def latest_stored(self) -> FxQuote:
        """외부 호출 없이 저장된 최신 값 (stale 여부는 SNAPSHOT TTL 기준)."""
        with self.engine.connect() as conn:
            snap = self._latest_snapshot(conn)
            row = self._latest_any(conn)
        if row is None:
            raise ServiceUnavailable("저장된 환율이 없습니다", code="FX_UNAVAILABLE")
        return FxQuote(row.usd_krw, row.rate_at, row.granularity, stale=not self._fresh(snap))

    # ------------------------------------------------------------ 내부
    def _fallback(self, conn: Connection, reason: str) -> FxQuote:
        row = self._latest_any(conn)
        if row is None:
            raise ServiceUnavailable("환율을 조회할 수 없고 저장된 값도 없습니다", detail={"reason": reason},
                                     code="FX_UNAVAILABLE")
        return FxQuote(row.usd_krw, row.rate_at, row.granularity, stale=True)

    def _log(self, conn: Connection, status: str, rows: int, note: str, started: datetime) -> None:
        conn.execute(text("""
            INSERT INTO ingestion_logs (source, job_type, status, rows_loaded, error, started_at, finished_at)
            VALUES (:source, 'FX', :status, :rows, :note, :started, :finished)"""),
            {"source": self.provider.source, "status": status, "rows": rows, "note": note,
             "started": started, "finished": max(self.clock(), started)})
