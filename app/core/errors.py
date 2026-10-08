"""예외 → {"error": {"code", "message", "detail"}} 통일."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str, detail: Any = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail
        if code:
            self.code = code


class NotFound(AppError):
    status_code, code = 404, "NOT_FOUND"


class Conflict(AppError):
    status_code, code = 409, "CONFLICT"


class Unprocessable(AppError):
    status_code, code = 422, "UNPROCESSABLE"


class ServiceUnavailable(AppError):
    status_code, code = 503, "SERVICE_UNAVAILABLE"


def _body(code: str, message: str, detail: Any = None) -> dict:
    return {"error": {"code": code, "message": message, "detail": jsonable_encoder(detail)}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(_: Request, e: AppError):
        log.info("%s %s: %s", e.status_code, e.code, e.message)
        return JSONResponse(_body(e.code, e.message, e.detail), status_code=e.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, e: RequestValidationError):
        errs = [{"loc": list(x.get("loc", [])), "msg": x.get("msg"), "type": x.get("type")} for x in e.errors()]
        return JSONResponse(_body("VALIDATION_ERROR", "요청 값이 올바르지 않습니다", errs), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, e: StarletteHTTPException):
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(e.status_code, "HTTP_ERROR")
        return JSONResponse(_body(code, str(e.detail)), status_code=e.status_code)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, e: Exception):
        # 대부분은 main.request_context 미들웨어가 먼저 처리한다(요청 ID 유지). 이 핸들러는 그 바깥의 최후 방어선.
        log.exception("처리되지 않은 오류")
        return internal_error_response()


def internal_error_response() -> JSONResponse:
    """500 응답. 예외 메시지·스택·SQL·내부 경로는 응답에 넣지 않는다(서버 로그에만)."""
    return JSONResponse(_body("INTERNAL_ERROR", "서버 오류가 발생했습니다"), status_code=500)
