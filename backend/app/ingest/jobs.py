"""적재 작업: DB 초기화, 마스터(유니버스) 적재, 시세·지수·환율 수집, 밸류에이션·재무·공시 수집(Stage 3).

수집 작업은 대상 1건(종목·지수)마다 ingestion_logs 1행을 남긴다.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Engine, text

from app.core.config import ROOT_DIR
from app.ingest.preprocess import Quarantined, clean_bars, clean_fx
from app.ingest.store import (LOCK_WAIT_NOTE_SECONDS, BatchWriter, LockSession, Unit, default_flush_every, error_text,
                              job_log, provider_lock_key, upsert)
from app.ingest.universe import index_refs, load_universe, stock_refs
from app.providers.base import Financial, ProviderError, StockRef
from app.providers.factory import Providers
from app.services import freshness
from app.services.scoring import sync_presets

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
        sync_presets(conn)


# ── [S4-D] 마이그레이션 ──
def migrate(engine: Engine, name: str) -> None:
    """마이그레이션 파일 → views.sql 재적용(CREATE OR REPLACE라 멱등, 뷰에 붙인 열을 반영) → 프리셋 동기화."""
    path = ROOT_DIR / "db" / "migrations" / f"{name}.sql"
    with engine.begin() as conn:
        raw = conn.connection.driver_connection
        raw.execute(path.read_text(encoding="utf-8"))
        raw.execute((ROOT_DIR / "db" / "views.sql").read_text(encoding="utf-8"))
        sync_presets(conn)
    log.info("적용: %s", path.relative_to(ROOT_DIR))


# ---------------------------------------------------------------- 마스터
def load_master(engine: Engine, offline: bool = False) -> None:
    """universe.yaml → markets·stocks·indices·peer_groups·peer_group_members + 기본 사용자 demo (재실행해도 행 수 불변).

    offline이 아니면 이어서 DART corp_code·SEC CIK를 매핑한다(재무·공시 수집에 필요).
    """
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
            # [S4-D] 주 그룹(섹터 중립화·비교군 선정 기준) = universe.yaml에서 종목이 처음 나오는 그룹
            seen: set[int] = set()
            members = []
            for g in u.peer_groups:
                for t in g.members:
                    s_id = sid[(market_of[t], t)]
                    members.append({"group_id": gid[g.name], "stock_id": s_id, "is_primary": s_id not in seen})
                    seen.add(s_id)
            conn.execute(text("UPDATE peer_group_members SET is_primary = false WHERE is_primary AND stock_id = ANY(:ids)"),
                         {"ids": list(seen)})      # 노출 종목만 다시 정한다(비교군 종목의 주 그룹은 그대로)
            res.rows += upsert(conn, "peer_group_members", members, ["group_id", "stock_id"], update=["is_primary"])
            # ── [S2-D] 기본 사용자(demo) — get_current_user_id가 돌려주는 DEFAULT_USER_ID(=1)의 행 ──
            conn.execute(text("INSERT INTO users (nickname) VALUES ('demo') ON CONFLICT (nickname) DO NOTHING"))
    if offline:
        return

    # ── [S3-B] DART corp_code·SEC CIK 매핑 ──
    with engine.connect() as conn:
        refs = stock_refs(conn)
    kr = [r for r in refs if r.country == "KR"]
    us = [r for r in refs if r.country == "US"]
    with job_log(engine, source="DART", job_type="MASTER", label="corp_code") as res:
        from app.providers.dart import DartClient
        dart = DartClient()
        codes = dart.corp_codes({r.ticker for r in kr})
        rows = []
        for r in kr:
            if r.ticker not in codes:
                res.notes.append(f"{r.ticker} corp_code 없음")
                continue
            info = dart.company(codes[r.ticker])
            rows.append({"stock_id": r.stock_id, "corp_code": codes[r.ticker], "name_en": info.get("corp_name_eng")})
            if info.get("acc_mt") != "12":
                res.notes.append(f"{r.ticker} 결산월 {info.get('acc_mt')}")
        if rows:
            with engine.begin() as conn:
                conn.execute(text("UPDATE stocks SET corp_code = :corp_code, name_en = :name_en WHERE stock_id = :stock_id"), rows)
        res.rows = len(rows)
    with job_log(engine, source="SEC", job_type="MASTER", label="cik") as res:
        from app.providers.sec import SecClient
        ciks = SecClient().ciks({r.ticker for r in us})
        rows = [{"stock_id": r.stock_id, "cik": ciks[r.ticker]} for r in us if r.ticker in ciks]
        res.notes += [f"{r.ticker} CIK 없음" for r in us if r.ticker not in ciks]
        if rows:
            with engine.begin() as conn:
                conn.execute(text("UPDATE stocks SET cik = :cik WHERE stock_id = :stock_id"), rows)
        res.rows = len(rows)


# ── [S1-D] 시세 수집 ──
# 수집 대상(stock_refs·index_refs)은 universe.py에 있다. 갱신 범위(scope) 구분은 Stage 4에서 추가한다.
PRICE_HISTORY_DAYS = 730       # 약 2년 → 종목당 약 485~500봉


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
                stock_ids: list[int] | None = None, history_days: int = PRICE_HISTORY_DAYS) -> dict[str, str]:
    """종목 일봉. 기본은 증분(저장된 마지막 날짜 다음 날부터), --full이면 history_days(기본 2년) 전체 재수집."""
    today = today or date.today()
    statuses = {}
    with engine.connect() as conn:
        refs = stock_refs(conn, tickers, stock_ids=stock_ids)
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
DATA_CUTOFF = {"KR": (ZoneInfo("Asia/Seoul"), time(18, 0)), "US": (ZoneInfo("America/New_York"), time(17, 0))}
MAX_BULK_GAP_DAYS = 20         # 마지막 일봉이 이보다 오래된 종목은 날짜별 전 종목 조회 대신 종목별로 받는다
ADJ_TOLERANCE = Decimal("0.005")   # 저장된 전일 종가로 계산한 값과 0.5% 넘게 다르면 수정주가 이벤트(분할·증자·배당)로 본다


def last_closed_day(country: str, now: datetime | None = None) -> date:
    """데이터가 확정된 가장 최근 평일. 휴장일은 조회 결과가 비어 건너뛴다(장 마감 전 값 미적재, A-07)."""
    tz, cutoff = DATA_CUTOFF[country]
    local = (now or datetime.now(timezone.utc)).astimezone(tz)
    d = local.date() if local.time() >= cutoff else local.date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _last_prices(engine: Engine, stock_ids: list[int]) -> dict[int, tuple[date, Decimal]]:
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT ON (stock_id) stock_id, trade_date, close FROM daily_prices
            WHERE stock_id = ANY(:ids) ORDER BY stock_id, trade_date DESC"""), {"ids": stock_ids}).all()
    return {r.stock_id: (r.trade_date, r.close) for r in rows}


def _bar_row(stock_id: int, b) -> dict:
    return {"stock_id": stock_id, "trade_date": b.trade_date, "open": b.open, "high": b.high, "low": b.low,
            "close": b.close, "volume": b.volume}


def load_prices_bulk(engine: Engine, providers: Providers, stock_ids: list[int], *, history_days: int,
                     today: date | None = None, end: dict[str, date] | None = None) -> dict[str, str]:
    """비교군처럼 종목이 많을 때의 일봉 증분.
    국내: 날짜마다 전 종목 1회 조회(수정 전 가격). 거래소 등락률로 계산한 값이 저장된 전일 종가와 맞지 않으면
          분할·증자 등으로 과거 가격이 바뀐 것이라 그 종목만 수정주가로 전체를 다시 받는다(A-06).
    미국: 묶음 다운로드(수정주가). 마지막 저장일을 겹쳐 받아 값이 달라졌으면 그 종목 전체를 다시 받는다.
    이력이 없거나 오래 비어 있는 종목, 대량 provider가 없는 경우는 종목별 수집(load_prices)으로 넘긴다."""
    today = today or date.today()
    with engine.connect() as conn:
        refs = stock_refs(conn, stock_ids=stock_ids)
    last = _last_prices(engine, [r.stock_id for r in refs])
    statuses: dict[str, str] = {}
    per_ticker: list[int] = []
    refetch: list[int] = []

    kr = [r for r in refs if r.country == "KR"]
    if kr and providers.kr_bulk is not None:
        end_kr = (end or {}).get("KR") or last_closed_day("KR")
        cut = end_kr - timedelta(days=MAX_BULK_GAP_DAYS)
        bulk = [r for r in kr if r.stock_id in last and last[r.stock_id][0] >= cut]
        per_ticker += [r.stock_id for r in kr if r not in bulk]
        statuses.update({r.ticker: "SUCCESS" for r in bulk})
        todo = [r for r in bulk if last[r.stock_id][0] < end_kr]
        prev = {r.stock_id: last[r.stock_id] for r in todo}
        d = min((prev[r.stock_id][0] for r in todo), default=end_kr) + timedelta(days=1)
        adjusted: set[int] = set()
        while todo and d <= end_kr:
            if d.weekday() < 5:
                with job_log(engine, source=providers.kr_bulk.source, job_type="PRICES", label=f"전 종목 {d}") as res:
                    bars = providers.kr_bulk.get_bars_by_date(d)
                    rows = []
                    if not bars:
                        res.notes.append("휴장")
                    for r in todo:
                        b = bars.get(r.ticker)
                        if b is None or r.stock_id in adjusted or prev[r.stock_id][0] >= d:
                            continue
                        p0 = prev[r.stock_id][1]
                        if b.change_rate is not None and p0:
                            expected = p0 * (1 + b.change_rate / 100)
                            if expected and abs(b.close / expected - 1) > ADJ_TOLERANCE:
                                adjusted.add(r.stock_id)
                                continue
                        ok, bad = clean_bars([b], r.timezone, require_volume=True)
                        res.quarantined += [Quarantined({**q.row, "ticker": r.ticker}, q.reason) for q in bad]
                        rows += [_bar_row(r.stock_id, x) for x in ok]
                        if ok:
                            prev[r.stock_id] = (d, ok[0].close)
                    with engine.begin() as conn:
                        res.rows = upsert(conn, "daily_prices", rows, ["stock_id", "trade_date"])
                    if adjusted:
                        res.notes.append(f"수정주가 이벤트 {len(adjusted)}종목 → 다시 받음")
                if res.status != "SUCCESS":
                    statuses.update({r.ticker: "FAILED" for r in todo})
            d += timedelta(days=1)
        refetch += list(adjusted)
    else:
        per_ticker += [r.stock_id for r in kr]

    us = [r for r in refs if r.country == "US"]
    if us and providers.us_batch_price is not None:
        end_us = (end or {}).get("US") or last_closed_day("US")
        p = providers.us_batch_price
        new = [r for r in us if r.stock_id not in last]
        inc = [r for r in us if r.stock_id in last and last[r.stock_id][0] < end_us]
        statuses.update({r.ticker: "SUCCESS" for r in us if r not in new and r not in inc})
        for group, start in ((new, end_us - timedelta(days=history_days)),
                             (inc, min((last[r.stock_id][0] for r in inc), default=end_us))):
            if not group:
                continue
            with job_log(engine, source=p.source, job_type="PRICES", label=f"묶음 {len(group)}종목") as res:
                fetched = p.get_daily_prices_batch(group, start, end_us)
                rows = []
                for r in group:
                    bars = fetched.get(r.ticker)
                    if not bars:
                        statuses[r.ticker] = "FAILED"
                        continue
                    if r.stock_id in last:
                        d0, c0 = last[r.stock_id]
                        overlap = next((b for b in bars if b.trade_date == d0), None)
                        if overlap and overlap.close and abs(overlap.close / c0 - 1) > ADJ_TOLERANCE:
                            refetch.append(r.stock_id)
                            continue
                        bars = [b for b in bars if b.trade_date > d0]
                    ok, bad = clean_bars(bars, r.timezone, require_volume=True)
                    res.quarantined += [Quarantined({**q.row, "ticker": r.ticker}, q.reason) for q in bad]
                    rows += [_bar_row(r.stock_id, x) for x in ok]
                    statuses[r.ticker] = "SUCCESS"
                with engine.begin() as conn:
                    res.rows = upsert(conn, "daily_prices", rows, ["stock_id", "trade_date"])
                missing = [r.ticker for r in group if statuses.get(r.ticker) == "FAILED"]
                if missing:
                    res.notes.append(f"받지 못함: {', '.join(missing[:20])}")
            if res.status != "SUCCESS":
                statuses.update({r.ticker: "FAILED" for r in group})
    else:
        per_ticker += [r.stock_id for r in us]

    if per_ticker:
        statuses.update(load_prices(engine, providers, stock_ids=per_ticker, history_days=history_days, today=today))
    if refetch:
        statuses.update(load_prices(engine, providers, stock_ids=refetch, history_days=history_days, full=True, today=today))
    return statuses


# 국내 밸류에이션 대체 경로: 거래일 종가 × (FY 순이익·자본 ÷ 발행주식수) — pykrx가 없거나 실패할 때(A-02)
DERIVED_SQL = """
INSERT INTO valuation_snapshots (stock_id, as_of, per, pbr, eps, bps, market_cap, shares_outstanding, source)
SELECT d.stock_id, d.trade_date,
       CASE WHEN f.net_income > 0 THEN ROUND(d.close / (f.net_income / :shares), 4) END,
       CASE WHEN f.total_equity > 0 THEN ROUND(d.close / (f.total_equity / :shares), 4) END,
       ROUND(f.net_income / :shares, 4),
       ROUND(f.total_equity / :shares, 4),
       ROUND(d.close * :shares, 0),
       :shares,
       'DERIVED'
FROM daily_prices d
CROSS JOIN LATERAL (            -- 거래일 기준 공시 시차 90일을 둔 최신 FY
    SELECT fs.net_income, fs.total_equity FROM financial_statements fs
    WHERE fs.stock_id = d.stock_id AND fs.period_type = 'FY' AND fs.period_end <= d.trade_date - 90
    ORDER BY fs.period_end DESC LIMIT 1) f
WHERE d.stock_id = :stock_id AND d.trade_date >= :start
ON CONFLICT (stock_id, as_of) DO UPDATE SET
  per = EXCLUDED.per, pbr = EXCLUDED.pbr, eps = EXCLUDED.eps, bps = EXCLUDED.bps,
  market_cap = EXCLUDED.market_cap, shares_outstanding = EXCLUDED.shares_outstanding, source = EXCLUDED.source
"""


# ── [S5-D] 미국 밸류에이션 = 기초값(SEC 발행주식수·FY 순이익·자본) × 최신 종가 — 외부 호출 없음(A-123) ──
# (배당 dps는 SEC 기초값의 최근 FY 주당배당금을 그대로 옮긴다)
DERIVED_US_SQL = """
INSERT INTO valuation_snapshots (stock_id, as_of, per, pbr, eps, bps, market_cap, shares_outstanding, dps, source)
SELECT lp.stock_id, lp.trade_date,
       CASE WHEN f.net_income > 0 THEN ROUND(lp.close / (f.net_income / b.shares_outstanding), 4) END,
       CASE WHEN f.total_equity > 0 THEN ROUND(lp.close / (f.total_equity / b.shares_outstanding), 4) END,
       ROUND(f.net_income / b.shares_outstanding, 4),
       ROUND(f.total_equity / b.shares_outstanding, 4),
       ROUND(lp.close * b.shares_outstanding, 0),
       b.shares_outstanding, b.dps, 'DERIVED'
FROM fundamental_bases b
JOIN v_latest_price lp ON lp.stock_id = b.stock_id
LEFT JOIN LATERAL (SELECT fs.net_income, fs.total_equity FROM financial_statements fs
                   WHERE fs.stock_id = b.stock_id AND fs.period_type = 'FY'
                   ORDER BY fs.period_end DESC LIMIT 1) f ON true
WHERE b.stock_id = ANY(:ids) AND b.shares_outstanding > 0
ON CONFLICT (stock_id, as_of) DO UPDATE SET
  per = EXCLUDED.per, pbr = EXCLUDED.pbr, eps = EXCLUDED.eps, bps = EXCLUDED.bps, market_cap = EXCLUDED.market_cap,
  shares_outstanding = EXCLUDED.shares_outstanding, dps = EXCLUDED.dps, source = EXCLUDED.source
"""


def derive_us_valuations(engine: Engine, stock_ids: list[int]) -> int:
    if not stock_ids:
        return 0
    with engine.begin() as conn:
        return conn.execute(text(DERIVED_US_SQL), {"ids": stock_ids}).rowcount


def _has_base(engine: Engine, stock_ids: list[int]) -> set[int]:
    if not stock_ids:
        return set()
    with engine.connect() as conn:
        return set(conn.execute(text("""SELECT stock_id FROM fundamental_bases
                                        WHERE stock_id = ANY(:ids) AND shares_outstanding > 0"""),
                                {"ids": stock_ids}).scalars())


def load_valuations_bulk(engine: Engine, providers: Providers, stock_ids: list[int], *,
                         today: date | None = None, day: date | None = None) -> dict[str, str]:
    """국내: 확정된 최근 거래일 하루치 전 종목 밸류에이션(호출 2회)에서 대상만 저장.
    미국: 기초값 × 종가로 계산(호출 없음). 기초값이 아직 없는 종목은 종목별 수집으로 넘긴다."""
    with engine.connect() as conn:
        refs = stock_refs(conn, stock_ids=stock_ids)
    statuses: dict[str, str] = {}
    rest: list[int] = []
    kr = [r for r in refs if r.country == "KR"]
    if kr and providers.kr_bulk is not None:
        d = day or last_closed_day("KR")
        rows: list[dict] = []
        with job_log(engine, source=providers.kr_bulk.source, job_type="VALUATION", label=f"전 종목 {d}") as res:
            vals = {}
            for back in range(7):                       # 휴장일이면 그 전 거래일
                vals = providers.kr_bulk.get_valuations_by_date(d - timedelta(days=back))
                if vals:
                    break
            rows = [{"stock_id": r.stock_id, "as_of": v.as_of, "per": v.per, "pbr": v.pbr, "eps": v.eps, "bps": v.bps,
                     "market_cap": v.market_cap, "shares_outstanding": v.shares_outstanding, "dps": v.dps,
                     "source": providers.kr_bulk.source}
                    for r in kr if (v := vals.get(r.ticker)) is not None]
            with engine.begin() as conn:
                res.rows = upsert(conn, "valuation_snapshots", rows, ["stock_id", "as_of"])
        got = {row["stock_id"] for row in rows} if res.status == "SUCCESS" else set()
        statuses.update({r.ticker: "SUCCESS" if r.stock_id in got else "FAILED" for r in kr})
    else:
        rest += [r.stock_id for r in kr]
    us = [r for r in refs if r.country == "US"]
    based = _has_base(engine, [r.stock_id for r in us])
    if based:
        with job_log(engine, source="INTERNAL", job_type="VALUATION", label=f"기초값×종가 {len(based)}종목") as res:
            res.rows = derive_us_valuations(engine, sorted(based))
        statuses.update({r.ticker: res.status for r in us if r.stock_id in based})
    rest += [r.stock_id for r in us if r.stock_id not in based]
    if rest:
        statuses.update(load_valuations(engine, providers, stock_ids=rest, history_days=10, today=today))
    return statuses


def load_valuations(engine: Engine, providers: Providers, *, full: bool = False,
                    tickers: list[str] | None = None, today: date | None = None,
                    stock_ids: list[int] | None = None, history_days: int = VALUATION_HISTORY_DAYS) -> dict[str, str]:
    """KR: pykrx 일별(증분) / US: yfinance 스냅샷(as_of = 해당 종목 최신 거래일).
    KR provider가 없거나 실패하면 DART FY 기반 파생값(DERIVED)으로 대체한다(ASSUMPTIONS A-02)."""
    today = today or date.today()
    statuses = {}
    with engine.connect() as conn:
        refs = stock_refs(conn, tickers, stock_ids=stock_ids)
        last = dict(conn.execute(text(
            "SELECT stock_id, MAX(as_of) FROM valuation_snapshots WHERE source <> 'DERIVED' GROUP BY stock_id")).all())
        last_trade = dict(conn.execute(text("SELECT stock_id, MAX(trade_date) FROM daily_prices GROUP BY stock_id")).all())
    based = _has_base(engine, [r.stock_id for r in refs if r.country == "US"])
    kr_end = min(today, last_closed_day("KR"))       # KRX 공표 전 당일 값(0 → 빈 행)을 받지 않는다
    for ref in refs:
        p = providers.valuation(ref.country)
        source = p.source if p else "DERIVED"
        if ref.stock_id in based:                     # 미국: 기초값이 있으면 기초값 × 종가 (외부 호출 없음)
            with job_log(engine, source="INTERNAL", job_type="VALUATION", stock_id=ref.stock_id, label=ref.ticker) as res:
                res.rows = derive_us_valuations(engine, [ref.stock_id])
                res.notes.append("기초값 × 종가")
            statuses[ref.ticker] = res.status
            continue
        with job_log(engine, source=source if source != "DERIVED" else "INTERNAL", job_type="VALUATION",
                     stock_id=ref.stock_id, label=ref.ticker) as res:
            if ref.country == "US":
                as_of = last_trade.get(ref.stock_id) or today
                vals = p.get_valuations(ref, as_of, as_of)
            elif p is not None:
                start = _start_date(last.get(ref.stock_id), full, history_days, today)
                if start > kr_end:
                    res.notes.append("최신 상태")
                    vals = []
                else:
                    try:
                        vals = p.get_valuations(ref, start, kr_end)
                        if not vals and last.get(ref.stock_id) is None:
                            raise ProviderError("빈 응답")
                    except ProviderError as e:
                        res.notes.append(f"pykrx 실패 → DERIVED 대체: {e}")
                        vals, p = None, None
            else:
                vals = None
            if vals is None:     # DERIVED
                shares = providers.us_valuation.get_valuations(ref, today, today)[0].shares_outstanding
                if not shares:
                    raise ProviderError("발행주식수 없음 — DERIVED 계산 불가")
                with engine.begin() as conn:
                    res.rows = conn.execute(text(DERIVED_SQL), {
                        "stock_id": ref.stock_id, "shares": Decimal(shares),
                        "start": today - timedelta(days=VALUATION_HISTORY_DAYS)}).rowcount
                res.notes.append(f"DERIVED shares={shares}")
            elif vals:
                with engine.begin() as conn:
                    res.rows = upsert(conn, "valuation_snapshots", [
                        {"stock_id": ref.stock_id, "as_of": v.as_of, "per": v.per, "pbr": v.pbr, "eps": v.eps,
                         "bps": v.bps, "market_cap": v.market_cap, "shares_outstanding": v.shares_outstanding,
                         "dps": v.dps, "source": p.source} for v in vals if v.as_of <= kr_end or ref.country == "US"],
                        ["stock_id", "as_of"])
        statuses[ref.ticker] = res.status
    return statuses


# ── [S3-B] 재무·공시 ──
# D의 RefreshService·Stage 4 상세 수집이 load_financials·load_disclosures를 부른다. 반환은 {대상: 상태}
DISCLOSURE_DAYS = 365
FIN_YEARS = 5


FIN_FIELDS = ["revenue", "operating_income", "net_income", "total_assets", "total_equity", "total_debt"]


def merge_supplement(primary: list[Financial], supplement: list[Financial], tolerance_days: int = 7) -> list[Financial]:
    """주 소스(SEC)의 빈 값을 보완 소스(yfinance)의 같은 결산기 값으로 채운다.
    주 소스에 없는 결산기는 보완 소스 행을 그대로 추가한다(data_source=YFINANCE)."""
    out = list(primary)
    for s in supplement:
        match = next((p for p in out if abs((p.period_end - s.period_end).days) <= tolerance_days), None)
        if match is None:
            out.append(s)
            continue
        if match is s:
            continue
        for f in FIN_FIELDS:
            pv, sv = getattr(match, f), getattr(s, f)
            if pv is None and sv is not None:
                setattr(match, f, sv)
                match.notes.append(f"{f}←yfinance")
            elif f == "revenue" and pv and sv and abs(pv / sv - 1) > Decimal("0.02"):
                match.notes.append(f"매출 SEC/yfinance 차이 {pv / sv - 1:+.1%}")
    return sorted(out, key=lambda x: x.period_end)


def load_financials(engine: Engine, providers: Providers, *, years: int = FIN_YEARS,
                    tickers: list[str] | None = None, stock_ids: list[int] | None = None,
                    flush_every: int | None = None) -> dict[str, str]:
    """FY 재무 years개년 — 국내 DART, 미국 SEC(+yfinance 보완). 잠금은 회사 단위, 저장은 flush_every개 회사씩 묶음."""
    with engine.connect() as conn:
        refs = stock_refs(conn, tickers, stock_ids=stock_ids)
    return _load_financials(engine, providers, refs, years, flush_every or default_flush_every())


def _load_financials(engine: Engine, providers: Providers, refs: list, years: int, flush_every: int) -> dict[str, str]:
    def on_flush(units: list[Unit]) -> None:          # 미국: 기초값 저장 뒤 기초값 × 종가 밸류에이션
        ids = [u.stock_id for u in units if any(t == "fundamental_bases" for t, _, _ in u.writes)]
        if ids:
            derive_us_valuations(engine, ids)

    writer = BatchWriter(engine, flush_every, on_flush=on_flush)
    with LockSession(engine) as locks:
        try:
            for ref in refs:
                writer.add(_fetch_financials(providers, locks, ref, years))
        finally:
            writer.flush()
    return {u.label: u.status for u in writer.done}


def _fetch_financials(providers: Providers, locks: LockSession, ref: StockRef, years: int) -> Unit:
    """회사 1개 재무를 받아 저장할 행을 만든다(DB 쓰기 없음). 실패는 Unit.error에 남기고 예외를 올리지 않는다."""
    p = providers.financial(ref.country)
    source = p.source if p else ("DART" if ref.country == "KR" else "SEC")
    u = Unit(source=source, job_type="FINANCIALS", stock_id=ref.stock_id, label=ref.ticker, country=ref.country,
             kind="financials", started_at=datetime.now(timezone.utc))
    try:
        if p is None:
            raise ProviderError(f"{source} 설정 없음(API 키/User-Agent)")
        if ref.country == "KR" and not ref.corp_code or ref.country == "US" and not ref.cik:
            raise ProviderError("corp_code/CIK 미매핑 — master 먼저 실행")
        base = None
        with locks.hold(provider_lock_key(ref.country)) as waited:     # DART·SEC를 부르는 구간만
            fins = p.get_annual_financials(ref, years)
            # 미국 기초값(발행주식수·주당 배당)은 재무와 같은 SEC 응답에서 꺼낸다
            if ref.country == "US" and ref.cik and providers.us_reference is not None:
                try:
                    base = providers.us_reference.get_valuation_base(ref)
                except ProviderError as e:
                    u.notes.append(f"기초값 실패: {e}")
        if waited >= LOCK_WAIT_NOTE_SECONDS:
            u.notes.append(f"잠금 대기 {waited:.1f}초")
        if ref.country == "US" and providers.us_financial_supplement:     # yfinance 보완은 잠금 밖
            try:
                fins = merge_supplement(fins, providers.us_financial_supplement.get_annual_financials(ref, years))
            except ProviderError as e:
                u.notes.append(f"yfinance 보완 실패: {e}")
            fins = fins[-years:]
        rows = [{"stock_id": ref.stock_id, "period_end": f.period_end, "period_type": f.period_type,
                 **{k: getattr(f, k) for k in FIN_FIELDS},
                 "data_source": f.data_source, "accounting_std": f.accounting_std} for f in fins]
        u.writes.append(("financial_statements", rows, ["stock_id", "period_end", "period_type"]))
        u.rows = len(rows)
        for f in fins:
            missing = [k for k in FIN_FIELDS if getattr(f, k) is None]
            if f.notes or missing:
                u.notes.append(f"{f.period_end.year}: " + ", ".join(f.notes + [f"{m} 없음" for m in missing]))
        if len(fins) < years:
            u.notes.append(f"FY {len(fins)}/{years}개")
        if base is not None:
            if base.shares_outstanding is None and base.dps is None:
                u.notes.append("기초값 없음")
            else:
                u.writes.append(("fundamental_bases", [{
                    "stock_id": ref.stock_id, "shares_outstanding": base.shares_outstanding,
                    "shares_as_of": base.shares_as_of, "dps": base.dps, "dps_period_end": base.dps_period_end,
                    "source": providers.us_reference.source, "updated_at": datetime.now(timezone.utc)}], ["stock_id"]))
    except Exception as e:  # noqa: BLE001 — 회사 하나 실패는 기록하고 다음 회사로
        u.error = error_text(e)
        log.error("FINANCIALS %s 실패: %s", ref.ticker, u.error)
    return u


def load_disclosures(engine: Engine, providers: Providers, *, days: int = DISCLOSURE_DAYS,
                     tickers: list[str] | None = None, today: date | None = None,
                     stock_ids: list[int] | None = None, flush_every: int | None = None) -> dict[str, str]:
    """최근 days일 공시 — 국내 DART, 미국 SEC. 잠금은 회사 단위, 저장은 묶음."""
    today = today or date.today()
    with engine.connect() as conn:
        refs = stock_refs(conn, tickers, stock_ids=stock_ids)
    return _load_disclosures(engine, providers, refs, days, today, flush_every or default_flush_every())


def _load_disclosures(engine: Engine, providers: Providers, refs: list, days: int, today: date,
                      flush_every: int) -> dict[str, str]:
    writer = BatchWriter(engine, flush_every)
    with LockSession(engine) as locks:
        try:
            for ref in refs:
                writer.add(_fetch_disclosures(providers, locks, ref, days, today))
        finally:
            writer.flush()
    return {u.label: u.status for u in writer.done}


def _expire_fin_on_annual_report(conn: Connection, u: Unit) -> None:
    # ── [S5-D] 받아 둔 재무 뒤에 사업보고서·10-K가 새로 올라왔으면 재무 유효기간을 바로 끝낸다 ──
    if freshness.invalidate_on_annual_report(conn, u.stock_id):
        u.notes.append("새 사업보고서 → 재무 유효기간 만료")


def _fetch_disclosures(providers: Providers, locks: LockSession, ref: StockRef, days: int, today: date) -> Unit:
    p = providers.disclosure(ref.country)
    source = p.source if p else ("DART" if ref.country == "KR" else "SEC")
    u = Unit(source=source, job_type="DISCLOSURES", stock_id=ref.stock_id, label=ref.ticker, country=ref.country,
             kind="disclosures", started_at=datetime.now(timezone.utc))
    try:
        if p is None:
            raise ProviderError(f"{source} 설정 없음(API 키/User-Agent)")
        with locks.hold(provider_lock_key(ref.country)) as waited:
            items = p.get_disclosures(ref, today - timedelta(days=days), today)
        if waited >= LOCK_WAIT_NOTE_SECONDS:
            u.notes.append(f"잠금 대기 {waited:.1f}초")
        rows = [{"stock_id": ref.stock_id, "rcept_no": d.rcept_no, "title": d.title, "report_type": d.report_type,
                 "filed_at": d.filed_at, "url": d.url, "data_source": source} for d in items]
        u.writes.append(("disclosures", rows, ["rcept_no"]))
        u.rows = len(rows)
        u.after.append(_expire_fin_on_annual_report)
    except Exception as e:  # noqa: BLE001
        u.error = error_text(e)
        log.error("DISCLOSURES %s 실패: %s", ref.ticker, u.error)
    return u


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
