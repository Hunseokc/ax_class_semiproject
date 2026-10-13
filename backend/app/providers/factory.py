"""시장·설정에 따라 Provider 구현을 고른다. 테스트는 Providers를 직접 만들어 fake를 주입한다.

Stage 1은 일봉·지수·환율만 있다. 밸류에이션·재무·공시·대량 조회 provider는 Stage 3에서 필드로 추가한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings
from app.providers import base


@dataclass
class Providers:
    """국가별 provider 묶음."""
    kr_price: base.PriceProvider
    us_price: base.PriceProvider
    kr_index: base.IndexProvider
    us_index: base.IndexProvider
    fx: base.FxProvider

    def price(self, country: str) -> base.PriceProvider:
        return self.kr_price if country == "KR" else self.us_price

    def index(self, country: str) -> base.IndexProvider:
        return self.kr_index if country == "KR" else self.us_index


def default_providers() -> Providers:
    from app.providers.krx import KrxProvider
    from app.providers.yahoo import YahooProvider

    s = get_settings()
    yahoo = YahooProvider()
    # PRICE_SOURCE_KR=yfinance면 국내도 yfinance(.KS/.KQ 심볼)로 받는다 — pykrx가 막혔을 때의 대체 경로
    kr = KrxProvider() if s.price_source_kr == "pykrx" else yahoo
    return Providers(kr_price=kr, us_price=yahoo, kr_index=kr, us_index=yahoo, fx=yahoo)
