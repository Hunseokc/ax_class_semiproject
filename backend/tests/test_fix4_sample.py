"""표본·시가총액·분류 (수정 4 PR B — 검토_장부 D-039·D-036, 개발산출물/09 2절 '미국 시가총액'·'표본에서 빼는 종목').

- 미국 순위는 yfinance 시총: ADR 비율(share_ratio) 기록, 주식 종류 여럿(발행주식수 없음)도 순위, 부푼 SEC 기준은 뺌(R4-3·R4-4)
- 미국 밸류에이션은 SEC 발행주식수 ÷ share_ratio
- 거래정지·분할 종목은 지표를 비우고 사유 코드(halted·corporate_action), 거래정지는 비교군에서도 뺌(R4-7·R4-8)
"""
from __future__ import annotations

import dataclasses
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text

from app.ingest import background, benchmark, jobs, universe as universe_mod
from app.services.sanity import Data, case_spinoff, rule_halted, rule_multiclass_ranked
from app.services.scoring import compute_scores
from tests.conftest import D, scalar
from tests.fakes import CallLog, FakeFinancial, FakeReference, FakeUsBatch, make_providers
from tests.test_scoring import universe  # noqa: F401 — 픽스처 재사용


class _Caps(CallLog):
    """yfinance 시총: 티커 → 달러."""

    def __init__(self, caps: dict[str, int]):
        super().__init__()
        self.caps = caps

    def get_market_caps(self, stocks):
        self.record(tuple(s.ticker for s in stocks))
        return {s.ticker: Decimal(self.caps[s.ticker]) for s in stocks if s.ticker in self.caps}


def test_rank_us_uses_yfinance_caps_records_adr_ratio_and_drops_inflated(engine, monkeypatch):
    ids = list(range(201, 207))
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO stocks (stock_id, market_id, ticker, name, coverage, cik)
                             VALUES (:i, 2, :t, :t, 'listed', :c)"""), [{"i": i, "t": f"U{i}", "c": f"{i:010d}"} for i in ids])
        conn.execute(text("""INSERT INTO financial_statements (stock_id, period_end, period_type, total_assets, data_source)
                             VALUES (205, '2025-12-31', 'FY', 10, 'SEC')"""))
    monkeypatch.setattr(background, "config", lambda: {"us_rank_pool": 6, "us_rank_days": 30})
    batch = FakeUsBatch()
    batch.closes = {"U201": Decimal(50), "U202": Decimal(1), "U203": Decimal(20), "U204": Decimal(30), "U205": Decimal(100),
                    "U206": Decimal(40)}
    ref = FakeReference(shares={"0000000201": 10, "0000000202": 1000, "0000000203": 100, "0000000205": 100})   # 204·206: 주식수 없음
    ref.files_us_reports = lambda cik: cik != "0000000206"          # 206: 20-F만 내는 해외 기업
    caps = _Caps({"U201": 50, "U202": 1000, "U204": 3000, "U206": 5000})   # 203·205: yfinance 값 없음
    pv = replace(make_providers(), us_reference=ref, us_batch_price=batch, us_market_cap=caps)
    assert background.rank_us(engine, pv) == 4
    with engine.connect() as conn:
        got = {r.stock_id: (r.cap_rank, r.cap_usd, r.share_ratio) for r in conn.execute(text(
            "SELECT stock_id, cap_rank, cap_usd, share_ratio FROM stocks WHERE stock_id >= 201"))}
    assert got[204][:2] == (1, 3000)               # 주식 종류 여럿(SEC 발행주식수 없음)도 yfinance 시총으로 순위(R4-4)
    assert got[203][:2] == (2, 2000)               # yfinance 값이 없으면 SEC 원주 수 × 종가
    assert got[202] == (3, 1000, None)             # SEC 기준과 같으면 비율 없음
    assert got[201] == (4, 50, Decimal("10.000000"))   # ADR: SEC 500 ÷ yfinance 50 = 원주 10주 = 1 ADS(R4-3)
    assert got[205][0] is None                     # SEC 기준 10,000이 총자산 10의 200배 초과 → 부푼 값으로 보고 뺌
    assert got[206][0] is None                     # 시총 5,000이라도 20-F만 내면 순위에서 뺌(점수 없는 종목이 비교군 자리를 차지하지 않게)


def test_derived_us_valuation_uses_listed_unit_shares(engine):
    with engine.begin() as conn:
        conn.execute(text("UPDATE stocks SET share_ratio = 10 WHERE stock_id = 3"))
        conn.execute(text("""INSERT INTO fundamental_bases (stock_id, shares_outstanding, dps, source)
                             VALUES (3, 1000, 0.5, 'SEC')"""))
        conn.execute(text("""INSERT INTO financial_statements (stock_id, period_end, period_type, net_income, total_equity, data_source)
                             VALUES (3, '2025-09-27', 'FY', 100, 500, 'SEC')"""))
    assert jobs.derive_us_valuations(engine, [3]) == 1
    with engine.connect() as conn:
        v = conn.execute(text("""SELECT shares_outstanding, market_cap, eps, bps, dps FROM valuation_snapshots
                                 WHERE stock_id = 3 AND source = 'DERIVED'""")).one()
    assert (v.shares_outstanding, v.market_cap, v.eps, v.bps, v.dps) == (100, 20000, 1, 5, 5)   # 종가 200, 1 ADS = 원주 10주


def test_halted_and_spinoff_stocks_have_no_score_and_reason(engine, universe, monkeypatch):  # noqa: F811
    with engine.begin() as conn:                   # 카카오(8): 마지막 일봉이 40일 전 → 20거래일 넘게 거래 없음
        conn.execute(text("DELETE FROM daily_prices WHERE stock_id = 8 AND trade_date > :d"), {"d": D - timedelta(days=40)})
    acts = [{"market": "KR", "ticker": "005380", "date": D - timedelta(days=1), "what": "사업부 분할", "source": "테스트"}]
    real = universe_mod.load_universe()
    monkeypatch.setattr(universe_mod, "load_universe", lambda: dataclasses.replace(real, corporate_actions=acts))
    compute_scores(engine, as_of=D)
    with engine.connect() as conn:
        dq = dict(conn.execute(text("""SELECT stock_id, data_quality FROM stock_scores st JOIN scoring_presets p USING (preset_id)
                                       WHERE as_of = :d AND p.code = 'balanced'"""), {"d": D}).all())
        raw6 = dict(conn.execute(text("""SELECT metric, raw_value FROM stock_metric_values WHERE stock_id = 6 AND as_of = :d"""),
                                 {"d": D}).all())
    assert dq[8]["score_null_code"] == "halted" and "20거래일 넘게 거래 없음" in dq[8]["score_null_reason"]
    assert dq[6]["score_null_code"] == "corporate_action" and "사업부 분할" in dq[6]["score_null_reason"]
    assert raw6["conservative_yield"] is None and raw6["book_yield"] is None and raw6["trap_signal"] is None
    assert raw6["return_on_assets"] is not None                                 # 저평가 지표만 비운다
    assert "분할 전 재무" in dq[6]["missing_metrics"]["conservative_yield"]
    with engine.connect() as conn:                 # sanity: 거래정지 점수 없음, 분할 저평가 없음 + 사유
        d = Data(conn, D)
        ok, val = rule_halted(d)
        assert ok and "035720 카카오" in val
        ok, val = case_spinoff(d, {})
        assert ok and "005380" in val


def test_select_benchmark_skips_halted_and_zero_volume(engine, universe):  # noqa: F811
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_prices WHERE stock_id = 8 AND trade_date > :d"), {"d": D - timedelta(days=40)})

    class Bulk(CallLog):
        source = "FAKE"

        def get_bars_by_date(self, day):
            from app.providers.base import Bar
            return {"000660": Bar(day, 1, 1, 1, 1, 0), "005930": Bar(day, 1, 1, 1, 1, 10)}   # SK하이닉스 거래량 0

    halted = benchmark.halted_ids(engine, replace(make_providers(), kr_bulk=Bulk()))
    assert halted == {8, 2}


def test_multiclass_rule_reads_cap_rank(engine):
    with engine.begin() as conn:
        conn.execute(text("UPDATE stocks SET cap_rank = 7 WHERE stock_id = 3"))
    with engine.connect() as conn:
        ok, val = rule_multiclass_ranked(Data(conn), {"ticker": ["AAPL", "NVDA"]})
    assert not ok and val == "AAPL 7 · NVDA 순위 없음"
