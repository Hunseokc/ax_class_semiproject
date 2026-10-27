"""업종 섹터와 테마 — config/universe.yaml sectors·themes·secondary_themes.

종목마다 주 테마 1개(섹터 중립화·비교군 선정 기준)와 보조 테마 여러 개(경쟁 비교·테마 필터에만)를 정한다.
  - 주 테마: tickers 직접 지정 > 업종 코드. 국내는 DART KSIC(induty_code) 가장 긴 접두어, 미국은 SEC SIC 가장 좁은 범위
  - 섹터(stocks.sector) = 주 테마의 sector. 어느 테마에도 없는 종목은 테마·섹터 없음 → 비교 표본 제외
  - 원자재 연동 테마(commodity): 연결 원자재 = commodity_by_ticker > commodity (none이면 연동이지만 시세 없음)
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import Connection, text

from app.ingest.store import upsert
from app.ingest.universe import load_universe

SCORING = ("general", "financial", "none")
NO_COMMODITY = "none"


@dataclass(frozen=True)
class Theme:
    name: str
    sector: str
    ksic: tuple[str, ...]
    sic: tuple[tuple[int, int], ...]
    tickers: frozenset[str]
    scoring: str                         # general / financial / none
    commodity: str | None                # 연결 원자재 indices.code, 연동이지만 시세가 없으면 'none', 연동이 아니면 None
    commodity_by_ticker: dict
    unscored_reason: str | None = None   # scoring none 테마의 상세 화면 사유

    @property
    def commodity_linked(self) -> bool:
        return self.commodity is not None


def _range(r: str | int) -> tuple[int, int]:
    s = str(r)
    lo, _, hi = s.partition("-")
    return int(lo), int(hi or lo)


@lru_cache
def sectors() -> tuple[str, ...]:
    return tuple(load_universe().sectors)


@lru_cache
def themes() -> tuple[Theme, ...]:
    """설정 검증: 섹터·scoring 값, 이름 중복, 한 티커가 두 테마에 직접 지정되는 경우, 보조 테마 이름."""
    u = load_universe()
    out, owner = [], {}
    for t in u.themes:
        th = Theme(name=t["name"], sector=t["sector"], ksic=tuple(str(k) for k in t.get("ksic", [])),
                   sic=tuple(_range(r) for r in t.get("sic", [])), tickers=frozenset(str(x) for x in t.get("tickers", [])),
                   scoring=t.get("scoring", "general"), commodity=t.get("commodity"),
                   commodity_by_ticker={str(k): v for k, v in (t.get("commodity_by_ticker") or {}).items()},
                   unscored_reason=t.get("unscored_reason"))
        if th.sector not in u.sectors:
            raise ValueError(f"universe.yaml themes: {th.name}의 섹터 {th.sector}가 sectors에 없다")
        if th.scoring not in SCORING:
            raise ValueError(f"universe.yaml themes: {th.name}의 scoring {th.scoring} — {SCORING} 중 하나")
        if th.scoring == "none" and not th.unscored_reason:
            raise ValueError(f"universe.yaml themes: {th.name}은 점수를 내지 않으니 unscored_reason이 필요하다")
        for x in th.tickers:
            if x in owner:
                raise ValueError(f"universe.yaml themes: 티커 {x}가 {owner[x]}·{th.name}에 함께 지정됨")
            owner[x] = th.name
        out.append(th)
    names = [t.name for t in out]
    if len(set(names)) != len(names):
        raise ValueError("universe.yaml themes: 테마 이름 중복")
    unknown = {n for v in u.secondary_themes.values() for n in v} - set(names)
    if unknown:
        raise ValueError(f"universe.yaml secondary_themes: 없는 테마 {', '.join(sorted(unknown))}")
    return tuple(out)


@lru_cache
def theme_by_name() -> dict[str, Theme]:
    return {t.name: t for t in themes()}


def primary_theme(country: str, ticker: str, ksic: str | None = None, sic: int | None = None) -> Theme | None:
    """주 테마: tickers 직접 지정 > 국내 KSIC 가장 긴 접두어 / 미국 SIC 가장 좁은 범위."""
    for t in themes():
        if ticker in t.tickers:
            return t
    if country == "KR" and ksic:
        hits = [(len(p), t.name) for t in themes() for p in t.ksic if ksic.startswith(p)]
    elif country == "US" and sic is not None:
        hits = [(lo - hi, t.name) for t in themes() for lo, hi in t.sic if lo <= sic <= hi]   # 좁을수록 큰 값
    else:
        hits = []
    return theme_by_name()[max(hits)[1]] if hits else None


def secondary_themes(ticker: str) -> list[Theme]:
    return [theme_by_name()[n] for n in load_universe().secondary_themes.get(ticker, [])]


def commodity_code(theme: Theme | None, ticker: str) -> str | None:
    """연결 원자재 indices.code. 연동 테마가 아니거나 시세가 없는 원자재(none)면 None."""
    if theme is None or not theme.commodity_linked:
        return None
    code = theme.commodity_by_ticker.get(ticker, theme.commodity)
    return None if code == NO_COMMODITY else code


# ---------------------------------------------------------------- DB 반영
def sync_themes(conn: Connection) -> int:
    """themes → peer_groups(이름·부모 섹터·점수 방식·원자재 연동). 설정에서 빠진 그룹은 구성원과 함께 지운다(재실행 안전)."""
    ts = themes()
    n = upsert(conn, "peer_groups", [{"name": t.name, "kind": "theme", "sector": t.sector, "scoring": t.scoring,
                                      "commodity_linked": t.commodity_linked} for t in ts], ["name"])
    conn.execute(text("DELETE FROM peer_groups WHERE NOT (name = ANY(:names))"), {"names": [t.name for t in ts]})
    return n


def assign_themes(conn: Connection) -> dict[str, int]:
    """모든 종목의 주 테마·보조 테마(peer_group_members)와 stocks.sector를 다시 정한다.
    업종 코드(ksic·sic)를 아직 받지 않은 종목은 직접 지정(tickers)으로만 정해진다. 반환: {'primary': n, 'secondary': n}."""
    gid = dict(conn.execute(text("SELECT name, group_id FROM peer_groups")).all())
    rows = conn.execute(text("""SELECT s.stock_id, m.country, s.ticker, s.ksic, s.sic
                                FROM stocks s JOIN markets m ON m.market_id = s.market_id""")).all()
    members, sector = [], []
    for r in rows:
        t = primary_theme(r.country, r.ticker, r.ksic, r.sic)
        if t is None:
            continue
        members.append({"group_id": gid[t.name], "stock_id": r.stock_id, "is_primary": True})
        members += [{"group_id": gid[x.name], "stock_id": r.stock_id, "is_primary": False}
                    for x in secondary_themes(r.ticker) if x.name != t.name]
        sector.append({"id": r.stock_id, "sec": t.sector})
    conn.execute(text("DELETE FROM peer_group_members"))
    if members:
        conn.execute(text("""INSERT INTO peer_group_members (group_id, stock_id, is_primary)
                             VALUES (:group_id, :stock_id, :is_primary)"""), members)
    conn.execute(text("UPDATE stocks SET sector = NULL WHERE sector IS NOT NULL AND NOT (stock_id = ANY(:ids))"),
                 {"ids": [x["id"] for x in sector]})
    if sector:
        conn.execute(text("UPDATE stocks SET sector = :sec WHERE stock_id = :id AND sector IS DISTINCT FROM :sec"), sector)
    primary = len(sector)
    return {"primary": primary, "secondary": len(members) - primary}
