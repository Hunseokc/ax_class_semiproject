"""시장·설정에 따라 Provider 구현을 고른다. 테스트는 Providers를 직접 만들어 fake를 주입한다.

Stage 6-B: 상장 목록(kr_listing·us_listing). 비교군 시가총액(market_caps)은 Stage 6-D.
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
    # ── [S3-C] 밸류에이션 ──
    kr_valuation: base.ValuationProvider | None      # None → DART 기반 파생 계산(DERIVED)
    us_valuation: base.ValuationProvider
    # ── [S3-B] 재무·공시 ── (B는 아래 default_providers의 [S3-B] 구역에서 dart·sec를 연결한다)
    kr_financial: base.FinancialProvider | None
    us_financial: base.FinancialProvider | None
    us_financial_supplement: base.FinancialProvider | None
    kr_disclosure: base.DisclosureProvider | None
    us_disclosure: base.DisclosureProvider | None
    # ── [S3-C] 대량 조회 ──
    kr_bulk: base.MarketBulkProvider | None = None   # 국내 날짜별 전 종목(일봉·밸류에이션). None이면 종목별 수집
    us_batch_price: base.BatchPriceProvider | None = None   # 미국 일봉 묶음 다운로드. None이면 종목별 수집
    # ── [S6-B] 상장 목록 ──
    kr_listing: base.ListingProvider | None = None   # 상장 보통주 목록(검색용). None이면 그 국가는 건너뛴다
    us_listing: base.ListingProvider | None = None
    # ── [S5-D] 미국 참조 데이터 ──
    us_reference: base.ReferenceDataProvider | None = None  # 미국 발행주식수·SIC·기초값(SEC). None이면 yfinance 밸류에이션
    # 국내 사업보고서 목록(회사 지정 없이 날짜로) — 공시 증분(jobs.load_dart_feed). None이면 건너뛴다
    kr_feed: object | None = None                             # DartClient (list_annual_reports)
    # 현재가(관심종목·상세 화면 표시 전용, 국내·미국 모두 KIS). None이면 일봉 종가만 보여 준다
    quote: base.QuoteProvider | None = None

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

    def listing(self, country: str) -> base.ListingProvider | None:
        return self.kr_listing if country == "KR" else self.us_listing


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
    # PRICE_SOURCE_KR=kis면 한국투자증권 API(일봉·지수·밸류에이션). 대량 조회·상장 목록은 없어 종목별 수집으로 간다
    from app.providers.kis import KisProvider
    kis = KisProvider() if s.kis_api_key and s.kis_api_secret else None
    if s.price_source_kr == "kis":
        kr = kis or KisProvider()                     # 키가 없으면 여기서 ProviderError
    else:
        kr = KrxProvider() if s.price_source_kr == "pykrx" else yahoo
    dart = lazy.dart if s.dart_api_key else None
    sec = lazy.sec if "@" in s.sec_user_agent else None
    return Providers(
        kr_price=kr, us_price=yahoo, kr_index=kr, us_index=yahoo, fx=yahoo,
        # ── [S3-C] 밸류에이션·대량 조회 ──
        kr_valuation=kr if s.price_source_kr in ("pykrx", "kis") else None,
        us_valuation=yahoo,
        kr_bulk=kr if s.price_source_kr == "pykrx" else None, us_batch_price=yahoo,
        # ── [S6-B] 상장 목록 ──
        kr_listing=kr if s.price_source_kr == "pykrx" else None, us_listing=sec,
        # ── [S5-D] 미국 참조 데이터 ──
        us_reference=sec,
        # ── [S3-B] 재무·공시 ──
        kr_financial=dart, us_financial=sec, us_financial_supplement=yahoo, kr_disclosure=dart, us_disclosure=sec,
        kr_feed=dart,                                     # 재무용과 같은 DartClient(분당 한도 공유)
        quote=kis,
    )
