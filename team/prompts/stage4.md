# Stage 4 — 분석: 매력도·경쟁 비교·통계

**단계 목표**: 같은 시장 안 상대 위치를 나타내는 매력도(다중 팩터: 지표 → 로버스트 Z → 섹터 중립화 → 프리셋 가중 → 100·Φ)를 계산·저장하고, 종목 상세에서 수치 분석·경쟁 비교·통계를 보여준다.
**D 선행 계약**: 마이그레이션 `001_scoring_v2.sql`·`002_presets.sql`과 schema 반영(scoring_presets, scoring_weights, stock_metric_values, stock_scores, peer_group_members.is_primary), `docs/05`에 `v_stock_metrics` 컬럼 목록과 `stock_scores` 구조 기록.
**D 껍데기**(단계 시작 전 stage4에, `TODO(껍데기)` 주석): `views.sql` v_stock_metrics(B ① — `docs/05` 컬럼 그대로, PER·PBR처럼 valuation_snapshots에서 바로 꺼낼 수 있는 값만 채우고 나머지는 NULL), `scoring.py`의 compute_scores 등 원본 시그니처(C — 0 반환), `seed-demo`에 stock_scores·stock_metric_values 시드 행(프리셋 4종 × 데모 종목), `analysis.py` router·scoring_router·stats_router 엔드포인트 + main.py 등록(B ② — `docs/06` 3-3·통계 예시 응답).
**머지·마감**: 순서 없음 — Ready PR은 도착하는 대로 머지한다. PR 마감 시각까지 Ready가 안 된 파일은 D가 인수한다(그전까지는 껍데기가 그대로 있어 앱은 정상 동작한다).
**PR 방식**: 파일마다 커밋·push, 파트 하나 = PR 하나로 끝나는 대로 D에게 넘긴다(CLAUDE.md 6절). 다른 팀원 브랜치는 받지 않는다. 다른 팀원 코드는 D가 미리 넣은 껍데기를 그대로 쓰고(✅ 있음), 내 파일의 껍데기는 본문을 원본대로 교체한다. 껍데기도 없을 때만 [연결 예정](CLAUDE.md 11절). 시니어는 자동 검사가 통과한 넘김 PR을 도착하는 대로 바로바로 머지한다.

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

[선행 작업] 없음 — B의 v_stock_metrics는 D의 껍데기(docs/05 컬럼, PER·PBR 등 일부 값만 채움)가 stage4에 있어 ✅ 그대로 쓴다. 2·6번 scoring.py의 compute_scores 등은 D의 껍데기가 들어 있으니 본문을 원본대로 교체한다. B가 실제 VIEW를 머지하면 같은 코드 그대로 모든 지표 값이 들어온다.
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
파트 2 (2~4번 분석 SQL·프리셋 검증·analysis 라우터) → 볼 것: curl `/stocks/KOSPI/005930/analysis?preset=growth` → 원본 3-3 예시와 칸 비교, preset=xxx → 422 UNKNOWN_PRESET, `/scoring/presets`. C 머지 전에는 seed-demo의 시드 점수가 나온다는 것을 말해 준다.
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

[선행 작업] 없음 — ①은 파트가 끝나는 대로 넘긴다(빨리 머지될수록 C가 실제 지표 값으로 확인할 수 있다). ②는 ① 머지와 상관없이 origin/stage4에서 갈라져 시작한다(VIEW 껍데기가 stage4에 있다). C의 stock_scores는 D의 시드 행이 있어 ✅ 그대로 쓰고, 테스트는 픽스처로 행을 직접 넣는다. 4~6번 analysis.py 엔드포인트는 D의 껍데기가 들어 있으니 본문을 원본대로 교체한다.
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
[참조 원본] ../ax_class_semiproject/frontend/js/components/preset-menu.js, js/pages/stock.js(분석 부분), docs/screenshots/{01_home,02_stocks,03_stock_detail}.png, docs/06 3-3 (읽기 전용) 스크린샷·원본 화면은 참고용 — 배치·디자인·문구 같은 표현은 A가 정해도 된다(CLAUDE.md 1절, PR "원본과 다르게 한 것"에 기록).

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

[선행 작업] 없음 — B의 analysis·peers·presets API는 D의 껍데기가 stage4에 있어 ✅ 그대로 쓴다. MOCK을 따로 만들지 않는다. 껍데기 동안은 docs/06 3-3 예시 값이라 프리셋을 바꿔도 점수가 같다 — Network 탭에서 preset 값이 바뀐 요청이 나가는 것으로 확인하고, B가 본문을 교체하면 같은 코드 그대로 점수가 바뀐다.
[시작] ① CLAUDE.md 10절대로 최신 코드부터 받는다: git fetch → [브랜치]로 이동(없으면 origin/stage4에서 새로 만듦) → origin/stage4 합치기. 이동한 뒤 CLAUDE.md를 다시 읽고 그 규칙을 따른다(설명은 9절 입문자 기준, 다른 팀원 파일이 없으면 11절대로 묻지 않고 진행).
② CLAUDE.md 2절의 작업 계획표만 출력하라(파트별 확인 지점 포함). 코드는 내가 승인한 뒤 파일 하나씩 진행하고, 파일마다 만든 직후 실제로 돌려서 보여 주며(3절 ③), 파트가 끝날 때마다 "여기까지 만든 것"을 실행해 보여 준다(3-1).
```

---

## 팀원 D(시니어) — 비교군·요청 시 상세 수집

```
시니어 모드. Stage 4.
[PR] 파트 단위로 넘어온(Ready) PR을 자동 검사 통과 확인 후 도착하는 대로 당일 머지하고, 팀 채팅에 알린다. 진행 중(Draft) PR은 코드만 미리 본다. 받은 요청 메모는 추천안에 OK/다른 지시만 답한다.
[마감] PR 마감 시각에 stage4에서 `git grep -n "TODO(껍데기)"`로 남은 껍데기를 본다. 남은 파일은 D가 인수한다 — 담당자 브랜치의 끝난 커밋까지 머지하고 나머지를 D가 작성한다. 시간이 모자라면 껍데기 그대로 태그를 달고 다음 단계를 연다(앱은 정상 동작). 인수 내역(파일·원래 담당·사유·상태)은 stage4 → main PR 본문 "인수 파트"에 적고, 인수분은 끝나는 대로 stage4에 머지한 뒤 다음 stage로 합친다.
[연결 예정 처리] 마감 후 stage에서 `git grep -n "TODO(연결)"` → 각 PR의 "연결 예정 목록"대로 연결(import를 원본처럼 맨 위로, MOCK 제거, 목록의 테스트 추가) → `pytest -q`·`python team/tools/check_contract.py 4` 통과 → 아래 통합으로.
[선행] stage3(인수분 포함 현재 상태)에서 stage4를 만든다 → 001_scoring_v2.sql·002_presets.sql + schema·ORM, docs/05 v_stock_metrics 컬럼 계약 + 머리말의 "D 껍데기" 전부(`TODO(껍데기): {담당} — {무엇}` 주석, 이름·인자·응답 모양은 원본 그대로) → `pytest -q` 통과 → 커밋 후 배포.
[내 구현]
1. 003_benchmark.sql(+schema: coverage, detail_synced_at), backend/app/ingest/benchmark.py — 국가·섹터별 시총 상위 비교군 선정·평시 데이터·정리
2. backend/app/services/hydration.py — 비교군 종목 상세 요청 시 백그라운드 수집, detail_status(ready/loading/failed, 실패 10분 뒤 재시도)
3. refresh.py에 SCORES 작업 연결(C 요청 메모), scheduler에 매일 07:00 KST 비교군 작업
4. stocks.py 상세 응답 detail_status·/stocks q 검색 시 비교군 포함 — B와 구역 합의 후 D가 추가, A에게 배지 요청
5. backend/tests/test_benchmark.py, docs/09 비교군 절
[통합] 마감·인수 후 benchmark → scores 실행 → 화면 확인 → stage4 → main, 태그 v4.0
```
