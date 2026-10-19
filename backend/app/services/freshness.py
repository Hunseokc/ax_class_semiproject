"""데이터 유효기간 — 가격 외 데이터를 종목·종류별로 언제 다시 받을지 정한다(data_freshness).

- 일봉은 이 표와 관계없이 항상 빠진 날짜만 증분으로 받는다(가격은 매 거래일 바뀐다).
- financials(FY 재무 + 미국 밸류에이션 기초값): 공시 일정 기반 + 90일 상한
    valid_until = min(받은 시각 + 90일(종목마다 0~6일 앞당겨 분산), 다음 사업보고서·10-K 예상일)
    다음 예상일 = 최신 FY 결산일 + 1년 + 제출 기한(90일) + 여유(7일)
    예상일이 이미 지났는데 새 FY가 없으면(제출 지연) 7일 뒤 다시 확인, 받지 못했으면(실패) 1일 뒤
    정기보고서 공시(사업보고서·10-K)가 받은 시각 뒤에 새로 올라오면 그때 바로 만료시킨다(invalidate_on_annual_report)
- disclosures: 1일 (상세를 열 때만 받는다)
- price_history: 2년 일봉 백필을 한 뒤 1년 (신규 상장처럼 원래 짧은 이력을 매번 다시 받지 않도록)
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, text

FIN_CAP = timedelta(days=90)
FILING_DAYS = {"KR": 90, "US": 90}         # 결산 후 사업보고서(국내 90일)·10-K(미국 60~90일) 제출 기한
FILING_GRACE = timedelta(days=7)
OVERDUE_RETRY = timedelta(days=7)
FAILED_RETRY = timedelta(days=1)
STAGGER_DAYS = 7                            # 같은 날 받은 종목들이 같은 날 한꺼번에 만료되지 않도록
TTL = {"disclosures": timedelta(days=1), "price_history": timedelta(days=365)}
ANNUAL_FORMS = ("10-K", "10-K/A")
SEOUL = ZoneInfo("Asia/Seoul")


def _plus_year(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:                      # 2월 29일
        return d.replace(year=d.year + 1, day=28)


def financials_valid_until(country: str, latest_fy_end: date | None, fetched_at: datetime, stock_id: int) -> datetime:
    if latest_fy_end is None:
        return fetched_at + OVERDUE_RETRY
    next_due = datetime.combine(_plus_year(latest_fy_end) + timedelta(days=FILING_DAYS[country]), time(0), SEOUL) + FILING_GRACE
    if next_due <= fetched_at:
        return fetched_at + OVERDUE_RETRY
    return min(fetched_at + FIN_CAP - timedelta(days=stock_id % STAGGER_DAYS), next_due)


def due(conn: Connection, kind: str, stock_ids: list[int], now: datetime | None = None,
        *, limit: int | None = None) -> list[int]:
    """유효기간이 지났거나 기록이 없는 종목.
    limit=None: 입력 순서 그대로. limit 지정: 기록 없음 → valid_until 오래된 순 → stock_id 순으로 앞 limit개(하루 예산)."""
    if not stock_ids or (limit is not None and limit <= 0):
        return []
    now = now or datetime.now(timezone.utc)
    if limit is not None:
        return list(conn.execute(text("""
            SELECT s.id
            FROM unnest(CAST(:ids AS int[])) AS s(id)
            LEFT JOIN data_freshness f ON f.stock_id = s.id AND f.kind = :k
            WHERE f.valid_until IS NULL OR f.valid_until <= :now
            ORDER BY f.valid_until ASC NULLS FIRST, s.id
            LIMIT :limit"""), {"ids": stock_ids, "k": kind, "now": now, "limit": limit}).scalars())
    fresh = set(conn.execute(text("""SELECT stock_id FROM data_freshness
                                     WHERE kind = :k AND stock_id = ANY(:ids) AND valid_until > :now"""),
                             {"k": kind, "ids": stock_ids, "now": now}).scalars())
    return [s for s in stock_ids if s not in fresh]


def _upsert(conn: Connection, kind: str, stock_id: int, fetched_at: datetime, valid_until: datetime,
            status: str, error: str | None) -> None:
    conn.execute(text("""
        INSERT INTO data_freshness (stock_id, kind, fetched_at, valid_until, status, error)
        VALUES (:s, :k, :f, :v, :st, :e)
        ON CONFLICT (stock_id, kind) DO UPDATE SET fetched_at = EXCLUDED.fetched_at, valid_until = EXCLUDED.valid_until,
                                                   status = EXCLUDED.status, error = EXCLUDED.error"""),
                 {"s": stock_id, "k": kind, "f": fetched_at, "v": valid_until, "st": status, "e": error})


def mark(conn: Connection, kind: str, stock_id: int, ok: bool, *, country: str = "KR", error: str | None = None,
         now: datetime | None = None) -> datetime:
    """수집 결과를 기록하고 valid_until을 돌려준다."""
    now = now or datetime.now(timezone.utc)
    if not ok:
        until = now + FAILED_RETRY
    elif kind == "financials":
        latest = conn.execute(text("""SELECT MAX(period_end) FROM financial_statements
                                      WHERE stock_id = :s AND period_type = 'FY'"""), {"s": stock_id}).scalar()
        until = financials_valid_until(country, latest, now, stock_id)
    else:
        until = now + TTL[kind]
    _upsert(conn, kind, stock_id, now, until, "SUCCESS" if ok else "FAILED", (error or "")[:500] or None)
    return until


def invalidate_on_annual_report(conn: Connection, stock_id: int) -> int:
    """받은 뒤에 사업보고서·10-K가 새로 공시됐으면 재무를 바로 만료시킨다. 반환: 만료시킨 행 수(0/1)."""
    return conn.execute(text("""
        UPDATE data_freshness f SET valid_until = f.fetched_at
        WHERE f.stock_id = :s AND f.kind = 'financials' AND f.valid_until > now()
          AND EXISTS (SELECT 1 FROM disclosures d
                      WHERE d.stock_id = f.stock_id AND d.filed_at > f.fetched_at
                        AND (d.title LIKE '%사업보고서%' OR d.report_type = ANY(:forms)))"""),
        {"s": stock_id, "forms": list(ANNUAL_FORMS)}).rowcount
