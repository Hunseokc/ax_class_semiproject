"""매력도 다중 팩터 모델 — 유니버스 안 상대적 위치를 나타내는 팩터 점수 (수익률 예측·투자 권유 아님).

계산은 SQL 3단계(app/queries/score_*.sql), 같은 as_of는 한 트랜잭션에서 DELETE 후 INSERT로 재생성한다.
  1) 지표 원값 → stock_metric_values.raw_value
  2) 국가 내 로버스트 Z(z_raw) → 주 그룹 축소 추정 섹터 중립화(z_adj)   — 프리셋과 무관, as_of당 1회
  3) 프리셋별 팩터 점수·종합·100·Φ 변환 → stock_scores
정의·근거는 docs/09_매력도_점수_정의서.md.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from zoneinfo import ZoneInfo

import yaml
from sqlalchemy import Connection, Engine, text

from app.core.config import CONFIG_DIR
from app.ingest.store import job_log
from app.queries import sql

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


# ------------------------------------------------------------------ 설정·프리셋
def load_config() -> dict:
    with open(CONFIG_DIR / "scoring.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    validate_presets(cfg["presets"])
    return cfg


@lru_cache
def default_preset() -> str:
    return load_config()["default_preset"]


def validate_presets(presets: list[dict]) -> None:
    """프리셋별 가중치 합 = 1 (행 간 제약이라 DB CHECK 대신 적재 시 검증)."""
    if not presets:
        raise ValueError("scoring.yaml에 프리셋이 없습니다")
    orders = [p.get("sort_order") for p in presets]
    if not all(isinstance(o, int) for o in orders) or len(set(orders)) != len(orders):
        raise ValueError("프리셋마다 서로 다른 정수 sort_order가 필요합니다")
    for p in presets:
        w = {k: Decimal(str(v)) for k, v in p["weights"].items()}
        if set(w) != set(FACTORS):
            raise ValueError(f"프리셋 {p['code']}: 팩터 5개({', '.join(FACTORS)})의 가중치가 모두 필요합니다")
        if any(v < 0 or v > 1 or v != v.quantize(Decimal("0.001")) for v in w.values()):
            raise ValueError(f"프리셋 {p['code']}: 가중치는 0~1, 소수점 셋째 자리까지입니다")
        if sum(w.values()) != 1:
            raise ValueError(f"프리셋 {p['code']}: 가중치 합이 1이 아닙니다 ({sum(w.values())})")


def sync_presets(conn: Connection, cfg: dict | None = None) -> None:
    """scoring.yaml 프리셋을 scoring_presets·scoring_weights에 맞춘다(재실행 안전).
    설정에서 빠진 프리셋은 그 점수 행과 함께 삭제한다."""
    cfg = cfg or load_config()
    codes = [p["code"] for p in cfg["presets"]]
    removed = "SELECT preset_id FROM scoring_presets WHERE NOT (code = ANY(CAST(:codes AS text[])))"
    conn.execute(text(f"DELETE FROM stock_scores WHERE preset_id IN ({removed})"), {"codes": codes})
    conn.execute(text(f"DELETE FROM scoring_presets WHERE preset_id IN ({removed})"), {"codes": codes})
    for p in cfg["presets"]:
        pid = conn.execute(text("""
            INSERT INTO scoring_presets (code, name, description, sort_order) VALUES (:code, :name, :description, :sort_order)
            ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description,
                                             sort_order = EXCLUDED.sort_order
            RETURNING preset_id"""), {"code": p["code"], "name": p["name"], "description": p.get("description"),
                                      "sort_order": p["sort_order"]}).scalar_one()
        conn.execute(text("""
            INSERT INTO scoring_weights (preset_id, factor, weight) VALUES (:pid, :factor, :weight)
            ON CONFLICT (preset_id, factor) DO UPDATE SET weight = EXCLUDED.weight"""),
            [{"pid": pid, "factor": k, "weight": Decimal(str(v))} for k, v in p["weights"].items()])


# ------------------------------------------------------------------ 계산 단계
def insert_metric_values(conn: Connection, as_of: date) -> dict[int, list[str]]:
    """1단계. 반환: 종목별 메모(대체 계산·고정 사유)."""
    rows = conn.execute(sql("score_metrics")).mappings().all()
    if rows:
        conn.execute(text("""INSERT INTO stock_metric_values (stock_id, as_of, metric, factor, raw_value, z_raw)
                             VALUES (:stock_id, :as_of, :metric, :factor, :raw_value, :z_fixed)"""),
                     [{**r, "as_of": as_of} for r in rows])
    notes: dict[int, list[str]] = {}
    for r in rows:
        if r["note"]:
            notes.setdefault(r["stock_id"], []).append(f"{r['metric']}: {r['note']}")
    return notes


def normalize(conn: Connection, as_of: date, k: float) -> None:
    """2단계. z_raw(국가 내 로버스트 Z) → z_adj(섹터 중립화)."""
    conn.execute(sql("score_zscore"), {"as_of": as_of, "negatives": NEGATIVE_METRICS})
    conn.execute(sql("score_neutralize"), {"as_of": as_of, "k": k})


def aggregate(conn: Connection, as_of: date, notes: dict[int, list[str]] | None = None) -> int:
    """3단계. 프리셋별 점수 → stock_scores. 반환: 생성 행 수."""
    rows = conn.execute(sql("score_aggregate"), {"as_of": as_of}).mappings().all()
    missing: dict[int, dict[str, str]] = {}
    for r in conn.execute(text("SELECT stock_id, metric FROM stock_metric_values WHERE as_of = :d AND z_adj IS NULL"),
                          {"d": as_of}):
        missing.setdefault(r.stock_id, {})[r.metric] = METRICS[r.metric].null_reason
    out = []
    for r in rows:
        dq: dict = {"partition": r["country"]}
        if r["stock_id"] in missing:
            dq["missing_metrics"] = missing[r["stock_id"]]
        unavailable = [f for f in FACTORS if r[f"{f}_score"] is None]
        if unavailable:
            dq["unavailable_factors"] = unavailable
        if r["composite"] is None:
            dq["score_null_reason"] = f"유효 팩터 {r['factor_coverage']}/5개 — {MIN_FACTORS}개 이상이어야 점수를 냅니다"
        if notes and r["stock_id"] in notes:
            dq["notes"] = notes[r["stock_id"]]
        out.append({**r, "as_of": as_of, "dq": json.dumps(dq, ensure_ascii=False)})
    if out:
        conn.execute(text("""
            INSERT INTO stock_scores (stock_id, as_of, preset_id, value_score, quality_score, growth_score, safety_score,
                                      momentum_score, composite, score, factor_coverage, data_quality)
            VALUES (:stock_id, :as_of, :preset_id, :value_score, :quality_score, :growth_score, :safety_score,
                    :momentum_score, :composite, :score, :factor_coverage, CAST(:dq AS jsonb))"""), out)
    return len(out)


def compute_scores(engine: Engine, as_of: date | None = None) -> int:
    """as_of(기본: 오늘, 서울) 스냅샷을 다시 만든다. 반환: stock_scores 생성 행 수(종목 × 프리셋)."""
    as_of = as_of or datetime.now(SEOUL).date()
    cfg = load_config()
    with job_log(engine, source="INTERNAL", job_type="SCORES", label=str(as_of)) as res:
        with engine.begin() as conn:
            sync_presets(conn, cfg)
            conn.execute(text("DELETE FROM stock_scores WHERE as_of = :d"), {"d": as_of})
            conn.execute(text("DELETE FROM stock_metric_values WHERE as_of = :d"), {"d": as_of})
            notes = insert_metric_values(conn, as_of)
            normalize(conn, as_of, cfg["shrinkage_k"])
            res.rows = aggregate(conn, as_of, notes)
        res.notes.append(f"presets={len(cfg['presets'])}, k={cfg['shrinkage_k']}")
    if res.status != "SUCCESS":
        raise RuntimeError("점수 계산 실패 — ingestion_logs 참고")
    return res.rows
