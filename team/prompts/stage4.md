# Stage 4 — 분석: 매력도·경쟁 비교·통계

**단계 목표**: 같은 시장 안 상대 위치를 나타내는 매력도(다중 팩터: 지표 → 로버스트 Z → 섹터 중립화 → 프리셋 가중 → 100·Φ)를 계산·저장하고, 종목 상세에서 수치 분석·경쟁 비교·통계를 보여준다.
**D 선행 계약**: 마이그레이션 `001_scoring_v2.sql`·`002_presets.sql`과 schema 반영(scoring_presets, scoring_weights, stock_metric_values, stock_scores, peer_group_members.is_primary), `docs/05`에 `v_stock_metrics` 컬럼 목록과 `stock_scores` 구조 기록.
**순서상 의존**: B의 `v_stock_metrics`가 C의 지표 입력이다 → **B는 1번(VIEW)부터 먼저 PR**하고 나머지를 이어서 한다.
**머지 순서**: B(VIEW) → C → B(API) → D → A
**PR 방식**: 파일마다 push, 첫 push 때 Draft PR, **파트 하나 = PR 하나**로 끝나는 대로 Ready(CLAUDE.md 6절). 앞 순서 팀원의 코드가 필요하면 머지를 기다리지 않고 그 팀원 브랜치를 merge해서 쓴다(11절). 이때 내 PR은 그 팀원 PR이 머지될 때까지 Draft. push·PR 상태는 팀 채팅에 📣 한 줄로 공유. 시니어는 CI가 통과한 Ready PR을 머지 순서대로 바로바로 머지한다.

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

[파트별 확인 — 계획표의 "파트별 확인 지점"으로 그대로 쓴다. 파일마다 만든 직후 돌려 보고(CLAUDE.md 3절 ③), 파트가 끝날 때마다 실제로 실행해서 "여기까지 만든 것"을 보여 주고 아주 쉽게 설명한다(3-1)]
파트 1 (1~2번 설정·프리셋) → 볼 것: load_config 결과로 지표 수·프리셋 4개·프리셋별 가중치 합(=1) 출력. 가중치 합이 틀린 설정을 메모리에서만 만들어 validate_presets가 어떤 에러를 내는지 1번. sync_presets 후 psql로 scoring_presets 4행·scoring_weights 행 수.
파트 2 (3번 지표값 저장) → 볼 것: insert_metric_values 실행 → psql로 005930의 stock_metric_values(지표 이름·원값) 출력, v_stock_metrics의 같은 값과 나란히.
파트 3 (4~5번 로버스트 Z·섹터 중립화) → 볼 것: 005930 PER 하나를 골라 원값 → Z(중앙값·MAD로 계산한 숫자를 손계산으로도 한 번) → 클리핑 → 중립화 후 값까지 한 줄씩 따라가기. 그룹 평균에 같은 국가 종목만 들어간 것을 psql로 보여 준다.
파트 4 (6~7번 집계·CLI) → 볼 것: `python -m app.ingest scores` → stock_scores 행 수, `explain` → 삼성전자 팩터별 기여도 읽어 주기. 프리셋(성장·가치)마다 점수가 달라지는 것을 표로 비교.
파트 5 (8~9번 테스트·정의서) → pytest -v 번역. 정의서는 파트 1~4에서 본 숫자가 문서의 어느 식에 해당하는지 짝지어 준다.

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
② "모델 한 장 요약"(9절 문체)만 먼저 출력하고, 그다음 CLAUDE.md 2절의 작업 계획표(파트별 확인 지점 포함). 코드는 내가 승인한 뒤 파일 하나씩 진행하고, 파일마다 만든 직후 실제로 돌려서 보여 주며(3절 ③), 파트가 끝날 때마다 "여기까지 만든 것"을 실행해 보여 준다(3-1).
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
   + schemas [S4-B] 구역에 이 응답 모델, main.py [S4-B]에 router·scoring_router 등록 (등록해야 바로 curl로 돌려 볼 수 있다)
5. backend/app/queries/peers.sql(그룹 내 RANK·AVG, 1인 그룹 처리), peers_chart.sql(기준일=100, 합집합 날짜 + 휴장 null) (+ 응답 모델)
6. backend/app/api/analysis.py stats_router + queries: stats_overview, stats_market_valuation(+stats_market_excluded, HAVING min_samples), stats_peer_group_valuation, stats_disclosure_frequency (+ 응답 모델, main.py에 stats_router 등록)
7. 기존 응답에 매력도 추가 — [S4-B] 구역: stock_list.sql·stock_detail.sql·watchlist.sql에 preset별 score JOIN, /stocks·/watchlist에 preset 파라미터 (포트폴리오 summary 가중 매력도는 C에게 요청 메모)
8. schemas [S4-B] 구역 남은 정리(공통 모델·필드 설명)
9. backend/tests/test_analysis.py

[파트별 확인 — 계획표의 "파트별 확인 지점"으로 그대로 쓴다. 파일마다 만든 직후 돌려 보고(CLAUDE.md 3절 ③), 파트가 끝날 때마다 실제로 실행해서 "여기까지 만든 것"을 보여 주고 아주 쉽게 설명한다(3-1)]
파트 1 (1번 v_stock_metrics — ①번 브랜치) → 볼 것: psql로 005930·AAPL의 return_1m·volatility·mdd·per·pbr 등 출력. 1개월 수익률 하나는 daily_prices에서 두 종가를 직접 꺼내 손계산해 VIEW 값과 같은지 보여 준다.
파트 2 (2~4번 분석 SQL·프리셋 검증·analysis 라우터) → 볼 것: curl `/stocks/KOSPI/005930/analysis?preset=growth` → 원본 3-3 예시와 칸 비교, preset=xxx → 422 UNKNOWN_PRESET, `/scoring/presets`. C 머지 전이라 점수가 null이면 그게 정상인 이유를 말해 준다.
파트 3 (5번 경쟁 비교·추이) → 볼 것: curl `/peers`(그룹 내 순위·평균), `/peers/chart?range=1m` → 첫날 값이 100인 것, 휴장일 null 위치를 짚어 준다. 1인 그룹 종목 응답도 1번.
파트 4 (6번 통계 4종) → 볼 것: 4개 엔드포인트 curl. min_samples로 빠진 그룹(stats_market_excluded)이 왜 빠졌는지 숫자로 설명.
파트 5 (7번 기존 응답에 매력도) → 볼 것: `/stocks?preset=growth` 와 `?preset=value` 결과를 나란히 — 점수 열이 달라짐. /watchlist도 같은 방식.
파트 6 (8~9번 남은 스키마·테스트) → pytest -v 번역.

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
② CLAUDE.md 2절의 작업 계획표만 출력하라(파트별 확인 지점 포함). 코드는 내가 승인한 뒤 파일 하나씩 진행하고, 파일마다 만든 직후 실제로 돌려서 보여 주며(3절 ③), 파트가 끝날 때마다 "여기까지 만든 것"을 실행해 보여 준다(3-1).
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

[파트별 확인 — 계획표의 "파트별 확인 지점"으로 그대로 쓴다. 파일마다 만든 직후 돌려 보고(CLAUDE.md 3절 ③), 파트가 끝날 때마다 실제로 실행해서 "여기까지 만든 것"을 보여 주고 아주 쉽게 설명한다(3-1)]
파트 1 (1~3번 api.js·투자 성향 메뉴·매력도 게이지) → 볼 것: /stocks/KOSPI/005930 에서 메뉴로 성장↔가치 바꾸면 게이지·순위·기여도 막대가 바뀜. 새로고침해도 선택이 유지되는 것과, 개발자 도구 Application 탭 localStorage에 저장된 값 보여 주기. "투자 권유가 아님" 문구 확인.
파트 2 (4~5번 수치 분석·경쟁 비교) → 볼 것: 수익률·변동성·MDD 값을 curl analysis 응답과 나란히 비교. 추이 차트에서 휴장일 null 때문에 선이 끊긴 곳 찾기. 1인 그룹 종목에서 '비교 대상 없음'.
파트 3 (6~7번 리스트·홈 매력도, 차트·CSS) → 볼 것: 프리셋을 바꾸면 상세·리스트·홈 점수가 같이 바뀜(Network 탭에 preset 값이 바뀐 요청). 점수 없는 종목 빈 상태. 화면별 스크린샷 안내.

[건드리지 않을 파일] backend/ 전부, 공통 css(D)
[이번 단계에서 뺄 것] 비교군 '상세 데이터 수집 중' 배지(D 작업 후 Stage 4 통합 때 D가 요청하면 추가), 월별 요약, 순위표, 상장 목록 참고 점수 안내
[완료 기준]
  프리셋 바꾸면 상세·리스트·홈 점수가 같이 바뀜 / 1인 그룹은 '비교 대상 없음' / 점수 없는 종목은 빈 상태 / 콘솔 에러 0

[선행 작업] B ②(feat/s4-b-analysis-api)의 analysis·peers·presets API. stage에 없으면 그 팀원 브랜치를 먼저 받고(CLAUDE.md 11절), 브랜치에도 없으면 docs/06 3-3 예시로 MOCK 하고 묻지 말고 진행한다. 머지 순서가 마지막이므로 B②·D 머지 전이면 Draft PR.
[시작] ① CLAUDE.md 10절대로 최신 코드부터 받는다: git fetch → [브랜치]로 이동(없으면 origin/stage4에서 새로 만듦) → origin/stage4 합치기. 이동한 뒤 CLAUDE.md를 다시 읽고 그 규칙을 따른다(설명은 9절 입문자 기준, 다른 팀원 파일이 없으면 11절대로 묻지 않고 진행).
② CLAUDE.md 2절의 작업 계획표만 출력하라(파트별 확인 지점 포함). 코드는 내가 승인한 뒤 파일 하나씩 진행하고, 파일마다 만든 직후 실제로 돌려서 보여 주며(3절 ③), 파트가 끝날 때마다 "여기까지 만든 것"을 실행해 보여 준다(3-1).
```

---

## 팀원 D(시니어) — 비교군·요청 시 상세 수집

```
시니어 모드. Stage 4.
[PR] Draft PR은 코드 리뷰만 한다. CI가 통과한 Ready PR(파트 단위)을 머지 순서대로 당일 머지하고, 머지할 때마다 팀 채팅에 알린다(다음 순서 팀원의 Claude가 동기화 중 머지를 감지해 Draft를 Ready로 바꾼다). 받은 요청 메모는 추천안에 OK/다른 지시만 답한다.
[선행] 001_scoring_v2.sql·002_presets.sql + schema·ORM, docs/05 v_stock_metrics 컬럼 계약 → 커밋 후 배포.
[내 구현]
1. 003_benchmark.sql(+schema: coverage, detail_synced_at), backend/app/ingest/benchmark.py — 국가·섹터별 시총 상위 비교군 선정·평시 데이터·정리
2. backend/app/services/hydration.py — 비교군 종목 상세 요청 시 백그라운드 수집, detail_status(ready/loading/failed, 실패 10분 뒤 재시도)
3. refresh.py에 SCORES 작업 연결(C 요청 메모), scheduler에 매일 07:00 KST 비교군 작업
4. stocks.py 상세 응답 detail_status·/stocks q 검색 시 비교군 포함 — B와 구역 합의 후 D가 추가, A에게 배지 요청
5. backend/tests/test_benchmark.py, docs/09 비교군 절
[통합] B(VIEW) → C → B(API) → D → A 머지, benchmark → scores 실행 → 화면 확인 → stage4 → main, 태그 v4.0
```
