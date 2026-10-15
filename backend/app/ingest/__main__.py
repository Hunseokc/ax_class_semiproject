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
    python -m app.ingest seed-demo           # demo 관심종목 8건 + 모의 포트폴리오 2개
    python -m app.ingest refresh             # POST /market/refresh와 같은 TTL 갱신 (cron용)
"""
from __future__ import annotations

import argparse
import sys
import time

from app.core.config import get_settings
from app.core.db import get_engine
from app.core.logging import setup_logging
from app.ingest import jobs, sample


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
        from app.services.fx import FxService
        from app.services.refresh import RefreshService
        pv = providers()
        ttl = get_settings().refresh_ttl_hours
        result = RefreshService(engine, pv, FxService(engine, pv.fx, ttl), ttl).refresh()
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
    print(f"[{args.cmd}] 완료 {time.monotonic() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
