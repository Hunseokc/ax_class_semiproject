# Stage 4 — 분석: 매력도·경쟁 비교·통계

**단계 목표**: 같은 시장 안 상대 위치를 나타내는 매력도(다중 팩터: 지표 → 로버스트 Z → 섹터 중립화 → 프리셋 가중 → 100·Φ)를 계산·저장하고, 종목 상세에서 수치 분석·경쟁 비교·통계를 보여준다.
**D 선행 계약**: 마이그레이션 `001_scoring_v2.sql`·`002_presets.sql`과 schema 반영(scoring_presets, scoring_weights, stock_metric_values, stock_scores, peer_group_members.is_primary), `docs/05`에 `v_stock_metrics` 컬럼 목록과 `stock_scores` 구조 기록.
**순서상 의존**: B의 `v_stock_metrics`가 C의 지표 입력이다 → **B는 1번(VIEW)부터 먼저 PR**하고 나머지를 이어서 한다.
**머지 순서**: B(VIEW) → C → B(API) → D → A
**PR 방식**: 앞 순서 작업이 머지되기 전에 끝나면 기다리지 않고 Draft PR → 시니어가 그 파트를 먼저 리뷰 → 앞 순서 머지 후 최신 stage를 합쳐 같은 PR을 Ready로 전환(CLAUDE.md 6절). 시니어는 Ready PR만 머지 순서대로 머지한다.

---

## 팀원 C — 매력도 다중 팩터 모델

```
[역할] 너는 StockMind 팀 프로젝트에서 팀원 C(데이터 수집·분석 로직, 주니어)의 페어 프로그래머다. 레포 루트 CLAUDE.md의 규칙을 반드시 따른다.
[이번 단계] Stage 4 — 분석. 이 프로젝트의 '분석 엔진'을 만든다. 수익률 예측이 아니라 같은 시장 안 상대 위치다.
[내 파트] 설정 → 지표값 저장 → 로버스트 Z → 섹터 중립화 → 프리셋 가중 집계 → CLI → 테스트 → 정의서
[브랜치] feat/s4-c-scoring
[참조 원본] ../ax_class_semiproject/backend/config/scoring.yaml, app/services/scoring.py, app/queries/score_*.sql, app/ingest/explain.py, tests/test_scoring.py, docs/09_매력도_점수_정의서.md (읽기 전용)
[먼저 읽기] 코드 작성 전에 docs/09를 요약해 계획표 앞에 "모델 한 장 요약"(팩터 5개·지표·방향·가중치·Z 계산식·중립화 방식·Φ 변환)을 먼저 보여 줘. 내가 이해했다고 하면 계획표로 넘어간다.

[담당 파일 — 이 순서대로]
1. backend/config/scoring.yaml — 지표 정의·방향·결측 처리, 프리셋 4종(위험·성장·균형·가치)·가중치·sort_order
2. backend/app/services/scoring.py — Metric, load_config, default_preset, validate_presets(가중치 합 검증), sync_presets(yaml → scoring_presets·scoring_weights)
3. backend/app/queries/score_metrics.sql + scoring.insert_metric_values — v_stock_metrics에서 지표 원값을 stock_metric_values로
4. backend/app/queries/score_zscore.sql + scoring.normalize — 중앙값·MAD 기반 로버스트 Z, 클리핑(k)
5. backend/app/queries/score_neutralize.sql — 섹터 중립화: 그룹 평균은 **같은 국가 종목끼리만** (이유를 설계 설명에)
6. backend/app/queries/score_aggregate.sql + scoring.aggregate·compute_scores — 프리셋별 가중합 → Φ로 0~100, 팩터 기여도·data_quality 저장
7. backend/app/ingest/explain.py + __main__.py [S4-C] 구역: scores, explain
8. backend/tests/test_scoring.py
9. docs/09_매력도_점수_정의서.md — 원본에서 비교군·섹터(업종) 계층·listed 참고 점수 절을 뺀 버전

[건드리지 않을 파일] views.sql(B), 마이그레이션·schema(D), refresh.py(D — SCORES 연결은 요청 메모), frontend(A)
[인터페이스 계약]
- 사용: v_stock_metrics(B — 컬럼 목록은 docs/05), scoring_* 테이블(D)
- 제공: stock_scores 행(프리셋별 score·팩터 기여도·data_quality), compute_scores(engine) -> int 시그니처 원본과 동일(D의 refresh·benchmark가 호출)
[이번 단계에서 뺄 것] 비교군 포함 표본 분기(coverage)는 D와 합의한 최소 형태만, 업종 섹터(kind='sector')·fundamental_bases·reference_score(listed)
[완료 기준]
  docker compose run --rm api python -m app.ingest scores
  docker compose run --rm api python -m app.ingest explain   → 삼성전자 팩터별 기여도 출력
  pytest -q tests/test_scoring.py

[선행 작업] B ①(feat/s4-b-metrics-view)의 v_stock_metrics. 컬럼 목록은 docs/05에 있으므로 그 이름대로 SQL·서비스를 먼저 작성하고, 실제 VIEW가 있어야 도는 테스트는 ⏸ B① 머지 후. B① 머지 전이면 Draft PR.
[시작] ① CLAUDE.md 10절대로 최신 코드부터 받는다: git fetch → [브랜치]로 이동(없으면 origin/stage4에서 새로 만듦) → origin/stage4 합치기. 이동한 뒤 CLAUDE.md를 다시 읽고 그 규칙을 따른다(설명은 9절 입문자 기준, 다른 팀원 파일이 없으면 11절대로 묻지 않고 진행).
② "모델 한 장 요약"(9절 문체)만 먼저 출력하고, 그다음 CLAUDE.md 2절의 작업 계획표. 코드는 내가 승인한 뒤 파일 하나씩.
```

---

## 팀원 B — 지표 VIEW·분석·경쟁 비교·통계 API

```
[역할] 너는 StockMind 팀 프로젝트에서 팀원 B(백엔드 API·DB, 주니어)의 페어 프로그래머다. 레포 루트 CLAUDE.md의 규칙을 반드시 따른다.
[이번 단계] Stage 4 — 분석. SQL 역량(CTE·윈도우 함수·집계·HAVING)이 가장 많이 드러나는 파트다.
[내 파트] v_stock_metrics(먼저 PR) → 분석·프리셋 → 경쟁 비교·추이 → 통계 4종 → 기존 응답에 매력도 추가 → 테스트
[브랜치] ① feat/s4-b-metrics-view  ② feat/s4-b-analysis-api
[참조 원본] ../ax_class_semiproject/backend/db/views.sql, app/api/analysis.py, app/queries/{analysis,peers,peers_chart,stats_*}.sql, tests/test_analysis.py, docs/06 3-3·통계 (읽기 전용)

[담당 파일 — 이 순서대로]
1. backend/db/views.sql — [S4-B] v_stock_metrics: 수익률(1m·3m·1y)·변동성·MDD·120일선 괴리율·PER·PBR·ROE·성장률 등 (CTE·윈도우 함수). 배당(dps·dividend_yield) 열은 Stage 6 → 뺀다  ← 여기까지 ①번 브랜치로 먼저 PR
2. backend/app/queries/analysis.sql — v_stock_metrics + stock_scores, 국가 내 RANK·PERCENT_RANK, 주 그룹 평균(peer_average)
3. backend/app/api/deps.py — [S4-B] get_preset(없으면 422 UNKNOWN_PRESET)
4. backend/app/api/analysis.py — router: /stocks/{m}/{t}/analysis, /peers, /peers/chart / scoring_router: /scoring/presets
5. backend/app/queries/peers.sql(그룹 내 RANK·AVG, 1인 그룹 처리), peers_chart.sql(기준일=100, 합집합 날짜 + 휴장 null)
6. backend/app/api/analysis.py stats_router + queries: stats_overview, stats_market_valuation(+stats_market_excluded, HAVING min_samples), stats_peer_group_valuation, stats_disclosure_frequency
7. 기존 응답에 매력도 추가 — [S4-B] 구역: stock_list.sql·stock_detail.sql·watchlist.sql에 preset별 score JOIN, /stocks·/watchlist에 preset 파라미터 (포트폴리오 summary 가중 매력도는 C에게 요청 메모)
8. schemas [S4-B] 구역, main.py [S4-B] 라우터 등록(router·stats_router·scoring_router)
9. backend/tests/test_analysis.py

[건드리지 않을 파일] scoring.py·score_*.sql(C), 마이그레이션·schema(D), frontend(A)
[인터페이스 계약]
- 제공: v_stock_metrics 컬럼(C가 입력으로 씀 — 이름 변경 금지), 응답은 원본 docs/06 3-3 예시에서 reference·reference_note·detail_status·dps 제외
- 사용: stock_scores(C), scoring_presets(D)
[이번 단계에서 뺄 것] statistics monthly·ranking·data-quality(Stage 5), listed 참고 점수, dps·dividend_yield
[완료 기준]
  curl "localhost:8000/api/v1/stocks/KOSPI/005930/analysis?preset=growth" → 원본 3-3 예시 구조
  curl localhost:8000/api/v1/stocks/KOSPI/005930/peers/chart?range=1m → 휴장일 null 포함
  pytest -q tests/test_analysis.py

[선행 작업] ①은 선행 없음 — 끝나면 바로 Ready PR(C가 이 VIEW를 기다린다). ②는 C(feat/s4-c-scoring)의 stock_scores 행이 필요하지만 테이블(D)은 이미 있으므로 테스트는 픽스처로 행을 직접 넣어 진행한다. ①이 머지 전이면 ②는 ①에서 갈라져 시작(CLAUDE.md 10절). C 머지 전이면 ②는 Draft PR.
[시작] ① CLAUDE.md 10절대로 최신 코드부터 받는다: git fetch → [브랜치]로 이동(없으면 origin/stage4에서 새로 만듦) → origin/stage4 합치기. 이동한 뒤 CLAUDE.md를 다시 읽고 그 규칙을 따른다(설명은 9절 입문자 기준, 다른 팀원 파일이 없으면 11절대로 묻지 않고 진행).
② CLAUDE.md 2절의 작업 계획표만 출력하라. 코드는 내가 승인한 뒤 파일 하나씩 진행한다.
```

---

## 팀원 A — 분석 화면

```
[역할] 너는 StockMind 팀 프로젝트에서 팀원 A(프론트엔드·사용자 경험, 주니어)의 페어 프로그래머다. 레포 루트 CLAUDE.md의 규칙을 반드시 따른다.
[이번 단계] Stage 4 — 분석 화면. 매력도는 "투자 권유가 아님" 문구를 항상 함께 표시한다.
[내 파트] 투자 성향 메뉴 → 상세 매력도 → 수치 분석 → 경쟁 비교 → 리스트·홈 카드 매력도
[브랜치] feat/s4-a-analysis-screens
[참조 원본] ../ax_class_semiproject/frontend/js/components/preset-menu.js, js/pages/stock.js(분석 부분), docs/screenshots/{01_home,02_stocks,03_stock_detail}.png, docs/06 3-3 (읽기 전용)

[담당 파일 — 이 순서대로]
1. frontend/js/api.js — [S4-A] 구역: getAnalysis·getPresets·getPeers·getPeersChart, 기존 함수에 preset 인자
2. frontend/js/components/preset-menu.js — 위험·성장·균형·가치 펼침 메뉴, 선택값 localStorage(try/catch)
3. frontend/js/pages/stock.js — [S4-A] 매력도 게이지·국가 내 순위·백분위·데이터 충족도, 팩터 기여도 막대, 지표 원값/Z 표, 레이더(주 그룹 평균 비교)
4. frontend/js/pages/stock.js — [S4-A] 수치 분석(수익률·변동성·MDD·120일선 괴리율)
5. frontend/js/pages/stock.js — [S4-A] 경쟁 비교 표(그룹 내 순위·평균) + 기준일=100 추이 차트(그룹 선택, 휴장 null은 선 끊김)
6. frontend/js/pages/stocks.js·home.js — [S4-A] 매력도 열·관심종목 카드 게이지, 프리셋 변경 시 재조회
7. frontend/js/components/charts.js·css/pages.css — [S4-A] 구역

[건드리지 않을 파일] backend/ 전부, 공통 css(D)
[이번 단계에서 뺄 것] 비교군 '상세 데이터 수집 중' 배지(D 작업 후 Stage 4 통합 때 D가 요청하면 추가), 월별 요약, 순위표, 상장 목록 참고 점수 안내
[완료 기준]
  프리셋 바꾸면 상세·리스트·홈 점수가 같이 바뀜 / 1인 그룹은 '비교 대상 없음' / 점수 없는 종목은 빈 상태 / 콘솔 에러 0

[선행 작업] B ②(feat/s4-b-analysis-api)의 analysis·peers·presets API. 아직 없으면 docs/06 3-3 예시로 MOCK 하고 묻지 말고 진행한다. 머지 순서가 마지막이므로 B②·D 머지 전이면 Draft PR.
[시작] ① CLAUDE.md 10절대로 최신 코드부터 받는다: git fetch → [브랜치]로 이동(없으면 origin/stage4에서 새로 만듦) → origin/stage4 합치기. 이동한 뒤 CLAUDE.md를 다시 읽고 그 규칙을 따른다(설명은 9절 입문자 기준, 다른 팀원 파일이 없으면 11절대로 묻지 않고 진행).
② CLAUDE.md 2절의 작업 계획표만 출력하라. 코드는 내가 승인한 뒤 파일 하나씩 진행한다.
```

---

## 팀원 D(시니어) — 비교군·요청 시 상세 수집

```
시니어 모드. Stage 4.
[PR] Draft PR은 코드 리뷰만 한다. Ready로 바뀐 PR을 머지 순서대로 머지하고, 머지할 때마다 다음 순서 팀원에게 알린다(그쪽 Claude가 동기화 중 머지를 감지해 Ready 전환을 시작한다).
[선행] 001_scoring_v2.sql·002_presets.sql + schema·ORM, docs/05 v_stock_metrics 컬럼 계약 → 커밋 후 배포.
[내 구현]
1. 003_benchmark.sql(+schema: coverage, detail_synced_at), backend/app/ingest/benchmark.py — 국가·섹터별 시총 상위 비교군 선정·평시 데이터·정리
2. backend/app/services/hydration.py — 비교군 종목 상세 요청 시 백그라운드 수집, detail_status(ready/loading/failed, 실패 10분 뒤 재시도)
3. refresh.py에 SCORES 작업 연결(C 요청 메모), scheduler에 매일 07:00 KST 비교군 작업
4. stocks.py 상세 응답 detail_status·/stocks q 검색 시 비교군 포함 — B와 구역 합의 후 D가 추가, A에게 배지 요청
5. backend/tests/test_benchmark.py, docs/09 비교군 절
[통합] B(VIEW) → C → B(API) → D → A 머지, benchmark → scores 실행 → 화면 확인 → stage4 → main, 태그 v4.0
```
