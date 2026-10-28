"""계산 규칙 (수정 4 PR C — 검토_장부 D-039·D-040·D-041, 개발산출물/09 5절·1절).

- 저평가 이력 축소는 보수 규칙(3년 평균 이익·가치 함정 신호) 중 쓸 수 있는 수로(value_rules 0~2)
- 점수는 07:00 비교군 갱신에서만 — 매시 갱신 API는 점수를 다시 계산하지 않는다, 점수에 쓴 일봉 날짜는 국가마다 하나
- R10 독립 기준 I1은 이름이 아니라 D-025 판정 목록
"""
from __future__ import annotations

from sqlalchemy import text

from app.queries import sql
from app.services.sanity import Data, Stock, i1, i1_name, rule_price_same_date
from app.services.scoring import compute_scores, metric_params, value_shrink
from tests.conftest import D
from tests.test_scoring import API, universe  # noqa: F401 — 픽스처 재사용


def test_value_rules_count_usable_conservative_rules(engine):
    """FY 3개 + 매출·부채가 비어 함정 신호를 2개만 셀 수 있으면 3년 평균만 씀 → 규칙 1개(× 2/3). FY 2개면 0개(× 1/3)."""
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO financial_statements (stock_id, period_end, period_type, operating_income, net_income,
                             total_assets, data_source) VALUES
            (1, '2023-12-31', 'FY', 10, 8, 100, 'DART'), (1, '2024-12-31', 'FY', 11, 9, 100, 'DART'),
            (1, '2025-12-31', 'FY', 12, 9, 100, 'DART'),
            (2, '2024-12-31', 'FY', 10, 8, 100, 'DART'), (2, '2025-12-31', 'FY', 11, 9, 100, 'DART')"""))
        rows = {r["stock_id"]: r for r in conn.execute(sql("score_metrics"), metric_params()).mappings()}
    assert (rows[1]["fy_count"], rows[1]["value_rules"]) == (3, 1)
    assert (rows[2]["fy_count"], rows[2]["value_rules"]) == (2, 0)
    assert rows[1]["price_date"] == D
    assert [value_shrink(n) for n in (0, 1, 2, None)] == [1 / 3, 2 / 3, 1.0, 1 / 3]


def test_price_same_date_rule_reads_score_price_date(engine, universe):  # noqa: F811
    compute_scores(engine, as_of=D)
    with engine.connect() as conn:
        ok, val = rule_price_same_date(Data(conn, D))
    assert ok and f"KR {D} " in val
    with engine.begin() as conn:                   # 삼성전자(1)만 마지막 일봉이 하루 앞섬 — 갱신 때 점수를 다시 계산하면 생기던 섞임
        conn.execute(text("DELETE FROM daily_prices WHERE stock_id = 1 AND trade_date = :d"), {"d": D})
    compute_scores(engine, as_of=D)
    with engine.connect() as conn:
        ok, val = rule_price_same_date(Data(conn, D))
    assert not ok and val.startswith("KR ") and val.count("종목") >= 2


def test_market_refresh_api_does_not_recompute_scores(client):
    jobs = {j["job_type"]: j for j in client.post(f"{API}/market/refresh").json()["jobs"]}
    assert jobs["SCORES"]["status"] == "SKIPPED" and "07:00" in jobs["SCORES"]["detail"]


def test_r10_i1_uses_d025_list_not_names():
    def st(name, theme, ticker="X", country="KR"):
        return Stock(1, ticker, name, country, "general", theme, False)
    psk = st("피에스케이홀딩스", "반도체 장비·소재")                 # 이름만 홀딩스, 장비 매출이 이익 원천(라운드 4)
    assert not i1(psk) and i1_name(psk)
    assert i1(st("한국앤컴퍼니", "지주회사")) and i1(st("다우기술", "지주회사", "023590"))
    assert i1(st("SPDR Gold", None, "GLD", "US"))
