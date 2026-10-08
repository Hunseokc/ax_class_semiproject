"""헬스체크: /health(DB 미접속), /health/db(SELECT 1, 실패 시 503 DB_UNAVAILABLE)."""
import time

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from app.api import deps
from app.main import app


def test_health_does_not_touch_db(client):
    def no_db():
        raise AssertionError("/health는 DB에 접근하면 안 된다")
    app.dependency_overrides[deps.get_engine_dep] = no_db
    app.dependency_overrides[deps.get_db] = no_db
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert r.headers["X-Request-ID"]


def test_health_db_ok(client):
    r = client.get("/health/db")
    assert r.status_code == 200 and r.json() == {"status": "ok", "db": "ok"}


class BrokenSession:
    def execute(self, *a, **kw):
        raise OperationalError("SELECT 1", {}, Exception("connection refused: host=db password=secret"))


def test_health_db_returns_503_when_query_fails(client):
    app.dependency_overrides[deps.get_db] = lambda: BrokenSession()
    r = client.get("/health/db")
    assert r.status_code == 503
    assert r.json() == {"error": {"code": "DB_UNAVAILABLE", "message": "DB에 연결할 수 없습니다", "detail": None}}
    assert "secret" not in r.text and r.headers["X-Request-ID"]


def test_health_db_returns_503_quickly_when_db_unreachable(client):
    """실제로 닫힌 포트에 연결 — 연결 오류도 503으로, 멈추지 않고 응답한다."""
    dead = create_engine("postgresql+psycopg://stock:stock@127.0.0.1:1/none", connect_args={"connect_timeout": 2})
    app.dependency_overrides[deps.get_engine_dep] = lambda: dead
    t0 = time.monotonic()
    r = client.get("/health/db")
    assert r.status_code == 503 and r.json()["error"]["code"] == "DB_UNAVAILABLE"
    assert time.monotonic() - t0 < 5
    dead.dispose()


def test_health_unknown_subpath_and_method(client):
    assert client.get("/health/nope").json()["error"]["code"] == "NOT_FOUND"
    r = client.post("/health")
    assert r.status_code == 405 and r.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_health_endpoints_in_swagger(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/health", "/health/db"} <= set(paths)
    assert "503" in paths["/health/db"]["get"]["responses"]
