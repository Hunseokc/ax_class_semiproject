"""매력도 회귀 테스트 실행기(app/services/sanity.py) — check 식 계산과 픽스처에서 끝까지 실행."""
from __future__ import annotations

from app.services.sanity import Data, Stock, case_theme, eval_check, run
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
    assert not ok and "통과 **5/6**" in report and "KAKAO-scored" in report.split("실패:")[1]
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
