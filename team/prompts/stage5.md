# Stage 5 — 고도화: 메모·목표가·통계 확장·운영 안정성

**단계 목표**: 사용 중 나온 요구(관심종목 메모·목표가, 월별·랭킹 통계, 균등 배분, 데이터 품질 확인)를 반영하고, 운영 중인 DB를 데이터 유지한 채 마이그레이션으로 바꾸는 흐름을 보여준다.
**D 선행 계약**: `004_watchlist_memo.sql`(memo·target_price) 마이그레이션과 schema 반영, `006_sector_freshness.sql`은 D 본인 작업.
**머지 순서**: C → B → D → A
**PR 방식**: 앞 순서 작업이 머지되기 전에 끝나면 기다리지 않고 Draft PR → 시니어가 그 파트를 먼저 리뷰 → 앞 순서 머지 후 최신 stage를 합쳐 같은 PR을 Ready로 전환(CLAUDE.md 6절). 시니어는 Ready PR만 머지 순서대로 머지한다.

---

## 팀원 B — 관심종목 메모·목표가 + 통계 확장

```
[역할] 너는 StockMind 팀 프로젝트에서 팀원 B(백엔드 API·DB, 주니어)의 페어 프로그래머다. 레포 루트 CLAUDE.md의 규칙을 반드시 따른다.
[이번 단계] Stage 5 — 고도화
[내 파트] 관심종목 PUT(메모·목표가·target_gap) → 월별 집계 → 지표별 랭킹 → 데이터 품질 API → 입력 검증 상한
[브랜치] feat/s5-b-memo-stats
[참조 원본] ../ax_class_semiproject/backend/app/api/{watchlist,analysis}.py, queries/{watchlist,stats_monthly,stats_ranking,stats_data_quality}.sql, docs/06 (PUT watchlist, statistics/monthly·ranking·data-quality) (읽기 전용)

[담당 파일 — 이 순서대로]
1. backend/app/queries/watchlist.sql + api/watchlist.py — PUT /watchlist/{market}/{ticker}: 보낸 필드만 변경, null이면 지움, 빈 본문 422, memo 200자, target_price > 0 소수 4자리. GET 응답에 memo·target_price·target_gap = (목표가 − 현재가) / 현재가
2. backend/app/queries/stats_monthly.sql + stats_router GET /statistics/monthly — date_trunc + GROUP BY, FIRST_VALUE/LAST_VALUE 윈도우, 진행 중인 달 is_partial
3. backend/app/queries/stats_ranking.sql + GET /statistics/ranking — RANK() OVER(같은 값 같은 순위 1,1,3), 지표값 없는 종목 제외, 전체+volume은 422 VOLUME_SORT_REQUIRES_MARKET
4. backend/app/queries/stats_data_quality.sql + GET /statistics/data-quality — C의 data_quality 서비스 호출(시그니처는 C와 PR 전에 합의)
5. deps·schemas [S5-B] — 입력 검증 상한(limit·offset·q 길이 등 원본 A-112 기준)
6. backend/tests/test_watchlist_api.py·test_analysis.py 추가분

[건드리지 않을 파일] 마이그레이션·schema(D), services/data_quality.py·portfolio.py(C), frontend(A)
[인터페이스 계약] 응답은 원본 docs/06 해당 엔드포인트 예시와 같은 구조
[이번 단계에서 뺄 것] /stocks/search, listed 종목, home API, dps
[완료 기준]
  curl -X PUT .../watchlist/NASDAQ/AAPL -d '{"memo":"테스트","target_price":250}' → target_gap 포함 200, 이후 null로 되돌림
  curl ".../statistics/ranking?metric=return_1m&country=KR&limit=5"
  pytest -q

[선행 작업] C(feat/s5-c-equal-weight-quality)의 data_quality 서비스(4번에서 호출). C와 합의한 시그니처(합의 전이면 원본 시그니처)대로 import 해 작성하고, 4번 테스트는 ⏸ C 머지 후. 1~3번은 선행 없음. C 머지 전이면 Draft PR.
[시작] ① CLAUDE.md 10절대로 최신 코드부터 받는다: git fetch → [브랜치]로 이동(없으면 origin/stage5에서 새로 만듦) → origin/stage5 합치기. 이동한 뒤 CLAUDE.md를 다시 읽고 그 규칙을 따른다(설명은 9절 입문자 기준, 다른 팀원 파일이 없으면 11절대로 묻지 않고 진행).
② CLAUDE.md 2절의 작업 계획표만 출력하라. 코드는 내가 승인한 뒤 파일 하나씩 진행한다.
```

---

## 팀원 C — 균등 배분 미리보기·데이터 품질 서비스

```
[역할] 너는 StockMind 팀 프로젝트에서 팀원 C(데이터 수집·분석 로직, 주니어)의 페어 프로그래머다. 레포 루트 CLAUDE.md의 규칙을 반드시 따른다.
[이번 단계] Stage 5 — 고도화
[내 파트] 균등 배분 계산 → 엔드포인트 → 데이터 품질 집계 서비스 → CLI status → 포트폴리오 가중 매력도 → 테스트
[브랜치] feat/s5-c-equal-weight-quality
[참조 원본] ../ax_class_semiproject/backend/app/services/{portfolio,data_quality}.py, api/portfolios.py, tests/{test_equal_weight,test_data_quality}.py, docs/06 (preview/equal-weight, data-quality) (읽기 전용)

[담당 파일 — 이 순서대로]
1. backend/app/services/portfolio.py — preview_equal_weight: 예산 ÷ 대상 수 = 균등 몫 → 1주 원화 원가로 내림한 정수 수량(담기 금액 모드와 같은 환산), 남는 금액, 제외 종목과 사유(ALREADY_IN_PORTFOLIO·NO_PRICE·PRICE_ABOVE_SHARE). **저장하지 않는 계산 전용**
2. backend/app/api/portfolios.py — POST /portfolios/{id}/preview/equal-weight (body 생략 시 관심종목 전체·잔여 시드, 관심종목 비면 422 EMPTY_WATCHLIST, 예산 > 잔여 409)
3. backend/app/services/portfolio.py summary — Stage 4에서 B가 요청한 가중 매력도(비중 가중 평균)
4. backend/app/services/data_quality.py — 작업 종류별 마지막 성공·실패(사유·티커), 최근 N일 상태별 건수, 격리 행 수, stale_jobs(작업 단위 성공이 TTL×2 초과)
5. backend/app/ingest/__main__.py — [S5-C] status 명령(같은 서비스 사용)
6. backend/tests/test_equal_weight.py, test_data_quality.py

[건드리지 않을 파일] stats_data_quality.sql·analysis.py(B — B가 내 서비스를 호출), schema(D), frontend(A)
[인터페이스 계약]
- 제공: data_quality 서비스 함수 시그니처를 PR 전에 B와 합의해 PR 본문에 기록
[이번 단계에서 뺄 것] 섹터 히트맵·시장 심리 지수(Stage 6), listing
[완료 기준]
  curl -X POST .../portfolios/{id}/preview/equal-weight → 수량·제외 사유, DB에 변화 없음
  docker compose run --rm api python -m app.ingest status
  pytest -q tests/test_equal_weight.py tests/test_data_quality.py

[선행 작업] 없음 — 머지 순서 1번이므로 끝나면 바로 Ready PR. data_quality 시그니처는 계획표 승인 직후 B에게 공유해 B가 기다리지 않게 하고, PR 본문에도 적는다.
[시작] ① CLAUDE.md 10절대로 최신 코드부터 받는다: git fetch → [브랜치]로 이동(없으면 origin/stage5에서 새로 만듦) → origin/stage5 합치기. 이동한 뒤 CLAUDE.md를 다시 읽고 그 규칙을 따른다(설명은 9절 입문자 기준, 다른 팀원 파일이 없으면 11절대로 묻지 않고 진행).
② CLAUDE.md 2절의 작업 계획표만 출력하라. 코드는 내가 승인한 뒤 파일 하나씩 진행한다.
```

---

## 팀원 A — 편집·설정 UI

```
[역할] 너는 StockMind 팀 프로젝트에서 팀원 A(프론트엔드·사용자 경험, 주니어)의 페어 프로그래머다. 레포 루트 CLAUDE.md의 규칙을 반드시 따른다.
[이번 단계] Stage 5 — 고도화 화면
[내 파트] 메모·목표가 편집 → 지수·환율 표시 지표 설정 → 월별 요약 → 균등 배분 패널 → 홈 순위 상위 5 → 모바일 점검
[브랜치] feat/s5-a-edit-settings
[참조 원본] ../ax_class_semiproject/frontend/js/components/{watch-note,metric-picker}.js, js/pages/{home,stock,portfolio}.js, docs/screenshots/{06_mobile_home,07_mobile_stocks,08_mobile_portfolio}.png (읽기 전용)

[담당 파일 — 이 순서대로]
1. frontend/js/api.js — [S5-A] 구역: putWatchlist·getMonthly·getRanking·previewEqualWeight
2. frontend/js/components/watch-note.js — 카드에서 메모·목표가 편집, 목표가 대비 괴리율 표시
3. frontend/js/components/metric-picker.js — 지수 10개 + 환율 중 표시할 지표 선택(localStorage, try/catch), 한 줄·넘치면 가로 스크롤
4. frontend/js/pages/stock.js — [S5-A] 월별 요약 표(최근 12개월, 진행 중인 달 표시)
5. frontend/js/pages/portfolio.js — [S5-A] 관심종목 균등 배분 미리보기 패널(제외 사유 표시, '모두 담기'로 연결)
6. frontend/js/pages/home.js — [S5-A] 순위 상위 5 (거래량·1개월·1년 수익률 × 국내/미국 탭)
7. 모바일(390px) 홈·리스트·포트폴리오 점검 — css/pages.css [S5-A]

[건드리지 않을 파일] backend/ 전부, 공통 css(D)
[이번 단계에서 뺄 것] 상단 검색, 섹터 히트맵·심리 지수, 홈 2열 개편
[완료 기준] 메모 수정 후 새로고침해도 유지 / 지표 설정 유지 / 균등 배분 '모두 담기' 후 요약 갱신 / 모바일 가로 스크롤 없음

[선행 작업] B(feat/s5-b-memo-stats)의 PUT watchlist·monthly·ranking, C(feat/s5-c-equal-weight-quality)의 equal-weight 미리보기. 아직 없으면 docs/06 예시로 MOCK 하고 묻지 말고 진행한다. 머지 순서가 마지막이므로 B·C·D 머지 전이면 Draft PR.
[시작] ① CLAUDE.md 10절대로 최신 코드부터 받는다: git fetch → [브랜치]로 이동(없으면 origin/stage5에서 새로 만듦) → origin/stage5 합치기. 이동한 뒤 CLAUDE.md를 다시 읽고 그 규칙을 따른다(설명은 9절 입문자 기준, 다른 팀원 파일이 없으면 11절대로 묻지 않고 진행).
② CLAUDE.md 2절의 작업 계획표만 출력하라. 코드는 내가 승인한 뒤 파일 하나씩 진행한다.
```

---

## 팀원 D(시니어) — 업종 섹터·유효기간·헬스체크

```
시니어 모드. Stage 5.
[PR] Draft PR은 코드 리뷰만 한다. Ready로 바뀐 PR을 머지 순서대로 머지하고, 머지할 때마다 다음 순서 팀원에게 알린다(그쪽 Claude가 동기화 중 머지를 감지해 Ready 전환을 시작한다).
[선행] 004_watchlist_memo.sql + schema·ORM → 커밋 후 배포. 마이그레이션 적용 시연: 기존 DB에 `python -m app.ingest migrate 004_watchlist_memo`.
[내 구현]
1. 006_sector_freshness.sql(+schema: peer_groups.kind, stocks.industry·sic, data_freshness, fundamental_bases)
2. backend/app/ingest/sectors.py(KRX 업종·SIC → 섹터), benchmark 섹터 계층, scoring 중립화가 업종 섹터를 쓰도록 C와 합의
3. backend/app/services/freshness.py — 재무 유효기간·사업보고서 공시 시 무효화, B의 load_financials와 연결
4. /health/db 503(연결 시간 제한), 컨테이너 HEALTHCHECK 교체, 500 응답 요청 ID 유지, 입력 검증 상한 리뷰
5. backend/tests/{test_freshness,test_health}.py, docs/architecture.md
[통합] C → B → D → A 머지, migrate 004·006 → benchmark --reselect → scores → 화면 확인 → stage5 → main, 태그 v5.0
```
