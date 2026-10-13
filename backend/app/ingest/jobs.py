"""적재 작업: DB 초기화, 마스터(유니버스) 적재. Stage 1은 외부 호출 없는 오프라인 경로만."""
from __future__ import annotations

import logging

from sqlalchemy import Engine, text

from app.core.config import ROOT_DIR
from app.ingest.store import job_log, upsert
from app.ingest.universe import load_universe

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- DB 초기화
def init_db(engine: Engine, reset: bool = False) -> None:
    # SQL 파일은 파라미터 없이 psycopg로 직접 실행한다(주석 속 '%'가 placeholder로 해석되지 않도록)
    with engine.begin() as conn:
        raw = conn.connection.driver_connection
        if reset:
            raw.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        for name in ("schema.sql", "indexes.sql", "views.sql"):
            path = ROOT_DIR / "db" / name
            if name == "views.sql" and not path.exists():
                # views.sql은 Stage 1-B(B)가 추가한다. 머지 전에도 이 명령이 돌도록 없으면 건너뛴다
                log.warning("건너뜀: db/%s (파일 없음)", name)
                continue
            raw.execute(path.read_text(encoding="utf-8"))
            log.info("적용: db/%s", name)


# ---------------------------------------------------------------- 마스터
def load_master(engine: Engine, offline: bool = True) -> None:
    """universe.yaml → markets·stocks·indices·peer_groups·peer_group_members (재실행해도 행 수 불변).

    Stage 1은 오프라인 경로만 있다. DART corp_code·SEC CIK 매핑(온라인)은 Stage 3에서 추가한다.
    """
    if not offline:
        raise NotImplementedError("온라인 마스터 적재(DART·SEC)는 Stage 3에서 추가한다. --offline을 사용하세요.")
    u = load_universe()
    with job_log(engine, source="INTERNAL", job_type="MASTER", label="universe") as res:
        with engine.begin() as conn:
            res.rows += upsert(conn, "markets", [
                {"code": m.code, "country": m.country, "currency": m.currency, "timezone": m.timezone}
                for m in u.markets], ["code"])
            mid = dict(conn.execute(text("SELECT code, market_id FROM markets")).all())
            res.rows += upsert(conn, "stocks", [
                {"market_id": mid[s.market], "ticker": s.ticker, "name": s.name,
                 "name_en": s.name if s.market in ("NASDAQ", "NYSE") else None, "is_active": True}
                for s in u.stocks], ["market_id", "ticker"], update=["name", "is_active"])
            res.rows += upsert(conn, "indices", [
                {"code": i.code, "name": i.name, "market_id": mid[i.market],
                 "source_symbol": i.source_symbol, "display_order": i.display_order}
                for i in u.indices], ["code"])
            res.rows += upsert(conn, "peer_groups", [{"name": g.name} for g in u.peer_groups], ["name"])
            gid = dict(conn.execute(text("SELECT name, group_id FROM peer_groups")).all())
            # 노출 종목 사이에 티커가 겹치지 않아 티커만으로 stock_id를 찾는다
            sid = dict(conn.execute(text("SELECT ticker, stock_id FROM stocks")).all())
            res.rows += upsert(conn, "peer_group_members", [
                {"group_id": gid[g.name], "stock_id": sid[t]} for g in u.peer_groups for t in g.members],
                ["group_id", "stock_id"])
