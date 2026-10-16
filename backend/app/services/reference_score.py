"""상장 목록(listed) 종목의 참고 매력도 — 유니버스에 넣지 않고, 최신 점수 스냅샷의 분포에 지표를 대입한다.

유니버스(노출 종목 + 비교군)의 점수는 그대로 두어 재현성을 지키고(클릭한 종목에 따라 점수가 바뀌지 않음),
listed 종목은 요청할 때마다 계산해 저장하지 않는다.
  1) 지표 원값: score_metrics.sql을 그 종목만으로 실행
  2) Z: 같은 as_of·같은 국가 유니버스 원값의 중앙값·MAD로 로버스트 Z(score_zscore.sql과 같은 규칙, 방향 반영, ±3)
     — 주 그룹이 없으므로 섹터 중립화는 하지 않는다(z_adj = NULL)
  3) 팩터 점수·종합: score_aggregate.sql과 같은 규칙(유효 팩터 3개 이상, 가중치 재정규화)
  4) 0~100: 유니버스 종합 점수의 국가·프리셋 평균·표본표준편차로 표준화 → 100·Φ(z)
"""
from __future__ import annotations

import math
import statistics
from decimal import Decimal

from sqlalchemy import Connection, text

from app.queries import sql
from app.services.scoring import FACTORS, METRICS, MIN_FACTORS

MAD_SCALE = 1.4826
MIN_ROBUST_N = 5


def _q(x: float | None, places: str = "0.0001") -> Decimal | None:
    return None if x is None else Decimal(str(x)).quantize(Decimal(places))


def robust_z(x: float, values: list[float]) -> float:
    """score_zscore.sql과 같은 규칙: 표본 5개 이상이고 MAD > 0이면 로버스트 Z, 아니면 평균·표본표준편차 Z, 그것도 안 되면 0."""
    n = len(values)
    if n == 0:
        return 0.0
    m = statistics.median(values)
    mad = statistics.median(abs(v - m) for v in values)
    if n >= MIN_ROBUST_N and mad > 0:
        return (x - m) / (MAD_SCALE * mad)
    sd = statistics.stdev(values) if n > 1 else 0.0
    return (x - statistics.fmean(values)) / sd if sd > 0 else 0.0


def reference_score(conn: Connection, stock_id: int, country: str, preset: dict) -> dict | None:
    """ScoreOut과 같은 모양(+ reference). 유니버스 점수가 아직 없거나 그 종목 시세가 없으면 None."""
    as_of = conn.execute(text("SELECT MAX(as_of) FROM stock_scores")).scalar()
    if as_of is None:
        return None
    mine = conn.execute(sql("score_metrics"), {"stock_id": stock_id}).mappings().all()
    if not mine:
        return None
    universe: dict[str, list[float]] = {}
    for r in conn.execute(text("""
            SELECT mv.metric, mv.raw_value FROM stock_metric_values mv
            JOIN stocks s ON s.stock_id = mv.stock_id JOIN markets mk ON mk.market_id = s.market_id
            WHERE mv.as_of = :d AND mk.country = :c AND mv.raw_value IS NOT NULL AND mv.stock_id <> :s"""),
            {"d": as_of, "c": country, "s": stock_id}):
        universe.setdefault(r.metric, []).append(float(r.raw_value))

    z: dict[str, float | None] = {}
    notes, missing = [], {}
    for r in mine:
        k = r["metric"]
        if r["note"]:
            notes.append(f"{k}: {r['note']}")
        if r["z_fixed"] is not None:
            z[k] = float(r["z_fixed"])
        elif r["raw_value"] is None:
            z[k] = None
            missing[k] = METRICS[k].null_reason
        elif not universe.get(k):            # 비교할 유니버스 값이 없으면 위치를 정할 수 없다(0으로 두지 않음)
            z[k] = None
            missing[k] = "같은 시장 비교군에 이 지표 값이 없음"
        else:
            v = robust_z(float(r["raw_value"]), universe.get(k, []))
            z[k] = max(-3.0, min(3.0, -v if METRICS[k].direction < 0 else v))
    raw = {r["metric"]: r["raw_value"] for r in mine}

    factor_score: dict[str, float | None] = {}
    for f in FACTORS:
        vals = [z[k] for k, m in METRICS.items() if m.factor == f and z.get(k) is not None]
        factor_score[f] = statistics.fmean(vals) if vals else None
    coverage = sum(1 for v in factor_score.values() if v is not None)
    weights = {f: float(w) for f, w in conn.execute(
        text("SELECT factor, weight FROM scoring_weights WHERE preset_id = :p"), {"p": preset["preset_id"]}).all()}
    valid_w = sum(weights[f] for f in FACTORS if factor_score[f] is not None)
    composite = (sum(weights[f] * factor_score[f] for f in FACTORS if factor_score[f] is not None) / valid_w
                 if coverage >= MIN_FACTORS and valid_w > 0 else None)

    peers = [float(x) for x in conn.execute(text("""
        SELECT st.composite FROM stock_scores st
        JOIN stocks s ON s.stock_id = st.stock_id JOIN markets mk ON mk.market_id = s.market_id
        WHERE st.as_of = :d AND st.preset_id = :p AND mk.country = :c AND st.composite IS NOT NULL"""),
        {"d": as_of, "p": preset["preset_id"], "c": country}).scalars()]
    score = rank = None
    if composite is not None and peers:
        sd = statistics.stdev(peers) if len(peers) > 1 else 0.0
        zc = (composite - statistics.fmean(peers)) / sd if sd > 0 else 0.0
        score = 100 * 0.5 * (1 + math.erf(zc / math.sqrt(2)))
        above = sum(1 for p in peers if p > composite)
        below = sum(1 for p in peers if p < composite)
        rank = {"country": country, "position": above + 1, "total": len(peers) + 1,
                "percentile": _q(100 * below / len(peers), "0.1")}

    use = composite is not None
    factors = {}
    for f in FACTORS:
        s = factor_score[f]
        ew = weights[f] / valid_w if use and s is not None else None
        factors[f] = {"score": _q(s), "weight": _q(weights[f], "0.001"), "effective_weight": _q(ew),
                      "contribution": _q(ew * s) if ew is not None else None, "available": s is not None}
    dq: dict = {"partition": country, "reference": True}
    if missing:
        dq["missing_metrics"] = missing
    if notes:
        dq["notes"] = notes
    if composite is None:
        dq["score_null_reason"] = f"유효 팩터 {coverage}/5개 — {MIN_FACTORS}개 이상이어야 점수를 냅니다"
    return {
        "preset": {k: preset[k] for k in ("code", "name", "description")},
        "as_of": as_of, "score": _q(score, "0.01"), "composite": _q(composite), "factor_coverage": coverage,
        "rank": rank, "factors": factors,
        "metrics": [{"metric": k, "label": m.label, "factor": m.factor, "direction": m.direction,
                     "raw_value": raw.get(k), "z_raw": _q(z.get(k)), "z_adj": None} for k, m in METRICS.items()],
        "data_quality": dq,
        "reference": True,
        "reference_note": (f"상장 종목 목록에서 찾은 종목이라 매력도 비교군에 들어 있지 않습니다. {as_of} 기준 같은 시장 비교군 "
                           f"{len(peers)}개의 분포에 이 종목 지표를 대입한 참고 점수이며, 경쟁 그룹이 없어 섹터 중립화는 하지 않았습니다."),
    }
