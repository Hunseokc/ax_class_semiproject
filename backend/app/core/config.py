"""환경변수 기반 설정. .env 파일이 있으면 함께 읽는다."""
from functools import lru_cache
from pathlib import Path

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
    log_level: str = "INFO"
    # 이후 단계 설정(시세 소스·API 키·갱신 TTL·기본 사용자·스케줄러)은 해당 단계 담당자가 이 클래스에 추가한다


@lru_cache
def get_settings() -> Settings:
    return Settings()
