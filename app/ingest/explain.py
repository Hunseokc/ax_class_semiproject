"""인덱스 전후 EXPLAIN (ANALYZE, BUFFERS) 비교 → docs/explain_result.md

'인덱스 전'은 트랜잭션 안에서 해당 인덱스를 DROP한 뒤 측정하고 ROLLBACK한다(실제 DB는 바뀌지 않음).
캐시 영향을 줄이려고 각 쿼리를 REPEAT회 실행하고 실행 시간 중앙값과 마지막 실행 계획을 기록한다.
"""
from __future__ import annotations

import re
import statistics
from datetime import datetime

from sqlalchemy import Engine, text

from app.core.config import ROOT_DIR

REPEAT = 7

CASES = [
    {
        "title": "종목별 최근 공시 5건 (종목 상세 '최근 공시')",
        "index": "ix_disclosures_stock_filed",
        "sql": "SELECT rcept_no, title, filed_at FROM disclosures WHERE stock_id = :sid ORDER BY filed_at DESC LIMIT 5",
        "params": "SELECT stock_id FROM disclosures GROUP BY stock_id ORDER BY count(*) DESC LIMIT 1",
    },
    {
        "title": "특정 거래일의 전 종목 시세 (거래량 순위·날짜 단위 조회)",
        "index": "ix_daily_prices_trade_date",
        "sql": "SELECT stock_id, close, volume FROM daily_prices WHERE trade_date = :d ORDER BY volume DESC",
        "params": "SELECT max(trade_date) FROM daily_prices",
    },
    {
        "title": "종목별 최신 FY 재무 5건 (재무 추이)",
        "index": "ix_fin_stock_type_end",
        "sql": "SELECT period_end, revenue FROM financial_statements WHERE stock_id = :sid AND period_type = 'FY' "
               "ORDER BY period_end DESC LIMIT 5",
        "params": "SELECT 1",
    },
    {
        "title": "종목별 최신 밸류에이션 1행 — 삭제한 인덱스가 PK(stock_id, as_of)와 기능이 겹치는지 확인 (A-34)",
        "index": "ix_valuation_stock_asof",
        "create": "CREATE INDEX ix_valuation_stock_asof ON valuation_snapshots (stock_id, as_of DESC)",
        "sql": "SELECT per, pbr, market_cap FROM valuation_snapshots WHERE stock_id = :sid ORDER BY as_of DESC LIMIT 1",
        "params": "SELECT 1",
    },
]


def _explain(conn, sql: str, params: dict) -> tuple[float, str]:
    times, plan = [], ""
    for _ in range(REPEAT):
        rows = conn.execute(text(f"EXPLAIN (ANALYZE, BUFFERS, COSTS) {sql}"), params).scalars().all()
        plan = "\n".join(rows)
        times.append(float(re.search(r"Execution Time: ([\d.]+) ms", plan).group(1)))
    return statistics.median(times), plan


def _node(plan: str) -> str:
    first = plan.splitlines()[0]
    nodes = re.findall(r"(Index Only Scan|Index Scan Backward|Index Scan|Bitmap Heap Scan|Bitmap Index Scan|Seq Scan)"
                       r"(?: using (\w+))?", plan)
    return ", ".join(f"{n}{' (' + i + ')' if i else ''}" for n, i in nodes) or first.split("(")[0].strip()


def run(engine: Engine) -> str:
    out = [f"# 인덱스 전후 EXPLAIN 비교 (실제 실행 결과)\n",
           f"- 실행 시각: {datetime.now().astimezone().isoformat(timespec='seconds')}",
           f"- 명령: `python -m app.ingest explain` / 각 쿼리 {REPEAT}회 실행, 실행 시간은 중앙값",
           "- '인덱스 전'은 트랜잭션 안에서 해당 인덱스를 DROP 후 측정하고 ROLLBACK\n"]
    with engine.connect() as conn:
        conn.execute(text("ANALYZE"))
        conn.commit()
        sizes = dict(conn.execute(text("""SELECT relname, n_live_tup FROM pg_stat_user_tables""")).all())
    summary = []
    for case in CASES:
        with engine.connect() as conn:
            p = conn.execute(text(case["params"])).scalar()
            params = {"sid": p if isinstance(p, int) and "stock_id" in case["params"] else 1, "d": p}
            if "create" in case:
                # 운영 스키마에 없는 인덱스: 현재(없음) 측정 → 트랜잭션 안에서 CREATE → 측정 → ROLLBACK
                before_ms, before_plan = _explain(conn, case["sql"], params)
                conn.rollback()
                conn.execute(text(case["create"]))
                conn.execute(text(f"ANALYZE {re.search(r'ON (\w+)', case['create']).group(1)}"))
                after_ms, after_plan = _explain(conn, case["sql"], params)
                conn.rollback()
            else:
                after_ms, after_plan = _explain(conn, case["sql"], params)
                conn.rollback()
                # 같은 트랜잭션에서 DROP → 측정 → ROLLBACK (인덱스는 복구됨)
                conn.execute(text(f"DROP INDEX {case['index']}"))
                before_ms, before_plan = _explain(conn, case["sql"], params)
                conn.rollback()
        table = re.search(r"FROM (\w+)", case["sql"]).group(1)
        summary.append((case["title"], case["index"], table, sizes.get(table), _node(before_plan), before_ms,
                        _node(after_plan), after_ms))
        out += [f"## {case['title']}\n", f"- 인덱스: `{case['index']}` / 테이블 `{table}` 약 {sizes.get(table):,}행",
                f"- 쿼리 (파라미터 {({k: str(v) for k, v in params.items() if f':{k}' in case['sql']})}):",
                f"```sql\n{case['sql']}\n```",
                f"### 인덱스 전 (중앙값 {before_ms:.3f} ms)\n```\n{before_plan}\n```",
                f"### 인덱스 후 (중앙값 {after_ms:.3f} ms)\n```\n{after_plan}\n```\n"]
    head = ["## 요약\n", "| 쿼리 | 인덱스 | 행 수 | 인덱스 전 계획 | 전(ms) | 인덱스 후 계획 | 후(ms) |", "|---|---|---|---|---|---|---|"]
    head += [f"| {t} | `{i}` | {n:,} | {bp} | {bm:.3f} | {ap} | {am:.3f} |" for t, i, _, n, bp, bm, ap, am in summary]
    text_out = "\n".join(out[:4] + head + [""] + out[4:])
    (ROOT_DIR / "docs" / "explain_result.md").write_text(text_out + "\n", encoding="utf-8")
    return "\n".join(head)
