"""FastAPI 앱. API는 /api/v1, 정적 파일은 /static, 화면은 /, /stocks, /stocks/{market}/{ticker}, /portfolio.

실행: uvicorn app.main:app --reload
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import deps, market, portfolios, stocks, watchlist
from app.core.config import ROOT_DIR, get_settings
from app.core.db import get_engine
from app.core.errors import NotFound, install_error_handlers, internal_error_response
from app.core.logging import request_id_var, setup_logging
from app.schemas.api import ErrorOut
from app.services.fx import FxService
from app.services.scheduler import Scheduler

setup_logging(get_settings().log_level)
log = logging.getLogger("app.request")
WEB_DIR = ROOT_DIR / "web"

@asynccontextmanager
async def lifespan(_: FastAPI):
    """SCHEDULER_ENABLED면 앱 안 스케줄러(4시간 갱신·비교군 1일 갱신)를 백그라운드로 돌린다."""
    task = None
    if get_settings().scheduler_enabled:
        engine, ttl = get_engine(), get_settings().refresh_ttl_hours

        def refresh_service():
            pv = deps.get_providers()
            return deps.RefreshService(engine, pv, FxService(engine, pv.fx, ttl), ttl, scorer=deps.get_scorer())

        task = asyncio.create_task(Scheduler(engine, refresh_service, deps.get_providers, deps.get_scorer()).run_forever())
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    lifespan=lifespan,
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
for r in (market.router, stocks.groups_router, stocks.router, watchlist.router, portfolios.router):
    api.include_router(r)
if importlib.util.find_spec("app.api.analysis"):     # 5단계: 분석·경쟁 비교·통계
    from app.api import analysis
    api.include_router(analysis.router)
    api.include_router(analysis.stats_router)
    api.include_router(analysis.scoring_router)
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
