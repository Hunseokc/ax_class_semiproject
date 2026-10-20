"""대시보드 섹터 히트맵 — 섹터별 전일 대비 등락률 수집·저장·조회.

외부 호출은 갱신 작업(RefreshService의 SECTORS_US·SECTORS_KR — 4시간 TTL, 실패 후 30분 재시도)에서만 한다.
홈 화면 조회(read_sectors)는 DB만 읽으므로 화면을 몇 번 열어도 외부 호출이 생기지 않는다.
- 미국: 섹터 ETF 11개를 묶음 다운로드 1회(providers.us_batch_price — 미국 종목 일봉과 같은 경로)
- 국내: KRX 코스피 200 섹터 지수(providers.kr_index — pykrx, PRICE_SOURCE_KR=kis면 KIS 업종 코드로 바꿔 조회). 첫 섹터부터 실패하면 나머지는 시도하지 않는다
  (같은 원인으로 KRX에 로그인·요청을 반복하지 않도록)
- 그 시장의 마지막 마감 거래일 값이 이미 있으면 다음 거래일까지 외부 호출 없이 끝낸다(주말·휴장 포함)
- 장중 미확정 봉은 저장하지 않는다(마지막 마감 거래일까지만)
섹터 구성(코드·이름·가중치)은 아래 상수로 분리해 두었다 — 이후 섹터별 종목 보기로 확장할 때 그대로 쓴다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.ingest.store import upsert
from app.providers.base import Bar, IndexRef, StockRef
from app.providers.factory import Providers
from app.services.market_calendar import TIMEZONES, last_closed_session, session_status

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Sector:
    code: str        # 미국: 섹터 ETF 티커 / 국내: KRX 섹터 지수 코드
    name: str        # 화면 표시용 한글명
    weight: float    # 타일 크기용 대략적인 시장 비중(%)


# 섹터 구성과 가중치 — 가중치는 타일 크기만 정하는 근사치(시장 비중을 대략 반영, 정기 갱신·저장하지 않음)
SECTORS: dict[str, tuple[Sector, ...]] = {
    "US": (   # S&P 500 섹터 SPDR ETF
        Sector("XLK", "정보기술", 31), Sector("XLF", "금융", 13), Sector("XLC", "커뮤니케이션", 10),
        Sector("XLY", "경기소비재", 10), Sector("XLV", "헬스케어", 9), Sector("XLI", "산업재", 8),
        Sector("XLP", "필수소비재", 5), Sector("XLE", "에너지", 3), Sector("XLU", "유틸리티", 2.5),
        Sector("XLRE", "부동산", 2), Sector("XLB", "소재", 2),
    ),
    "KR": (   # 코스피 200 섹터 지수 (KRX 지수 코드)
        Sector("1155", "정보기술", 35), Sector("1156", "금융", 12), Sector("1158", "경기소비재", 10),
        Sector("1160", "헬스케어", 9), Sector("1159", "산업재", 8), Sector("1152", "중공업", 7),
        Sector("1150", "커뮤니케이션", 6), Sector("1154", "에너지/화학", 5), Sector("1153", "철강/소재", 4),
        Sector("1157", "생활소비재", 3), Sector("1151", "건설", 1),
    ),
}
WINDOW_DAYS = 10     # 등락률 계산용 조회 구간(달력일) — 연휴가 끼어도 거래일이 2개 이상 들어가게
KEEP_DAYS = 30       # 캐시 성격이라 이보다 오래된 행은 정리


def _changes(bars: list[Bar], until: date | None) -> list[tuple[date, Decimal]]:
    """연속한 두 거래일 종가로 전일 대비 등락률(%) 목록. until 이후(장중 미확정) 봉은 뺀다."""
    closes = sorted((b.trade_date, b.close) for b in bars if b.close and (until is None or b.trade_date <= until))
    return [(d, round((c / pc - 1) * 100, 4)) for (_, pc), (d, c) in zip(closes, closes[1:]) if pc]


def _fetch_us(providers: Providers, start: date, end: date) -> tuple[dict[str, list[Bar]], str | None]:
    if providers.us_batch_price is None:
        return {}, "미국 묶음 다운로드 provider 없음"
    refs = [StockRef(stock_id=0, market="NYSE", country="US", ticker=s.code, yf_symbol=s.code,
                     timezone="America/New_York") for s in SECTORS["US"]]
    return providers.us_batch_price.get_daily_prices_batch(refs, start, end), None      # 11개를 한 번에


def _fetch_kr(providers: Providers, start: date, end: date) -> tuple[dict[str, list[Bar]], str | None]:
    out: dict[str, list[Bar]] = {}
    for s in SECTORS["KR"]:
        ref = IndexRef(index_id=0, code=s.code, country="KR", timezone="Asia/Seoul", pykrx_code=s.code, yf_symbol=None)
        try:
            out[s.code] = providers.kr_index.get_index_prices(ref, start, end)
        except Exception as e:  # noqa: BLE001 — 섹터 하나 실패는 그 타일만 '-'
            log.warning("국내 섹터 지수 %s 조회 실패: %s", s.code, e)
            if not out:                       # 첫 섹터부터 실패 → 소스 자체 문제로 보고 중단
                return {}, f"KRX 섹터 지수 조회 실패: {type(e).__name__}: {e}"[:300]
    return out, None


def load_sectors(engine: Engine, providers: Providers, country: str,
                 now: datetime | None = None) -> tuple[str, dict[str, int], str | None]:
    """갱신 작업 1회 — RefreshService._run 형식 (status, counts, detail)."""
    now = now or datetime.now(timezone.utc)
    closed = last_closed_session(country, now)
    with engine.connect() as conn:
        latest = conn.execute(text("SELECT MAX(trade_date) FROM sector_performance_daily WHERE market = :m"),
                              {"m": country}).scalar()
    if closed and latest and latest >= closed:
        return "SUCCESS", {"rows": 0}, f"마감 거래일({latest}) 값 있음 — 다음 거래일까지 호출하지 않음"

    end = now.astimezone(TIMEZONES[country]).date()
    got, error = (_fetch_us if country == "US" else _fetch_kr)(providers, end - timedelta(days=WINDOW_DAYS), end)
    names = {s.code: s.name for s in SECTORS[country]}
    rows = [{"market": country, "sector_code": code, "sector_name": names[code], "trade_date": d,
             "change_pct": pct, "fetched_at": now}
            for code, bars in got.items() if code in names for d, pct in _changes(bars, closed)]
    with engine.begin() as conn:
        n = upsert(conn, "sector_performance_daily", rows, ["market", "sector_code", "trade_date"])
        conn.execute(text("DELETE FROM sector_performance_daily WHERE market = :m AND trade_date < :cut"),
                     {"m": country, "cut": end - timedelta(days=KEEP_DAYS)})
    ok = {r["sector_code"] for r in rows}
    counts = {"rows": n, "sectors": len(ok), "missing": len(names) - len(ok)}
    if error or not ok:
        return "FAILED", counts, error or "받은 섹터 등락률 없음"
    missing = [names[c] for c in names if c not in ok]
    return ("PARTIAL" if missing else "SUCCESS"), counts, (f"누락: {', '.join(missing)}" if missing else None)


def read_sectors(db: Session, country: str) -> dict:
    """홈 화면용 — DB만 읽는다. 가장 최근 거래일 기준, 그날 값이 없는 섹터는 change_pct=None('-')."""
    latest = db.execute(text("SELECT MAX(trade_date) FROM sector_performance_daily WHERE market = :m"),
                        {"m": country}).scalar()
    rows = {} if latest is None else {r.sector_code: r for r in db.execute(text("""
        SELECT sector_code, change_pct, fetched_at FROM sector_performance_daily
        WHERE market = :m AND trade_date = :d"""), {"m": country, "d": latest})}
    return {
        "country": country,
        "available": latest is not None,
        "as_of": latest,
        "session_status": session_status(country, latest),
        "fetched_at": max((r.fetched_at for r in rows.values()), default=None),
        "sectors": [{"code": s.code, "name": s.name, "weight": s.weight,
                     "change_pct": rows[s.code].change_pct if s.code in rows else None} for s in SECTORS[country]],
    }
