"""시장·설정에 따라 Provider 구현을 고른다. 테스트는 Providers를 직접 만들어 fake를 주입한다.

Stage 1은 일봉·지수·환율만 있다. 밸류에이션·재무·공시·대량 조회 provider는 Stage 3에서 필드로 추가한다.
이후 단계: 상장 목록(kr_listing·us_listing)·미국 참조 데이터(us_reference)·비교군 시가총액(market_caps)은 Stage 4~5.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from app.core.config import get_settings
from app.providers import base


@dataclass
class Providers:
    """국가별 provider 묶음. None이면 해당 작업을 건너뛴다."""
    kr_price: base.PriceProvider
    us_price: base.PriceProvider
    kr_index: base.IndexProvider
    us_index: base.IndexProvider
    fx: base.FxProvider
    # TODO(껍데기): C — 아래 필드(재무·공시 포함)의 순서·기본값을 원본대로 맞추고 tests/fakes.py의 Providers(...)도 함께 고친다
    #   (원본: 밸류에이션·재무·공시 필드는 기본값 없음, kr_bulk·us_batch_price만 = None)
    # ── [S3-C] 밸류에이션·대량 조회 ──
    kr_valuation: base.ValuationProvider | None = None      # None → DART 기반 파생 계산(DERIVED)
    us_valuation: base.ValuationProvider | None = None
    kr_bulk: base.MarketBulkProvider | None = None          # 국내 날짜별 전 종목(일봉·밸류에이션). None이면 종목별 수집
    us_batch_price: base.BatchPriceProvider | None = None   # 미국 일봉 묶음 다운로드. None이면 종목별 수집
    # ── [S3-B] 재무·공시 ── (B는 아래 default_providers의 [S3-B] 구역에서 dart·sec를 연결한다)
    kr_financial: base.FinancialProvider | None = None
    us_financial: base.FinancialProvider | None = None
    us_financial_supplement: base.FinancialProvider | None = None
    kr_disclosure: base.DisclosureProvider | None = None
    us_disclosure: base.DisclosureProvider | None = None

    def price(self, country: str) -> base.PriceProvider:
        return self.kr_price if country == "KR" else self.us_price

    def index(self, country: str) -> base.IndexProvider:
        return self.kr_index if country == "KR" else self.us_index

    def valuation(self, country: str) -> base.ValuationProvider | None:
        return self.kr_valuation if country == "KR" else self.us_valuation

    def financial(self, country: str) -> base.FinancialProvider | None:
        return self.kr_financial if country == "KR" else self.us_financial

    def disclosure(self, country: str) -> base.DisclosureProvider | None:
        return self.kr_disclosure if country == "KR" else self.us_disclosure


class _Lazy:
    """API 키가 없으면 생성 시점에 실패하므로 처음 쓸 때 만든다."""

    @cached_property
    def dart(self):
        from app.providers.dart import DartClient
        return DartClient()

    @cached_property
    def sec(self):
        from app.providers.sec import SecClient
        return SecClient()


def default_providers() -> Providers:
    from app.providers.krx import KrxProvider
    from app.providers.yahoo import YahooProvider

    s = get_settings()
    yahoo, lazy = YahooProvider(), _Lazy()
    # PRICE_SOURCE_KR=yfinance면 국내도 yfinance(.KS/.KQ 심볼)로 받는다 — pykrx가 막혔을 때의 대체 경로
    kr = KrxProvider() if s.price_source_kr == "pykrx" else yahoo
    dart = lazy.dart if s.dart_api_key else None
    sec = lazy.sec if "@" in s.sec_user_agent else None
    return Providers(
        kr_price=kr, us_price=yahoo, kr_index=kr, us_index=yahoo, fx=yahoo,
        # TODO(껍데기): C — kr_valuation·us_valuation·kr_bulk·us_batch_price 연결 (지금은 None → 해당 작업 건너뜀)
        # ── [S3-C] 밸류에이션·대량 조회 ──
        kr_valuation=None, us_valuation=None, kr_bulk=None, us_batch_price=None,
        # ── [S3-B] 재무·공시 ──
        # us_financial_supplement(원본: yahoo)는 stage3 yahoo.py에 get_annual_financials가 없어 None — 보충 없이 SEC 값만 쓴다
        kr_financial=dart, us_financial=sec, us_financial_supplement=None, kr_disclosure=dart, us_disclosure=sec,
    )
