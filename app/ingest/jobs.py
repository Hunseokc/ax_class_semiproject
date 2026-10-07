"""수집·적재 작업. 각 함수는 대상 1건(종목·지수)마다 ingestion_logs 1행을 남긴다."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Engine, text

from app.core.config import ROOT_DIR, get_settings
from app.ingest.preprocess import clean_bars, clean_fx
from app.ingest.store import job_log, upsert
from app.ingest.universe import index_refs, load_universe, stock_refs
from app.providers.base import Financial, ProviderError
from app.providers.factory import Providers
from app.services.scoring import sync_presets

log = logging.getLogger(__name__)

PRICE_HISTORY_DAYS = 730       # 약 2년 → 종목당 약 485~500봉
VALUATION_HISTORY_DAYS = 365   # KR 일별 밸류에이션 1년
DISCLOSURE_DAYS = 365
FIN_YEARS = 5


# ---------------------------------------------------------------- DB 초기화
def init_db(engine: Engine, reset: bool = False) -> None:
    # SQL 파일은 파라미터 없이 psycopg로 직접 실행한다(주석 속 '%'가 placeholder로 해석되지 않도록)
    with engine.begin() as conn:
        raw = conn.connection.driver_connection
        if reset:
            raw.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        for name in ("schema.sql", "indexes.sql", "views.sql"):
            raw.execute((ROOT_DIR / "db" / name).read_text(encoding="utf-8"))
            log.info("적용: db/%s", name)
        sync_presets(conn)


def migrate(engine: Engine, name: str) -> None:
    path = ROOT_DIR / "db" / "migrations" / f"{name}.sql"
    with engine.begin() as conn:
        conn.connection.driver_connection.execute(path.read_text(encoding="utf-8"))
        sync_presets(conn)
    log.info("적용: %s", path.relative_to(ROOT_DIR))


# ---------------------------------------------------------------- 마스터
def load_master(engine: Engine, providers: Providers | None = None, offline: bool = False) -> None:
    """universe.yaml → markets·stocks·peer_groups·indices, 그리고 DART corp_code·SEC CIK 매핑."""
    u = load_universe()
    s = get_settings()
    with job_log(engine, source="INTERNAL", job_type="MASTER", label="universe") as res:
        with engine.begin() as conn:
            res.rows += upsert(conn, "markets", u["markets"], ["code"])
            mid = dict(conn.execute(text("SELECT code, market_id FROM markets")).all())
            res.rows += upsert(conn, "stocks", [
                {"market_id": mid[x["market"]], "ticker": x["ticker"], "name": x["name"],
                 "name_en": x.get("name_en") or (x["name"] if mid and x["market"] in ("NASDAQ", "NYSE") else None)}
                for x in u["stocks"]], ["market_id", "ticker"], update=["name"])
            res.rows += upsert(conn, "indices", [
                {"code": i["code"], "name": i["name"], "market_id": mid[i["market"]],
                 "source_symbol": i["pykrx"] if (i.get("pykrx") and s.price_source_kr == "pykrx") else i["yf_symbol"],
                 "display_order": i["display_order"]} for i in u["indices"]], ["code"])
            res.rows += upsert(conn, "peer_groups", [{"name": g["name"]} for g in u["peer_groups"]], ["name"])
            gid = dict(conn.execute(text("SELECT name, group_id FROM peer_groups")).all())
            sid = {t: i for t, i in conn.execute(text("SELECT ticker, stock_id FROM stocks")).all()}
            # 주 그룹(섹터 중립화 기준) = universe.yaml에서 종목이 처음 나오는 그룹
            seen: set[int] = set()
            members = []
            for g in u["peer_groups"]:
                for t in g["members"]:
                    s_id = sid[str(t)]
                    members.append({"group_id": gid[g["name"]], "stock_id": s_id, "is_primary": s_id not in seen})
                    seen.add(s_id)
            conn.execute(text("UPDATE peer_group_members SET is_primary = false WHERE is_primary"))
            res.rows += upsert(conn, "peer_group_members", members, ["group_id", "stock_id"], update=["is_primary"])
            conn.execute(text("INSERT INTO users (nickname) VALUES ('demo') ON CONFLICT (nickname) DO NOTHING"))
    if offline:
        return

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
        with engine.begin() as conn:
            conn.execute(text("UPDATE stocks SET corp_code = :corp_code, name_en = :name_en WHERE stock_id = :stock_id"), rows)
        res.rows = len(rows)
    with job_log(engine, source="SEC", job_type="MASTER", label="cik") as res:
        from app.providers.sec import SecClient
        ciks = SecClient().ciks({r.ticker for r in us})
        rows = [{"stock_id": r.stock_id, "cik": ciks[r.ticker]} for r in us if r.ticker in ciks]
        res.notes += [f"{r.ticker} CIK 없음" for r in us if r.ticker not in ciks]
        with engine.begin() as conn:
            conn.execute(text("UPDATE stocks SET cik = :cik WHERE stock_id = :stock_id"), rows)
        res.rows = len(rows)


# ---------------------------------------------------------------- 시세
def _start_date(last: date | None, full: bool, history_days: int, today: date) -> date:
    if last is None or full:
        return today - timedelta(days=history_days)
    return last + timedelta(days=1)


def load_prices(engine: Engine, providers: Providers, *, full: bool = False,
                tickers: list[str] | None = None, today: date | None = None) -> dict[str, str]:
    """종목 일봉. 기본은 증분(저장된 마지막 날짜 다음 날부터), --full이면 2년 전체 재수집."""
    today = today or date.today()
    statuses = {}
    with engine.connect() as conn:
        refs = stock_refs(conn, tickers)
        last = dict(conn.execute(text("SELECT stock_id, MAX(trade_date) FROM daily_prices GROUP BY stock_id")).all())
    for ref in refs:
        p = providers.price(ref.country)
        with job_log(engine, source=p.source, job_type="PRICES", stock_id=ref.stock_id, label=ref.ticker) as res:
            start = _start_date(last.get(ref.stock_id), full, PRICE_HISTORY_DAYS, today)
            if start > today:
                res.notes.append("최신 상태")
            else:
                # yfinance는 시작일 이전 마지막 봉을 함께 돌려줄 수 있어 요청 구간만 남긴다
                fetched = [b for b in p.get_daily_prices(ref, start, today) if b.trade_date >= start]
                bars, bad = clean_bars(fetched, ref.timezone, require_volume=True)
                res.quarantined = bad
                with engine.begin() as conn:
                    res.rows = upsert(conn, "daily_prices", [
                        {"stock_id": ref.stock_id, "trade_date": b.trade_date, "open": b.open, "high": b.high,
                         "low": b.low, "close": b.close, "volume": b.volume} for b in bars],
                        ["stock_id", "trade_date"])
                res.notes.append(f"{start}~{today}")
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
            start = _start_date(last.get(ref.index_id), full, PRICE_HISTORY_DAYS, today)
            if start > today:
                res.notes.append("최신 상태")
            else:
                fetched = [b for b in p.get_index_prices(ref, start, today) if b.trade_date >= start]
                bars, bad = clean_bars(fetched, ref.timezone, require_volume=False)
                res.quarantined = bad
                with engine.begin() as conn:
                    res.rows = upsert(conn, "index_daily_prices", [
                        {"index_id": ref.index_id, "trade_date": b.trade_date, "open": b.open, "high": b.high,
                         "low": b.low, "close": b.close} for b in bars], ["index_id", "trade_date"])
                res.notes.append(f"{start}~{today}")
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


# ---------------------------------------------------------------- 밸류에이션
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


def load_valuations(engine: Engine, providers: Providers, *, full: bool = False,
                    tickers: list[str] | None = None, today: date | None = None) -> dict[str, str]:
    """KR: pykrx 일별(증분) / US: yfinance 스냅샷(as_of = 해당 종목 최신 거래일).
    KR provider가 없거나 실패하면 DART FY 기반 파생값(DERIVED)으로 대체한다(ASSUMPTIONS A-02)."""
    today = today or date.today()
    statuses = {}
    with engine.connect() as conn:
        refs = stock_refs(conn, tickers)
        last = dict(conn.execute(text(
            "SELECT stock_id, MAX(as_of) FROM valuation_snapshots WHERE source <> 'DERIVED' GROUP BY stock_id")).all())
        last_trade = dict(conn.execute(text("SELECT stock_id, MAX(trade_date) FROM daily_prices GROUP BY stock_id")).all())
    for ref in refs:
        p = providers.valuation(ref.country)
        source = p.source if p else "DERIVED"
        with job_log(engine, source=source if source != "DERIVED" else "INTERNAL", job_type="VALUATION",
                     stock_id=ref.stock_id, label=ref.ticker) as res:
            if ref.country == "US":
                as_of = last_trade.get(ref.stock_id) or today
                vals = p.get_valuations(ref, as_of, as_of)
            elif p is not None:
                start = _start_date(last.get(ref.stock_id), full, VALUATION_HISTORY_DAYS, today)
                if start > today:
                    res.notes.append("최신 상태")
                    vals = []
                else:
                    try:
                        vals = p.get_valuations(ref, start, today)
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
                         "source": p.source} for v in vals], ["stock_id", "as_of"])
        statuses[ref.ticker] = res.status
    return statuses


# ---------------------------------------------------------------- 재무
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
                    tickers: list[str] | None = None) -> dict[str, str]:
    statuses = {}
    with engine.connect() as conn:
        refs = stock_refs(conn, tickers)
    for ref in refs:
        p = providers.financial(ref.country)
        source = p.source if p else ("DART" if ref.country == "KR" else "SEC")
        with job_log(engine, source=source, job_type="FINANCIALS", stock_id=ref.stock_id, label=ref.ticker) as res:
            if p is None:
                raise ProviderError(f"{source} 설정 없음(API 키/User-Agent)")
            if ref.country == "KR" and not ref.corp_code or ref.country == "US" and not ref.cik:
                raise ProviderError("corp_code/CIK 미매핑 — master 먼저 실행")
            fins = p.get_annual_financials(ref, years)
            if ref.country == "US" and providers.us_financial_supplement:
                try:
                    fins = merge_supplement(fins, providers.us_financial_supplement.get_annual_financials(ref, years))
                except ProviderError as e:
                    res.notes.append(f"yfinance 보완 실패: {e}")
                fins = fins[-years:]
            with engine.begin() as conn:
                res.rows = upsert(conn, "financial_statements", [
                    {"stock_id": ref.stock_id, "period_end": f.period_end, "period_type": f.period_type,
                     **{k: getattr(f, k) for k in FIN_FIELDS},
                     "data_source": f.data_source, "accounting_std": f.accounting_std} for f in fins],
                    ["stock_id", "period_end", "period_type"])
            for f in fins:
                missing = [k for k in FIN_FIELDS if getattr(f, k) is None]
                if f.notes or missing:
                    res.notes.append(f"{f.period_end.year}: " + ", ".join(f.notes + [f"{m} 없음" for m in missing]))
            if len(fins) < years:
                res.notes.append(f"FY {len(fins)}/{years}개")
        statuses[ref.ticker] = res.status
    return statuses


# ---------------------------------------------------------------- 공시
def load_disclosures(engine: Engine, providers: Providers, *, days: int = DISCLOSURE_DAYS,
                     tickers: list[str] | None = None, today: date | None = None) -> dict[str, str]:
    today = today or date.today()
    statuses = {}
    with engine.connect() as conn:
        refs = stock_refs(conn, tickers)
    for ref in refs:
        p = providers.disclosure(ref.country)
        source = p.source if p else ("DART" if ref.country == "KR" else "SEC")
        with job_log(engine, source=source, job_type="DISCLOSURES", stock_id=ref.stock_id, label=ref.ticker) as res:
            if p is None:
                raise ProviderError(f"{source} 설정 없음(API 키/User-Agent)")
            items = p.get_disclosures(ref, today - timedelta(days=days), today)
            with engine.begin() as conn:
                res.rows = upsert(conn, "disclosures", [
                    {"stock_id": ref.stock_id, "rcept_no": d.rcept_no, "title": d.title, "report_type": d.report_type,
                     "filed_at": d.filed_at, "url": d.url, "data_source": source} for d in items], ["rcept_no"])
        statuses[ref.ticker] = res.status
    return statuses


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
