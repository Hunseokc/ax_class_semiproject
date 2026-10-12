"""요청·응답 스키마 (Swagger 문서의 근거).

공유 파일: 각 팀원은 자기 구역(`# ── [S{단계}-{팀원}] ... ──`) 아래에만 추가한다. 다른 구역은 수정하지 않는다.
구역에서 필요한 import(date·Decimal·Field·Num·Market·Ticker 등)는 이 파일 맨 위에 추가한다.
"""
from __future__ import annotations

from typing import Any, Literal

from app.schemas.common import Schema


# ------------------------------------------------------------------ 공통 오류
class ErrorBody(Schema):
    code: str
    message: str
    detail: Any = None


class ErrorOut(Schema):
    error: ErrorBody


# ------------------------------------------------------------------ 헬스체크
class HealthOut(Schema):
    status: Literal["ok"] = "ok"


class HealthDbOut(Schema):
    status: Literal["ok"] = "ok"
    db: Literal["ok"] = "ok"


# ── [S1-B] stocks·market ──────────────────────────────────────────
# (시장 지수·환율, 종목 목록·상세·candles·peer-groups 응답)

# ── [S2-B] watchlist ──────────────────────────────────────────────

# ── [S2-C] portfolios ─────────────────────────────────────────────

# ── [S3-B] financials·disclosures ─────────────────────────────────

# ── [S4-A] 매력도·프리셋 ──────────────────────────────────────────

# ── [S4-B] 비교군·분석 ────────────────────────────────────────────

# ── [S5] 메모·통계·검색·홈 위젯 ───────────────────────────────────
