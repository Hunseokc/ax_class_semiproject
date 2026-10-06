"""FastAPI 앱. API는 /api/v1, 정적 파일은 /static, 화면은 /, /stocks, /stocks/{market}/{ticker}, /portfolio.

실행: uvicorn app.main:app --reload
"""
from __future__ import annotations

import importlib.util
import logging
import time
import uuid

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import market, portfolios, stocks, watchlist
from app.core.config import ROOT_DIR, get_settings
from app.core.errors import NotFound, install_error_handlers
from app.core.logging import request_id_var, setup_logging
from app.schemas.api import ErrorOut

setup_logging(get_settings().log_level)
log = logging.getLogger("app.request")
WEB_DIR = ROOT_DIR / "web"

app = FastAPI(
    title="주식 분석 대시보드 API",
    version="1.0.0",
    description="국내·미국 주식 일봉·지수·환율·재무·공시 기반 조회·분석 API. 일봉 기준이며 투자 권유가 아닙니다.",
)
install_error_handlers(app)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """요청 ID를 contextvar에 넣어 모든 로그에 남기고 응답 헤더로 돌려준다."""
    token = request_id_var.set(request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12])
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id_var.get()
        log.info("%s %s → %d (%.0fms)", request.method, request.url.path, response.status_code,
                 (time.perf_counter() - t0) * 1000)
        return response
    finally:
        request_id_var.reset(token)


api = APIRouter(prefix="/api/v1", responses={404: {"model": ErrorOut}, 409: {"model": ErrorOut}, 422: {"model": ErrorOut}})
for r in (market.router, stocks.groups_router, stocks.router, watchlist.router, portfolios.router):
    api.include_router(r)
if importlib.util.find_spec("app.api.analysis"):     # 5단계: 분석·경쟁 비교·통계
    from app.api import analysis
    api.include_router(analysis.router)
    api.include_router(analysis.stats_router)
app.include_router(api)

# ------------------------------------------------------------------ 화면 (6단계)
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
