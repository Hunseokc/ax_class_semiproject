"""적재 작업: DB 초기화, 마스터(유니버스) 적재, 시세·지수·환율 수집, 밸류에이션·재무·공시 수집(Stage 3).

수집 작업은 대상 1건(종목·지수)마다 ingestion_logs 1행을 남긴다.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Engine, text

from app.core.config import ROOT_DIR
from app.ingest.preprocess import clean_bars, clean_fx
from app.ingest.store import job_log, upsert
from app.ingest.universe import load_universe, yf_symbol
from app.providers.base import IndexRef, StockRef
from app.providers.factory import Providers

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- DB 초기화
def init_db(engine: Engine, reset: bool = False) -> None:
    # SQL 파일은 파라미터 없이 psycopg로 직접 실행한다(주석 속 '%'가 placeholder로 해석되지 않도록)
    with engine.begin() as conn:
        raw = conn.connection.driver_connection
        if reset:
            raw.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        for name in ("schema.sql", "indexes.sql", "views.sql"):
            path = ROOT_DIR / "db" / name
            if name == "views.sql" and not path.exists():
                # views.sql은 Stage 1-B(B)가 추가한다. 머지 전에도 이 명령이 돌도록 없으면 건너뛴다
                log.warning("건너뜀: db/%s (파일 없음)", name)
                continue
            raw.execute(path.read_text(encoding="utf-8"))
            log.info("적용: db/%s", name)


# ---------------------------------------------------------------- 마스터
def load_master(engine: Engine, offline: bool = True) -> None:
    """universe.yaml → markets·stocks·indices·peer_groups·peer_group_members + 기본 사용자 demo (재실행해도 행 수 불변).

    Stage 1은 오프라인 경로만 있다. DART corp_code·SEC CIK 매핑(온라인)은 Stage 3에서 추가한다.
    """
    if not offline:
        raise NotImplementedError("온라인 마스터 적재(DART·SEC)는 Stage 3에서 추가한다. --offline을 사용하세요.")
    u = load_universe()
    # peer_groups.members는 티커만 적는다 → 같은 티커가 두 시장에 있으면 어느 종목인지 정할 수 없으므로 적재 전에 막는다
    market_of: dict[str, str] = {}
    for s in u.stocks:
        if s.ticker in market_of:
            raise ValueError(f"universe.yaml: 티커 {s.ticker}가 {market_of[s.ticker]}·{s.market}에 중복 — "
                             "peer_groups.members가 가리키는 종목을 정할 수 없다")
        market_of[s.ticker] = s.market
    # 마스터가 실패하면 뒤따르는 적재가 모두 의미 없으므로 FAILED를 기록한 뒤 예외를 전파한다(CLI가 0이 아닌 코드로 끝난다)
    with job_log(engine, source="INTERNAL", job_type="MASTER", label="universe", reraise=True) as res:
        with engine.begin() as conn:
            res.rows += upsert(conn, "markets", [
                {"code": m.code, "country": m.country, "currency": m.currency, "timezone": m.timezone}
                for m in u.markets], ["code"])
            mid = dict(conn.execute(text("SELECT code, market_id FROM markets")).all())
            res.rows += upsert(conn, "stocks", [
                {"market_id": mid[s.market], "ticker": s.ticker, "name": s.name,
                 "name_en": s.name if s.market in ("NASDAQ", "NYSE") else None, "is_active": True}
                for s in u.stocks], ["market_id", "ticker"], update=["name", "is_active"])
            res.rows += upsert(conn, "indices", [
                {"code": i.code, "name": i.name, "market_id": mid[i.market],
                 "source_symbol": i.source_symbol, "display_order": i.display_order}
                for i in u.indices], ["code"])
            res.rows += upsert(conn, "peer_groups", [{"name": g.name} for g in u.peer_groups], ["name"])
            gid = dict(conn.execute(text("SELECT name, group_id FROM peer_groups")).all())
            sid = {(m, t): i for i, m, t in conn.execute(text(
                "SELECT s.stock_id, m.code, s.ticker FROM stocks s JOIN markets m USING (market_id)")).all()}
            res.rows += upsert(conn, "peer_group_members", [
                {"group_id": gid[g.name], "stock_id": sid[(market_of[t], t)]}
                for g in u.peer_groups for t in g.members], ["group_id", "stock_id"])
            # ── [S2-D] 기본 사용자(demo) — get_current_user_id가 돌려주는 DEFAULT_USER_ID(=1)의 행 ──
            conn.execute(text("INSERT INTO users (nickname) VALUES ('demo') ON CONFLICT (nickname) DO NOTHING"))


# ── [S1-D] 시세 수집 ──
# 원본의 대량 경로(load_prices_bulk)·밸류에이션·재무·공시, 갱신 범위(scope) 구분은 Stage 3에서 추가한다.
PRICE_HISTORY_DAYS = 730       # 약 2년 → 종목당 약 485~500봉


def stock_refs(conn: Connection, tickers: list[str] | None = None) -> list[StockRef]:
    """수집 대상(활성 종목). tickers를 주면 그 종목만.
    yfinance 심볼은 universe.yaml 값을 쓰고, 없으면 시장 규칙(.KS/.KQ)으로 만든다."""
    where, params = "s.is_active", {}
    if tickers:
        where, params = "s.is_active AND s.ticker = ANY(:tickers)", {"tickers": tickers}
    yf = {(s.market, s.ticker): s.yf_symbol for s in load_universe().stocks}
    rows = conn.execute(text(f"""
        SELECT s.stock_id, m.code, m.country, s.ticker, m.timezone, s.corp_code, s.cik
        FROM stocks s JOIN markets m ON m.market_id = s.market_id
        WHERE {where} ORDER BY s.stock_id"""), params).all()
    return [StockRef(stock_id=r[0], market=r[1], country=r[2], ticker=r[3],
                     yf_symbol=yf.get((r[1], r[3])) or yf_symbol(r[1], r[3]),
                     timezone=r[4], corp_code=r[5], cik=r[6]) for r in rows]


def index_refs(conn: Connection) -> list[IndexRef]:
    meta = {i.code: i for i in load_universe().indices}
    rows = conn.execute(text("""
        SELECT i.index_id, i.code, m.country, m.timezone
        FROM indices i JOIN markets m ON m.market_id = i.market_id ORDER BY i.display_order""")).all()
    return [IndexRef(index_id=r[0], code=r[1], country=r[2], timezone=r[3],
                     pykrx_code=meta[r[1]].pykrx, yf_symbol=meta[r[1]].yf_symbol) for r in rows]


def _start_date(last: date | None, full: bool, history_days: int, today: date) -> date:
    if last is None or full:
        return today - timedelta(days=history_days)
    return last + timedelta(days=1)


def _market_today(tz: str, today: date) -> date:
    """시장 현지 날짜(today보다 늦지 않게). KST 오전의 미국은 아직 전날이라, 이미 최신인 종목에 열리지 않은 날을 요청하지 않는다."""
    return min(today, datetime.now(ZoneInfo(tz)).date())


def _no_session(start: date, end: date) -> str | None:
    """요청할 거래일이 없으면 사유. 주말뿐인 구간은 외부 호출 없이 '최신 상태'로 둔다."""
    if start > end:
        return "최신 상태"
    if all((start + timedelta(days=i)).weekday() >= 5 for i in range((end - start).days + 1)):
        return "최신 상태(주말)"
    return None


def load_prices(engine: Engine, providers: Providers, *, full: bool = False,
                tickers: list[str] | None = None, today: date | None = None,
                history_days: int = PRICE_HISTORY_DAYS) -> dict[str, str]:
    """종목 일봉. 기본은 증분(저장된 마지막 날짜 다음 날부터), --full이면 history_days(기본 2년) 전체 재수집."""
    today = today or date.today()
    statuses = {}
    with engine.connect() as conn:
        refs = stock_refs(conn, tickers)
        last = dict(conn.execute(text("SELECT stock_id, MAX(trade_date) FROM daily_prices GROUP BY stock_id")).all())
    for ref in refs:
        p = providers.price(ref.country)
        with job_log(engine, source=p.source, job_type="PRICES", stock_id=ref.stock_id, label=ref.ticker) as res:
            end = _market_today(ref.timezone, today)
            start = _start_date(last.get(ref.stock_id), full, history_days, today)
            if skip := _no_session(start, end):
                res.notes.append(skip)
            else:
                # yfinance는 시작일 이전 마지막 봉을 함께 돌려줄 수 있어 요청 구간만 남긴다
                fetched = [b for b in p.get_daily_prices(ref, start, end) if b.trade_date >= start]
                bars, bad = clean_bars(fetched, ref.timezone, require_volume=True)
                res.quarantined = bad
                with engine.begin() as conn:
                    res.rows = upsert(conn, "daily_prices", [
                        {"stock_id": ref.stock_id, "trade_date": b.trade_date, "open": b.open, "high": b.high,
                         "low": b.low, "close": b.close, "volume": b.volume} for b in bars],
                        ["stock_id", "trade_date"])
                res.notes.append(f"{start}~{end}")
        statuses[ref.ticker] = res.status
    return statuses


def load_indices(engine: Engine, providers: Providers, *, full: bool = False, today: date | None = None) -> dict[str, str]:
    today = today or date.today()
    statuses = {}
    with engine.connect() as conn:
        refs = index_refs(conn)
        last = dict(conn.execute(text("SELECT index_id, MAX(trade_date) FROM index_daily_prices GROUP BY index_id")).all())
    for ref in refs:
        p = providers.index(ref.country)
        with job_log(engine, source=p.source, job_type="INDICES", label=ref.code) as res:
            end = _market_today(ref.timezone, today)
            start = _start_date(last.get(ref.index_id), full, PRICE_HISTORY_DAYS, today)
            if skip := _no_session(start, end):
                res.notes.append(skip)
            else:
                fetched = [b for b in p.get_index_prices(ref, start, end) if b.trade_date >= start]
                bars, bad = clean_bars(fetched, ref.timezone, require_volume=False)
                res.quarantined = bad
                with engine.begin() as conn:
                    res.rows = upsert(conn, "index_daily_prices", [
                        {"index_id": ref.index_id, "trade_date": b.trade_date, "open": b.open, "high": b.high,
                         "low": b.low, "close": b.close} for b in bars], ["index_id", "trade_date"])
                res.notes.append(f"{start}~{end}")
        statuses[ref.code] = res.status
    return statuses


def load_fx_daily(engine: Engine, providers: Providers, *, full: bool = False, today: date | None = None) -> str:
    today = today or date.today()
    with engine.connect() as conn:
        last = conn.execute(text(
            "SELECT MAX(rate_at AT TIME ZONE 'Asia/Seoul')::date FROM fx_rates WHERE granularity = 'DAILY'")).scalar()
    with job_log(engine, source=providers.fx.source, job_type="FX", label="USD/KRW daily") as res:
        # 외환은 24시간 거래라 마지막 일자 값이 적재 후에도 바뀐다 → 마지막 일자부터 다시 받아 upsert
        start = _start_date(last - timedelta(days=1) if last else None, full, PRICE_HISTORY_DAYS, today)
        if start > today:
            res.notes.append("최신 상태")
        else:
            pts, bad = clean_fx([x for x in providers.fx.get_daily_rates(start, today) if x.rate_at.date() >= start])
            res.quarantined = bad
            with engine.begin() as conn:
                res.rows = upsert(conn, "fx_rates", [
                    {"rate_at": p.rate_at, "usd_krw": p.usd_krw, "granularity": "DAILY", "source": providers.fx.source}
                    for p in pts], ["granularity", "rate_at"])
            res.notes.append(f"{start}~{today}")
    return res.status


# ── [S3-C] 대량 일봉·밸류에이션 ──
# D의 RefreshService가 load_prices_bulk·load_valuations를 부른다. 반환은 {대상: 상태}
VALUATION_HISTORY_DAYS = 365   # KR 일별 밸류에이션 1년


# TODO(껍데기): C — 원본 load_prices_bulk로 교체 (지금은 아무것도 받지 않고 빈 결과)
def load_prices_bulk(engine: Engine, providers: Providers, stock_ids: list[int], *, history_days: int,
                     today: date | None = None, end: dict[str, date] | None = None) -> dict[str, str]:
    """종목이 많을 때의 일봉 증분 — 국내 날짜별 전 종목 조회, 미국 묶음 다운로드."""
    return {}


# TODO(껍데기): C — 원본 load_valuations로 교체 (지금은 아무것도 받지 않고 빈 결과)
def load_valuations(engine: Engine, providers: Providers, *, full: bool = False,
                    tickers: list[str] | None = None, today: date | None = None,
                    stock_ids: list[int] | None = None, history_days: int = VALUATION_HISTORY_DAYS) -> dict[str, str]:
    """KR: pykrx 일별(증분) / US: yfinance 스냅샷. KR provider가 없거나 실패하면 DART FY 기반 파생값(DERIVED)."""
    return {}


# ── [S3-B] 재무·공시 ──
# D의 RefreshService·Stage 4 상세 수집이 load_financials·load_disclosures를 부른다. 반환은 {대상: 상태}
DISCLOSURE_DAYS = 365
FIN_YEARS = 5


# TODO(껍데기): B — 원본 load_financials로 교체 (지금은 아무것도 받지 않고 빈 결과)
def load_financials(engine: Engine, providers: Providers, *, years: int = FIN_YEARS,
                    tickers: list[str] | None = None, stock_ids: list[int] | None = None) -> dict[str, str]:
    """FY 재무 years개년 — 국내 DART, 미국 SEC(+yfinance 보완)."""
    return {}


# TODO(껍데기): B — 원본 load_disclosures로 교체 (지금은 아무것도 받지 않고 빈 결과)
def load_disclosures(engine: Engine, providers: Providers, *, days: int = DISCLOSURE_DAYS,
                     tickers: list[str] | None = None, today: date | None = None,
                     stock_ids: list[int] | None = None) -> dict[str, str]:
    """최근 days일 공시 — 국내 DART, 미국 SEC."""
    return {}


# ---------------------------------------------------------------- 데모 사용자
DEMO_WATCHLIST = [("KOSPI", "005930"), ("KOSPI", "000660"), ("KOSPI", "035420"), ("KOSPI", "373220"),
                  ("NASDAQ", "AAPL"), ("NASDAQ", "NVDA"), ("NASDAQ", "MSFT"), ("NASDAQ", "TSLA")]


def seed_demo_watchlist(engine: Engine) -> int:
    with engine.begin() as conn:
        uid = conn.execute(text("SELECT user_id FROM users WHERE nickname = 'demo'")).scalar_one()
        rows = []
        for order, (market, ticker) in enumerate(DEMO_WATCHLIST, start=1):
            sid = conn.execute(text("""SELECT s.stock_id FROM stocks s JOIN markets m USING (market_id)
                                       WHERE m.code = :m AND s.ticker = :t"""), {"m": market, "t": ticker}).scalar_one()
            rows.append({"user_id": uid, "stock_id": sid, "sort_order": order})
        return upsert(conn, "watchlist_items", rows, ["user_id", "stock_id"], update=["sort_order"])
