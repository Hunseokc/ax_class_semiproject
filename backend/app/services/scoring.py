"""매력도 다중 팩터 모델 — 유니버스 안 상대적 위치를 나타내는 팩터 점수 (수익률 예측·투자 권유 아님).

계산은 SQL 3단계(app/queries/score_*.sql), 같은 as_of는 한 트랜잭션에서 DELETE 후 INSERT로 재생성한다.
  1) 지표 원값 → stock_metric_values.raw_value (+ 종목별 이어지는 FY 수)
  2) 국가·점수 묶음(family) 내 로버스트 Z(z_raw) → 주 테마 축소 추정 섹터 중립화(z_adj, 저평가는 B/P만·안정성 제외)
     — 프리셋과 무관, as_of당 1회
  3) 프리셋별 팩터 점수(이력 축소·재표준화)·종합·같은 시장 백분위(국가·묶음 안) → stock_scores
점수 묶음(family): 주 테마의 scoring — general / financial(금융끼리). none(리츠·지주회사·상품 신탁)은 점수를 내지 않는다
정의·근거는 개발산출물/09_매력도_점수_정의서.md (모델 v2 — 검토_장부 D-002·D-003·D-010).
"""
from __future__ import annotations

import json
from collections import Counter
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
REQUIRED_FACTORS = ("value", "quality")                  # 이 둘이 없으면 점수를 내지 않는다(D-004 — 재무 없는 종목·신탁)
ONEOFF_RATIO = 1.2                                       # 순이익 > 1.2 × 영업이익이면 일회성 이익 배지(D-003)
FISCAL_GAP_DAYS = 182                                    # 최빈 결산일과 6개월 넘게 다르면 결산 시점 배지(D-008)
FAMILY_LABEL = {"general": None, "financial": "금융"}     # data_quality.partition 표시(KR·금융)


@dataclass(frozen=True)
class Metric:
    factor: str
    label: str
    direction: int                    # +1: 클수록 좋음, −1: 작을수록 좋음
    null_reason: str
    weight: int = 1                   # 팩터 안 가중치(안정성 = 변동성 2 · 부채/자산 1)
    penalty_only: bool = False        # Z를 0 이하로 자른다(나쁠 때만 깎고 좋을 때는 0)
    neutralize: bool = True           # 주 테마 섹터 중립화 여부(False면 z_adj = z_raw — 09 4절, D-018)


METRICS: dict[str, Metric] = {
    "conservative_yield": Metric("value", "세후 보수 이익/시총", 1, "재무(이익) 또는 시가총액 없음", neutralize=False),
    "book_yield":         Metric("value", "B/P", 1, "BPS 또는 종가 없음"),
    "trap_signal":        Metric("value", "가치 함정 신호(감점만)", 1, "2년 전 FY 없음 또는 계산할 수 있는 신호 3개 미만",
                                 penalty_only=True, neutralize=False),
    "return_on_assets":   Metric("quality", "총자산 이익률", 1, "재무(이익·자산) 없음"),
    "operating_margin":   Metric("quality", "영업이익률", 1, "재무 없음 또는 매출 0"),
    "revenue_cagr2":      Metric("growth", "2년 매출 연평균 성장률", 1, "2년 전 FY 없음 또는 2년 전 매출 ≤ 0"),
    "profit_growth2":     Metric("growth", "2년 이익 변화/2년 전 총자산", 1, "2년 전 FY 없음"),
    "volatility":         Metric("safety", "변동성(1년)", -1, "일봉 253개 미만", weight=2, neutralize=False),
    "liab_assets":        Metric("safety", "부채/자산", -1, "재무(부채·자산) 없음", neutralize=False),
    "momentum":           Metric("momentum", "12-1개월 수익률", 1, "일봉 127개 미만"),
}
NEGATIVE_METRICS = [k for k, m in METRICS.items() if m.direction < 0]
PENALTY_ONLY_METRICS = [k for k, m in METRICS.items() if m.penalty_only]
FIXED_METRICS = [k for k, m in METRICS.items() if not m.neutralize]


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
def partition_label(country: str, family: str) -> str:
    return "·".join(x for x in (country, FAMILY_LABEL.get(family)) if x)


def metric_params(cfg: dict | None = None, stock_id: int | None = None) -> dict:
    """score_metrics.sql 파라미터."""
    cfg = cfg or load_config()
    return {"stock_id": stock_id, "after_tax": float(cfg["after_tax"])}


def score_badges(fact: dict, family: str, fiscal_mode: date | None) -> list[dict]:
    """경고 배지(D-003): 일회성 이익 · 결산 시점 다름 · 재무 이력 짧음. fact = 최신 FY 결산일·순이익·영업이익·이어지는 FY 수."""
    out = []
    ni, oi = (None if fact.get(k) is None else float(fact[k]) for k in ("ni0", "oi0"))
    if family != "financial" and ni is not None and oi is not None and ni > 0 and (oi <= 0 or ni > ONEOFF_RATIO * oi):
        what = f"순이익이 영업이익의 {ni / oi:.1f}배" if oi > 0 else "영업적자인데 순이익 흑자"
        out.append({"code": "oneoff", "label": "일회성 이익",
                    "detail": f"{what} — 일회성 이익으로 보고 저평가 이익은 0.78 × 영업이익으로 계산했습니다. 순이익 기준 PER과 다를 수 있습니다."})
    end = fact.get("fy_end")
    if end and fiscal_mode and abs((end - fiscal_mode).days) > FISCAL_GAP_DAYS:
        months = round(abs((end - fiscal_mode).days) / 30.44)
        out.append({"code": "fiscal_gap", "label": "결산 시점 다름",
                     "detail": f"최신 연간 재무 결산 {end:%Y-%m} — 같은 시장 대부분({fiscal_mode:%Y-%m})과 약 {months}개월 차이라 "
                               f"업황 변화가 먼저(또는 늦게) 반영됩니다."})
    n = fact.get("fy_count")
    if n is not None and n < 3:
        out.append({"code": "short_history", "label": "재무 이력 짧음",
                    "detail": f"이어지는 연간 재무 {n}년 — 3년 평균·가치 함정 신호를 쓸 수 없어 저평가 점수를 {n}/3로 줄였습니다."})
    return out


def fiscal_modes(facts: dict[int, dict], countries: dict[int, str]) -> dict[str, date]:
    """국가별 최빈 최신 FY 결산일."""
    by: dict[str, Counter] = {}
    for sid, f in facts.items():
        if f.get("fy_end") and sid in countries:
            by.setdefault(countries[sid], Counter())[f["fy_end"]] += 1
    return {c: cnt.most_common(1)[0][0] for c, cnt in by.items()}


def insert_metric_values(conn: Connection, as_of: date, cfg: dict | None = None, facts: dict[int, dict] | None = None
                         ) -> tuple[dict[int, list[str]], dict[int, dict[str, str]], dict[int, int]]:
    """1단계. 반환: (종목별 메모 — 대체 계산, 종목별 규칙으로 비운 지표 {metric: 사유}, 종목별 이어지는 FY 수).
    facts를 주면 종목별 배지 재료(최신 FY 결산일·순이익·영업이익·FY 수)를 채운다."""
    rows = conn.execute(sql("score_metrics"), metric_params(cfg)).mappings().all()
    if rows:
        conn.execute(text("""INSERT INTO stock_metric_values (stock_id, as_of, metric, factor, raw_value)
                             VALUES (:stock_id, :as_of, :metric, :factor, :raw_value)"""),
                     [{**r, "as_of": as_of} for r in rows])
    notes: dict[int, list[str]] = {}
    excluded: dict[int, dict[str, str]] = {}
    history: dict[int, int] = {}
    for r in rows:
        history[r["stock_id"]] = r["fy_count"]
        if facts is not None:
            facts[r["stock_id"]] = {k: r[k] for k in ("fy_end", "ni0", "oi0", "fy_count")}
        if r["note"]:
            notes.setdefault(r["stock_id"], []).append(f"{r['metric']}: {r['note']}")
        if r["null_note"]:
            excluded.setdefault(r["stock_id"], {})[r["metric"]] = r["null_note"]
    return notes, excluded, history


def normalize(conn: Connection, as_of: date, k: float) -> None:
    """2단계. z_raw(국가·묶음 내 로버스트 Z) → z_adj(주 테마 섹터 중립화, FIXED_METRICS는 그대로)."""
    conn.execute(sql("score_zscore"), {"as_of": as_of, "negatives": NEGATIVE_METRICS, "penalty_only": PENALTY_ONLY_METRICS})
    conn.execute(sql("score_neutralize"), {"as_of": as_of, "k": k, "fixed": FIXED_METRICS})


def aggregate_params(as_of: date, history: dict[int, int] | None = None) -> dict:
    """score_aggregate.sql 파라미터. history가 없으면 모든 종목을 이력 3년으로 본다(축소 없음)."""
    history = history or {}
    weighted = {k: m.weight for k, m in METRICS.items() if m.weight != 1}
    return {"as_of": as_of, "w_metrics": list(weighted), "w_values": list(weighted.values()),
            "h_stocks": list(history), "h_counts": list(history.values()),
            "required": list(REQUIRED_FACTORS), "min_factors": MIN_FACTORS}


NO_FINANCIALS = "재무 정보가 없어 표기할 수 없습니다"


def null_reason(coverage: int, has_required: bool) -> tuple[str, str]:
    """점수를 내지 않는 이유 (코드, 문구). no_financials: 저평가·수익성을 계산할 재무가 없다 — 주가·B/P 같은
    일부 정보만으로 점수·요소값을 보이지 않는다(D-014, 재무 원천이 없는 해외 상장 등)."""
    if not has_required:
        return "no_financials", f"{NO_FINANCIALS} — 저평가·수익성을 계산할 재무가 없어 일부 지표만으로는 점수를 내지 않습니다"
    return "few_factors", f"유효 팩터 {coverage}/5개 — {MIN_FACTORS}개 이상이어야 점수를 냅니다"


def aggregate(conn: Connection, as_of: date, notes: dict[int, list[str]] | None = None,
              excluded: dict[int, dict[str, str]] | None = None, history: dict[int, int] | None = None,
              model_version: str | None = None, facts: dict[int, dict] | None = None) -> int:
    """3단계. 프리셋별 점수 → stock_scores. 반환: 생성 행 수."""
    if history is None:                                   # 단계별 테스트처럼 1단계를 건너뛰면 축소하지 않는다
        history = {sid: 3 for sid in conn.execute(text("SELECT DISTINCT stock_id FROM stock_metric_values "
                                                        "WHERE as_of = :d"), {"d": as_of}).scalars()}
    rows = conn.execute(sql("score_aggregate"), aggregate_params(as_of, history)).mappings().all()
    excluded = excluded or {}
    missing: dict[int, dict[str, str]] = {}
    for r in conn.execute(text("SELECT stock_id, metric FROM stock_metric_values WHERE as_of = :d AND z_adj IS NULL"),
                          {"d": as_of}):
        missing.setdefault(r.stock_id, {})[r.metric] = (excluded.get(r.stock_id, {}).get(r.metric)
                                                        or METRICS[r.metric].null_reason)
    facts = facts or {}
    modes = fiscal_modes(facts, {r["stock_id"]: r["country"] for r in rows})
    out = []
    for r in rows:
        dq: dict = {"partition": partition_label(r["country"], r["family"]), "family": r["family"],
                    "fy_history": history.get(r["stock_id"])}
        if r["stock_id"] in facts:
            mode = modes.get(r["country"])
            dq["badges"] = score_badges(facts[r["stock_id"]], r["family"], mode)
            dq["fiscal_mode"] = mode.isoformat() if mode else None
        if model_version:
            dq["model_version"] = model_version
        if r["stock_id"] in missing:
            dq["missing_metrics"] = missing[r["stock_id"]]
        unavailable = [f for f in FACTORS if r[f"{f}_score"] is None]
        if unavailable:
            dq["unavailable_factors"] = unavailable
        if r["composite"] is None:
            dq["score_null_code"], dq["score_null_reason"] = null_reason(r["factor_coverage"], r["has_required"])
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
            facts: dict[int, dict] = {}
            notes, excluded, history = insert_metric_values(conn, as_of, cfg, facts)
            normalize(conn, as_of, cfg["shrinkage_k"])
            res.rows = aggregate(conn, as_of, notes, excluded, history, cfg["model_version"], facts)
        res.notes.append(f"model={cfg['model_version']}, presets={len(cfg['presets'])}, k={cfg['shrinkage_k']}")
    if res.status != "SUCCESS":
        raise RuntimeError("점수 계산 실패 — ingestion_logs 참고")
    return res.rows
