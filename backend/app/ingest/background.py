"""백그라운드 재무 적재 — 상장 목록(listed) 종목의 재무를 우선순위대로 미리 받아, 검색해서 열었을 때 기다리지 않게 한다.

- 순서: 노출 종목·비교군은 4시간 갱신·07:00 비교군 갱신이 맡고, 여기서는 재무 기록(data_freshness)이 아예 없는 listed 종목만.
  국내는 최근 거래일 거래대금(종가 × 거래량) 순, 같으면 시가총액 순 — 날짜별 전 종목 조회 2회로 구한다.
  미국은 시가총액 상위 us_rank_pool개 안에서 순위대로(D11). 순위는 us_rank_days마다 stocks.cap_rank에 저장하고,
  비교군 선정 순서에도 쓴다(benchmark.selection_order). 시가총액은 yfinance 시총이다(수정 4 R4-3·R4-4 — SEC 발행주식수는
  원주 기준이라 ADR이 수백~수천 배 부풀고, 주식 종류가 여럿인 회사는 frames 값이 비어 순위에서 빠졌다).
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
from app.ingest.universe import load_universe, stock_refs
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


def priority_queue(conn: Connection, country: str, limit: int, ranking: dict[str, tuple[Decimal, Decimal]],
                   *, ranked_only: bool = False) -> list[int]:
    """재무 기록이 아예 없는 활성 listed 종목(재무를 받을 수 있게 corp_code·CIK가 있는 것)을 순위대로 limit개.
    ranking: 티커 → (1순위 값, 2순위 값), 클수록 앞. 순위에 없는 종목은 맨 뒤(종목 id 순), ranked_only면 빼고."""
    if limit <= 0:
        return []
    rows = conn.execute(text("""
        SELECT s.stock_id, s.ticker FROM stocks s JOIN markets m ON m.market_id = s.market_id
        WHERE m.country = :c AND s.is_active AND s.coverage = 'listed'
          AND (CASE WHEN :c = 'KR' THEN s.corp_code ELSE s.cik END) IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM data_freshness f WHERE f.stock_id = s.stock_id AND f.kind = 'financials')"""),
        {"c": country}).all()
    if ranked_only:
        rows = [r for r in rows if r.ticker in ranking]
    zero = (Decimal(0), Decimal(0))
    rows = sorted(rows, key=lambda r: (*(-v for v in ranking.get(r.ticker, zero)), r.stock_id))
    return [r.stock_id for r in rows[:limit]]


RATIO_TOLERANCE = Decimal("1.2")    # SEC 원주 수 × 종가가 yfinance 시총과 이 배수 넘게 다르면 ADR·주식 종류 여럿으로 본다
INFLATED_CAP_TO_ASSETS = 200         # yfinance 값이 없을 때 SEC 기준 시총이 최신 FY 총자산의 이 배수를 넘으면 순위에서 뺀다


def rank_us(engine: Engine, providers: Providers, now: datetime | None = None, *, force: bool = False) -> int | None:
    """미국 활성 종목(CIK 있음)의 시가총액 순위 → stocks.cap_rank(상위 us_rank_pool개, 나머지 NULL)·cap_usd·share_ratio.
    1) SEC 발행주식수 × 종가로 후보를 고른다(상위 pool × 4/3개 + 발행주식수가 비는 회사 중 DB 일봉이 있는 종목과
       최근 거래대금 상위 pool / 3개 — 비는 회사는 1,800여 개이고 대부분 20-F를 내는 해외 기업이다).
    2) 후보는 yfinance 시총으로 바꾸고, SEC 기준과 20% 넘게 다르면 그 비율(share_ratio = SEC 원주 수 ÷ 상장 단위 주식수)을
       남긴다 — 미국 밸류에이션(jobs.DERIVED_US_SQL)이 이 비율로 상장 단위 주식수를 쓴다(ADR, R4-3).
    3) yfinance 값이 없으면 SEC 기준을 쓰되 최신 FY 총자산의 200배를 넘으면 뺀다(부푼 ADR).
    4) 발행주식수가 비는 회사가 순위 안에 들면 10-K·10-Q를 내는 회사인지 확인하고, 20-F·40-F만 내면 뺀다 — 재무를 받지 않아
       점수가 없는데(D-014) 비교군 자리를 차지하지 않게.
    마지막으로 매긴 지 us_rank_days가 안 지났으면 하지 않고 None. 반환: 순위를 매긴 종목 수."""
    cfg, now = config(), now or datetime.now(timezone.utc)
    ref, batch = providers.us_reference, providers.us_batch_price
    if ref is None or batch is None:
        return None
    with engine.connect() as conn:
        last = conn.execute(text("""SELECT MAX(s.cap_ranked_at) FROM stocks s JOIN markets m ON m.market_id = s.market_id
                                    WHERE m.country = 'US'""")).scalar()
        if not force and last is not None and now - last < timedelta(days=int(cfg.get("us_rank_days", 30))):
            return None
        rows = conn.execute(text("""
            SELECT s.stock_id, s.cik,
                   (SELECT d.close FROM daily_prices d WHERE d.stock_id = s.stock_id AND d.trade_date >= :since
                    ORDER BY d.trade_date DESC LIMIT 1) AS close
            FROM stocks s JOIN markets m ON m.market_id = s.market_id
            WHERE m.country = 'US' AND s.is_active AND s.cik IS NOT NULL"""),
            {"since": now.date() - timedelta(days=10)}).all()
    shares = ref.get_shares_frame(now.date())
    mc, pool = providers.us_market_cap, int(cfg.get("us_rank_pool", 1500))
    closes = {r.stock_id: r.close for r in rows if r.close}
    dollar_vol: dict[int, Decimal] = {}                 # 묶음으로 받은 종목의 최근 평균 거래대금(발행주식수 없는 후보 고르기)
    missing = [r.stock_id for r in rows if not r.close and (r.cik in shares or mc is not None)]
    if missing:                                         # listed 종목은 일봉이 없어 묶음으로 최근 종가만
        with engine.connect() as conn:
            refs = stock_refs(conn, stock_ids=missing)
        got = batch.get_daily_prices_batch(refs, now.date() - timedelta(days=10), now.date())
        for r in refs:
            bars = [b for b in got.get(r.ticker, []) if b.close]
            if bars:
                closes[r.stock_id] = bars[-1].close
                dollar_vol[r.stock_id] = sum(b.close * (b.volume or 0) for b in bars) / len(bars)
    sec_caps = {r.stock_id: Decimal(shares[r.cik]) * closes[r.stock_id] for r in rows
                if r.cik in shares and r.stock_id in closes}
    caps, ratios = dict(sec_caps), {}
    no_share = {r.stock_id for r in rows if r.cik not in shares and r.stock_id in closes}   # 주식 종류 여럿(V·MA·BRK)·해외
    if mc is not None:
        cand = sorted(sec_caps, key=lambda s: (-sec_caps[s], s))[:pool + pool // 3]
        cand += [s for s in no_share if s not in dollar_vol]                             # DB 일봉이 있는 표본 종목(META 등)
        cand += sorted((s for s in no_share if s in dollar_vol), key=lambda s: (-dollar_vol[s], s))[:pool // 3]
        with engine.connect() as conn:
            refs = stock_refs(conn, stock_ids=cand)
            assets = dict(conn.execute(text("""
                SELECT DISTINCT ON (f.stock_id) f.stock_id, f.total_assets FROM financial_statements f
                WHERE f.stock_id = ANY(:ids) AND f.period_type = 'FY' AND f.total_assets > 0
                ORDER BY f.stock_id, f.period_end DESC"""), {"ids": cand}).all())
        got = mc.get_market_caps(refs)
        yf = {r.stock_id: got[r.ticker] for r in refs if r.ticker in got}
        for sid in cand:
            if sid in yf:
                caps[sid] = yf[sid]
                if sid in sec_caps and not 1 / RATIO_TOLERANCE <= sec_caps[sid] / yf[sid] <= RATIO_TOLERANCE:
                    ratios[sid] = (sec_caps[sid] / yf[sid]).quantize(Decimal("0.000001"))
            elif sid in assets and sec_caps.get(sid, 0) > INFLATED_CAP_TO_ASSETS * assets[sid]:
                caps.pop(sid, None)
        log.info("미국 시가총액: 후보 %d · yfinance %d · 비율 %d · 부풀어 뺀 종목 %d", len(cand), len(yf), len(ratios),
                 sum(1 for s in cand if s not in caps))
    files_us = getattr(ref, "files_us_reports", None) if mc is not None else None
    cik_of = {r.stock_id: r.cik for r in rows}
    ranked, foreign = [], []
    for sid in sorted(caps, key=lambda s: (-caps[s], s)):
        if len(ranked) >= pool:
            break
        if files_us is not None and sid in no_share and sid in caps and not files_us(cik_of[sid]):
            foreign.append(sid)
            continue
        ranked.append(sid)
    if foreign:
        log.info("미국 시가총액: 발행주식수가 없고 20-F·40-F만 내는 회사 %d개 순위에서 뺌", len(foreign))
    with engine.begin() as conn:
        conn.execute(text("""UPDATE stocks s SET cap_rank = NULL, cap_usd = NULL, share_ratio = NULL, cap_ranked_at = :now
                             FROM markets m WHERE m.market_id = s.market_id AND m.country = 'US'"""), {"now": now})
        if ranked:
            conn.execute(text("UPDATE stocks SET cap_rank = :r, cap_usd = :c WHERE stock_id = :s"),
                         [{"r": i, "c": caps[s].quantize(Decimal(1)), "s": s} for i, s in enumerate(ranked, 1)])
        if ratios:
            conn.execute(text("UPDATE stocks SET share_ratio = :r WHERE stock_id = :s"),
                         [{"r": r, "s": s} for s, r in ratios.items()])
        sample = conn.execute(text("""SELECT s.stock_id FROM stocks s JOIN markets m ON m.market_id = s.market_id
                                      WHERE m.country = 'US' AND s.is_active AND s.coverage IN ('featured', 'benchmark')""")
                              ).scalars().all()
    jobs.derive_us_valuations(engine, list(sample))     # 비율이 바뀐 비교 표본의 시가총액·EPS·BPS를 바로 다시 계산
    return len(ranked)


def _us_ranking(conn: Connection) -> dict[str, tuple[Decimal, Decimal]]:
    """저장된 미국 순위 → priority_queue용 (점수, 0). 순위가 없는 종목은 빠진다(큐에도 넣지 않음)."""
    return {t: (Decimal(-r), Decimal(0)) for t, r in conn.execute(text("""
        SELECT s.ticker, s.cap_rank FROM stocks s JOIN markets m ON m.market_id = s.market_id
        WHERE m.country = 'US' AND s.cap_rank IS NOT NULL"""))}


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
                if budget > used and country == "KR":
                    ranking = _kr_ranking(providers)
                    with engine.connect() as conn:
                        queue = priority_queue(conn, country, budget - used, ranking)
                elif budget > used:                       # 미국: 시가총액 상위 us_rank_pool 안에서 순위대로 (D11)
                    n = rank_us(engine, providers, now)
                    if n is not None:
                        res.notes.append(f"미국 시가총액 순위 갱신 {n}개")
                    with engine.connect() as conn:
                        queue = priority_queue(conn, country, budget - used, _us_ranking(conn), ranked_only=True)
                statuses = (jobs.load_financials(engine, providers, years=load_universe().benchmark["fin_years"], stock_ids=queue)
                            if queue else {})
                out[country] = {"budget": budget, "used": used, "queued": len(queue), "statuses": statuses}
                ok = sum(1 for v in statuses.values() if v == "SUCCESS")
                res.notes.append(f"{country} 예산 {budget} 사용 {used} 큐 {len(queue)} 성공 {ok}")
            res.rows = sum(v["queued"] for v in out.values())
        return out
