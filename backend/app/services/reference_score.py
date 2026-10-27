"""상장 목록(listed) 종목의 참고 매력도 — 유니버스에 넣지 않고, 최신 점수 스냅샷의 분포에 지표를 대입한다.

유니버스(노출 종목 + 비교군)의 점수는 그대로 두어 재현성을 지키고(클릭한 종목에 따라 점수가 바뀌지 않음),
listed 종목은 요청할 때마다 계산해 저장하지 않는다.
  1) 지표 원값: score_metrics.sql을 그 종목만으로 실행(주 테마 규칙 — 금융·원자재 연동 — 도 같다)
  2) Z: 같은 as_of·같은 국가·같은 점수 묶음(family) 유니버스 원값의 중앙값·MAD로 로버스트 Z
     (score_zscore.sql과 같은 규칙, 방향 반영, ±3)
  3) 섹터 중립화: 주 테마가 있으면 같은 국가·같은 주 테마 유니버스 구성원의 z_raw 평균(자기 자신 포함)을
     축소 추정으로 뺀다(score_neutralize.sql과 같은 규칙, 안정성 제외, ±3). 주 테마가 없으면 z_adj = z
  4) 팩터 점수·종합: score_aggregate.sql과 같은 규칙(유효 팩터 3개 이상, 가중치 재정규화)
  5) 0~100: 유니버스 종합 점수의 국가·묶음·프리셋 평균·표본표준편차로 표준화 → 100·Φ(z)
점수를 내지 않는 테마(scoring none — 리츠·지주회사·상품 신탁)는 그 테마의 사유(unscored_reason)만 돌려준다.
"""
from __future__ import annotations

import math
import statistics
from decimal import Decimal

from sqlalchemy import Connection, text

from app.ingest.sectors import theme_by_name
from app.queries import sql
from app.services.data_quality import fiscal_year_mix
from app.services.scoring import FACTORS, METRICS, MIN_FACTORS, load_config, partition_label

MAD_SCALE = 1.4826
MIN_ROBUST_N = 5
UNSCORED_DEFAULT = "업종 특성상 이익·매출 기준인 매력도 점수를 내지 않습니다."
FAMILY_WORD = {"general": "", "financial": " 금융"}

# 같은 국가·같은 묶음 유니버스 종목(대상 제외)의 지표 원값과, 대상과 같은 주 테마인지
UNIVERSE_SQL = text("""
    SELECT mv.metric, mv.raw_value, mv.z_raw, (t.group_id IS NOT DISTINCT FROM CAST(:g AS int)) AS same_theme
    FROM stock_metric_values mv
    JOIN stocks s ON s.stock_id = mv.stock_id JOIN markets mk ON mk.market_id = s.market_id
    LEFT JOIN v_stock_theme t ON t.stock_id = mv.stock_id
    WHERE mv.as_of = :d AND mk.country = :c AND COALESCE(t.family, 'general') = :f
      AND mv.raw_value IS NOT NULL AND mv.stock_id <> :s""")


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


def neutralize(z: float, peers: list[float], k: float) -> float:
    """score_neutralize.sql과 같은 규칙: 그룹 평균(자기 자신 포함)을 n/(n+k)만큼 빼고 ±3. 구성원이 자기뿐이면 그대로."""
    n = len(peers) + 1
    if n == 1:
        return z
    mean = (sum(peers) + z) / n
    return max(-3.0, min(3.0, z - n / (n + k) * mean))


def unscored_reason(theme: str | None) -> str:
    """scoring none 테마의 사유(config/universe.yaml unscored_reason)."""
    t = theme_by_name().get(theme) if theme else None
    return (t.unscored_reason if t else None) or UNSCORED_DEFAULT


def reference_score(conn: Connection, stock_id: int, country: str, preset: dict) -> dict | None:
    """ScoreOut과 같은 모양(+ reference). 유니버스 점수가 아직 없거나 그 종목 시세가 없으면 None."""
    theme = conn.execute(text("SELECT group_id, theme, family FROM v_stock_theme WHERE stock_id = :s"),
                         {"s": stock_id}).mappings().first()
    family = theme["family"] if theme else "general"
    if family == "none":
        return {"preset": {k: preset[k] for k in ("code", "name", "description")}, "reference": True,
                "unscored_reason": unscored_reason(theme["theme"])}
    as_of = conn.execute(text("SELECT MAX(as_of) FROM stock_scores")).scalar()
    if as_of is None:
        return None
    mine = conn.execute(sql("score_metrics"), {"stock_id": stock_id}).mappings().all()
    if not mine:
        return None
    universe: dict[str, list[float]] = {}
    group: dict[str, list[float]] = {}             # 같은 주 테마 구성원의 z_raw (중립화)
    for r in conn.execute(UNIVERSE_SQL, {"d": as_of, "c": country, "f": family, "s": stock_id,
                                         "g": theme["group_id"] if theme else None}):
        universe.setdefault(r.metric, []).append(float(r.raw_value))
        if theme and r.same_theme and r.z_raw is not None:
            group.setdefault(r.metric, []).append(float(r.z_raw))
    k = float(load_config()["shrinkage_k"])

    z: dict[str, float | None] = {}
    z_adj: dict[str, float | None] = {}
    notes, missing = [], {}
    for r in mine:
        m = r["metric"]
        if r["note"]:
            notes.append(f"{m}: {r['note']}")
        if r["z_fixed"] is not None:
            z[m] = float(r["z_fixed"])
        elif r["raw_value"] is None:
            z[m] = None
            missing[m] = r["null_note"] or METRICS[m].null_reason
        elif not universe.get(m):            # 비교할 유니버스 값이 없으면 위치를 정할 수 없다(0으로 두지 않음)
            z[m] = None
            missing[m] = "같은 시장 비교군에 이 지표 값이 없음"
        else:
            v = robust_z(float(r["raw_value"]), universe[m])
            z[m] = max(-3.0, min(3.0, -v if METRICS[m].direction < 0 else v))
        z_adj[m] = (None if z[m] is None else
                    z[m] if METRICS[m].factor == "safety" or not theme else neutralize(z[m], group.get(m, []), k))
    raw = {r["metric"]: r["raw_value"] for r in mine}

    factor_score: dict[str, float | None] = {}
    for f in FACTORS:
        vals = [z_adj[m] for m, d in METRICS.items() if d.factor == f and z_adj.get(m) is not None]
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
        LEFT JOIN v_stock_theme t ON t.stock_id = st.stock_id
        WHERE st.as_of = :d AND st.preset_id = :p AND mk.country = :c AND COALESCE(t.family, 'general') = :f
          AND st.composite IS NOT NULL"""),
        {"d": as_of, "p": preset["preset_id"], "c": country, "f": family}).scalars()]
    score = rank = None
    if composite is not None and peers:
        sd = statistics.stdev(peers) if len(peers) > 1 else 0.0
        zc = (composite - statistics.fmean(peers)) / sd if sd > 0 else 0.0
        score = 100 * 0.5 * (1 + math.erf(zc / math.sqrt(2)))
        above = sum(1 for p in peers if p > composite)
        below = sum(1 for p in peers if p < composite)
        rank = {"country": country, "family": family, "position": above + 1, "total": len(peers) + 1,
                "percentile": _q(100 * below / len(peers), "0.1")}

    use = composite is not None
    factors = {}
    for f in FACTORS:
        s = factor_score[f]
        ew = weights[f] / valid_w if use and s is not None else None
        factors[f] = {"score": _q(s), "weight": _q(weights[f], "0.001"), "effective_weight": _q(ew),
                      "contribution": _q(ew * s) if ew is not None else None, "available": s is not None}
    dq: dict = {"partition": partition_label(country, family), "family": family, "reference": True}
    if missing:
        dq["missing_metrics"] = missing
    if notes:
        dq["notes"] = notes
    if composite is None:
        dq["score_null_reason"] = f"유효 팩터 {coverage}/5개 — {MIN_FACTORS}개 이상이어야 점수를 냅니다"
    neutral = (f"주 테마 '{theme['theme']}' 비교군 {max(map(len, group.values()), default=0)}개로 섹터 중립화했습니다." if theme
               else "주 테마가 없어 섹터 중립화는 하지 않았습니다.")
    return {
        "preset": {k: preset[k] for k in ("code", "name", "description")},
        "as_of": as_of, "score": _q(score, "0.01"), "composite": _q(composite), "factor_coverage": coverage,
        "rank": rank, "factors": factors,
        "metrics": [{"metric": m, "label": d.label, "factor": d.factor, "direction": d.direction,
                     "raw_value": raw.get(m), "z_raw": _q(z.get(m)), "z_adj": _q(z_adj.get(m))} for m, d in METRICS.items()],
        "data_quality": dq,
        "fin_basis": fiscal_year_mix(conn, country, as_of),
        "reference": True,
        "reference_note": (f"상장 종목 목록에서 찾은 종목이라 매력도 비교군에 들어 있지 않습니다. {as_of} 기준 같은 시장{FAMILY_WORD[family]} "
                           f"비교군 {len(peers)}개의 분포에 이 종목 지표를 대입한 참고 점수이며, {neutral}"),
    }
