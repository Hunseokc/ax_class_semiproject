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
    log_level: str = "INFO"
    # ── [S1-D] 시세 수집 ──
    price_source_kr: Literal["pykrx", "yfinance"] = "pykrx"
    krx_id: str = ""
    krx_pw: str = ""
    # ── [S2-D] 사용자·갱신 TTL ──
    default_user_id: int = Field(default=1, ge=1)   # 인증 없는 단일 사용자(demo) 모드: get_current_user_id가 돌려주는 값
    # 게스트 세션(배포용): 켜면 브라우저마다 쿠키로 게스트 사용자를 나눈다. 쿠키가 없을 때 조회는 default_user_id를 보여 준다
    guest_session_enabled: bool = False
    session_secret: str = ""                         # 세션 쿠키 서명 키. guest_session_enabled=true면 필수 (인스턴스끼리 같아야 함)
    refresh_ttl_hours: float = Field(default=4, ge=3, le=4)   # 같은 종류 외부 호출은 이 시간에 최대 1회 (FxService TTL)
    # ── [S3-D] 재무·공시 소스 ── (비어 있으면 factory가 DART·SEC provider를 만들지 않는다)
    dart_api_key: str = ""
    sec_user_agent: str = ""                         # 연락처(이메일)가 들어간 User-Agent — SEC EDGAR 필수
    # ── [S3-D] 스케줄러 ──
    scheduler_enabled: bool = True                       # 앱 안 스케줄러(4시간 갱신)
    scheduler_check_minutes: int = Field(default=5, ge=1)
    # 이후 단계 설정은 해당 단계 담당자가 이 클래스에 추가한다


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ── [S1-D] 시세 수집 ──
def export_krx_credentials() -> None:
    """pykrx는 import 시점에 os.environ의 KRX_ID/KRX_PW를 읽는다. pykrx import 전에 호출한다."""
    import os

    s = get_settings()
    if s.krx_id and s.krx_pw:
        os.environ.setdefault("KRX_ID", s.krx_id)
        os.environ.setdefault("KRX_PW", s.krx_pw)
