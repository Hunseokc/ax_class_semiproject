"""환경변수 기반 설정. .env 파일이 있으면 함께 읽는다."""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]   # backend/ (컨테이너에서는 /srv)
CONFIG_DIR = ROOT_DIR / "config"


def _sibling(name: str) -> Path:
    """backend/와 같은 층(저장소 루트)의 폴더. 컨테이너처럼 backend 내용이 /srv에 펼쳐진 경우엔 ROOT_DIR 아래를 쓴다."""
    inside = ROOT_DIR / name
    return inside if inside.exists() else ROOT_DIR.parent / name


FRONTEND_DIR = _sibling("frontend")
DOCS_DIR = _sibling("docs")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(ROOT_DIR / ".env", ROOT_DIR.parent / ".env"), extra="ignore")

    database_url: str = "postgresql+psycopg://stock:stock@localhost:5432/stockdb"
    test_database_url: str = "postgresql+psycopg://stock:stock@localhost:5432/stockdb_test"
    price_source_kr: Literal["pykrx", "yfinance"] = "pykrx"
    krx_id: str = ""
    krx_pw: str = ""
    refresh_ttl_hours: float = Field(default=4, ge=3, le=4)
    dart_api_key: str = ""
    sec_user_agent: str = ""
    log_level: str = "INFO"
    default_user_id: int = Field(default=1, ge=1)
    scheduler_enabled: bool = True                       # 앱 안 스케줄러(4시간 갱신·비교군 1일 갱신)
    scheduler_check_minutes: int = Field(default=5, ge=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def export_krx_credentials() -> None:
    """pykrx는 import 시점에 os.environ의 KRX_ID/KRX_PW를 읽는다. pykrx import 전에 호출한다."""
    import os

    s = get_settings()
    if s.krx_id and s.krx_pw:
        os.environ.setdefault("KRX_ID", s.krx_id)
        os.environ.setdefault("KRX_PW", s.krx_pw)
