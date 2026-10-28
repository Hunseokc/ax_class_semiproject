"""OpenDART 재무정보 일괄다운로드(사업보고서) → financial_statements. 개발 PC에서 한 번 돌리는 첫 적재 (D10).

파일: 공시정보 활용마당 > 재무정보 일괄다운로드의 연도별 사업보고서(4Q) 재무상태표(BS)·손익계산서(PL) zip.
  zip 안에 cp949 탭 구분 txt가 여러 개(일반·금융기타·보험·은행·증권 × 별도·연결) 들어 있다.
  열: 재무제표종류 · 종목코드([005930]) · 회사명 · … · 결산기준일 · 보고서종류 · 통화 · 항목코드 · 항목명 · 당기 · 전기 · 전전기
  통화가 원화가 아니면(두산밥캣 USD) 결산일 USD/KRW로 환산해 넣는다(D-026 — jobs.to_krw, 환율은 DB fx_rates).
  손익 파일은 이름 없는 빈 열이 끼어 있어 열 위치가 파일마다 다르다 → 헤더 이름으로 찾는다.
  손익은 '손익계산서'(02)와 '단일 포괄손익계산서'(03) 중 회사가 고른 쪽에 있어 둘 다 읽는다.

계정 규칙은 DART API 적재와 같다(DartClient._extract — ACCOUNT_MAP, 연결 우선 → 별도). 파일마다 '당기' 값만 쓴다.
여러 해를 넣으려면 연도별 파일을 함께 넘긴다.

**임시 값이다(D-039)**: API 경로는 빈 해를 다음 해 보고서 전기값으로 채우고 추가 계정·분기도 받지만, 이 경로는 당기만 읽어
같은 회사의 FY 수가 달라진다(라운드 4 R4-1 — 대한조선 가치 14 ↔ 42위). 그래서 재무 유효기간을 PROVISIONAL_TTL(7일)로
짧게 두고 notes에 path=DART_BULK를 남긴다. 비교군에 뽑히면 그날 API로 다시 받는다(benchmark.select_benchmark).
"""
from __future__ import annotations

import logging
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Engine, text

from app.ingest.jobs import to_krw
from app.ingest.store import job_log, upsert
from app.ingest.us_bulk import PROVISIONAL_TTL
from app.providers.base import Financial, ProviderError
from app.providers.convert import to_dec
from app.providers.dart import DartClient
from app.services import freshness

log = logging.getLogger(__name__)

ENCODING = "cp949"
REQUIRED_COLUMNS: tuple[str, ...] = ("재무제표종류", "종목코드", "결산기준일", "보고서종류", "항목코드", "항목명", "당기")
CURRENCY_COLUMN = "통화"             # 있으면 읽는다(없는 옛 파일은 원화로 본다)
FIN_FIELDS = ("revenue", "operating_income", "net_income", "total_assets", "total_equity", "total_debt")
CURSOR_SOURCE = "DART_A001"          # jobs.FEED_SOURCE와 같은 값 — 일괄 적재 뒤 공시 증분이 이어 받을 지점
LOG_SOURCE = "DART_BULK"             # 하루 호출 예산(source='DART' 행)에 세지 않으려고 따로 둔다
CHUNK = 200                          # 회사 몇 개씩 한 트랜잭션으로 넣을지


@dataclass(frozen=True)
class BulkRow:
    stock_code: str                 # "005930" (괄호 제거)
    period_end: date                # 결산기준일
    consolidated: bool              # 연결재무제표면 True
    statement: str                  # "BS" / "IS" / "CIS"
    account_id: str                 # 항목코드
    account_nm: str                 # 항목명
    amount: Decimal | None          # 당기 금액(쉼표 제거). 빈 칸이면 None
    currency: str | None = None     # 표시통화(KRW·USD). 열이 없으면 None


def _statement(kind: str) -> str | None:
    if kind.startswith("재무상태표"):
        return "BS"
    if "포괄손익계산서" in kind:
        return "CIS"
    if "손익계산서" in kind:
        return "IS"
    return None


def parse_text(content: str, name: str = "") -> list[BulkRow]:
    """txt 한 개의 내용 → 행. 헤더 이름으로 열을 찾고, 없는 열이 있으면 ValueError(없는 열 이름 목록)."""
    lines = content.splitlines()
    if not lines:
        return []
    header = [h.strip() for h in lines[0].split("\t")]
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise ValueError(f"{name}: 필요한 열이 없습니다 — {', '.join(missing)}")
    col = {c: header.index(c) for c in REQUIRED_COLUMNS}      # 같은 이름이 둘이면 첫 번째(당기)
    cur = header.index(CURRENCY_COLUMN) if CURRENCY_COLUMN in header else None
    out = []
    for line in lines[1:]:
        c = line.split("\t")
        if len(c) <= max(col.values()):
            continue
        kind = c[col["재무제표종류"]].strip()
        stmt = _statement(kind)
        code = c[col["종목코드"]].strip().strip("[]")
        if stmt is None or not code.isdigit() or c[col["보고서종류"]].strip() != "사업보고서":
            continue
        out.append(BulkRow(stock_code=code, period_end=date.fromisoformat(c[col["결산기준일"]].strip()),
                           consolidated=kind.endswith("연결"), statement=stmt,
                           account_id=c[col["항목코드"]].strip(), account_nm=c[col["항목명"]].strip(),
                           amount=to_dec(c[col["당기"]]),
                           currency=(c[cur].strip().upper() or None) if cur is not None and cur < len(c) else None))
    return out


def parse_file(path: Path) -> list[BulkRow]:
    """txt 파일 하나, 또는 txt가 든 zip 하나. zip 안 파일 이름은 cp949."""
    if path.suffix.lower() != ".zip":
        return parse_text(path.read_bytes().decode(ENCODING), path.name)
    rows = []
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.filename.lower().endswith(".txt"):
                rows += parse_text(zf.read(info).decode(ENCODING), f"{path.name}:{info.filename}")
    return rows


def to_financials(rows: list[BulkRow]) -> dict[str, list[Financial]]:
    """종목코드 → FY 재무 목록(결산일 오름차순). 회사·결산일마다 연결 행이 있으면 연결만, 없으면 별도만."""
    groups: dict[tuple[str, date], dict[bool, list[BulkRow]]] = defaultdict(lambda: {True: [], False: []})
    for r in rows:
        groups[(r.stock_code, r.period_end)][r.consolidated].append(r)
    out: dict[str, list[Financial]] = defaultdict(list)
    order = {"BS": 0, "IS": 1, "CIS": 2}                       # API 응답과 같이 손익계산서를 포괄손익보다 먼저 본다
    for (code, period_end), by in groups.items():
        consolidated = bool(by[True])
        picked = sorted(by[consolidated], key=lambda r: order[r.statement])
        api_rows = [{"sj_div": r.statement, "account_id": r.account_id, "account_nm": r.account_nm,
                     "thstrm_amount": None if r.amount is None else str(r.amount)} for r in picked]
        vals, notes = DartClient._extract(api_rows, "thstrm_amount")
        if all(v is None for v in vals.values()):
            continue
        out[code].append(Financial(period_end=period_end, period_type="FY", data_source="DART", accounting_std="K-IFRS",
                                   notes=([] if consolidated else ["fs_div=OFS"]) + notes,
                                   currency=next((r.currency for r in picked if r.currency), None), **vals))
    return {k: sorted(v, key=lambda f: f.period_end) for k, v in out.items()}


def _db_rate_on(engine: Engine, day: date) -> Decimal | None:
    """결산일(또는 그 전 10일 안 가장 가까운 날)의 DB USD/KRW 일별 환율."""
    with engine.connect() as conn:
        return conn.execute(text("""SELECT usd_krw FROM fx_rates WHERE granularity = 'DAILY'
                                     AND (rate_at AT TIME ZONE 'Asia/Seoul')::date BETWEEN CAST(:d AS date) - 10 AND CAST(:d AS date)
                                     ORDER BY rate_at DESC LIMIT 1"""), {"d": day}).scalar()


def load_bulk(engine: Engine, paths: list[Path], *, as_of: date, years: int = 4) -> dict:
    """DB의 국내 종목(stocks.ticker)에 맞는 회사만 최근 years개 FY를 넣고 회사마다 재무 유효기간을 기록한다.
    공시 증분 기준점(ingest_cursor DART_A001)이 없거나 as_of보다 앞이면 as_of로 둔다(일괄 적재와 증분 사이 빈틈 방지).
    반환: {"files", "companies", "rows", "skipped"}"""
    out = {"files": len(paths), "companies": 0, "rows": 0, "skipped": 0}
    with job_log(engine, source=LOG_SOURCE, job_type="FINANCIALS", label=f"bulk {as_of}") as res:
        rows: list[BulkRow] = []
        for p in paths:
            rows += parse_file(p)
        fins = to_financials(rows)
        with engine.connect() as conn:
            ids = dict(conn.execute(text("""SELECT s.ticker, s.stock_id FROM stocks s JOIN markets m ON m.market_id = s.market_id
                                            WHERE m.country = 'KR'""")).all())
        matched = [(ids[code], fs[-years:]) for code, fs in fins.items() if code in ids]
        out["skipped"] = len(fins) - len(matched)
        converted = []                                   # 외화 공시(두산밥캣 USD)는 결산일 환율로 원화 환산(D-026)
        for sid, fs in matched:
            try:
                converted.append((sid, to_krw(fs, lambda d: _db_rate_on(engine, d))))
            except ProviderError as e:
                out["skipped"] += 1
                res.notes.append(f"stock_id {sid}: {e}")
        matched = converted
        now = datetime.now(timezone.utc)
        for i in range(0, len(matched), CHUNK):
            with engine.begin() as conn:
                for sid, fs in matched[i:i + CHUNK]:
                    out["rows"] += upsert(conn, "financial_statements", [
                        {"stock_id": sid, "period_end": f.period_end, "period_type": "FY", **{k: getattr(f, k) for k in FIN_FIELDS},
                         "data_source": f.data_source, "accounting_std": f.accounting_std,
                         "currency": f.currency, "fx_rate": f.fx_rate,
                         "notes": "; ".join(["path=DART_BULK", *f.notes])} for f in fs],
                        ["stock_id", "period_end", "period_type"])
                    freshness.mark_provisional(conn, "financials", sid, PROVISIONAL_TTL, now=now)
        out["companies"] = len(matched)
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO ingest_cursor (source, last_rcept_no, last_rcept_dt) VALUES (:s, :no, :d)
                ON CONFLICT (source) DO UPDATE SET last_rcept_no = EXCLUDED.last_rcept_no,
                                                   last_rcept_dt = EXCLUDED.last_rcept_dt, updated_at = now()
                WHERE ingest_cursor.last_rcept_dt < EXCLUDED.last_rcept_dt"""),
                {"s": CURSOR_SOURCE, "no": f"{as_of:%Y%m%d}000000", "d": as_of})
        res.rows = out["rows"]
        res.notes.append(f"파일 {out['files']} · 회사 {out['companies']} · DB에 없는 회사 {out['skipped']}")
    return out
