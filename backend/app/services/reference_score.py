"""상장 목록(listed) 종목의 참고 매력도 — 유니버스에 넣지 않고, 최신 점수 스냅샷의 분포에 지표를 대입한다.

유니버스(노출 종목 + 비교군)의 점수는 그대로 두어 재현성을 지키고(클릭한 종목에 따라 점수가 바뀌지 않음),
listed 종목은 요청할 때마다 계산해 저장하지 않는다.
  1) 지표 원값: score_metrics.sql을 그 종목만으로 실행(묶음 규칙 — 금융 — 도 같다)
  2) Z: 같은 as_of·같은 국가·같은 점수 묶음(family) 유니버스 원값 + 이 종목 안 순위로 순위 정규 점수(RN)
     (score_rank_normal.sql과 같은 규칙 — 같은 값은 평균 순위, 방향 반영, 감점 전용 지표는 0 이하)
  3) 섹터 중립화: 주 테마가 있으면 같은 국가·같은 주 테마 유니버스 구성원의 z_raw 평균(자기 자신 포함)을
     축소 추정으로 뺀다(score_neutralize.sql과 같은 규칙, Metric.neutralize = False인 지표 — 안정성·세후 보수 이익·
     가치 함정 신호 — 는 제외, ±3). 주 테마가 없으면 z_adj = z
  4) 팩터 점수: score_aggregate.sql과 같은 규칙(지표 가중 평균, 재무 3년 미만이면 저평가 축소) →
     유니버스 팩터 점수의 평균·표준편차로 재표준화 → 종합 = Σ 가중치 × 팩터(빠진 팩터 0), 저평가·수익성 필수
  5) 0~100: 유니버스 종합 점수 사이 순위로 같은 시장 백분위 100 × (n − 순위) / n (n = 유니버스 + 이 종목)
점수를 내지 않는 테마(scoring none — 리츠·지주회사·상품 신탁)는 그 테마의 사유(unscored_reason)만 돌려준다.
금융 묶음은 종합 점수 대신 같은 하위 업종 안 P/B·ROE 비교만 돌려준다(D-028, services/financial_profile.py).
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection, text

from app.ingest.sectors import theme_by_name
from app.queries import sql
from app.services.data_quality import fiscal_year_mix
from app.services.financial_profile import stock_profile
from app.services.scoring import (BADGE_FACTS, FACTORS, METRICS, MIN_FACTORS, REQUIRED_FACTORS, load_config, metric_params,
                                  null_reason, partition_label, rank_normal, score_badges)

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

# 같은 국가·같은 묶음 유니버스 종목의 z_adj와 이어지는 FY 수 — 팩터 재표준화의 평균·표준편차를 다시 만든다
UNIVERSE_ADJ_SQL = text("""
    SELECT mv.stock_id, mv.metric, mv.z_adj, CAST(sc.data_quality->>'fy_history' AS int) AS fy_count
    FROM stock_metric_values mv
    JOIN stocks s ON s.stock_id = mv.stock_id JOIN markets mk ON mk.market_id = s.market_id
    LEFT JOIN v_stock_theme t ON t.stock_id = mv.stock_id
    LEFT JOIN stock_scores sc ON sc.stock_id = mv.stock_id AND sc.as_of = mv.as_of AND sc.preset_id = :p
    WHERE mv.as_of = :d AND mk.country = :c AND COALESCE(t.family, 'general') = :f AND mv.z_adj IS NOT NULL""")


def _q(x: float | None, places: str = "0.0001") -> Decimal | None:
    return None if x is None else Decimal(str(x)).quantize(Decimal(places))


def rank_p(x: float, values: list[float]) -> float:
    """score_rank_normal.sql과 같은 규칙: 유니버스 값 + 이 종목(n개) 안 오름차순 평균 순위 r → (r − 0.5) / n.
    자기와 같은 값이 유니버스에 e개면 자리 less+1 ~ less+e+1의 평균 = less + 1 + e / 2."""
    less = sum(1 for v in values if v < x)
    equal = sum(1 for v in values if v == x)
    return (less + 1 + equal / 2 - 0.5) / (len(values) + 1)


def factor_scores(z_adj: dict[str, float | None], fy_count: int | None) -> dict[str, float | None]:
    """score_aggregate.sql과 같은 규칙: 팩터 = 지표 z_adj 가중 평균, 재무 FY 3개 미만이면 저평가 × (FY 수 / 3)."""
    out: dict[str, float | None] = {}
    for f in FACTORS:
        pairs = [(METRICS[m].weight, v) for m, v in z_adj.items() if v is not None and METRICS[m].factor == f]
        out[f] = sum(w * v for w, v in pairs) / sum(w for w, _ in pairs) if pairs else None
    n = fy_count if fy_count is not None else 0
    if out["value"] is not None and n < 3:
        out["value"] *= n / 3
    return out


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
    if family == "financial":
        code, reason = null_reason(0, False, family)
        return {"preset": {k: preset[k] for k in ("code", "name", "description")}, "as_of": as_of, "reference": True,
                "data_quality": {"partition": partition_label(country, family), "family": family,
                                 "score_null_code": code, "score_null_reason": reason},
                "financial_profile": stock_profile(conn, stock_id, country)}
    cfg = load_config()
    mine = conn.execute(sql("score_metrics"), metric_params(cfg, stock_id)).mappings().all()
    if not mine:
        return None
    fy_count = mine[0]["fy_count"]
    universe: dict[str, list[float]] = {}
    group: dict[str, list[float]] = {}             # 같은 주 테마 구성원의 z_raw (중립화)
    for r in conn.execute(UNIVERSE_SQL, {"d": as_of, "c": country, "f": family, "s": stock_id,
                                         "g": theme["group_id"] if theme else None}):
        universe.setdefault(r.metric, []).append(float(r.raw_value))
        if theme and r.same_theme and r.z_raw is not None:
            group.setdefault(r.metric, []).append(float(r.z_raw))
    k = float(cfg["shrinkage_k"])

    z: dict[str, float | None] = {}
    z_adj: dict[str, float | None] = {}
    notes, missing = [], {}
    for r in mine:
        m = r["metric"]
        if r["note"]:
            notes.append(f"{m}: {r['note']}")
        if r["raw_value"] is None:
            z[m] = None
            missing[m] = r["null_note"] or METRICS[m].null_reason
        elif not universe.get(m):            # 비교할 유니버스 값이 없으면 위치를 정할 수 없다(0으로 두지 않음)
            z[m] = None
            missing[m] = "같은 시장 비교군에 이 지표 값이 없음"
        else:
            z[m] = rank_normal(rank_p(float(r["raw_value"]), universe[m]), m)
        z_adj[m] = (None if z[m] is None else
                    z[m] if not METRICS[m].neutralize or not theme else neutralize(z[m], group.get(m, []), k))
    raw = {r["metric"]: r["raw_value"] for r in mine}

    # 팩터 재표준화: 유니버스(같은 국가·묶음) 팩터 점수의 평균·표본표준편차 — score_aggregate.sql의 fz와 같은 분포
    by_stock: dict[int, dict[str, float]] = defaultdict(dict)
    hist: dict[int, int | None] = {}
    for r in conn.execute(UNIVERSE_ADJ_SQL, {"d": as_of, "c": country, "f": family, "p": preset["preset_id"]}):
        by_stock[r.stock_id][r.metric] = float(r.z_adj)
        hist[r.stock_id] = r.fy_count
    dist: dict[str, list[float]] = defaultdict(list)
    for sid, zs in by_stock.items():
        for f, v in factor_scores(zs, hist.get(sid)).items():
            if v is not None:
                dist[f].append(v)
    raw_factor = factor_scores(z_adj, fy_count)
    factor_score: dict[str, float | None] = {}
    for f in FACTORS:
        v, xs = raw_factor[f], dist.get(f, [])
        sd = statistics.stdev(xs) if len(xs) > 1 else 0.0
        factor_score[f] = None if v is None else ((v - statistics.fmean(xs)) / sd if sd > 0 else 0.0)
    coverage = sum(1 for v in factor_score.values() if v is not None)
    has_required = all(factor_score[f] is not None for f in REQUIRED_FACTORS)
    weights = {f: float(w) for f, w in conn.execute(
        text("SELECT factor, weight FROM scoring_weights WHERE preset_id = :p"), {"p": preset["preset_id"]}).all()}
    composite = (sum(weights[f] * v for f, v in factor_score.items() if v is not None)
                 if has_required and coverage >= MIN_FACTORS else None)

    peers = [float(x) for x in conn.execute(text("""
        SELECT st.composite FROM stock_scores st
        JOIN stocks s ON s.stock_id = st.stock_id JOIN markets mk ON mk.market_id = s.market_id
        LEFT JOIN v_stock_theme t ON t.stock_id = st.stock_id
        WHERE st.as_of = :d AND st.preset_id = :p AND mk.country = :c AND COALESCE(t.family, 'general') = :f
          AND st.composite IS NOT NULL"""),
        {"d": as_of, "p": preset["preset_id"], "c": country, "f": family}).scalars()]
    score = rank = None
    if composite is not None and peers:
        above = sum(1 for p in peers if p > composite)
        below = sum(1 for p in peers if p < composite)
        total = len(peers) + 1
        score = 100 * (total - (above + 1)) / total                   # score_aggregate.sql과 같은 백분위
        rank = {"country": country, "family": family, "position": above + 1, "total": total,
                "percentile": _q(100 * below / len(peers), "0.1")}

    use = composite is not None
    factors = {}
    for f in FACTORS:
        s = factor_score[f]
        ew = weights[f] if use and s is not None else None             # 빠진 팩터는 0(중립)이라 가중치를 다시 나누지 않는다
        xs, v = dist.get(f, []), raw_factor[f]
        pct = None if v is None or not xs else 100 * (len(xs) - sum(1 for x in xs if x > v)) / (len(xs) + 1)
        factors[f] = {"score": _q(s), "weight": _q(weights[f], "0.001"), "effective_weight": _q(ew),
                      "contribution": _q(ew * s) if ew is not None else None, "available": s is not None,
                      "percentile": _q(pct, "0.01")}
    dq: dict = {"partition": partition_label(country, family), "family": family, "reference": True,
                "fy_history": fy_count, "model_version": cfg["model_version"]}
    mode = conn.execute(text("""SELECT st.data_quality->>'fiscal_mode' FROM stock_scores st
                                JOIN stocks s ON s.stock_id = st.stock_id JOIN markets mk ON mk.market_id = s.market_id
                                WHERE st.as_of = :d AND mk.country = :c AND st.data_quality ? 'fiscal_mode' LIMIT 1"""),
                        {"d": as_of, "c": country}).scalar()
    dq["badges"] = score_badges({k: mine[0][k] for k in BADGE_FACTS}, family,
                                date.fromisoformat(mode) if mode else None)
    if missing:
        dq["missing_metrics"] = missing
    if notes:
        dq["notes"] = notes
    if composite is None:
        dq["score_null_code"], dq["score_null_reason"] = null_reason(coverage, has_required)
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
