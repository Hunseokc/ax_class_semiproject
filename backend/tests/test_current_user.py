"""요청 사용자: 1차는 DEFAULT_USER_ID 설정값 (2차에서 JWT 검증으로 교체)."""
from app.api import deps
from app.core.config import Settings


def test_current_user_comes_from_default_user_id(monkeypatch):
    assert deps.get_current_user_id() == 1
    monkeypatch.setattr(deps, "get_settings", lambda: Settings(default_user_id=2))
    assert deps.get_current_user_id() == 2
