"""오류 응답 형식: {"error": {"code", "message", "detail"}} 통일, 예상하지 못한 예외(500)의 형식·로그.

도메인 에러 코드(GROUP_NOT_FOUND·DUPLICATE_ITEM 등)와 입력 검증 경계값 테스트는 각 단계 담당자가 이 파일에 추가한다.
"""
import logging

import pytest
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import deps
from app.core.errors import AppError, Conflict, NotFound
from app.main import app


def code(r):
    return r.json()["error"]["code"]


# ---------------------------------------------------------------- 테스트 전용 라우트 (실제 API가 생기기 전 핸들러를 검증)
@app.get("/_test/not-found", include_in_schema=False)
def _raise_not_found():
    raise NotFound("없는 대상", detail={"id": 1})


@app.get("/_test/conflict", include_in_schema=False)
def _raise_conflict():
    raise Conflict("충돌", code="DUPLICATE_ITEM")


@app.get("/_test/app-error", include_in_schema=False)
def _raise_app_error():
    raise AppError("잘못된 요청")


@app.get("/_test/int/{value}", include_in_schema=False)
def _int_path(value: int):
    return {"value": value}


# ---------------------------------------------------------------- AppError 계열
def test_not_found_has_detail(client):
    r = client.get("/_test/not-found")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "NOT_FOUND", "message": "없는 대상", "detail": {"id": 1}}}


def test_conflict_with_custom_code(client):
    r = client.get("/_test/conflict")
    assert r.status_code == 409 and code(r) == "DUPLICATE_ITEM"
    assert r.json()["error"]["detail"] is None


def test_app_error_default_is_bad_request(client):
    r = client.get("/_test/app-error")
    assert r.status_code == 400 and code(r) == "BAD_REQUEST"


# ---------------------------------------------------------------- 프레임워크 오류도 같은 형식
def test_validation_error_format(client):
    r = client.get("/_test/int/abc")
    assert r.status_code == 422 and code(r) == "VALIDATION_ERROR"
    detail = r.json()["error"]["detail"]
    assert detail[0]["loc"] == ["path", "value"] and "msg" in detail[0] and "type" in detail[0]


def test_unknown_path_and_method(client):
    r = client.get("/api/v1/no-such-path")
    assert r.status_code == 404 and code(r) == "NOT_FOUND"
    r = client.post("/health")
    assert r.status_code == 405 and code(r) == "METHOD_NOT_ALLOWED"


def test_other_http_exception_is_http_error(client):
    def teapot():
        raise StarletteHTTPException(status_code=418, detail="teapot")
    app.dependency_overrides[deps.get_db] = teapot
    r = client.get("/health/db")
    assert r.status_code == 418 and code(r) == "HTTP_ERROR"


# ---------------------------------------------------------------- 500: 형식·정보 노출·로그
def test_unexpected_error_is_internal_error_without_leak(client, caplog):
    secret = "SELECT password FROM users -- /srv/app/secret.py"

    def boom():
        raise RuntimeError(secret)
    app.dependency_overrides[deps.get_db] = boom
    plain = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR):
        r = plain.get("/health/db", headers={"X-Request-ID": "req-500-test"})
    assert r.status_code == 500
    assert r.json() == {"error": {"code": "INTERNAL_ERROR", "message": "서버 오류가 발생했습니다", "detail": None}}
    assert "password" not in r.text and "/srv/" not in r.text and "Traceback" not in r.text
    assert r.headers["X-Request-ID"] == "req-500-test"                 # 500에도 요청 ID 헤더
    rec = next(x for x in caplog.records if x.levelno == logging.ERROR)
    assert rec.request_id == "req-500-test" and rec.exc_info is not None   # 서버 로그엔 요청 ID와 스택


def test_request_id_is_generated_when_missing(client):
    r = client.get("/health")
    assert len(r.headers["X-Request-ID"]) == 12


@pytest.mark.parametrize("path", ["/health", "/no-such-page"])
def test_non_api_responses_are_revalidated(client, path):
    """화면·정적 경로는 Cache-Control: no-cache (수정한 CSS·JS가 바로 반영)."""
    assert client.get(path).headers["Cache-Control"] == "no-cache"
