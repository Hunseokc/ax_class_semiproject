"""FastAPI 앱. API는 /api/v1, 정적 파일은 /static, 화면은 /, /stocks, /stocks/{market}/{ticker}, /portfolio.

실행: uvicorn app.main:app --reload
"""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import health, market, stocks
from app.core.config import FRONTEND_DIR, get_settings
from app.core.errors import NotFound, install_error_handlers, internal_error_response
from app.core.logging import request_id_var, setup_logging
from app.schemas.api import ErrorOut

setup_logging(get_settings().log_level)
log = logging.getLogger("app.request")
WEB_DIR = FRONTEND_DIR

# 앱 안 스케줄러(lifespan)는 Stage 3에서 추가한다
app = FastAPI(
    title="주식 분석 대시보드 API",
    version="0.1.0",
    description="국내·미국 주식 일봉·지수·환율·재무·공시 기반 조회·분석 API. 일봉 기준이며 투자 권유가 아닙니다.",
)
install_error_handlers(app)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """요청 ID를 contextvar에 넣어 모든 로그에 남기고 응답 헤더로 돌려준다."""
    token = request_id_var.set(request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12])
    t0 = time.perf_counter()
    try:
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001
            # 예상하지 못한 예외: 스택은 요청 ID와 함께 서버 로그에만 남기고, 응답에는 형식화된 500만 보낸다.
            # (Exception 핸들러는 이 미들웨어 바깥에서 돌아 요청 ID·헤더를 잃으므로 여기서 처리한다)
            log.exception("처리되지 않은 오류: %s %s", request.method, request.url.path)
            response = internal_error_response()
        response.headers["X-Request-ID"] = request_id_var.get()
        if not request.url.path.startswith("/api/"):
            # 화면·정적 파일은 매번 ETag/Last-Modified로 변경 여부를 확인(바뀌지 않았으면 304) → 수정한 CSS·JS가 바로 반영
            response.headers.setdefault("Cache-Control", "no-cache")
        log.info("%s %s → %d (%.0fms)", request.method, request.url.path, response.status_code,
                 (time.perf_counter() - t0) * 1000)
        return response
    finally:
        request_id_var.reset(token)


api = APIRouter(prefix="/api/v1", responses={404: {"model": ErrorOut}, 409: {"model": ErrorOut}, 422: {"model": ErrorOut}})
# 라우터 등록은 자기 구역에 import 1줄 + include_router 1줄만 추가한다.
# ── [S1-B] stocks·market ──
for r in (market.router, stocks.groups_router, stocks.router):
    api.include_router(r)

# ── [S2-B] watchlist ──

# ── [S2-C] portfolios ──
from app.api import portfolios  # noqa: E402
api.include_router(portfolios.router)

# ── [S3-B] financials·disclosures ──

# ── [S4] 매력도·비교군·분석 ──

# ── [S5] 홈 위젯·통계·검색 ──

app.include_router(api)
app.include_router(health.router)       # /health, /health/db — /api/v1 밖


# ------------------------------------------------------------------ 화면
if (WEB_DIR / "css").exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def _page(name: str) -> FileResponse:
    path = WEB_DIR / name
    if not path.exists():
        raise NotFound(f"화면 {name}이 아직 없습니다")
    return FileResponse(path)


@app.get("/", include_in_schema=False)
def page_home():
    return _page("index.html")


@app.get("/stocks", include_in_schema=False)
def page_stocks():
    return _page("stocks.html")


@app.get("/stocks/{market}/{ticker}", include_in_schema=False)
def page_stock(market: str, ticker: str):
    return _page("stock.html")


@app.get("/portfolio", include_in_schema=False)
def page_portfolio():
    return _page("portfolio.html")
