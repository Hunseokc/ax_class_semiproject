# Stage 0 — 시니어(D) 뼈대 프롬프트

새 팀 레포(`stockmind-team`) 루트에 `CLAUDE.md`와 `.github/pull_request_template.md`를 먼저 커밋한 뒤, Claude Code에 아래를 붙여넣는다.

```
시니어 모드.

[역할] 나는 StockMind 팀의 시니어 D(통합·배포 책임)다. 지금은 Stage 0 — 팀원이 바로 작업을 시작할 수 있는 뼈대를 만든다.
[원본] ../ax_class_stockmind/ (읽기 전용 정답지). 경로·파일명·코드 스타일을 그대로 따른다.
[레포 구조] 처음부터 원본 최종 구조(backend/, frontend/, docs/)로 만든다.

[만들 것] 02_단계별_로드맵.md의 Stage 0 표 그대로:
1. 실행 환경: compose.yml, compose.dev.yml, .env.example, .gitignore, .gitattributes, .dockerignore, certs/.gitkeep,
   backend/Dockerfile, backend/docker/entrypoint.sh, backend/requirements.txt(원본 그대로), backend/db/init/00_create_test_db.sql
2. 코어: backend/app/core/{config,db,errors,logging}.py, backend/app/__init__.py, backend/app/queries/__init__.py
   - errors.py는 AppError·NotFound·Conflict·핸들러·internal_error_response까지만. 도메인 에러 코드는 각 단계에서 추가.
3. 앱: backend/app/main.py — 요청 ID 미들웨어, 에러 핸들러, /static, 화면 라우트(/, /stocks, /stocks/{market}/{ticker}, /portfolio), health 라우터.
   스케줄러 lifespan 없음. /api/v1 APIRouter는 만들되 include_router 자리에 아래 구역 주석만 둔다:
     # ── [S1-B] stocks·market ── / # ── [S2-B] watchlist ── / # ── [S2-C] portfolios ── / ...
4. backend/app/api/{__init__,health,deps}.py — deps는 get_db만. health는 /health, /health/db.
5. backend/app/schemas/{__init__,common}.py, backend/app/schemas/api.py(ErrorOut + 단계·팀원 구역 주석)
6. DB 계약: backend/db/schema.sql, backend/db/indexes.sql — Stage 1 테이블만
   (markets, stocks, peer_groups, peer_group_members, daily_prices, valuation_snapshots, indices, index_daily_prices, fx_rates, ingestion_logs).
   원본 최종 컬럼 중 이후 단계 것(coverage, detail_synced_at, industry, sic, is_primary, dps 등)은 뺀다.
   backend/app/models/__init__.py — 위 테이블 ORM.
7. 테스트: backend/tests/{__init__,conftest}.py, test_health.py, test_errors.py, test_schema.py(Stage 1 테이블 기준)
8. 프론트 공통: frontend/css/{tokens,base,components,pages}.css, frontend/js/components/{ui,icons,sidebar}.js,
   frontend/js/format.js, frontend/js/api.js(fetch 래퍼·에러 처리만), frontend/{index,stocks,stock,portfolio}.html(사이드바 + 빈 main)
   - sidebar.js의 '마지막 갱신 시각'은 Stage 3에서 추가.
9. docs/: 원본 01·02·03·04(기획·요구사항·데이터 조사·도메인 모델)와 assets/design_reference.png는 그대로 가져오고, 05·06은 "Stage 1 범위" 절만 남긴 초안.

[계약 규칙] DDL·ORM·deps·config는 원본 블록을 복사한 뒤 이번 단계에서 뺄 것만 지운다(이름·타입·제약을 다시 쓰지 않는다).
  원본과의 차이는 team/contracts/stage{N}.toml에 전부 적고, `python team/tools/check_contract.py {N}`이 통과해야 커밋한다.
[진행] 계획표 → 내가 승인 → 위 그룹 단위(1~9)로 작성·커밋. 각 그룹 끝에 원본과 차이 요약.
[완료 기준] docker compose -f compose.yml -f compose.dev.yml up -d --build →
  curl localhost:8000/health/db 가 {"status":"ok","db":"ok"}, docker compose run --rm api pytest -q 통과, 화면 4개에 사이드바.
```

완료 후: `main`에 push → 태그 `v0.1` → `stage1` 브랜치 생성 → `prompts/stage1.md` 배포.
