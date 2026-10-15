"""매력도 다중 팩터 모델 — 유니버스 안 상대적 위치를 나타내는 팩터 점수 (수익률 예측·투자 권유 아님).

계산은 SQL 3단계(app/queries/score_*.sql), 같은 as_of는 한 트랜잭션에서 DELETE 후 INSERT로 재생성한다.
  1) 지표 원값 → stock_metric_values.raw_value
  2) 국가 내 로버스트 Z(z_raw) → 주 그룹 축소 추정 섹터 중립화(z_adj)   — 프리셋과 무관, as_of당 1회
  3) 프리셋별 팩터 점수·종합·100·Φ 변환 → stock_scores
정의·근거는 docs/09_매력도_점수_정의서.md.

TODO(껍데기): C — 이 파일 전체. 이름·인자·반환 타입과 FACTORS·METRICS는 원본 그대로이고 본문만 비어 있다.
  - load_config: config/scoring.yaml을 읽고 validate_presets로 검증 (지금은 아래 _SHELL_CONFIG를 돌려줌)
  - validate_presets: 가중치 합 = 1 등 검증 (지금은 검사하지 않음)
  - sync_presets: 설정에서 빠진 프리셋 삭제까지 원본대로 (지금은 _SHELL_CONFIG 4종을 upsert만 — init-db·migrate가 호출)
  - insert_metric_values·normalize·aggregate·compute_scores: 계산 3단계 (지금은 아무것도 쓰지 않고 0 반환)
  그동안 화면·API용 점수는 seed-demo가 넣는 시드 행(app/ingest/demo.py)이 대신한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Engine, text

SEOUL = ZoneInfo("Asia/Seoul")
FACTORS = ("value", "quality", "growth", "safety", "momentum")
MIN_FACTORS = 3


@dataclass(frozen=True)
class Metric:
    factor: str
    label: str
    direction: int                    # +1: 클수록 좋음, −1: 작을수록 좋음
    null_reason: str


METRICS: dict[str, Metric] = {
    "earnings_yield":   Metric("value", "이익수익률 E/P", 1, "EPS·순이익 또는 종가 없음"),
    "book_yield":       Metric("value", "B/P", 1, "BPS 또는 종가 없음"),
    "roe":              Metric("quality", "ROE", 1, "재무 없음 또는 자본 ≤ 0"),
    "operating_margin": Metric("quality", "영업이익률", 1, "재무 없음 또는 매출 0"),
    "revenue_yoy":      Metric("growth", "매출 YoY", 1, "직전 FY 없음 또는 직전 매출 ≤ 0"),
    "eps_change_yield": Metric("growth", "EPS 변화/주가", 1, "직전 FY 없음 또는 주식수 없음"),
    "debt_ratio":       Metric("safety", "부채비율", -1, "재무(부채·자본) 없음"),
    "volatility":       Metric("safety", "변동성(1년)", -1, "일봉 253개 미만"),
    "momentum":         Metric("momentum", "12-1개월 수익률", 1, "일봉 127개 미만"),
}
NEGATIVE_METRICS = [k for k, m in METRICS.items() if m.direction < 0]

# 껍데기 전용: 원본 config/scoring.yaml(= migration 002_presets)과 같은 값. C가 scoring.yaml을 만들면 지운다
_SHELL_CONFIG = {
    "shrinkage_k": 5,
    "default_preset": "balanced",
    "presets": [
        {"code": "aggressive", "name": "위험", "description": "모멘텀·성장 중심", "sort_order": 1,
         "weights": {"value": 0.05, "quality": 0.10, "growth": 0.35, "safety": 0.10, "momentum": 0.40}},
        {"code": "growth", "name": "성장", "description": "성장성 중심", "sort_order": 2,
         "weights": {"value": 0.10, "quality": 0.20, "growth": 0.40, "safety": 0.05, "momentum": 0.25}},
        {"code": "balanced", "name": "균형", "description": "5개 팩터 균등", "sort_order": 3,
         "weights": {"value": 0.20, "quality": 0.20, "growth": 0.20, "safety": 0.20, "momentum": 0.20}},
        {"code": "value", "name": "가치", "description": "저평가·안정성 중심", "sort_order": 4,
         "weights": {"value": 0.40, "quality": 0.20, "growth": 0.10, "safety": 0.20, "momentum": 0.10}},
    ],
}


# ------------------------------------------------------------------ 설정·프리셋
def load_config() -> dict:
    return _SHELL_CONFIG


@lru_cache
def default_preset() -> str:
    return load_config()["default_preset"]


def validate_presets(presets: list[dict]) -> None:
    """프리셋별 가중치 합 = 1 (행 간 제약이라 DB CHECK 대신 적재 시 검증)."""


def sync_presets(conn: Connection, cfg: dict | None = None) -> None:
    """scoring.yaml 프리셋을 scoring_presets·scoring_weights에 맞춘다(재실행 안전)."""
    cfg = cfg or load_config()
    for p in cfg["presets"]:
        pid = conn.execute(text("""
            INSERT INTO scoring_presets (code, name, description, sort_order) VALUES (:code, :name, :description, :sort_order)
            ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description,
                                             sort_order = EXCLUDED.sort_order
            RETURNING preset_id"""), {k: p[k] for k in ("code", "name", "description", "sort_order")}).scalar_one()
        conn.execute(text("""
            INSERT INTO scoring_weights (preset_id, factor, weight) VALUES (:pid, :factor, :weight)
            ON CONFLICT (preset_id, factor) DO UPDATE SET weight = EXCLUDED.weight"""),
            [{"pid": pid, "factor": k, "weight": v} for k, v in p["weights"].items()])


# ------------------------------------------------------------------ 계산 단계
def insert_metric_values(conn: Connection, as_of: date) -> dict[int, list[str]]:
    """1단계. 반환: 종목별 메모(대체 계산·고정 사유)."""
    return {}


def normalize(conn: Connection, as_of: date, k: float) -> None:
    """2단계. z_raw(국가 내 로버스트 Z) → z_adj(섹터 중립화)."""


def aggregate(conn: Connection, as_of: date, notes: dict[int, list[str]] | None = None) -> int:
    """3단계. 프리셋별 점수 → stock_scores. 반환: 생성 행 수."""
    return 0


def compute_scores(engine: Engine, as_of: date | None = None) -> int:
    """as_of(기본: 오늘, 서울) 스냅샷을 다시 만든다. 반환: stock_scores 생성 행 수(종목 × 프리셋)."""
    return 0
