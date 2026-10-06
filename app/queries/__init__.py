"""SQL 원문 로더. 조회·분석 쿼리는 app/queries/*.sql에 원문으로 두고 text()로 실행한다."""
from functools import lru_cache
from pathlib import Path

from sqlalchemy import TextClause, text

_DIR = Path(__file__).parent


@lru_cache
def sql(name: str) -> TextClause:
    return text((_DIR / f"{name}.sql").read_text(encoding="utf-8"))


def raw(name: str) -> str:
    return (_DIR / f"{name}.sql").read_text(encoding="utf-8")
