"""Stage 계약 검사 — 원본(정답지)과 이번 단계 코드가 어디서 다른지 기계적으로 찾는다.

검사 3가지
  1) DB   : 원본·stage의 schema.sql → indexes.sql → views.sql을 임시 DB 2개에 적용하고
            PostgreSQL 카탈로그(컬럼 타입·NULL·기본값·생성식, 제약, 인덱스, 트리거, 뷰)를 비교한다.
  2) ORM  : 원본·stage의 app/models/__init__.py를 AST로 읽어 클래스 속성(컬럼·relationship·__table_args__)을 비교한다.
  3) 소비자: 이번 단계 팀원이 옮길 원본 파일(consumers)이 import·사용하는 이름(app.* 심볼, get_settings().X,
            모델 클래스 속성, sql("이름"))이 stage에 있는지, 없으면 누가 만들기로 했는지(planned) 확인한다.

원본과 다른 점은 team/contracts/stage{N}.toml에 적힌 것만 허용한다.
  [[exclude]] 이후 단계에 추가될 것(이번 단계에서 뺀 것)   [[allow]] 의도적으로 원본과 다르게 둔 것
  [[planned]] 이번 단계에 팀원이 새로 만드는 이름          [[skip_import]] 소비자가 옮길 때 빼는 import
예외에 걸리지 않은 차이가 하나라도 있으면 종료 코드 1. 쓰이지 않는 예외 항목도 경고한다(계약 파일을 정직하게 유지).

사용 (저장소 루트에서, DB 컨테이너가 떠 있어야 함):
  python team/tools/check_contract.py 2
  python team/tools/check_contract.py 2 --original ../semi --skip-db
표준 라이브러리만 쓴다(호스트에 SQLAlchemy가 없어도 됨). DB 비교는 `docker exec <DB 컨테이너> psql`로 한다.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ORIGINAL_CANDIDATES = ("../ax_class_stockmind", "../semi")   # CLAUDE.md 1절 경로, 없으면 ../semi
SQL_FILES = ("schema.sql", "indexes.sql", "views.sql")


@dataclass
class Report:
    """차이 하나 = key 하나. key는 계약 파일의 keys에 그대로 복사해 쓸 수 있는 문자열이다."""
    diffs: dict[str, str] = field(default_factory=dict)
    info: list[str] = field(default_factory=list)

    def add(self, key: str, msg: str) -> None:
        self.diffs[key] = msg


# ------------------------------------------------------------------ 계약 파일
@dataclass
class Contract:
    stage: int
    required_tables: list[str]
    excluded_cols: dict[str, set[str]]           # 테이블 → 이번 단계에서 뺀 컬럼
    suppress: dict[str, str]                     # key → 사유 (exclude.keys + allow.keys)
    consumers: dict[str, list[str]]
    planned: dict[str, str]                      # 이름 → 담당자
    skip_import: dict[str, str]                  # 이름 → 사유

    @classmethod
    def load(cls, path: Path) -> Contract:
        d = tomllib.loads(path.read_text(encoding="utf-8"))
        excluded: dict[str, set[str]] = {}
        suppress: dict[str, str] = {}
        for e in d.get("exclude", []):
            if "table" in e:
                excluded.setdefault(e["table"], set()).update(e.get("columns", []))
            for k in e.get("keys", []):
                suppress[k] = f"exclude: {e.get('until', '')}"
        for a in d.get("allow", []):
            for k in a["keys"]:
                suppress[k] = f"allow: {a['reason']}"
        planned = {n: p["owner"] for p in d.get("planned", []) for n in p["names"]}
        skip = {n: s["reason"] for s in d.get("skip_import", []) for n in s["names"]}
        return cls(d["stage"], d.get("required_tables", []), excluded, suppress, d.get("consumers", {}), planned, skip)

    def mentions_excluded(self, table: str, text: str) -> bool:
        return any(re.search(rf"\b{re.escape(c)}\b", text) for c in self.excluded_cols.get(table, ()))


# ------------------------------------------------------------------ 1) DB
CATALOG_SQL = r"""
SELECT json_build_object(
 'columns', (SELECT coalesce(json_agg(json_build_array(c.relname, a.attname, format_type(a.atttypid, a.atttypmod),
                     a.attnotnull, pg_get_expr(d.adbin, d.adrelid), a.attgenerated::text)), '[]')
             FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
             LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
             WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped),
 'constraints', (SELECT coalesce(json_agg(json_build_array(conrelid::regclass::text, pg_get_constraintdef(oid))), '[]')
                 FROM pg_constraint WHERE connamespace = 'public'::regnamespace AND conrelid <> 0),
 'indexes', (SELECT coalesce(json_agg(json_build_array(tablename, indexname, indexdef)), '[]') FROM pg_indexes
             WHERE schemaname = 'public' AND indexname NOT LIKE '%\_pkey' AND indexname NOT LIKE '%\_key'),
 'triggers', (SELECT coalesce(json_agg(json_build_array(tgrelid::regclass::text, tgname, pg_get_triggerdef(oid))), '[]')
              FROM pg_trigger WHERE NOT tgisinternal),
 'views', (SELECT coalesce(json_agg(json_build_array(viewname, definition)), '[]') FROM pg_views WHERE schemaname = 'public'));
"""


def psql(container: str, db: str, sql: str) -> str:
    r = subprocess.run(["docker", "exec", "-i", container, "psql", "-U", "stock", "-d", db, "-v", "ON_ERROR_STOP=1",
                        "-q", "-At"], input=sql.encode("utf-8"), capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f"psql 실패 ({db}): {r.stderr.decode('utf-8', 'replace').strip()}")
    return r.stdout.decode("utf-8")


def catalog(container: str, db: str, db_dir: Path) -> dict:
    psql(container, "postgres", f"DROP DATABASE IF EXISTS {db}; CREATE DATABASE {db} OWNER stock;")
    try:
        for name in SQL_FILES:
            if (db_dir / name).exists():
                psql(container, db, (db_dir / name).read_text(encoding="utf-8"))
        return json.loads(psql(container, db, CATALOG_SQL))
    finally:
        psql(container, "postgres", f"DROP DATABASE IF EXISTS {db};")


def compare_db(orig: dict, stage: dict, c: Contract, rep: Report) -> None:
    o_cols = {(t, n): (ty, nn, df, g) for t, n, ty, nn, df, g in orig["columns"]}
    s_cols = {(t, n): (ty, nn, df, g) for t, n, ty, nn, df, g in stage["columns"]}
    s_tables = {t for t, _ in s_cols}
    o_tables = {t for t, _ in o_cols}

    for t in c.required_tables:
        if t not in s_tables:
            rep.add(f"table:{t}", "이번 단계 필수 테이블이 stage에 없음")
    for t in sorted(s_tables - o_tables):
        rep.add(f"table:{t}", "원본에 없는 테이블")
    later = sorted(o_tables - s_tables)
    if later:
        rep.info.append(f"원본에만 있는 테이블 {len(later)}개(이후 단계): {', '.join(later)}")

    def show(v):
        ty, nn, df, g = v
        return f"{ty}{' NOT NULL' if nn else ''}{f' DEFAULT {df}' if df and not g else ''}{f' GENERATED AS {df}' if g else ''}"

    for (t, n), v in sorted(o_cols.items()):
        if t not in s_tables:
            continue
        if (t, n) not in s_cols:
            if n not in c.excluded_cols.get(t, ()):
                rep.add(f"column:{t}.{n}", f"원본에만 있음 — 원본: {show(v)}")
        elif s_cols[(t, n)] != v:
            rep.add(f"column:{t}.{n}", f"정의가 다름 — 원본: {show(v)} / stage: {show(s_cols[(t, n)])}")
    for (t, n), v in sorted(s_cols.items()):
        if (t, n) not in o_cols and t in o_tables:
            rep.add(f"column:{t}.{n}", f"원본에 없는 컬럼 — stage: {show(v)}")

    def by_table(rows, key_idx, def_idx, kind):
        o = {(r[0], r[def_idx]) for r in orig[rows] if r[0] in s_tables}
        s = {(r[0], r[def_idx]) for r in stage[rows]}
        for t, d in sorted(o - s):
            if not c.mentions_excluded(t, d):
                rep.add(f"{kind}:{t}:{d}", "원본에만 있음")
        for t, d in sorted(s - o):
            if t in o_tables:
                rep.add(f"{kind}:{t}:{d}", "stage에만 있음(또는 정의가 다름)")

    by_table("constraints", 0, 1, "constraint")
    by_table("indexes", 0, 2, "index")
    by_table("triggers", 0, 2, "trigger")

    o_views = dict(orig["views"])
    for name, d in sorted(stage["views"]):
        if name not in o_views:
            rep.add(f"view:{name}", "원본에 없는 뷰")
        elif " ".join(o_views[name].split()) != " ".join(d.split()):
            rep.add(f"view:{name}", "뷰 정의가 원본과 다름")


# ------------------------------------------------------------------ 2) ORM
def orm_classes(path: Path) -> dict[str, dict]:
    """클래스 이름 → {"__tablename__": 이름, 속성: 정의 문자열, "__table_args__": 원소 집합}"""
    out: dict[str, dict] = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if not isinstance(node, ast.ClassDef):
            continue
        attrs: dict = {}
        for st in node.body:
            if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                attrs[st.target.id] = f"{ast.unparse(st.annotation)} = {ast.unparse(st.value) if st.value else ''}"
            elif isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
                name, val = st.targets[0].id, st.value
                if name == "__tablename__":
                    attrs[name] = ast.literal_eval(val)
                elif name == "__table_args__":
                    elts = val.elts if isinstance(val, ast.Tuple) else [val]
                    attrs[name] = {ast.unparse(e) for e in elts}
                else:
                    attrs[name] = ast.unparse(val)
        out[node.name] = attrs
    return out


def compare_orm(orig_path: Path, stage_path: Path, c: Contract, rep: Report) -> dict[str, dict]:
    o, s = orm_classes(orig_path), orm_classes(stage_path)
    for cls, s_attrs in s.items():
        if cls not in o:
            if "__tablename__" in s_attrs:
                rep.add(f"orm:{cls}", "원본에 없는 모델 클래스")
            continue
        o_attrs, table = o[cls], s_attrs.get("__tablename__", "")
        for name, ov in o_attrs.items():
            sv = s_attrs.get(name)
            if name == "__table_args__":
                missing = {e for e in ov - (sv or set()) if not c.mentions_excluded(table, e)}
                extra = (sv or set()) - ov
                for e in sorted(missing):
                    rep.add(f"orm:{cls}.__table_args__:{e}", "원본에만 있음")
                for e in sorted(extra):
                    rep.add(f"orm:{cls}.__table_args__:{e}", "stage에만 있음")
            elif sv is None:
                if name not in c.excluded_cols.get(table, ()):
                    rep.add(f"orm:{cls}.{name}", f"원본에만 있음 — 원본: {ov}")
            elif sv != ov:
                rep.add(f"orm:{cls}.{name}", f"정의가 다름 — 원본: {ov} / stage: {sv}")
        for name in s_attrs.keys() - o_attrs.keys():
            rep.add(f"orm:{cls}.{name}", f"원본에 없는 속성 — stage: {s_attrs[name]}")
    return s


# ------------------------------------------------------------------ 3) 소비자
def module_file(root: Path, module: str) -> Path | None:
    base = root / "backend" / Path(*module.split("."))
    for p in (base.with_suffix(".py"), base / "__init__.py"):
        if p.exists():
            return p
    return None


def top_level_names(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.ImportFrom, ast.Import)):
            names.update((a.asname or a.name).split(".")[0] for a in node.names)
    return names


def settings_fields(stage: Path) -> set[str]:
    for node in ast.walk(ast.parse((stage / "backend/app/core/config.py").read_text(encoding="utf-8"))):
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            return {st.target.id for st in node.body if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name)}
    return set()


def check_consumers(original: Path, stage: Path, c: Contract, stage_orm: dict[str, dict], rep: Report) -> None:
    fields = settings_fields(stage)
    rows: list[tuple[str, str, str, str]] = []   # 담당자, 원본 파일, 이름, 상태

    def resolve(owner: str, rel: str, name: str, ok: bool) -> None:
        if ok:
            return
        if name in c.skip_import:
            rows.append((owner, rel, name, f"뺄 것 — {c.skip_import[name]}"))
        elif name in c.planned or name.split(":")[0] in c.planned:
            rows.append((owner, rel, name, f"계획됨 — {c.planned.get(name) or c.planned[name.split(':')[0]]}가 만듦"))
        else:
            key = name if name.split(":")[0] in ("settings", "orm-use", "query") else f"import:{name}"
            rep.add(key, f"{owner}가 옮길 {rel}이(가) 쓰는데 stage에 없고 담당자도 없음")

    for owner, files in c.consumers.items():
        for rel in files:
            path = original / rel
            if not path.exists():
                rep.add(f"consumer:{rel}", "consumers에 적힌 원본 파일이 없음")
                continue
            if path.suffix != ".py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            model_names: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "app":
                    mf = module_file(stage, node.module)
                    defined = top_level_names(mf) if mf else set()
                    for a in node.names:
                        sub = module_file(stage, f"{node.module}.{a.name}")
                        resolve(owner, rel, f"{node.module}:{a.name}", sub is not None or a.name in defined)
                        if node.module == "app.models":
                            model_names.add(a.asname or a.name)
                elif isinstance(node, ast.Attribute):
                    v = node.value
                    if isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == "get_settings":
                        resolve(owner, rel, f"settings:{node.attr}", node.attr in fields)
                    elif isinstance(v, ast.Name) and v.id in model_names and v.id in stage_orm:
                        resolve(owner, rel, f"orm-use:{v.id}.{node.attr}", node.attr in stage_orm[v.id])
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "sql"
                      and node.args and isinstance(node.args[0], ast.Constant)):
                    q = node.args[0].value
                    resolve(owner, rel, f"query:{q}", (stage / f"backend/app/queries/{q}.sql").exists())
    for owner, rel, name, status in sorted(set(rows)):
        rep.info.append(f"[{owner}] {rel}: {name} → {status}")


# ------------------------------------------------------------------ 실행
def find_original(arg: str | None) -> Path:
    cands = [arg] if arg else [os.environ.get("STOCKMIND_ORIGINAL", ""), *ORIGINAL_CANDIDATES]
    for cand in filter(None, cands):
        p = (REPO / cand).resolve() if not Path(cand).is_absolute() else Path(cand)
        if (p / "backend/db/schema.sql").exists():
            return p
    raise SystemExit(f"원본 폴더를 찾지 못했습니다 (시도: {', '.join(filter(None, cands))}). --original로 지정하세요")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="원본 대비 Stage 계약 검사")
    ap.add_argument("stage", type=int)
    ap.add_argument("--original", help="원본 폴더 (기본: ../ax_class_stockmind → ../semi)")
    ap.add_argument("--container", default="stockmind_db", help="PostgreSQL 컨테이너 이름")
    ap.add_argument("--skip-db", action="store_true", help="DB 비교 생략 (ORM·소비자만)")
    args = ap.parse_args()

    original = find_original(args.original)
    contract = Contract.load(REPO / f"team/contracts/stage{args.stage}.toml")
    rep = Report()
    print(f"원본: {original}\n계약: team/contracts/stage{args.stage}.toml\n")

    if not args.skip_db:
        compare_db(catalog(args.container, "contract_orig", original / "backend/db"),
                   catalog(args.container, "contract_stage", REPO / "backend/db"), contract, rep)
    stage_orm = compare_orm(original / "backend/app/models/__init__.py", REPO / "backend/app/models/__init__.py", contract, rep)
    check_consumers(original, REPO, contract, stage_orm, rep)

    open_diffs = {k: v for k, v in rep.diffs.items() if k not in contract.suppress}
    used = {k for k in rep.diffs if k in contract.suppress}
    unused = [k for k in contract.suppress if k not in used and not (args.skip_db and k.split(":")[0] in
                                                                      ("table", "column", "constraint", "index", "trigger", "view"))]

    for line in rep.info:
        print(f"  · {line}")
    print(f"\n예외로 허용된 차이 {len(used)}개")
    if unused:
        print(f"\n⚠ 쓰이지 않는 예외 {len(unused)}개 — 이미 원본과 같아졌거나 key가 틀림. 계약 파일에서 지우세요:")
        for k in unused:
            print(f"  - {k}")
    if open_diffs:
        print(f"\n✗ 원본과 다른데 계약에 없는 차이 {len(open_diffs)}개 — 고치거나, 의도라면 계약 파일에 key와 사유를 적으세요:")
        for k, v in sorted(open_diffs.items()):
            print(f"  [{k}]\n      {v}")
        return 1
    print("\n✓ 계약 검사 통과 — 원본과의 차이가 모두 계약 파일에 적혀 있습니다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
