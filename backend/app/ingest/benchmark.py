"""매력도 비교군(benchmark) — 점수 계산 표본을 넓히기 위한 종목들. 화면 기본 목록에는 나오지 않는다(개발산출물/09 11절).

- 선정: 업종 코드(국내 DART KSIC·미국 SEC SIC)로 상장 종목마다 주 테마를 정하고(app/ingest/sectors.py),
  국가·테마마다 노출 종목 + 같은 주 테마 상장 종목 중 시가총액 상위 (per_sector − 노출 종목 수)개.
  reselect_days(30일)마다 다시 고르고, 빠진 종목은 coverage = 'listed'로 돌아간다(데이터는 보존)
- 평시 데이터(1일 1회): 일봉은 국내 날짜별 전 종목·미국 묶음 다운로드로 증분, 최신 밸류에이션,
  재무는 유효기간(data_freshness — 공시 일정 기반 + 90일 상한)이 지난 종목만. 상세 화면을 열지 않은 지 30일이 지나면 그 밖의 데이터는 정리
- 공시·2년 일봉·5개년 재무는 상세 화면을 열거나 관심종목에 추가할 때 유효기간이 지난 것만 받는다(app/services/hydration.py)
- 업종 섹터(stocks.sector) = 주 테마의 섹터. 시장·섹터 점수의 섹터 흐름 표본이 된다(app/services/market_condition.py)
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import Engine, text

from app.ingest import jobs
from app.ingest.sectors import assign_themes
from app.ingest.store import BENCHMARK_LOCK_KEY, advisory_lock, job_log
from app.ingest.universe import FREQUENT_SQL, load_universe, stock_refs
from app.providers.base import ProviderError
from app.providers.factory import Providers
from app.services import freshness

log = logging.getLogger(__name__)
PRUNE_AFTER_DAYS = 30           # 상세를 마지막으로 받은 뒤 이 기간이 지나면 평시 데이터만 남긴다
FEATURED_FIN_YEARS = jobs.FIN_YEARS


def config() -> dict:
    return load_universe().benchmark


# ---------------------------------------------------------------- 업종 코드
def classify_industries(engine: Engine, providers: Providers, notes: list[str]) -> None:
    """업종 코드 → stocks.ksic(국내 DART 기업개황)·sic(미국 SEC). 코드를 확인한 지 industry_recheck_days가 지난
    활성 종목만, 국가별 classify_per_run개까지(노출 → 비교군 → 시가총액 순위 순). 국내는 고유번호, 미국은 CIK가 있고
    노출·비교군이거나 시가총액 순위(cap_rank) 안인 종목. 코드가 없다고 답한 종목도 확인 시각을 남겨 다시 묻지 않는다."""
    cfg = config()
    params = {"d": cfg["industry_recheck_days"], "n": cfg["classify_per_run"]}
    due = """s.is_active AND (s.industry_checked_at IS NULL OR s.industry_checked_at < now() - make_interval(days => :d))"""
    first = "ORDER BY (s.coverage = 'featured') DESC, (s.coverage = 'benchmark') DESC, s.cap_rank NULLS LAST, s.stock_id LIMIT :n"
    counts = {}
    for country, ref, sql_need, fetch in (
            ("KR", providers.kr_reference,
             f"""SELECT s.stock_id, s.corp_code AS key FROM stocks s JOIN markets m ON m.market_id = s.market_id
                 WHERE m.country = 'KR' AND s.corp_code IS NOT NULL AND {due} {first}""",
             lambda ref, key: {"ksic": ref.get_ksic(key)}),
            ("US", providers.us_reference,
             f"""SELECT s.stock_id, s.cik AS key FROM stocks s JOIN markets m ON m.market_id = s.market_id
                 WHERE m.country = 'US' AND s.cik IS NOT NULL AND {due}
                   AND (s.coverage IN ('featured', 'benchmark') OR s.cap_rank IS NOT NULL) {first}""",
             lambda ref, key: dict(zip(("sic", "ind"), ref.get_sic(key))))):
        if ref is None:
            continue
        with engine.connect() as conn:
            need = conn.execute(text(sql_need), params).all()
        upd, failed = [], 0
        for sid, key in need:
            try:
                upd.append({"id": sid, "ksic": None, "sic": None, "ind": None, **fetch(ref, key)})
            except ProviderError:
                failed += 1
        if upd:
            col = "ksic = :ksic" if country == "KR" else "sic = :sic, industry = COALESCE(LEFT(:ind, 64), industry)"
            with engine.begin() as conn:
                conn.execute(text(f"UPDATE stocks SET {col}, industry_checked_at = now() WHERE stock_id = :id"), upd)
        counts[country] = f"{len(upd)}" + (f"(실패 {failed})" if failed else "")
    notes.append("업종 코드: " + (" · ".join(f"{'국내 KSIC' if c == 'KR' else '미국 SIC'} {v}" for c, v in counts.items())
                                  or "provider 없음"))


# ---------------------------------------------------------------- 선정
def selection_order(engine: Engine, providers: Providers) -> dict[int, tuple[int, float]]:
    """비교군 선정 순서 {stock_id: 정렬 키(클수록 앞)}.
    국내: KRX 전 종목 시가총액(최근 거래일 1회 조회) — 대량 provider가 없거나 실패하면 DB 최신 시가총액.
    미국: stocks.cap_rank(작을수록 앞) — 순위가 없는 종목은 DB 최신 시가총액으로 그 뒤에 둔다."""
    with engine.connect() as conn:
        tickers = {r.ticker: r.stock_id for r in conn.execute(text("""
            SELECT s.ticker, s.stock_id FROM stocks s JOIN markets m ON m.market_id = s.market_id
            WHERE m.country = 'KR' AND s.is_active"""))}
        db_caps = dict(conn.execute(text("""
            SELECT s.stock_id, v.market_cap FROM stocks s
            JOIN LATERAL (SELECT x.market_cap FROM valuation_snapshots x WHERE x.stock_id = s.stock_id AND x.market_cap > 0
                          ORDER BY x.as_of DESC LIMIT 1) v ON true WHERE s.is_active""")).all())
        ranks = dict(conn.execute(text("SELECT stock_id, cap_rank FROM stocks WHERE is_active AND cap_rank IS NOT NULL")).all())
    order = {sid: (0, float(cap)) for sid, cap in db_caps.items()}
    if providers.kr_bulk is not None:
        day = jobs.last_closed_day("KR")
        for back in range(8):                         # 휴장일이면 결과가 비어 하루씩 앞으로
            try:
                vals = providers.kr_bulk.get_valuations_by_date(day - timedelta(days=back))
            except ProviderError as e:
                log.warning("국내 시가총액 조회 실패 %s: %s", day - timedelta(days=back), e)
                continue
            if vals:
                order.update({tickers[t]: (0, float(v.market_cap)) for t, v in vals.items() if t in tickers and v.market_cap})
                break
    order.update({sid: (1, -float(rank)) for sid, rank in ranks.items()})
    return order


# 거래정지(R4-7, 09 2절): 마지막 일봉이 같은 국가 비교 표본의 최근 21번째 거래일보다 앞선 종목 — score_metrics.sql과 같은 기준
HALTED_SQL = """
WITH cal AS (
    SELECT x.country, x.trade_date, ROW_NUMBER() OVER (PARTITION BY x.country ORDER BY x.trade_date DESC) AS rk
    FROM (SELECT DISTINCT m.country, d.trade_date
          FROM daily_prices d
          JOIN stocks s  ON s.stock_id = d.stock_id AND s.is_active AND s.coverage <> 'listed'
          JOIN markets m ON m.market_id = s.market_id
          WHERE d.trade_date >= CURRENT_DATE - 120) x
)
SELECT lp.stock_id FROM v_latest_price lp
JOIN cal c ON c.country = lp.country AND c.rk = 21
WHERE lp.trade_date < c.trade_date"""


def halted_ids(engine: Engine, providers: Providers) -> set[int]:
    """비교군에서 뺄 거래정지 종목: DB 마지막 일봉이 20거래일 넘게 앞섬 + 국내는 최근 거래일 전 종목 일봉의 거래량 0."""
    with engine.connect() as conn:
        out = set(conn.execute(text(HALTED_SQL)).scalars())
        kr = dict(conn.execute(text("""SELECT s.ticker, s.stock_id FROM stocks s JOIN markets m ON m.market_id = s.market_id
                                       WHERE m.country = 'KR' AND s.is_active""")).all())
    if providers.kr_bulk is not None:
        day = jobs.last_closed_day("KR")
        for back in range(8):                         # 휴장일이면 결과가 비어 하루씩 앞으로
            try:
                bars = providers.kr_bulk.get_bars_by_date(day - timedelta(days=back))
            except ProviderError as e:
                log.warning("국내 일봉 조회 실패 %s: %s", day - timedelta(days=back), e)
                continue
            if bars:
                out |= {kr[t] for t, b in bars.items() if t in kr and not b.volume}
                break
    return out


def select_benchmark(engine: Engine, providers: Providers, *, per_sector: int | None = None) -> dict:
    """업종 코드 확인 → 주 테마·보조 테마 지정 → 국가·테마별 시가총액 상위로 비교군 선정.
    점수를 내지 않는 테마(scoring none — 리츠)와 거래정지 종목(halted_ids, R4-7)은 고르지 않는다.
    재무·공시를 받으려면 고유번호(국내)·CIK(미국)가 있어야 한다.
    회사(고유번호·CIK)당 1종목만 — 같은 회사의 다른 주식 종류·채권형 상장(GOOG, TMUSI 등)이 표본을 겹치지 않게."""
    per_sector = per_sector or config()["per_sector"]
    out: dict = {"selected": [], "by_group": {}}
    with job_log(engine, source="INTERNAL", job_type="BENCHMARK", label="select") as res:
        res.notes.append("선정:")
        classify_industries(engine, providers, res.notes)
        with engine.begin() as conn:
            res.notes.append("테마: 주 {primary} · 보조 {secondary}".format(**assign_themes(conn)))
            pool = conn.execute(text("""
                SELECT s.stock_id, s.ticker, s.coverage, m.country, t.theme,
                       CASE WHEN m.country = 'KR' THEN s.corp_code ELSE s.cik END AS company
                FROM stocks s
                JOIN markets m        ON m.market_id = s.market_id
                JOIN v_stock_theme t  ON t.stock_id = s.stock_id AND t.family <> 'none'
                WHERE s.is_active
                  AND (s.coverage = 'featured' OR CASE WHEN m.country = 'KR' THEN s.corp_code ELSE s.cik END IS NOT NULL)
                ORDER BY t.theme, m.country""")).all()
        order = selection_order(engine, providers)
        halted = halted_ids(engine, providers)
        res.notes.append(f"거래정지 제외 {len(halted)}")
        groups: dict[tuple[str, str], list] = {}
        for r in pool:
            if r.stock_id in halted:
                continue
            groups.setdefault((r.theme, r.country), []).append(r)
        chosen = []
        taken = {(r.country, r.company) for r in pool if r.coverage == "featured" and r.company}
        for (theme, country), rows in groups.items():
            n_featured = sum(1 for r in rows if r.coverage == "featured")
            ranked = []
            for r in sorted((r for r in rows if r.coverage != "featured" and r.stock_id in order),
                            key=lambda r: order[r.stock_id], reverse=True):
                if len(ranked) >= per_sector - n_featured:
                    break
                if (country, r.company) not in taken:
                    taken.add((country, r.company))
                    ranked.append(r)
            chosen += ranked
            out["by_group"][f"{theme}·{country}"] = f"노출 {n_featured} + 비교군 {len(ranked)}"
        chosen_ids = [r.stock_id for r in chosen]
        with engine.begin() as conn:
            conn.execute(text("UPDATE stocks SET coverage = 'benchmark' WHERE stock_id = ANY(:ids) AND coverage = 'listed'"),
                         {"ids": chosen_ids})
            # 비교 표본의 재무는 한 경로(API)로만(D-039): 일괄 경로 임시 값·경로 기록이 없는 옛 재무는 만료시켜 아래
            # 재무 갱신이 다시 받게 한다(분기·추가 계정도 이때 들어온다)
            res.notes.append("재무 경로 만료 {}".format(conn.execute(text("""
                UPDATE data_freshness f SET valid_until = f.fetched_at
                WHERE f.kind = 'financials' AND f.stock_id = ANY(:ids) AND f.valid_until > f.fetched_at
                  AND EXISTS (SELECT 1 FROM financial_statements x WHERE x.stock_id = f.stock_id AND x.period_type = 'FY'
                                AND (x.notes IS NULL OR x.notes LIKE 'path=DART_BULK%' OR x.notes LIKE 'path=SEC_FRAMES%'))"""),
                {"ids": chosen_ids}).rowcount))
            # 빠진 비교군은 상장 목록 종목으로 돌아간다(데이터는 보존). 관심종목·포트폴리오에 있으면 4시간 갱신 대상으로 남는다
            dropped = conn.execute(text("""
                UPDATE stocks s SET coverage = 'listed'
                WHERE s.coverage = 'benchmark' AND NOT (s.stock_id = ANY(:ids)) RETURNING s.ticker"""),
                {"ids": chosen_ids}).scalars().all()
        map_ids(engine, providers, chosen_ids, res.notes)
        out["selected"] = [r.ticker for r in chosen]
        out["dropped"] = list(dropped)
        res.rows = len(chosen)
        res.notes.append(", ".join(f"{k} {v}" for k, v in out["by_group"].items()))
        if dropped:
            res.notes.append(f"비교군에서 빠짐 {len(dropped)}: {', '.join(dropped[:30])}{' …' if len(dropped) > 30 else ''}")
    return out


def map_ids(engine: Engine, providers: Providers, stock_ids: list[int], notes: list[str]) -> None:
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
def load_benchmark(engine: Engine, providers: Providers, *, today: date | None = None) -> dict:
    """비교군 평시 데이터: 일봉 증분(대량), 최신 밸류에이션(대량), 유효기간이 지난 재무만.
    재무는 노출·관심·포트폴리오 종목(5개년)도 함께 유효기간을 확인한다(4시간 갱신에는 재무가 없다)."""
    cfg, today = config(), today or date.today()
    with engine.connect() as conn:
        ids = [r.stock_id for r in stock_refs(conn, scope="benchmark")]
        frequent = [r.stock_id for r in stock_refs(conn, scope="frequent")]
        due_bench = freshness.due(conn, "financials", ids, limit=cfg["fin_daily_budget"])   # 실적 시즌에도 하루 작업량 일정
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
    """상세를 30일 넘게 열지 않은 비교군 종목은 평시 데이터(일봉 price_days, 밸류에이션 10일, FY fin_years,
    분기 FIN_QUARTERS)만 남긴다."""
    cfg = config()
    params = {"cut": today - timedelta(days=cfg["price_days"]), "vcut": today - timedelta(days=10),
              "years": cfg["fin_years"], "quarters": jobs.FIN_QUARTERS, "grace": f"{PRUNE_AFTER_DAYS} days"}
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
        n += conn.execute(text(f"""DELETE FROM financial_statements f WHERE f.stock_id IN ({target}) AND f.period_type <> 'FY'
            AND f.period_end < (SELECT MIN(p) FROM (SELECT x.period_end AS p FROM financial_statements x
                                 WHERE x.stock_id = f.stock_id AND x.period_type <> 'FY'
                                 ORDER BY x.period_end DESC LIMIT :quarters) t)"""), params).rowcount
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
            try:                              # 새 사업보고서를 낸 종목의 재무를 먼저 만료시킨다 → 아래 재무 갱신 대상
                out["feed"] = jobs.load_dart_feed(engine, providers, today=today)
            except Exception as e:  # noqa: BLE001 — 실패 사유는 load_dart_feed의 ingestion_logs 행에 남는다
                res.notes.append(f"공시 증분 실패: {e}")
            if reselect or selection_due(engine):
                out["select"] = select_benchmark(engine, providers)
            out.update(load_benchmark(engine, providers, today=today))
            if scorer is not None:
                out["scores"] = scorer(engine)
            res.rows = out["stocks"]
            failed = sum(1 for k in ("prices", "valuation", "financials") for v in out[k].values() if v == "FAILED")
            res.notes.append(f"종목 {out['stocks']}, 실패 {failed}, 정리 {out['pruned']}행")
        return out
