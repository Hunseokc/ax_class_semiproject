"""시장·설정에 따라 Provider 구현을 고른다. 테스트는 Providers를 직접 만들어 fake를 주입한다."""
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
    kr_valuation: base.ValuationProvider | None      # None → DART 기반 파생 계산(DERIVED)
    us_valuation: base.ValuationProvider
    kr_financial: base.FinancialProvider | None
    us_financial: base.FinancialProvider | None
    us_financial_supplement: base.FinancialProvider | None
    kr_disclosure: base.DisclosureProvider | None
    us_disclosure: base.DisclosureProvider | None

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
    kr = KrxProvider() if s.price_source_kr == "pykrx" else yahoo
    dart = lazy.dart if s.dart_api_key else None
    sec = lazy.sec if "@" in s.sec_user_agent else None
    return Providers(
        kr_price=kr, us_price=yahoo, kr_index=kr, us_index=yahoo, fx=yahoo,
        kr_valuation=kr if s.price_source_kr == "pykrx" else None,
        us_valuation=yahoo,
        kr_financial=dart, us_financial=sec, us_financial_supplement=yahoo,
        kr_disclosure=dart, us_disclosure=sec,
    )
