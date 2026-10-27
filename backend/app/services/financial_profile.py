"""금융 묶음 하위 업종 비교(D-028) — 종합 매력도 대신 같은 하위 업종 안 P/B·ROE(3년 평균)·P/E와 'ROE 대비 P/B' 위치.

은행·보험·증권은 회계 구조가 서로 다르고(예대 마진·보험부채 할인율·시장 수익) 30개 안팎이라, 한 줄 종합 순위는
현대해상처럼 자본이 2년간 줄었는데 1위가 되는 결과를 냈다(라운드 3 R3-4). 잔여이익 모델에서 P/B는 ROE가 자본비용을
얼마나 넘는가로 정해지므로, 같은 업종 안 ROE 대비 P/B가 근거 있는 비교 틀이다(근거_정렬표 4절).
  - 하위 업종 = 주 테마(은행·카드 / 보험 / 증권·자산운용), 같은 국가, 비교 표본(노출 + 비교군, 상장 목록 종목은 연 종목만)
  - P/B·ROE가 둘 다 있는 종목이 8개 이상이면 단순 회귀선(P/B = a + b × ROE) 대비 위·아래, 미만이면 중앙값 기준 위치
  - 참고 정보다. 점수·순위를 만들지 않는다(score_null_code = financial_profile)
조회 API만 쓰고 외부 호출은 없다(DB 값만).
"""
from __future__ import annotations

import statistics
from decimal import Decimal

from sqlalchemy import Connection

from app.queries import sql

REGRESSION_MIN = 8          # 이 수 이상이면 회귀선, 미만이면 중앙값 기준(D-028)
NOTE = ("금융 업종은 은행·보험·증권의 회계 구조가 서로 달라 종합 매력도 점수를 내지 않습니다. 같은 하위 업종 안에서 "
        "P/B·ROE(3년 평균)·P/E를 나란히 보이고, ROE 대비 P/B 위치를 참고 정보로 보여 줍니다(투자 권유 아님).")


def _q(x: float | None, places: str = "0.0001") -> Decimal | None:
    return None if x is None else Decimal(str(x)).quantize(Decimal(places))


def fit(points: list[tuple[float, float]]) -> dict:
    """points = [(ROE, P/B)]. 8개 이상이면 최소제곱 회귀선, 아니면(또는 ROE가 모두 같으면) 중앙값."""
    n = len(points)
    if n >= REGRESSION_MIN:
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        mx, my = statistics.fmean(xs), statistics.fmean(ys)
        sxx = sum((x - mx) ** 2 for x in xs)
        if sxx > 0:
            slope = sum((x - mx) * (y - my) for x, y in points) / sxx
            return {"method": "regression", "n": n, "slope": slope, "intercept": my - slope * mx,
                    "median_roe": None, "median_pb": None}
    return {"method": "median", "n": n, "slope": None, "intercept": None,
            "median_roe": statistics.median(p[0] for p in points) if n else None,
            "median_pb": statistics.median(p[1] for p in points) if n else None}


def position(f: dict, roe: float | None, pb: float | None) -> tuple[float | None, str | None]:
    """(P/B 차이, 문구). 회귀: 실제 P/B − 같은 ROE의 회귀선 P/B. 중앙값: 실제 P/B − 중앙값 P/B(ROE 위치와 함께 적음)."""
    if roe is None or pb is None or not f["n"]:
        return None, None
    if f["method"] == "regression":
        gap = pb - (f["intercept"] + f["slope"] * roe)
        word = "싸게" if gap < 0 else "비싸게"
        return gap, f"같은 ROE의 동종사보다 장부가 대비 {word} 거래됨(회귀선 대비) — 참고 정보"
    gap = pb - f["median_pb"]
    roe_word = "높고" if roe >= f["median_roe"] else "낮고"
    pb_word = "낮습니다" if gap <= 0 else "높습니다"
    return gap, f"동종사 중앙값보다 ROE는 {roe_word} P/B는 {pb_word}(표본이 적어 중앙값 기준) — 참고 정보"


def _groups(conn: Connection, country: str, stock_id: int | None = None) -> dict[str, dict]:
    rows = conn.execute(sql("financial_profile"), {"country": country, "stock_id": stock_id}).mappings().all()
    out: dict[str, dict] = {}
    for r in rows:
        g = out.setdefault(r["theme"], {"theme": r["theme"], "country": country, "members": []})
        g["members"].append({"stock_id": r["stock_id"], "ticker": r["ticker"], "name": r["name"], "market": r["market"],
                             "pb": None if r["pb"] is None else float(r["pb"]),
                             "pe": None if r["pe"] is None else float(r["pe"]),
                             "roe3": None if r["roe3"] is None else float(r["roe3"]),
                             "is_target": r["stock_id"] == stock_id})
    for g in out.values():
        f = fit([(m["roe3"], m["pb"]) for m in g["members"] if m["roe3"] is not None and m["pb"] is not None])
        for m in g["members"]:
            gap, label = position(f, m["roe3"], m["pb"])
            m.update(gap=_q(gap), position=label, pb=_q(m["pb"]), pe=_q(m["pe"]), roe3=_q(m["roe3"]))
        g.update(method=f["method"], n=f["n"], slope=_q(f["slope"]), intercept=_q(f["intercept"]),
                 median_roe=_q(f["median_roe"]), median_pb=_q(f["median_pb"]), note=NOTE)
    return out


def financial_overview(conn: Connection, country: str) -> list[dict]:
    """홈 금융 탭 — 하위 업종마다 구성원의 P/B·ROE·P/E·위치. 순위를 매기지 않고 이름순이다(D-028)."""
    return list(_groups(conn, country).values())


def stock_profile(conn: Connection, stock_id: int, country: str) -> dict | None:
    """종목 화면 — 그 종목 주 테마(하위 업종)의 비교와 그 종목 행(target). 금융 묶음이 아니면 None."""
    for g in _groups(conn, country, stock_id).values():
        target = next((m for m in g["members"] if m["is_target"]), None)
        if target is not None:
            return {**g, "target": target}
    return None
