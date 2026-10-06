"""매력도 점수 생성 — stock_scores는 재생성 가능한 파생 테이블(의도적 비정규화 2).

같은 as_of는 DELETE 후 INSERT로 다시 만든다(한 트랜잭션). 계산 자체는 app/queries/scores.sql.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import yaml
from sqlalchemy import Engine, text

from app.core.config import CONFIG_DIR
from app.ingest.store import job_log
from app.queries import sql

SEOUL = ZoneInfo("Asia/Seoul")


def load_weights() -> dict:
    with open(CONFIG_DIR / "scoring.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    w = cfg["weights"]
    if any(v < 0 for v in w.values()) or sum(w.values()) <= 0:
        raise ValueError("scoring.yaml 가중치가 올바르지 않습니다")
    return {"version": str(cfg["version"]), "w_val": w["valuation"], "w_gro": w["growth"],
            "w_pro": w["profitability"], "w_mom": w["momentum"]}


def compute_scores(engine: Engine, as_of: date | None = None, weights: dict | None = None) -> int:
    """as_of(기본: 오늘, 서울) 스냅샷을 다시 만든다. 반환: 생성 행 수."""
    as_of = as_of or datetime.now(SEOUL).date()
    params = {**(weights or load_weights()), "as_of": as_of}
    with job_log(engine, source="INTERNAL", job_type="SCORES", label=str(as_of)) as res:
        with engine.begin() as conn:
            rows = conn.execute(sql("scores"), params).mappings().all()
            conn.execute(text("DELETE FROM stock_scores WHERE as_of = :d"), {"d": as_of})
            if rows:
                conn.execute(text("""
                    INSERT INTO stock_scores (stock_id, as_of, score, valuation_score, growth_score,
                                              profitability_score, momentum_score, data_quality, weights_version)
                    VALUES (:stock_id, :as_of, :score, :valuation_score, :growth_score,
                            :profitability_score, :momentum_score, CAST(:dq AS jsonb), :weights_version)"""),
                    [{**r, "dq": json.dumps(r["data_quality"], ensure_ascii=False)} for r in rows])
        res.rows = len(rows)
        res.notes.append(f"weights={params['version']}")
    if res.status != "SUCCESS":
        raise RuntimeError("점수 계산 실패 — ingestion_logs 참고")
    return res.rows
