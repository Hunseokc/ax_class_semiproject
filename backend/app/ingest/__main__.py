"""수집·적재 CLI (Stage 1).

    python -m app.ingest init-db [--reset]   # db/schema.sql → indexes.sql → views.sql(있을 때만)
    python -m app.ingest master --offline    # universe.yaml → markets·stocks·indices·peer_groups
    python -m app.ingest import-sample       # sample_data/*.csv → 시세·지수·환율·밸류에이션 (수집이 안 될 때 대체)
    python -m app.ingest prices [--full] [--tickers 005930 AAPL]   # 종목 일봉 (국내 pykrx, 미국 yfinance)
    python -m app.ingest indices [--full]
    python -m app.ingest fx [--full]         # USD/KRW DAILY
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
    # Stage 1에는 온라인(DART·SEC) 경로가 없어 --offline을 필수로 둔다. Stage 3에서 선택 옵션으로 바꾼다
    sub.add_parser("master").add_argument("--offline", action="store_true", required=True, help="DART/SEC 매핑 생략")
    sub.add_parser("import-sample")
    # ── [S1-D] 시세 수집 ──
    p = sub.add_parser("prices")
    p.add_argument("--full", action="store_true")
    p.add_argument("--tickers", nargs="*")
    for name in ("indices", "fx"):
        sub.add_parser(name).add_argument("--full", action="store_true")
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
    print(f"[{args.cmd}] 완료 {time.monotonic() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
