"""백그라운드 재무 적재 — 상장 목록(listed) 종목의 재무를 우선순위대로 미리 받아, 검색해서 열었을 때 기다리지 않게 한다.

- 순서: 노출 종목·비교군은 4시간 갱신·07:00 비교군 갱신이 맡고, 여기서는 재무 기록(data_freshness)이 아예 없는 listed 종목만.
  국내는 최근 거래일 거래대금(종가 × 거래량) 순, 같으면 시가총액 순 — 날짜별 전 종목 조회 2회로 구한다.
  미국은 순위 소스(D11)를 정하기 전이라 건너뛴다.
- 하루 예산: 오늘(서울 0시부터) 남긴 ingestion_logs 행 수(source='DART'·'SEC'의 재무·공시)가 universe.yaml background
  *_calls_per_day에 닿으면 멈춘다. 상세 화면·07:00 갱신이 쓴 만큼 줄어든다. 일괄 적재(DART_BULK)는 세지 않는다.
- 한 번 받은 종목은 freshness 기록이 생겨 큐에서 빠지고, 이후에는 공시 목록 증분(jobs.load_dart_feed)이 만료시킬 때만 다시 받는다.
- 상세 요청은 큐와 상관없이 바로 받는다(회사 단위 잠금이라 이 작업 전체를 기다리지 않음).
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Engine, text

from app.ingest import jobs
from app.ingest.store import advisory_lock, job_log
from app.ingest.universe import load_universe
from app.providers.base import ProviderError
from app.providers.factory import Providers

log = logging.getLogger(__name__)
SEOUL = ZoneInfo("Asia/Seoul")
BACKGROUND_LOCK_KEY = 7_301_013     # 백그라운드 적재가 프로세스 여러 개에서 겹치지 않게
SOURCES = {"KR": "DART", "US": "SEC"}


def config() -> dict:
    return load_universe().background


def used_today(conn: Connection, source: str, now: datetime | None = None) -> int:
    """오늘(서울 0시 이후) ingestion_logs에서 source가 같고 job_type IN ('FINANCIALS','DISCLOSURES')인 행 수."""
    now = now or datetime.now(timezone.utc)
    midnight = datetime.combine(now.astimezone(SEOUL).date(), time(0), SEOUL)
    return conn.execute(text("""SELECT COUNT(*) FROM ingestion_logs
                                WHERE source = :s AND job_type IN ('FINANCIALS', 'DISCLOSURES') AND started_at >= :m"""),
                        {"s": source, "m": midnight}).scalar()


def _kr_ranking(providers: Providers) -> dict[str, tuple[Decimal, Decimal]]:
    """티커 → (거래대금, 시가총액). 최근 거래일 전 종목(휴장이면 하루씩 앞으로). 조회할 수 없으면 빈 dict."""
    bulk = providers.kr_bulk
    if bulk is None:
        return {}
    day = jobs.last_closed_day("KR")
    for back in range(8):
        d = day - timedelta(days=back)
        try:
            bars = bulk.get_bars_by_date(d)
            if not bars:
                continue
            vals = bulk.get_valuations_by_date(d)
        except ProviderError as e:
            log.warning("거래대금 조회 실패 %s: %s", d, e)
            continue
        return {t: ((b.close or 0) * (b.volume or 0), (vals.get(t).market_cap if vals.get(t) else None) or Decimal(0))
                for t, b in bars.items()}
    return {}


def priority_queue(conn: Connection, country: str, limit: int, ranking: dict[str, tuple[Decimal, Decimal]]) -> list[int]:
    """재무 기록이 아예 없는 활성 listed 종목(재무를 받을 수 있게 corp_code가 있는 것)을 순위대로 limit개.
    ranking: 티커 → (거래대금, 시가총액). 순위에 없는 종목은 맨 뒤(종목 id 순)."""
    if limit <= 0:
        return []
    rows = conn.execute(text("""
        SELECT s.stock_id, s.ticker FROM stocks s JOIN markets m ON m.market_id = s.market_id
        WHERE m.country = :c AND s.is_active AND s.coverage = 'listed'
          AND (CASE WHEN :c = 'KR' THEN s.corp_code ELSE s.cik END) IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM data_freshness f WHERE f.stock_id = s.stock_id AND f.kind = 'financials')"""),
        {"c": country}).all()
    zero = (Decimal(0), Decimal(0))
    rows = sorted(rows, key=lambda r: (*(-v for v in ranking.get(r.ticker, zero)), r.stock_id))
    return [r.stock_id for r in rows[:limit]]


def run_background(engine: Engine, providers: Providers, *, now: datetime | None = None) -> dict | None:
    """국가마다 남은 예산만큼 큐 앞에서부터 재무를 받는다. 다른 프로세스가 실행 중이면 None.
    반환: {"KR": {"budget", "used", "queued", "statuses"}, "US": {...}}"""
    cfg = config()
    with advisory_lock(engine, BACKGROUND_LOCK_KEY, wait=False) as got:
        if not got:
            log.info("백그라운드 적재가 이미 실행 중 — 건너뜀")
            return None
        out: dict = {}
        with job_log(engine, source="INTERNAL", job_type="BENCHMARK", label="background") as res:
            res.notes.append("백그라운드:")
            for country, key in (("KR", "dart_calls_per_day"), ("US", "sec_calls_per_day")):
                budget = int(cfg.get(key, 0))
                with engine.connect() as conn:
                    used = used_today(conn, SOURCES[country], now)
                queue: list[int] = []
                if country == "KR" and budget > used:     # 미국 순위 소스는 D11 결정 뒤
                    ranking = _kr_ranking(providers)
                    with engine.connect() as conn:
                        queue = priority_queue(conn, country, budget - used, ranking)
                statuses = (jobs.load_financials(engine, providers, years=load_universe().benchmark["fin_years"], stock_ids=queue)
                            if queue else {})
                out[country] = {"budget": budget, "used": used, "queued": len(queue), "statuses": statuses}
                ok = sum(1 for v in statuses.values() if v == "SUCCESS")
                res.notes.append(f"{country} 예산 {budget} 사용 {used} 큐 {len(queue)} 성공 {ok}"
                                 + (" (순위 소스 미정 — D11)" if country == "US" else ""))
            res.rows = sum(v["queued"] for v in out.values())
        return out
