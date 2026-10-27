"""매력도 회귀 테스트 실행기(app/services/sanity.py) — check 식 계산과 픽스처에서 끝까지 실행."""
from __future__ import annotations

from app.services.sanity import Stock, eval_check, run
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
""", encoding="utf-8")
    with engine.connect() as conn:
        report, ok = run(conn, cases)
    assert not ok and "통과 **3/4**" in report and "KAKAO-scored" in report.split("실패:")[1]
    assert "| KAKAO-known | known_fail | 실패(감수 D-999) |" in report
    assert "| R6-score-honesty | required | 통과 |" in report
