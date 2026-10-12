"""매력도 비교군(benchmark) — 점수 계산 표본을 넓히기 위한 종목들. 화면 기본 목록에는 나오지 않는다(docs/09 9절).

- 섹터: 공식 업종(국내 KRX 업종, 미국 SEC SIC)을 config/universe.yaml sectors로 묶는다(app/ingest/sectors.py).
  섹터 그룹(peer_groups.kind = 'sector')이 섹터 중립화의 주 그룹이 되고, 테마 그룹(kind = 'theme')은 화면 경쟁 비교용이다.
- 선정: 국가·섹터마다 노출 종목 + 상장 보통주 중 시가총액 상위 (per_sector − 노출 종목 수)개. reselect_days(30일)마다.
  국내는 KRX 업종·시가총액 전 종목 조회 2회, 미국은 SEC 발행주식수(frames) × 종가로 시가총액을 구해
  상위 us_rank_pool개만 SIC를 확인한다. 빠진 종목은 상장 종목 목록(listed)으로 돌아간다(검색은 계속 됨).
- 평시 데이터(1일 1회): 일봉은 국내 날짜별 전 종목·미국 묶음 다운로드로 증분, 밸류에이션은 국내 전 종목 1일치·미국 기초값 × 종가,
  재무는 유효기간(data_freshness — 공시 일정 기반 + 90일 상한)이 지난 종목만. 상세 화면을 열지 않은 지 30일이 지나면 그 밖의 데이터는 정리
- 공시·2년 일봉·5개년 재무는 상세 화면을 열거나 관심종목에 추가할 때 유효기간이 지난 것만 받는다(app/services/hydration.py)
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import Engine, text

from app.ingest import jobs
from app.ingest.sectors import sector_for_krx, sector_for_sic, sectors
from app.ingest.store import BENCHMARK_LOCK_KEY, advisory_lock, job_log, upsert
from app.ingest.universe import FREQUENT_SQL, load_universe, stock_refs
from app.providers.base import ProviderError
from app.providers.factory import Providers
from app.services import freshness

log = logging.getLogger(__name__)
PRUNE_AFTER_DAYS = 30           # 상세를 마지막으로 받은 뒤 이 기간이 지나면 평시 데이터만 남긴다
FEATURED_FIN_YEARS = jobs.FIN_YEARS


def config() -> dict:
    return load_universe()["benchmark"]


# ---------------------------------------------------------------- 업종 분류
def classify_kr(engine: Engine, providers: Providers, today: date) -> dict[int, Decimal]:
    """국내 전 종목 KRX 업종 → stocks.industry·sector. 반환: stock_id → 시가총액(원)."""
    if providers.kr_bulk is None:
        return {}
    rows = providers.kr_bulk.get_sector_classifications(today)
    with engine.begin() as conn:
        ids = {r.ticker: r.stock_id for r in conn.execute(text("""
            SELECT s.ticker, s.stock_id FROM stocks s JOIN markets m ON m.market_id = s.market_id
            WHERE m.country = 'KR' AND s.is_active"""))}
        upd = [{"id": ids[c.ticker], "ind": c.industry[:64], "sec": sector_for_krx(c.industry)}
               for c in rows if c.ticker in ids]
        if upd:
            conn.execute(text("""UPDATE stocks SET industry = :ind, sector = :sec, industry_checked_at = now()
                                 WHERE stock_id = :id"""), upd)
    return {ids[c.ticker]: c.market_cap for c in rows if c.ticker in ids and c.market_cap}


def classify_us(engine: Engine, providers: Providers, today: date, notes: list[str]) -> dict[int, Decimal]:
    """미국: SEC 발행주식수 × 종가 = 시가총액 → 상위 us_rank_pool개(+노출 종목)만 SIC를 확인해 섹터를 정한다.
    반환: stock_id → 시가총액(달러), 순위 안 종목만."""
    ref = providers.us_reference
    if ref is None:
        return {}
    cfg = config()
    shares = ref.get_shares_frame(today)
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT s.stock_id, s.ticker, s.cik, s.sic, s.industry_checked_at, s.coverage,
                   (SELECT d.close FROM daily_prices d WHERE d.stock_id = s.stock_id
                      AND d.trade_date >= CAST(:since AS date) ORDER BY d.trade_date DESC LIMIT 1) AS close
            FROM stocks s JOIN markets m ON m.market_id = s.market_id
            WHERE m.country = 'US' AND s.is_active AND s.cik IS NOT NULL"""),
            {"since": today - timedelta(days=10)}).mappings().all()
    cand = [r for r in rows if r["cik"] in shares]
    closes = {r["stock_id"]: r["close"] for r in cand if r["close"]}
    missing = [r["stock_id"] for r in cand if not r["close"]]
    if missing and providers.us_batch_price is not None:
        with engine.connect() as conn:
            refs = stock_refs(conn, stock_ids=missing)
        with job_log(engine, source=providers.us_batch_price.source, job_type="BENCHMARK", label="시가총액용 종가") as res:
            fetched = providers.us_batch_price.get_daily_prices_batch(refs, today - timedelta(days=10), today)
            for r in refs:
                bars = [b for b in fetched.get(r.ticker, []) if b.close]
                if bars:
                    closes[r.stock_id] = bars[-1].close
            res.rows = len(fetched)
    caps = {r["stock_id"]: Decimal(shares[r["cik"]]) * closes[r["stock_id"]] for r in cand if r["stock_id"] in closes}
    ranked = sorted(caps, key=caps.get, reverse=True)[:cfg["us_rank_pool"]]
    pool = set(ranked) | {r["stock_id"] for r in rows if r["coverage"] == "featured"}
    stale = datetime.now(timezone.utc) - timedelta(days=cfg["sic_recheck_days"])
    need = [r for r in rows if r["stock_id"] in pool and (r["sic"] is None or r["industry_checked_at"] is None
                                                            or r["industry_checked_at"] < stale)]
    upd, failed = [], 0
    for r in need:
        try:
            sic, desc = ref.get_sic(r["cik"])
        except ProviderError:
            failed += 1
            continue
        upd.append({"id": r["stock_id"], "sic": sic, "ind": (desc or "")[:64] or None, "sec": sector_for_sic(sic)})
    if upd:
        with engine.begin() as conn:
            conn.execute(text("""UPDATE stocks SET sic = :sic, industry = :ind, sector = :sec, industry_checked_at = now()
                                 WHERE stock_id = :id"""), upd)
    notes.append(f"미국 시가총액 {len(caps)}종목 중 상위 {len(ranked)} · SIC 조회 {len(need)}건(실패 {failed})")
    return {k: caps[k] for k in pool if k in caps}


# ---------------------------------------------------------------- 선정
def select_benchmark(engine: Engine, providers: Providers, *, today: date | None = None,
                     per_sector: int | None = None) -> dict:
    today = today or date.today()
    per_sector = per_sector or config()["per_sector"]
    out: dict = {"selected": [], "dropped": [], "by_sector": {}}
    with job_log(engine, source="INTERNAL", job_type="BENCHMARK", label="select") as res:
        res.notes.append("선정:")
        caps = classify_kr(engine, providers, today)
        caps.update(classify_us(engine, providers, today, res.notes))
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT s.stock_id, s.ticker, s.coverage, s.sector, m.country
                FROM stocks s JOIN markets m ON m.market_id = s.market_id
                WHERE s.is_active AND s.sector IS NOT NULL""")).mappings().all()
        chosen: list[int] = []
        universe: list[tuple[int, str]] = []          # (stock_id, sector) — 섹터 그룹 구성원
        for country in ("KR", "US"):
            for sec in sectors():
                grp = [r for r in rows if r["country"] == country and r["sector"] == sec.name]
                featured = [r["stock_id"] for r in grp if r["coverage"] == "featured"]
                others = sorted((r for r in grp if r["coverage"] != "featured" and r["stock_id"] in caps),
                                key=lambda r: caps[r["stock_id"]], reverse=True)
                pick = [r["stock_id"] for r in others[:max(0, per_sector - len(featured))]]
                chosen += pick
                universe += [(i, sec.name) for i in featured + pick]
                if featured or pick:
                    out["by_sector"][f"{sec.name}·{country}"] = f"노출 {len(featured)} + 비교군 {len(pick)}"
        with engine.begin() as conn:
            conn.execute(text("UPDATE stocks SET coverage = 'benchmark', is_active = true WHERE stock_id = ANY(:ids)"),
                         {"ids": chosen})
            # 빠진 비교군은 상장 종목 목록으로 돌아간다(검색·상세는 계속 됨). 관심종목·포트폴리오면 4시간 갱신 대상으로 남는다
            dropped = conn.execute(text("""UPDATE stocks SET coverage = 'listed'
                                           WHERE coverage = 'benchmark' AND NOT (stock_id = ANY(:ids))
                                           RETURNING ticker"""), {"ids": chosen}).scalars().all()
            upsert(conn, "peer_groups", [{"name": sec.name, "kind": "sector"} for sec in sectors()], ["name"],
                   update=["kind"])
            gid = dict(conn.execute(text("SELECT name, group_id FROM peer_groups WHERE kind = 'sector'")).all())
            conn.execute(text("UPDATE peer_group_members SET is_primary = false WHERE is_primary"))
            conn.execute(text("""DELETE FROM peer_group_members gm USING peer_groups g
                                 WHERE g.group_id = gm.group_id AND g.kind = 'sector'"""))
            upsert(conn, "peer_group_members", [{"group_id": gid[s], "stock_id": i, "is_primary": True} for i, s in universe],
                   ["group_id", "stock_id"], update=["is_primary"])
        map_ids(engine, providers, chosen, res.notes)
        with engine.connect() as conn:
            out["selected"] = list(conn.execute(text("SELECT ticker FROM stocks WHERE stock_id = ANY(:ids)"),
                                                {"ids": chosen}).scalars())
        out["dropped"] = list(dropped)
        res.rows = len(chosen)
        res.notes.append(", ".join(f"{k} {v}" for k, v in out["by_sector"].items()))
        if dropped:
            res.notes.append(f"비교군에서 빠짐 {len(dropped)}종목")
    return out


def map_ids(engine: Engine, providers: Providers, stock_ids: list[int], notes: list[str]) -> None:
    """새 비교군·상장 목록 종목의 DART 고유번호(KR)·SEC CIK(US). 매핑이 없으면 재무를 받을 수 없다."""
    with engine.connect() as conn:
        refs = stock_refs(conn, stock_ids=stock_ids)
    kr = [r for r in refs if r.country == "KR" and not r.corp_code]
    us = [r for r in refs if r.country == "US" and not r.cik]
    updates = []
    dart, sec = providers.kr_financial, providers.us_financial
    if kr and hasattr(dart, "corp_codes"):
        codes = dart.corp_codes({r.ticker for r in kr})
        updates += [{"id": r.stock_id, "corp": codes[r.ticker], "cik": None} for r in kr if r.ticker in codes]
    if us and hasattr(sec, "ciks"):
        ciks = sec.ciks({r.ticker for r in us})
        updates += [{"id": r.stock_id, "corp": None, "cik": ciks[r.ticker]} for r in us if r.ticker in ciks]
    if updates:
        with engine.begin() as conn:
            conn.execute(text("""UPDATE stocks SET corp_code = COALESCE(:corp, corp_code), cik = COALESCE(:cik, cik)
                                 WHERE stock_id = :id"""), updates)
    updated = {u["id"] for u in updates}
    unmapped = sorted(r.ticker for r in kr + us if r.stock_id not in updated)
    if unmapped:
        notes.append(f"고유번호/CIK 없음: {', '.join(unmapped)}")


def selection_due(engine: Engine, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    with engine.connect() as conn:
        last = conn.execute(text("""SELECT MAX(finished_at) FROM ingestion_logs
                                    WHERE job_type = 'BENCHMARK' AND status = 'SUCCESS' AND error LIKE '선정:%'""")).scalar()
        has_any = conn.execute(text("SELECT EXISTS (SELECT 1 FROM stocks WHERE coverage = 'benchmark')")).scalar()
    return not has_any or last is None or now - last > timedelta(days=config()["reselect_days"])


# ---------------------------------------------------------------- 평시 데이터
def load_benchmark(engine: Engine, providers: Providers, *, today: date | None = None) -> dict:
    """비교군 평시 데이터: 일봉 증분(대량), 최신 밸류에이션(대량·계산), 유효기간이 지난 재무만.
    재무는 노출·관심·포트폴리오 종목(5개년)도 함께 유효기간을 확인한다(4시간 갱신에는 재무가 없다)."""
    cfg, today = config(), today or date.today()
    with engine.connect() as conn:
        ids = [r.stock_id for r in stock_refs(conn, scope="benchmark")]
        frequent = [r.stock_id for r in stock_refs(conn, scope="frequent")]
        due_bench = freshness.due(conn, "financials", ids)
        due_freq = freshness.due(conn, "financials", frequent)
    out: dict = {"stocks": len(ids)}
    out["prices"] = jobs.load_prices_bulk(engine, providers, ids, history_days=cfg["price_days"], today=today)
    out["valuation"] = jobs.load_valuations_bulk(engine, providers, ids, today=today)
    out["financials"] = {}
    if due_bench:
        out["financials"].update(jobs.load_financials(engine, providers, years=cfg["fin_years"], stock_ids=due_bench))
    if due_freq:
        out["financials"].update(jobs.load_financials(engine, providers, years=FEATURED_FIN_YEARS, stock_ids=due_freq))
    out["pruned"] = prune_benchmark(engine, today)
    return out


def prune_benchmark(engine: Engine, today: date) -> int:
    """상세를 30일 넘게 열지 않은 비교군 종목은 평시 데이터(일봉 price_days, 밸류에이션 10일, FY fin_years)만 남긴다."""
    cfg = config()
    params = {"cut": today - timedelta(days=cfg["price_days"]), "vcut": today - timedelta(days=10),
              "years": cfg["fin_years"], "grace": f"{PRUNE_AFTER_DAYS} days"}
    target = f"""SELECT s.stock_id FROM stocks s WHERE s.coverage = 'benchmark' AND NOT {FREQUENT_SQL}
                 AND (s.detail_synced_at IS NULL OR s.detail_synced_at < now() - CAST(:grace AS interval))"""
    with engine.begin() as conn:
        n = conn.execute(text(f"DELETE FROM daily_prices WHERE trade_date < :cut AND stock_id IN ({target})"), params).rowcount
        n += conn.execute(text(f"""DELETE FROM valuation_snapshots v WHERE v.stock_id IN ({target})
            AND v.as_of < LEAST(:vcut, (SELECT MAX(x.as_of) FROM valuation_snapshots x WHERE x.stock_id = v.stock_id))"""),
            params).rowcount
        n += conn.execute(text(f"DELETE FROM disclosures WHERE stock_id IN ({target})"), params).rowcount
        n += conn.execute(text(f"""DELETE FROM financial_statements f WHERE f.stock_id IN ({target}) AND f.period_type = 'FY'
            AND f.period_end < (SELECT MIN(p) FROM (SELECT x.period_end AS p FROM financial_statements x
                                 WHERE x.stock_id = f.stock_id AND x.period_type = 'FY'
                                 ORDER BY x.period_end DESC LIMIT :years) t)"""), params).rowcount
    return n


# ---------------------------------------------------------------- 실행
def run_benchmark(engine: Engine, providers: Providers, scorer: Callable[[Engine], int] | None = None, *,
                  reselect: bool = False, today: date | None = None) -> dict | None:
    """선정(필요 시) → 평시 데이터 → 점수. 다른 프로세스가 실행 중이면 건너뛴다(None)."""
    with advisory_lock(engine, BENCHMARK_LOCK_KEY, wait=False) as got:
        if not got:
            log.info("비교군 갱신이 이미 실행 중 — 건너뜀")
            return None
        out: dict = {}
        with job_log(engine, source="INTERNAL", job_type="BENCHMARK", label="daily") as res:
            res.notes.append("일일:")
            try:                              # 상장 종목 목록을 먼저 맞춘다 — 비교군 선정 후보가 된다(실패해도 갱신은 계속)
                from app.ingest.listing import sync_listing
                out["listing"] = sync_listing(engine, providers, today=today)
            except Exception as e:  # noqa: BLE001 — 실패 사유는 sync_listing의 ingestion_logs 행에 남는다
                res.notes.append(f"상장 종목 목록 실패: {e}")
            if reselect or selection_due(engine):
                out["select"] = select_benchmark(engine, providers, today=today)
            out.update(load_benchmark(engine, providers, today=today))
            if scorer is not None:
                out["scores"] = scorer(engine)
            res.rows = out["stocks"]
            failed = sum(1 for k in ("prices", "valuation", "financials") for v in out[k].values() if v == "FAILED")
            res.notes.append(f"종목 {out['stocks']}, 실패 {failed}, 정리 {out['pruned']}행")
        return out
