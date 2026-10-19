"""수집·적재 CLI.

    python -m app.ingest init-db [--reset]   # db/schema.sql → indexes.sql → views.sql(있을 때만) (+ 매력도 프리셋)
    python -m app.ingest migrate 001_scoring_v2   # db/migrations/<이름>.sql을 기존 DB에 적용
    python -m app.ingest master [--offline]  # universe.yaml → 마스터, DART corp_code·SEC CIK 매핑, demo 사용자
    python -m app.ingest import-sample       # sample_data/*.csv → 시세·지수·환율·밸류에이션 (수집이 안 될 때 대체)
    python -m app.ingest prices [--full] [--tickers 005930 AAPL]   # 종목 일봉 (국내 pykrx, 미국 yfinance)
    python -m app.ingest indices [--full]
    python -m app.ingest fx [--full]         # USD/KRW DAILY
    python -m app.ingest valuation [--full] [--tickers 005930 AAPL]   # 국내 pykrx 일별, 미국 yfinance 스냅샷
    python -m app.ingest financials [--years 5] [--tickers 005930 AAPL]   # FY 재무 (국내 DART, 미국 SEC)
    python -m app.ingest disclosures [--days 365] [--tickers 005930]      # 최근 공시
    python -m app.ingest all                 # master → prices → indices → fx → financials → valuation → disclosures
    python -m app.ingest scores              # 매력도 점수 재생성 (오늘 as_of, DELETE 후 INSERT)
    python -m app.ingest explain             # 인덱스 전후 EXPLAIN 비교 → docs/explain_result.md
    python -m app.ingest seed-demo           # demo 관심종목 8건 + 모의 포트폴리오 2개
    python -m app.ingest status              # 테이블별 행 수·기간·최근 실패
    python -m app.ingest refresh             # POST /market/refresh와 같은 TTL 갱신 (cron용)
    python -m app.ingest benchmark [--reselect]   # 매력도 비교군: 선정(30일마다/강제) → 평시 데이터 → 점수
    python -m app.ingest hydrate 042700      # 비교군 종목 상세(공시·2년 일봉·5개년 재무) 받기
    python -m app.ingest listing             # 상장 보통주 목록(국내 pykrx·미국 SEC) → 검색용 마스터(coverage=listed)
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_engine
from app.core.logging import setup_logging
from app.ingest import jobs, sample


# ── [S5-C] 데이터 상태 ──
def status(engine) -> None:
    q = {
        "markets": "SELECT count(*) FROM markets",
        "stocks": "SELECT count(*) FROM stocks",
        "peer_groups / members": "SELECT (SELECT count(*) FROM peer_groups) || ' / ' || (SELECT count(*) FROM peer_group_members)",
        "daily_prices": "SELECT count(*) || '  (' || min(trade_date) || ' ~ ' || max(trade_date) || ')' FROM daily_prices",
        "  종목당 봉 수 min/avg/max": """SELECT min(c) || ' / ' || round(avg(c)) || ' / ' || max(c)
                                     FROM (SELECT count(*) c FROM daily_prices GROUP BY stock_id) t""",
        "index_daily_prices": "SELECT count(*) || '  (' || min(trade_date) || ' ~ ' || max(trade_date) || ')' FROM index_daily_prices",
        "fx_rates DAILY": "SELECT count(*) || '  (' || min(rate_at AT TIME ZONE 'Asia/Seoul')::date || ' ~ ' || max(rate_at AT TIME ZONE 'Asia/Seoul')::date || ')' FROM fx_rates WHERE granularity='DAILY'",
        "fx_rates SNAPSHOT": "SELECT count(*) FROM fx_rates WHERE granularity='SNAPSHOT'",
        "valuation_snapshots": """SELECT (SELECT count(*) FROM valuation_snapshots) || '  (' ||
                                  (SELECT string_agg(source || ' ' || n, ', ' ORDER BY source)
                                   FROM (SELECT source, count(*) n FROM valuation_snapshots GROUP BY source) t) || ')'""",
        "financial_statements FY": "SELECT count(*) FROM financial_statements WHERE period_type='FY'",
        "  종목당 FY min/max": """SELECT min(c) || ' / ' || max(c) FROM (SELECT count(*) c FROM financial_statements
                                WHERE period_type='FY' GROUP BY stock_id) t""",
        "disclosures": "SELECT count(*) || '  (DART ' || count(*) FILTER (WHERE data_source='DART') || ', SEC ' || count(*) FILTER (WHERE data_source='SEC') || ')' FROM disclosures",
        "users / watchlist / portfolios / items": """SELECT (SELECT count(*) FROM users) || ' / ' || (SELECT count(*) FROM watchlist_items)
                                    || ' / ' || (SELECT count(*) FROM portfolios) || ' / ' || (SELECT count(*) FROM portfolio_items)""",
        "ingestion_logs (S/F/K)": """SELECT count(*) FILTER (WHERE status='SUCCESS') || ' / ' || count(*) FILTER (WHERE status='FAILED')
                                    || ' / ' || count(*) FILTER (WHERE status='SKIPPED') FROM ingestion_logs""",
    }
    with engine.connect() as conn:
        for label, sql in q.items():
            print(f"{label:<40} {conn.execute(text(sql)).scalar()}")
        fails = conn.execute(text("""
            SELECT l.job_type, coalesce(s.ticker, '-'), l.finished_at::timestamp(0), left(split_part(l.error, chr(10), 1), 160) FROM ingestion_logs l LEFT JOIN stocks s USING (stock_id)
            WHERE l.status = 'FAILED' ORDER BY l.log_id DESC LIMIT 10""")).all()
        if fails:
            print("\n최근 실패:")
            for f in fails:
                print("  ", *f)
        # GET /api/v1/statistics/data-quality와 같은 기준(app/services/data_quality.py)
        from app.core.config import get_settings
        from app.services.data_quality import data_quality
        dq = data_quality(conn, days=7, ttl_hours=get_settings().refresh_ttl_hours)
        t = dq["totals"]
        print(f"\n데이터 품질 (최근 {dq['days']}일): 성공 {t['success']} / 실패 {t['failed']} / 부분 실패 {t['partial']}"
              f" / 건너뜀 {t['skipped']} / 격리 {t['quarantined_rows']}행")
        if dq["stale_jobs"]:
            print(f"   오래된 갱신 작업(TTL×2 = {dq['stale_after_hours']:g}시간 초과):",
                  ", ".join(f"{s['job_type']}(" + (f"{s['hours_since_success']}시간 전" if s["hours_since_success"] is not None
                                                     else "작업 단위 성공 기록 없음") + ")" for s in dq["stale_jobs"]))
        else:
            print(f"   오래된 갱신 작업 없음 (기준 TTL×2 = {dq['stale_after_hours']:g}시간)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.ingest")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db").add_argument("--reset", action="store_true", help="스키마를 지우고 다시 만든다")
    sub.add_parser("migrate").add_argument("name", help="db/migrations/<name>.sql")
    sub.add_parser("master").add_argument("--offline", action="store_true", help="DART/SEC 매핑 생략")
    sub.add_parser("import-sample")
    # ── [S1-D] 시세 수집 ──
    p = sub.add_parser("prices")
    p.add_argument("--full", action="store_true")
    p.add_argument("--tickers", nargs="*")
    for name in ("indices", "fx"):
        sub.add_parser(name).add_argument("--full", action="store_true")
    # ── [S2-D] 데모 데이터 ──
    sub.add_parser("seed-demo")
    # ── [S3-B] 재무·공시 ──
    p = sub.add_parser("financials")
    p.add_argument("--years", type=int, default=jobs.FIN_YEARS)
    p.add_argument("--tickers", nargs="*")
    p = sub.add_parser("disclosures")
    p.add_argument("--days", type=int, default=jobs.DISCLOSURE_DAYS)
    p.add_argument("--tickers", nargs="*")
    # ── [S3-D] 갱신 ──
    sub.add_parser("refresh")
    # ── [S3-C] 밸류에이션·전체 적재 ──
    p = sub.add_parser("valuation")
    p.add_argument("--full", action="store_true")
    p.add_argument("--tickers", nargs="*")
    sub.add_parser("all")
    # ── [S4-C] 매력도 ──
    for name in ("scores", "explain"):
        sub.add_parser(name)
    # ── [S4-D] 비교군 ──
    sub.add_parser("benchmark").add_argument("--reselect", action="store_true", help="시가총액 순위로 지금 다시 고른다")
    sub.add_parser("hydrate").add_argument("tickers", nargs="+")
    # ── [S5-C] 데이터 상태 ──
    sub.add_parser("status")
    # ── [S6-B] 상장 목록 ──
    sub.add_parser("listing")
    # ── 추가 기능 4-1: 공시 목록 증분 · 재무 일괄 첫 적재 ──
    sub.add_parser("dart-feed")
    sub.add_parser("background", help="listed 종목 재무를 하루 예산만큼 우선순위대로 (평소에는 스케줄러가 08:00 이후)")
    p = sub.add_parser("dart-bulk", help="OpenDART 재무정보 일괄다운로드(사업보고서 BS·PL zip/txt) 첫 적재")
    p.add_argument("--as-of", type=date.fromisoformat, required=True, help="파일 기준일 — 공시 증분이 이 날부터 이어 받는다")
    p.add_argument("--years", type=int, default=4)
    p.add_argument("files", nargs="+", type=Path)
    args = ap.parse_args(argv)

    setup_logging(get_settings().log_level)
    engine = get_engine()
    t0 = time.monotonic()

    def providers():
        # pykrx·yfinance import가 느리고 KRX 로그인이 필요하므로 수집 명령에서만 만든다
        from app.providers.factory import default_providers
        return default_providers()

    if args.cmd == "init-db":
        jobs.init_db(engine, reset=args.reset)
    elif args.cmd == "migrate":
        jobs.migrate(engine, args.name)
    elif args.cmd == "master":
        jobs.load_master(engine, offline=args.offline)
    elif args.cmd == "import-sample":
        for k, v in sample.import_sample(engine).items():
            print(f"{k}: {v} rows")
    # ── [S1-D] 시세 수집 ──
    elif args.cmd == "prices":
        jobs.load_prices(engine, providers(), full=args.full, tickers=args.tickers)
    elif args.cmd == "indices":
        jobs.load_indices(engine, providers(), full=args.full)
    elif args.cmd == "fx":
        jobs.load_fx_daily(engine, providers(), full=args.full)
    # ── [S2-D] 데모 데이터 ──
    elif args.cmd == "seed-demo":
        from app.ingest.demo import seed_demo
        print(seed_demo(engine, providers()))
    # ── [S3-B] 재무·공시 ──
    elif args.cmd == "financials":
        jobs.load_financials(engine, providers(), years=args.years, tickers=args.tickers)
    elif args.cmd == "disclosures":
        jobs.load_disclosures(engine, providers(), days=args.days, tickers=args.tickers)
    # ── [S3-D] 갱신 ──
    elif args.cmd == "refresh":
        # 갱신 정책은 API(POST /market/refresh)와 같다: 작업별 TTL 이내면 SKIPPED
        from app.api.deps import get_scorer
        from app.services.fx import FxService
        from app.services.refresh import RefreshService
        from app.services.sectors import load_sectors
        pv = providers()
        ttl = get_settings().refresh_ttl_hours
        result = RefreshService(engine, pv, FxService(engine, pv.fx, ttl), ttl, scorer=get_scorer(),
                                sector_loader=load_sectors).refresh()
        for j in result.jobs:
            print(f"{j.job_type:<10} {j.status:<8} {j.detail or ''}")
        print("next_refresh_available_at:", result.next_refresh_available_at.isoformat())
    # ── [S3-C] 밸류에이션·전체 적재 ──
    elif args.cmd == "valuation":
        jobs.load_valuations(engine, providers(), full=args.full, tickers=args.tickers)
    elif args.cmd == "all":
        pv = providers()
        jobs.load_master(engine)
        jobs.load_prices(engine, pv)
        jobs.load_indices(engine, pv)
        jobs.load_fx_daily(engine, pv)
        jobs.load_financials(engine, pv)      # DERIVED 밸류에이션 대체 시 재무가 먼저 필요
        jobs.load_valuations(engine, pv)
        jobs.load_disclosures(engine, pv)
    # ── [S4-C] 매력도 ──
    elif args.cmd == "scores":
        from app.services.scoring import compute_scores
        print("stock_scores rows:", compute_scores(engine))
    elif args.cmd == "explain":
        from app.ingest import explain
        print(explain.run(engine))
        print("→ docs/explain_result.md")
    # ── [S4-D] 비교군 ──
    elif args.cmd == "benchmark":
        from app.ingest.benchmark import run_benchmark
        from app.services.scoring import compute_scores
        out = run_benchmark(engine, providers(), compute_scores, reselect=args.reselect)
        if out is None:
            print("다른 프로세스가 비교군 갱신 중 — 건너뜀")
        else:
            if "select" in out:
                print("선정:", out["select"]["by_group"])
                print("시가총액 없음(제외):", out["select"]["no_market_cap"] or "-")
            print({k: v for k, v in out.items() if k in ("stocks", "pruned", "scores")})
    elif args.cmd == "hydrate":
        from app.services.hydration import hydrate
        with engine.connect() as conn:
            ids = conn.execute(text("SELECT stock_id FROM stocks WHERE ticker = ANY(:t)"), {"t": args.tickers}).scalars().all()
        for sid in ids:
            print(sid, hydrate(engine, providers(), sid))
    # ── [S5-C] 데이터 상태 ──
    elif args.cmd == "status":
        status(engine)
    # ── [S6-B] 상장 목록 ──
    elif args.cmd == "listing":
        from app.ingest.listing import sync_listing
        for country, res in sync_listing(engine, providers()).items():
            print(country, res)
    elif args.cmd == "dart-feed":
        print(jobs.load_dart_feed(engine, providers()))
    elif args.cmd == "background":
        from app.ingest.background import run_background
        print(run_background(engine, providers()))
    elif args.cmd == "dart-bulk":
        from app.ingest.dart_bulk import load_bulk
        print(load_bulk(engine, args.files, as_of=args.as_of, years=args.years))
    if args.cmd not in ("status",):
        print(f"[{args.cmd}] 완료 {time.monotonic() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
