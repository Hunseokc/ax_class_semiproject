"""외부 데이터 소스 smoke test.

실행: python -m app.ingest.smoke
결과는 콘솔과 docs/smoke_test_result.md 에 기록된다(실제 호출 결과만 기록).
"""
from __future__ import annotations

import io
import logging
import time
import zipfile
from datetime import date, datetime, timedelta
from xml.etree import ElementTree

import httpx
import yaml

from app.core.config import CONFIG_DIR, ROOT_DIR, export_krx_credentials, get_settings

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

PAUSE = 0.6
lines: list[str] = []


def out(s: str = "") -> None:
    print(s)
    lines.append(s)


def check(name: str, fn):
    """fn()은 (ok: bool, detail: str)을 반환한다. 예외는 FAIL로 기록."""
    try:
        ok, detail = fn()
    except Exception as e:  # noqa: BLE001 - smoke test는 모든 실패를 기록한다
        ok, detail = False, f"{type(e).__name__}: {str(e)[:200]}"
    detail = " ".join(str(detail).split())  # 표 깨짐 방지
    out(f"| {name} | {'OK' if ok else 'FAIL'} | {detail} |")
    time.sleep(PAUSE)
    return ok


def load_universe() -> dict:
    with open(CONFIG_DIR / "universe.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------- pykrx
def smoke_pykrx(u: dict) -> None:
    from pykrx import stock

    end = date.today().strftime("%Y%m%d")
    start = (date.today() - timedelta(days=30)).strftime("%Y%m%d")
    out("\n## pykrx\n")
    out("| 항목 | 결과 | 상세 |\n|---|---|---|")

    def ohlcv():
        df = stock.get_market_ohlcv(start, end, "005930", adjusted=True)
        return len(df) > 0, f"005930 수정주가 {len(df)}행, 컬럼={list(df.columns)}"

    def cap():
        df = stock.get_market_cap(start, end, "005930")
        return len(df) > 0, f"005930 {len(df)}행, 컬럼={list(df.columns)}"

    def fundamental():
        df = stock.get_market_fundamental(start, end, "005930")
        return len(df) > 0, f"005930 {len(df)}행, 컬럼={list(df.columns)}"

    def index(code):
        def f():
            df = stock.get_index_ohlcv(start, end, code)
            return len(df) > 0, f"{code} {len(df)}행, 컬럼={list(df.columns)}"
        return f

    check("일봉 get_market_ohlcv(adjusted=True)", ohlcv)
    check("시가총액 get_market_cap", cap)
    check("펀더멘털 get_market_fundamental", fundamental)
    check("지수 KOSPI(1001)", index("1001"))
    check("지수 KOSDAQ(2001)", index("2001"))

    out("\n### 국내 티커 검증 (pykrx 종목명)\n")
    out("| 티커 | 설정 이름 | pykrx 이름 | 일치 |\n|---|---|---|---|")
    for s in u["stocks"]:
        if s["market"] not in ("KOSPI", "KOSDAQ"):
            continue
        try:
            name = stock.get_market_ticker_name(s["ticker"])
        except Exception as e:  # noqa: BLE001
            name = f"ERROR {type(e).__name__}"
        name = name if isinstance(name, str) else "(없음)"
        match = "O" if name.replace(" ", "") == s["name"].replace(" ", "") else "X"
        out(f"| {s['ticker']} | {s['name']} | {name} | {match} |")
        time.sleep(0.2)


# ---------------------------------------------------------------- yfinance
def smoke_yfinance(u: dict) -> None:
    import yfinance as yf

    out("\n## yfinance\n")
    out("### 종목 일봉(2년, auto_adjust=True) 및 거래소 검증\n")
    out("| 시장 | 티커 | 심볼 | 행 수 | 첫 날짜 | 마지막 날짜 | 통화 | 거래소 | 결과 |\n|---|---|---|---|---|---|---|---|---|")
    expected_exch = {"KOSPI": "KSC", "KOSDAQ": "KOE", "NASDAQ": "NMS"}
    for s in u["stocks"]:
        sym = s["yf_symbol"]
        try:
            t = yf.Ticker(sym)
            h = t.history(period="2y", auto_adjust=True)
            fi = t.fast_info
            cur, exch = fi.get("currency"), fi.get("exchange")
            ok = len(h) > 0 and exch == expected_exch.get(s["market"], exch)
            out(f"| {s['market']} | {s['ticker']} | {sym} | {len(h)} | {h.index[0].date() if len(h) else '-'} | "
                f"{h.index[-1].date() if len(h) else '-'} | {cur} | {exch} | {'OK' if ok else 'FAIL'} |")
        except Exception as e:  # noqa: BLE001
            out(f"| {s['market']} | {s['ticker']} | {sym} | - | - | - | - | - | FAIL {type(e).__name__} |")
        time.sleep(PAUSE)

    out("\n### 지수·환율 (2년)\n")
    out("| 코드 | 심볼 | 행 수 | 마지막 날짜 | 마지막 종가 | 인덱스 tz |\n|---|---|---|---|---|---|")
    targets = [(i["code"], i["yf_symbol"]) for i in u["indices"]] + [("USD/KRW", u["fx"]["usd_krw"]["yf_symbol"])]
    for code, sym in targets:
        try:
            h = yf.Ticker(sym).history(period="2y")
            out(f"| {code} | {sym} | {len(h)} | {h.index[-1].date()} | {h['Close'].iloc[-1]:.4f} | {h.index.tz} |")
        except Exception as e:  # noqa: BLE001
            out(f"| {code} | {sym} | FAIL {type(e).__name__}: {e} | | | |")
        time.sleep(PAUSE)

    out("\n### 밸류에이션 필드 (Ticker.info)\n")
    keys = ["marketCap", "trailingPE", "priceToBook", "trailingEps", "bookValue", "sharesOutstanding", "currency"]
    out("| 심볼 | " + " | ".join(keys) + " |\n|---|" + "---|" * len(keys))
    for sym in ["005930.KS", "247540.KQ", "AAPL", "NVDA"]:
        try:
            info = yf.Ticker(sym).info
            out(f"| {sym} | " + " | ".join(str(info.get(k)) for k in keys) + " |")
        except Exception as e:  # noqa: BLE001
            out(f"| {sym} | FAIL {type(e).__name__} |")
        time.sleep(PAUSE)

    out("\n### 재무제표 (연간, 보완용)\n")
    out("| 심볼 | income_stmt 기간 수 | 기간 | 주요 행 존재 |\n|---|---|---|---|")
    want = ["Total Revenue", "Operating Income", "Net Income", "Total Assets", "Stockholders Equity", "Total Debt"]
    for sym in ["AAPL", "005930.KS"]:
        try:
            t = yf.Ticker(sym)
            inc, bs = t.income_stmt, t.balance_sheet
            idx = set(inc.index) | set(bs.index)
            have = ", ".join(f"{w}={'O' if w in idx else 'X'}" for w in want)
            out(f"| {sym} | {inc.shape[1]} | {[c.date().isoformat() for c in inc.columns]} | {have} |")
        except Exception as e:  # noqa: BLE001
            out(f"| {sym} | FAIL {type(e).__name__} | | |")
        time.sleep(PAUSE)


# ---------------------------------------------------------------- OpenDART
def smoke_dart(u: dict, key: str) -> None:
    out("\n## OpenDART\n")
    if not key:
        out("SKIPPED: DART_API_KEY 미설정")
        return
    base = "https://opendart.fss.or.kr/api"
    out("| 항목 | 결과 | 상세 |\n|---|---|---|")
    mapping: dict[str, str] = {}

    def corp_code():
        r = httpx.get(f"{base}/corpCode.xml", params={"crtfc_key": key}, timeout=60)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        root = ElementTree.fromstring(z.read(z.namelist()[0]))
        kr = {s["ticker"] for s in u["stocks"] if s["market"] in ("KOSPI", "KOSDAQ")}
        for el in root.iter("list"):
            sc = (el.findtext("stock_code") or "").strip()
            if sc in kr:
                mapping[sc] = el.findtext("corp_code")
        missing = kr - mapping.keys()
        return not missing, f"전체 {sum(1 for _ in root.iter('list'))}개 법인, 매핑 {len(mapping)}/{len(kr)}, 누락={sorted(missing)}"

    check("corpCode.xml 티커→corp_code", corp_code)
    cc = mapping.get("005930")
    if not cc:
        return

    def disclosure_list():
        r = httpx.get(f"{base}/list.json", params={
            "crtfc_key": key, "corp_code": cc,
            "bgn_de": (date.today() - timedelta(days=365)).strftime("%Y%m%d"),
            "end_de": date.today().strftime("%Y%m%d"), "page_count": 100}, timeout=30).json()
        first = r.get("list", [{}])[0]
        return r.get("status") == "000", f"status={r.get('status')}, total={r.get('total_count')}, 필드={list(first.keys())}"

    check("공시검색 list.json (삼성전자 1년)", disclosure_list)

    def fin(year: int, fs_div: str):
        def f():
            r = httpx.get(f"{base}/fnlttSinglAcntAll.json", params={
                "crtfc_key": key, "corp_code": cc, "bsns_year": str(year),
                "reprt_code": "11011", "fs_div": fs_div}, timeout=30).json()
            rows = r.get("list", [])
            names = {x.get("account_id") for x in rows}
            want = ["ifrs-full_Revenue", "dart_OperatingIncomeLoss", "ifrs-full_ProfitLoss",
                    "ifrs-full_Assets", "ifrs-full_Equity", "ifrs-full_Liabilities"]
            have = ", ".join(f"{w.split('_',1)[1]}={'O' if w in names else 'X'}" for w in want)
            return r.get("status") == "000", f"status={r.get('status')}, {len(rows)}행, {have}"
        return f

    last_fy = date.today().year - 1
    check(f"단일회사 전체재무제표 {last_fy} 사업보고서 CFS(연결)", fin(last_fy, "CFS"))
    check(f"단일회사 전체재무제표 {last_fy - 4} 사업보고서 CFS(연결)", fin(last_fy - 4, "CFS"))


# ---------------------------------------------------------------- SEC EDGAR
def smoke_sec(u: dict, ua: str) -> None:
    out("\n## SEC EDGAR\n")
    if not ua:
        out("SKIPPED: SEC_USER_AGENT 미설정 (연락처 없는 요청은 403 확인됨)")
        return
    headers = {"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}
    out("| 항목 | 결과 | 상세 |\n|---|---|---|")
    ciks: dict[str, str] = {}

    def tickers():
        r = httpx.get("https://www.sec.gov/files/company_tickers.json", headers=headers, timeout=30)
        r.raise_for_status()
        us = {s["ticker"] for s in u["stocks"] if s["market"] == "NASDAQ"}
        for v in r.json().values():
            if v["ticker"] in us:
                ciks[v["ticker"]] = str(v["cik_str"]).zfill(10)
        return us <= ciks.keys(), f"매핑 {len(ciks)}/{len(us)}: {ciks}"

    check("company_tickers.json 티커→CIK", tickers)
    # 매핑이 실패해도 응답 구조 확인은 계속한다 (AAPL CIK는 SEC 공시 원문 기준 0000320193)
    cik = ciks.get("AAPL", "0000320193")

    def submissions():
        r = httpx.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=headers, timeout=30)
        r.raise_for_status()
        rec = r.json()["filings"]["recent"]
        return True, f"recent 필드={list(rec.keys())[:8]}..., 건수={len(rec['accessionNumber'])}"

    check("submissions (AAPL)", submissions)

    def companyfacts():
        r = httpx.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", headers=headers, timeout=60)
        r.raise_for_status()
        g = r.json()["facts"]["us-gaap"]
        want = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "OperatingIncomeLoss",
                "NetIncomeLoss", "Assets", "StockholdersEquity", "LongTermDebt"]
        have = ", ".join(f"{w}={'O' if w in g else 'X'}" for w in want)
        fy = [x for x in g.get("NetIncomeLoss", {}).get("units", {}).get("USD", []) if x.get("fp") == "FY" and x.get("form") == "10-K"]
        years = sorted({x["end"] for x in fy})[-6:]
        return True, f"{have}; NetIncomeLoss 10-K FY end 최근={years}"

    check("companyfacts (AAPL)", companyfacts)


def main() -> None:
    s = get_settings()
    export_krx_credentials()
    u = load_universe()
    out("# Smoke Test 결과\n")
    out(f"- 실행 시각: {datetime.now().astimezone().isoformat(timespec='seconds')}")
    out(f"- PRICE_SOURCE_KR={s.price_source_kr}, KRX 로그인 설정={'예' if s.krx_id else '아니오'}")
    import pykrx, yfinance  # noqa: E401
    out(f"- pykrx {pykrx.__version__ if hasattr(pykrx, '__version__') else '?'}, yfinance {yfinance.__version__}")
    smoke_pykrx(u)
    smoke_yfinance(u)
    smoke_dart(u, s.dart_api_key)
    smoke_sec(u, s.sec_user_agent)
    path = ROOT_DIR / "docs" / "smoke_test_result.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n→ {path.relative_to(ROOT_DIR)} 저장")


if __name__ == "__main__":
    main()
