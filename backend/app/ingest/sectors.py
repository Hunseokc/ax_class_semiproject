"""점수 비교 표본의 섹터 — 공식 업종(국내 KRX 업종명, 미국 SEC SIC)을 config/universe.yaml sectors로 묶는다.

한 SIC가 여러 범위에 걸리면 가장 좁은 범위가 이긴다(예: 3826 분석기기 → 헬스케어, 3800-3839 → 산업재).
어느 섹터에도 없는 업종(금융·보험·부동산 등)은 None → 비교 표본에 넣지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.ingest.universe import load_universe


@dataclass(frozen=True)
class Sector:
    name: str
    krx: frozenset[str]
    sic: tuple[tuple[int, int], ...]


def _range(r: str | int) -> tuple[int, int]:
    s = str(r)
    lo, _, hi = s.partition("-")
    return int(lo), int(hi or lo)


@lru_cache
def sectors() -> tuple[Sector, ...]:
    return tuple(Sector(s["name"], frozenset(s.get("krx", [])), tuple(_range(r) for r in s.get("sic", [])))
                 for s in load_universe().sectors)


def sector_for_krx(industry: str | None) -> str | None:
    return next((s.name for s in sectors() if industry in s.krx), None) if industry else None


def sector_for_sic(sic: int | None) -> str | None:
    if sic is None:
        return None
    hits = [(hi - lo, s.name) for s in sectors() for lo, hi in s.sic if lo <= sic <= hi]
    return min(hits)[1] if hits else None
