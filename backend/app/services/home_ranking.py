"""대시보드 '시장 주목 종목' 순위 조회 — 라우터·화면과 분리한 서비스 함수.

대상 종목은 두 순위 모두 같다: 노출 종목(주식 리스트) + 사용자의 관심종목. 전 종목 스캔은 하지 않는다.
새 점수를 계산하거나 저장하지 않고, 이미 적재된 일봉·이미 계산된 매력도만 읽는다.
매력도 점수의 출처를 바꿀 때(예: 외부 모델 점수)는 get_attractiveness_ranking 내부만 교체하면 된다 —
반환 형식(rank·종목 식별자·value·as_of·is_watched)만 지키면 라우터·화면은 그대로 쓴다.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.queries import sql


def get_volume_surge_ranking(db: Session, country: str, limit: int = 5, *, user_id: int) -> list[dict]:
    """거래량 급증 TOP N. value = 당일 거래량 / 직전 20거래일 평균 거래량(배수). 20거래일 미만·거래량 0은 제외."""
    rows = db.execute(sql("home_volume_surge"), {"country": country, "limit": limit, "user_id": user_id})
    return [dict(r) for r in rows.mappings().all()]


def get_attractiveness_ranking(db: Session, country: str, limit: int = 5, *, preset: str, user_id: int,
                               family: str = "general") -> list[dict]:
    """매력도 순위 TOP N. value = 프리셋별 최신 매력도 점수(같은 시장·같은 점수 묶음 안 백분위). 점수 없는 종목은 제외.
    family: 점수 묶음(general / financial) — 금융끼리 매긴 백분위를 일반 기업과 한 줄에 세우지 않는다(D-003)."""
    rows = db.execute(sql("home_attractiveness"),
                      {"country": country, "limit": limit, "preset": preset, "user_id": user_id, "family": family})
    return [dict(r) for r in rows.mappings().all()]
