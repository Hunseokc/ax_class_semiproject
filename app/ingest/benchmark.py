"""매력도 비교군(benchmark) — 점수 계산 표본을 넓히기 위한 종목들. 화면 기본 목록에는 나오지 않는다(docs/09 9절).

- 선정: 국가·섹터마다 노출 종목 + 후보(config/universe.yaml benchmark_candidates) 중 시가총액 상위
  (per_sector − 노출 종목 수)개. reselect_days(30일)마다 다시 고르고, 빠진 종목은 is_active = false
  (관심종목·포트폴리오에 있으면 계속 활성)
- 평시 데이터(1일 1회): 일봉 price_days(400일) 증분, 최신 밸류에이션, FY fin_years(3)개년 — 재무는 새 결산기가
  나왔을 법할 때만 확인한다(DART 호출 절약). 상세 화면을 열지 않은 지 30일이 지나면 그 밖의 데이터는 정리
- 공시·2년 일봉·5개년 재무는 상세 화면을 열거나 관심종목에 추가할 때만 받는다(app/services/hydration.py)
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import Engine, text

from app.ingest import jobs
from app.ingest.store import BENCHMARK_LOCK_KEY, advisory_lock, job_log, upsert
from app.ingest.universe import FREQUENT_SQL, load_universe, stock_refs, yf_symbol
from app.providers.base import StockRef
from app.providers.factory import Providers

log = logging.getLogger(__name__)
PRUNE_AFTER_DAYS = 30           # 상세를 마지막으로 받은 뒤 이 기간이 지나면 평시 데이터만 남긴다


def config() -> dict:
    return load_universe()["benchmark"]


def candidates_from_config() -> list[dict]:
    return [{"group": g, "country": country, **c}
            for g, by_country in load_universe()["benchmark_candidates"].items()
            for country, items in by_country.items() for c in items]


# ---------------------------------------------------------------- 선정
def select_benchmark(engine: Engine, providers: Providers, *, today: date | None = None,
                     candidates: list[dict] | None = None, per_sector: int | None = None) -> dict:
    today = today or date.today()
    candidates = candidates if candidates is not None else candidates_from_config()
    per_sector = per_sector or config()["per_sector"]
    out: dict = {"selected": [], "by_group": {}, "no_market_cap": []}
    with job_log(engine, source="INTERNAL", job_type="BENCHMARK", label="select") as res:
        res.notes.append("선정:")
        with engine.connect() as conn:
            featured = conn.execute(text("""
                SELECT g.name AS grp, m.country, COUNT(*) AS n
                FROM stocks s JOIN markets m ON m.market_id = s.market_id
                JOIN peer_group_members gm ON gm.stock_id = s.stock_id AND gm.is_primary
                JOIN peer_groups g ON g.group_id = gm.group_id
                WHERE s.coverage = 'featured' AND s.is_active GROUP BY g.name, m.country""")).all()
            n_featured = {(r.grp, r.country): r.n for r in featured}
            market_id = dict(conn.execute(text("SELECT code, market_id FROM markets")).all())
            group_id = dict(conn.execute(text("SELECT name, group_id FROM peer_groups")).all())
        caps: dict[tuple[str, str], object] = {}
        for country in ("KR", "US"):
            refs = [StockRef(stock_id=0, market=c["market"], country=country, ticker=str(c["ticker"]),
                             yf_symbol=yf_symbol(c["market"], str(c["ticker"])), timezone="")
                    for c in candidates if c["country"] == country]
            caps.update({(country, t): v for t, v in providers.market_caps(country, refs, today).items()})
        chosen = []
        for key in sorted({(c["group"], c["country"]) for c in candidates}):
            pool = [c for c in candidates if (c["group"], c["country"]) == key]
            out["no_market_cap"] += [f"{c['ticker']}" for c in pool if not caps.get((key[1], str(c["ticker"])))]
            room = max(0, per_sector - n_featured.get(key, 0))
            ranked = sorted((c for c in pool if caps.get((key[1], str(c["ticker"])))),
                            key=lambda c: caps[(key[1], str(c["ticker"]))], reverse=True)[:room]
            chosen += ranked
            out["by_group"][f"{key[0]}·{key[1]}"] = f"노출 {n_featured.get(key, 0)} + 비교군 {len(ranked)}"
        with engine.begin() as conn:
            upsert(conn, "stocks", [
                {"market_id": market_id[c["market"]], "ticker": str(c["ticker"]), "name": c["name"],
                 "name_en": c["name"] if c["country"] == "US" else None, "coverage": "benchmark", "is_active": True}
                for c in chosen], ["market_id", "ticker"], update=["name", "is_active"])
            ids = {(r[0], r[1]): r[2] for r in conn.execute(text(
                "SELECT m.code, s.ticker, s.stock_id FROM stocks s JOIN markets m ON m.market_id = s.market_id"))}
            chosen_ids = [ids[(c["market"], str(c["ticker"]))] for c in chosen]
            upsert(conn, "peer_group_members", [
                {"group_id": group_id[c["group"]], "stock_id": ids[(c["market"], str(c["ticker"]))], "is_primary": True}
                for c in chosen], ["group_id", "stock_id"], update=["is_primary"])
            dropped = conn.execute(text(f"""
                UPDATE stocks s SET is_active = false
                WHERE s.coverage = 'benchmark' AND s.is_active AND NOT (s.stock_id = ANY(:ids)) AND NOT {FREQUENT_SQL}
                RETURNING s.ticker"""), {"ids": chosen_ids}).scalars().all()
        _map_ids(engine, providers, chosen_ids, res.notes)
        out["selected"] = [str(c["ticker"]) for c in chosen]
        out["dropped"] = list(dropped)
        res.rows = len(chosen)
        res.notes.append(", ".join(f"{k} {v}" for k, v in out["by_group"].items()))
        if out["no_market_cap"]:
            res.notes.append(f"시가총액 없음(제외): {', '.join(out['no_market_cap'])}")
        if dropped:
            res.notes.append(f"비교군에서 빠짐: {', '.join(dropped)}")
    return out


def _map_ids(engine: Engine, providers: Providers, stock_ids: list[int], notes: list[str]) -> None:
    """새 비교군 종목의 DART 고유번호(KR)·SEC CIK(US). 매핑이 없으면 재무를 받을 수 없다."""
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
def financials_due(engine: Engine, stock_ids: list[int], today: date, now: datetime | None = None) -> list[int]:
    """최신 FY가 없거나 오래돼 새 사업보고서가 나왔을 법하고, 최근 fin_retry_days 안에 확인하지 않은 종목."""
    cfg, now = config(), now or datetime.now(timezone.utc)
    if not stock_ids:
        return []
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT s.stock_id,
                   (SELECT MAX(f.period_end) FROM financial_statements f
                     WHERE f.stock_id = s.stock_id AND f.period_type = 'FY') AS latest,
                   (SELECT MAX(l.finished_at) FROM ingestion_logs l
                     WHERE l.stock_id = s.stock_id AND l.job_type = 'FINANCIALS') AS tried
            FROM stocks s WHERE s.stock_id = ANY(:ids)"""), {"ids": stock_ids}).all()
    stale = timedelta(days=cfg["fin_refresh_days"])
    retry = timedelta(days=cfg["fin_retry_days"])
    return [r.stock_id for r in rows
            if (r.latest is None or today - r.latest > stale) and (r.tried is None or now - r.tried > retry)]


def load_benchmark(engine: Engine, providers: Providers, *, today: date | None = None) -> dict:
    cfg, today = config(), today or date.today()
    with engine.connect() as conn:
        ids = [r.stock_id for r in stock_refs(conn, scope="benchmark")]
    out = {"stocks": len(ids)}
    out["prices"] = jobs.load_prices(engine, providers, scope="benchmark", history_days=cfg["price_days"], today=today)
    # 밸류에이션은 최신값만 필요 → 처음이면 최근 10일만(국내는 일별, 미국은 스냅샷 1행)
    out["valuation"] = jobs.load_valuations(engine, providers, scope="benchmark", history_days=10, today=today)
    due = financials_due(engine, ids, today)
    out["financials"] = jobs.load_financials(engine, providers, years=cfg["fin_years"], stock_ids=due) if due else {}
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
            if reselect or selection_due(engine):
                out["select"] = select_benchmark(engine, providers, today=today)
            out.update(load_benchmark(engine, providers, today=today))
            if scorer is not None:
                out["scores"] = scorer(engine)
            res.rows = out["stocks"]
            failed = sum(1 for k in ("prices", "valuation", "financials") for v in out[k].values() if v == "FAILED")
            res.notes.append(f"종목 {out['stocks']}, 실패 {failed}, 정리 {out['pruned']}행")
        return out
