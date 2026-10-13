"""수집·적재 CLI (Stage 1).

    python -m app.ingest init-db [--reset]   # db/schema.sql → indexes.sql → views.sql(있을 때만)
    python -m app.ingest master --offline    # universe.yaml → markets·stocks·indices·peer_groups
    python -m app.ingest import-sample       # sample_data/*.csv → 시세·지수·환율·밸류에이션
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
    args = ap.parse_args(argv)

    setup_logging(get_settings().log_level)
    engine = get_engine()
    t0 = time.monotonic()

    if args.cmd == "init-db":
        jobs.init_db(engine, reset=args.reset)
    elif args.cmd == "master":
        jobs.load_master(engine, offline=args.offline)
    elif args.cmd == "import-sample":
        for k, v in sample.import_sample(engine).items():
            print(f"{k}: {v} rows")
    print(f"[{args.cmd}] 완료 {time.monotonic() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
