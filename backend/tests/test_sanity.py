"""매력도 회귀 테스트 실행기(app/services/sanity.py) — check 식 계산과 픽스처에서 끝까지 실행."""
from __future__ import annotations

from app.services.sanity import Data, Stock, case_theme, classify, eval_check, run
from app.services.scoring import compute_scores
from tests.conftest import D
from tests.test_scoring import universe  # noqa: F401 — 픽스처 재사용


def _stock(**kw) -> Stock:
    s = Stock(1, "X", "엑스", "US", kw.pop("family", "general"), None, False)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_eval_check_ranks_percentiles_factors_and_scored_flags():
    s = _stock(rank={"growth": 60, "value": 25, "balanced": 3}, pct={"growth": 70.0, "balanced": 90.0},
               factors={"safety": -0.4})
    assert eval_check("growth_rank > 50", s) and eval_check("value_rank > 20 and balanced_rank <= 100", s)
    assert eval_check("growth_percentile < 80", s) and not eval_check("growth_percentile < 80 and not_scored", s)
    assert eval_check("stability_factor < 0", s) and eval_check("scored", s)
    assert eval_check("family == financial or not_scored", _stock(family="financial"))
    assert eval_check("not_scored", None) and not eval_check("value_rank > 20", None)   # 값 없는 비교는 실패
    assert eval_check("__import__('os')", s) is None                                   # 모르는 이름·문자는 해석하지 않음


def test_run_reports_required_failures(engine, universe, tmp_path):  # noqa: F811
    compute_scores(engine, as_of=D)
    cases = tmp_path / "cases.yaml"
    cases.write_text("""
cases:
  - {id: KIA-scored, ticker: "000270", check: scored, status: required}
  - {id: KAKAO-scored, ticker: "035720", check: scored, status: required}
  - {id: KAKAO-known, ticker: "035720", check: scored, status: known_fail, decision: D-999}
rules:
  - {id: R6-score-honesty, check: 구간 라벨, status: required}
  - {id: TRAP-penalty-only, check: 함정 신호 z_adj ≤ 0, status: required}
  - {id: WEAK-theme-first, check: 약한 테마 1등 수, status: target}
  - {id: THEME-position-raw, check: 테마 위치 = 중립화 전 테마 평균 순위, status: required}
  - {id: CLIP-order, check: 원값 상위 7% 안 순서, status: target}
""", encoding="utf-8")
    with engine.connect() as conn:
        report, ok = run(conn, cases)
    # 네 칸(D-030): 통과 / 감수한 실패 / target 실패 / 미검증 + required 실패는 따로 — 감수한 실패를 통과에 합치지 않는다
    assert not ok and "**통과 5 · 감수한 실패 1 · target 실패 1 · 미검증 0** · **required 실패 1** — KAKAO-scored" in report
    assert "required(known_fail 포함) 6개: 통과 4 + 감수한 실패 1 · 실패 1" in report
    assert "| KAKAO-known | known_fail | 실패(감수 D-999) |" in report
    assert "| R6-score-honesty | required | 통과 |" in report
    assert "| TRAP-penalty-only | required | 통과 |" in report and "양수 0" in report     # 중립화하지 않아 감점만(D-018)
    assert "| WEAK-theme-first | target | 통과 |" in report and "(기록만)" in report
    assert "| THEME-position-raw | required | 통과 |" in report and "차이 0" in report    # 화면 테마 위치 = 중립화 전(D-020)
    assert "| CLIP-order | target |" in report                       # 픽스처는 지표당 3~4종목이라 상위 7%가 3개 미만 → 지표 없음


def test_theme_cases_compare_primary_theme_and_record_unreviewed_top20(engine, universe, tmp_path):  # noqa: F811
    """D-024: 주 테마 == expected(비교 표본 밖 종목도 DB 주 테마로), DB에 없는 종목만 있으면 판정 못함(미검증).
    TOP20-theme-reviewed는 업종 코드로만 분류된 top20 종목을 기록만 한다."""
    compute_scores(engine, as_of=D)
    cases = tmp_path / "cases.yaml"
    cases.write_text("""
cases:
  - {id: THEME-main-business-KR, ticker: ["005380", "035420"], market: KR, check: 주 테마 == expected,
     expected: {"005380": 자동차, "035420": 자동차}, status: required}
  - {id: THEME-main-business-US, ticker: [AAPL, ZZZZ], market: US, check: 주 테마 == expected,
     expected: {AAPL: 반도체}, status: required}
rules:
  - {id: TOP20-theme-reviewed, check: 업종 코드로만 분류된 top20, status: target}
""", encoding="utf-8")
    with engine.connect() as conn:
        report, ok = run(conn, cases)
        missing = case_theme(Data(conn), {"market": "US", "ticker": ["ZZZZ"], "expected": {"ZZZZ": "빅테크"}})
    assert "| THEME-main-business-KR | required | 통과 | 2종목 중 다름 0 [] |" in report
    assert "| THEME-main-business-US | required | 실패 |" in report and "AAPL 빅테크≠반도체" in report
    assert "| TOP20-theme-reviewed | target | 통과 |" in report and "(기록만)" in report and not ok
    assert missing == (None, "0종목 중 다름 0 [] · DB에 없음 ['ZZZZ']")


def test_data_accuracy_rules_negative_equity_badge_wording_and_preferred_basis(engine, universe, tmp_path):  # noqa: F811
    """D-026·D-027·D-029: 자본 음수면 B/P 없음, 배지는 사실만, 우선주 보통주 몫, 원화 단위 대조(픽스처는 단위가 맞지 않아 실패)."""
    from sqlalchemy import text
    with engine.begin() as conn:                                   # 삼성전자 BPS 주식수 1,260 = 보통주 1,000 + 26%
        conn.execute(text("UPDATE valuation_snapshots SET bps = 0.1 WHERE stock_id = 1"))
    compute_scores(engine, as_of=D)
    cases = tmp_path / "cases.yaml"
    cases.write_text("""
rules:
  - {id: NEG-EQUITY-no-bp, check: 자본 ≤ 0 이면 B/P 없음, status: required}
  - {id: ONEOFF-badge-recurring, check: 배지 문구, status: required}
  - {id: PREF-share-basis, check: 우선주 보통주 몫, status: required}
  - {id: CURRENCY-krw, check: KRX EPS·BPS 대조, status: required}
""", encoding="utf-8")
    with engine.connect() as conn:
        report, _ = run(conn, cases)
    assert "| NEG-EQUITY-no-bp | required | 통과 | 자본 ≤ 0 1종목 ['005380'] 중 B/P 있음 0 [] |" in report
    assert "| ONEOFF-badge-recurring | required | 통과 | 배지 1개 중 단정 문구 0 [] |" in report
    assert "| PREF-share-basis | required | 통과 | 대상 1종목 ['005930(+26%)'] · 다름 0 [] |" in report
    assert "| CURRENCY-krw | required | 실패 |" in report      # 픽스처 EPS 8 vs 순이익 12 ÷ 1,000주 — 단위가 다르면 잡는다


def test_financial_and_growth_label_rules(engine, universe, tmp_path):  # noqa: F811
    """D-028·D-032: 금융 묶음은 종합 점수·홈 순위 없이 업종 안 비교(표본 < 8이면 중앙값), 성장 팩터 이름·프리셋 설명."""
    from tests.test_scoring import _theme_rule
    _theme_rule(engine, 3, scoring="financial")                    # 자동차(NAVER·현대차)를 금융 묶음으로
    compute_scores(engine, as_of=D)
    cases = tmp_path / "cases.yaml"
    cases.write_text("""
cases:
  - {id: FIN-pb-roe-view, target: stock 화면 (금융), check: 업종 안 P/B·ROE·P/E, status: required}
  - {id: INSURER-oci-roe, target: stock 화면 (보험), check: 총포괄이익 ROE, status: target}
  - {id: GROWTH-label, target: stock·홈 화면, check: 과거 실적 성장, status: required}
rules:
  - {id: FIN-no-composite, check: 금융 종합 점수 없음, status: required}
""", encoding="utf-8")
    with engine.connect() as conn:
        report, ok = run(conn, cases)
    assert "| FIN-no-composite | required | 통과 | 금융 2종목 중 종합 점수 있음 0 [] · 홈 금융 순위 행 0 |" in report
    assert "| FIN-pb-roe-view | required | 통과 | KR 자동차 1개 median" in report
    assert "| INSURER-oci-roe | target | 확인 못함 |" in report
    assert "| GROWTH-label | required | 통과 |" in report and "미래 성장 예측이 아닙니다" in report


def test_out_of_sample_is_unverified_not_passed(engine, universe, tmp_path):  # noqa: F811
    """D-043: 검사할 종목이 표본 밖(테마 상위 n 밖·DB에 없음)이면 not_scored로 통과시키지 않고 미검증. 점수를 내지 않는 테마
    (지주회사)라 빠진 종목만 설계상 점수 없음으로 식을 계산한다. 여러 종목 중 하나라도 실패면 실패, 실패 없이 표본 밖이 있으면 미검증."""
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO peer_groups (group_id, name, scoring) VALUES (4, '지주회사', 'none')"))
        conn.execute(text("INSERT INTO peer_group_members VALUES (3, 8, true), (4, 7, true)"))
        conn.execute(text("UPDATE stocks SET coverage = 'listed', cap_rank = 808 WHERE stock_id = 8"))     # 카카오 — 자동차 상위 밖
        conn.execute(text("UPDATE stocks SET coverage = 'listed' WHERE stock_id = 7"))                     # 기아 — 지주회사 테마
    compute_scores(engine, as_of=D)
    cases = tmp_path / "cases.yaml"
    cases.write_text("""
cases:
  - {id: OUT-growth, ticker: "035720", market: KR, check: growth_rank > 50 or not_scored, status: required}
  - {id: HOLD-growth, ticker: "000270", market: KR, check: growth_percentile < 80 or not_scored, status: required}
  - {id: MIX-scored, ticker: ["035420", "035720"], market: KR, check: scored, status: required}
  - {id: MIX-fail, ticker: ["035420", "035720"], market: KR, check: not_scored, status: required}
  - {id: NODB-scored, ticker: ZZZZ, market: US, check: scored, status: required}
  - {id: CJ-LOGISTICS-history, ticker: "035720", market: KR, check: 재무 FY ≥ 3, status: required}
""", encoding="utf-8")
    with engine.connect() as conn:
        report, ok = run(conn, cases)
    assert "| OUT-growth | required | 확인 못함 | 035720: 표본 밖(자동차 KR 상위 10 밖, cap_rank 808) |" in report
    assert "| HOLD-growth | required | 통과 | 000270: 표본에 없음(설계상 점수 없음 — 지주회사 테마) |" in report
    assert "| MIX-scored | required | 확인 못함 | 035420: 균형 " in report and "035720: 표본 밖(" in report
    assert "| MIX-fail | required | 실패 |" in report                    # 실패가 표본 밖(미검증)에 가려지지 않는다
    assert "| NODB-scored | required | 확인 못함 | ZZZZ: 표본 밖(상장 종목 DB에 없음) |" in report
    assert "| CJ-LOGISTICS-history | required | 확인 못함 | 표본 밖(자동차 KR 상위 10 밖, cap_rank 808) |" in report
    assert not ok and ("⚠ required 표본 밖 미검증 4개 > 3 (OUT-growth, MIX-scored, NODB-scored, CJ-LOGISTICS-history)"
                       " — 표본 안 종목으로 케이스를 바꿀 것(D-043)") in report


def test_classify_four_columns():
    """D-030: 결정 번호 없는 known_fail은 감수한 실패가 아니라 required 실패, 판정 못함은 상태와 관계없이 미검증."""
    assert classify("required", True, None) == "passed" and classify("target", None, None) == "unverified"
    assert classify("known_fail", False, "D-001") == "known_fail" and classify("known_fail", False, None) == "required_fail"
    assert classify("target", False, None) == "target_fail" and classify("required", False, "D-024") == "required_fail"


def test_save_records_run_and_deploy_rule(engine, universe, tmp_path):  # noqa: F811
    """--save --env deploy면 sanity_runs에 네 칸을 남기고 DEPLOY-sanity-ran이 통과. 저장하지 않는 실행은 미검증(종료 코드에는 안 넣음)."""
    from sqlalchemy import text
    compute_scores(engine, as_of=D)
    cases = tmp_path / "cases.yaml"
    cases.write_text("""
rules:
  - {id: DEPLOY-sanity-ran, check: 배포 sanity 기록, status: required, decision: D-030}
  - {id: R6-score-honesty, check: 구간 라벨, status: required}
  - {id: CLIP-order, check: 원값 상위 7% 안 순서, status: target}
""", encoding="utf-8")
    with engine.begin() as conn:
        report, ok = run(conn, cases, save=True, env="deploy")
    assert ok and "| DEPLOY-sanity-ran | required | 통과 | 이번 실행을 배포 DB sanity_runs에 기록" in report
    with engine.connect() as conn:
        row = conn.execute(text("""SELECT as_of, environment, passed, known_fail, target_fail, unverified, required_fail, ok,
                                          jsonb_array_length(results) FROM sanity_runs""")).one()
        report, ok = run(conn, cases)
    assert tuple(row) == (D, "deploy", 2, 0, 1, 0, 0, True, 3)
    assert ok and "| DEPLOY-sanity-ran | required | 확인 못함 | 배포 DB Job(--save --env deploy)에서만 확인" in report
    assert f"마지막 배포 기록 {D}" in report and "미검증 1 (DEPLOY-sanity-ran)" in report
