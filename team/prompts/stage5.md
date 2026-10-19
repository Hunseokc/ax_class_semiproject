# Stage 5 — 고도화: 메모·목표가·통계 확장·운영 안정성

**단계 목표**: 사용 중 나온 요구(관심종목 메모·목표가, 월별·랭킹 통계, 균등 배분, 데이터 품질 확인)를 반영하고, 운영 중인 DB를 데이터 유지한 채 마이그레이션으로 바꾸는 흐름을 보여준다.
**D 선행 계약**: `004_watchlist_memo.sql`(memo·target_price) 마이그레이션과 schema 반영, `006_sector_freshness.sql`은 D 본인 작업.
**D 껍데기**(단계 시작 전 stage5에, `TODO(껍데기)` 주석): `services/data_quality.py`(C — 원본 시그니처, 예시 값 반환), `portfolio.py` preview_equal_weight + `portfolios.py` POST preview/equal-weight(C — `docs/06` 예시 응답), `watchlist.py` PUT(B — 예시 응답), stats_router monthly·ranking·data-quality(B — `docs/06` 예시 응답).
**머지·마감**: 순서 없음 — Ready PR은 도착하는 대로 머지한다. PR 마감 시각까지 Ready가 안 된 파일은 D가 인수한다(그전까지는 껍데기가 그대로 있어 앱은 정상 동작한다).
**PR 방식**: 파일마다 커밋·push, 파트 하나 = PR 하나로 끝나는 대로 D에게 넘긴다(CLAUDE.md 6절). 다른 팀원 브랜치는 받지 않는다. 다른 팀원 코드는 D가 미리 넣은 껍데기를 그대로 쓰고(✅ 있음), 내 파일의 껍데기는 본문을 원본대로 교체한다. 껍데기도 없을 때만 [연결 예정](CLAUDE.md 11절). 시니어는 자동 검사가 통과한 넘김 PR을 도착하는 대로 바로바로 머지한다.

---

## 팀원 B — 관심종목 메모·목표가 + 통계 확장

```
[역할] 너는 StockMind 팀 프로젝트에서 팀원 B(백엔드 API·DB, 주니어)의 페어 프로그래머다. 레포 루트 CLAUDE.md의 규칙을 반드시 따른다.
[이번 단계] Stage 5 — 고도화
[내 파트] 관심종목 PUT(메모·목표가·target_gap) → 월별 집계 → 지표별 랭킹 → 데이터 품질 API → 입력 검증 상한
[브랜치] feat/s5-b-memo-stats
[참조 원본] ../ax_class_stockmind/backend/app/api/{watchlist,analysis}.py, queries/{watchlist,stats_monthly,stats_ranking,stats_data_quality}.sql, docs/06 (PUT watchlist, statistics/monthly·ranking·data-quality) (읽기 전용)

[담당 파일 — 이 순서대로]
1. backend/app/queries/watchlist.sql + api/watchlist.py — PUT /watchlist/{market}/{ticker}: 보낸 필드만 변경, null이면 지움, 빈 본문 422, memo 200자, target_price > 0 소수 4자리. GET 응답에 memo·target_price·target_gap = (목표가 − 현재가) / 현재가
2. backend/app/queries/stats_monthly.sql + stats_router GET /statistics/monthly — date_trunc + GROUP BY, FIRST_VALUE/LAST_VALUE 윈도우, 진행 중인 달 is_partial
3. backend/app/queries/stats_ranking.sql + GET /statistics/ranking — RANK() OVER(같은 값 같은 순위 1,1,3), 지표값 없는 종목 제외, 전체+volume은 422 VOLUME_SORT_REQUIRES_MARKET
4. backend/app/queries/stats_data_quality.sql + GET /statistics/data-quality — C의 data_quality 서비스 호출(시그니처는 D의 껍데기 = 원본)
5. deps·schemas [S5-B] — 입력 검증 상한(limit·offset·q 길이 등 원본 A-112 기준)
6. backend/tests/test_watchlist_api.py·test_analysis.py 추가분

[파트별 확인 — 계획표의 "파트별 확인 지점"으로 그대로 쓴다. 파일마다 만든 직후 돌려 보고(CLAUDE.md 3절 ③), 파트가 끝날 때마다 실제로 실행해서 "여기까지 만든 것"을 보여 주고 아주 쉽게 설명한다(3-1)]
파트 1 (1번 PUT 메모·목표가) → 볼 것: curl PUT AAPL `{"memo":"테스트","target_price":250}` → GET에 target_gap. 현재가로 (250 − 현재가) ÷ 현재가를 손계산해 같은지 보여 준다. `{"memo":null}` → 지워짐, 빈 본문 → 422, memo 201자 → 422. 마지막에 원래대로 되돌린다.
파트 2 (2번 월별 집계) → 볼 것: curl monthly → 진행 중인 달 is_partial=true. psql로 한 달의 첫 종가·마지막 종가를 꺼내 응답 값과 같은지 비교.
파트 3 (3번 랭킹) → 볼 것: curl ranking?metric=return_1m&country=KR&limit=5. 같은 값이 있으면 1,1,3 순위를 짚어 준다. country 없이 volume → 422 VOLUME_SORT_REQUIRES_MARKET.
파트 4 (4번 데이터 품질 API — 테스트는 [연결 예정] D 연결 후) → 볼 것: ✅ C 서비스가 stage에 있으면 curl data-quality 응답 읽어 주기, 연결 예정이면 "D가 연결하면 볼 수 있어요" 한 줄.
파트 5 (5~6번 입력 검증 상한·테스트) → 볼 것: limit=100000, q 길이 초과 → 422 응답 모양. pytest -v 번역.

[건드리지 않을 파일] 마이그레이션·schema(D), services/data_quality.py·portfolio.py(C), frontend(A)
[인터페이스 계약] 응답은 원본 docs/06 해당 엔드포인트 예시와 같은 구조
[이번 단계에서 뺄 것] /stocks/search, listed 종목, home API, dps
[완료 기준]
  curl -X PUT .../watchlist/NASDAQ/AAPL -d '{"memo":"테스트","target_price":250}' → target_gap 포함 200, 이후 null로 되돌림
  curl ".../statistics/ranking?metric=return_1m&country=KR&limit=5"
  pytest -q

[선행 작업] 없음 — C의 data_quality 서비스는 D의 껍데기(원본 시그니처, 예시 값 반환)가 stage5에 있어 ✅ 그대로 쓴다. 1번 PUT, 2~4번 monthly·ranking·data-quality는 D의 껍데기가 들어 있으니 본문을 원본대로 교체한다.
[시작] ① CLAUDE.md 10절대로 최신 코드부터 받는다: git fetch → [브랜치]로 이동(없으면 origin/stage5에서 새로 만듦) → origin/stage5 합치기. 이동한 뒤 CLAUDE.md를 다시 읽고 그 규칙을 따른다(설명은 9절 입문자 기준, 다른 팀원 파일이 없으면 11절대로 묻지 않고 진행).
② CLAUDE.md 2절의 작업 계획표만 출력하라(파트별 확인 지점 포함). 코드는 내가 승인한 뒤 파일 하나씩 진행하고, 파일마다 만든 직후 실제로 돌려서 보여 주며(3절 ③), 파트가 끝날 때마다 "여기까지 만든 것"을 실행해 보여 준다(3-1).
```

---

## 팀원 C — 균등 배분 미리보기·데이터 품질 서비스

```
[역할] 너는 StockMind 팀 프로젝트에서 팀원 C(데이터 수집·분석 로직, 주니어)의 페어 프로그래머다. 레포 루트 CLAUDE.md의 규칙을 반드시 따른다.
[이번 단계] Stage 5 — 고도화
[내 파트] 균등 배분 계산 → 엔드포인트 → 데이터 품질 집계 서비스 → CLI status → 포트폴리오 가중 매력도 → 테스트
[브랜치] feat/s5-c-equal-weight-quality
[참조 원본] ../ax_class_stockmind/backend/app/services/{portfolio,data_quality}.py, api/portfolios.py, tests/{test_equal_weight,test_data_quality}.py, docs/06 (preview/equal-weight, data-quality) (읽기 전용)

[담당 파일 — 이 순서대로]
1. backend/app/services/portfolio.py — preview_equal_weight: 예산 ÷ 대상 수 = 균등 몫 → 1주 원화 원가로 내림한 정수 수량(담기 금액 모드와 같은 환산), 남는 금액, 제외 종목과 사유(ALREADY_IN_PORTFOLIO·NO_PRICE·PRICE_ABOVE_SHARE). **저장하지 않는 계산 전용**
2. backend/app/api/portfolios.py — POST /portfolios/{id}/preview/equal-weight (body 생략 시 관심종목 전체·잔여 시드, 관심종목 비면 422 EMPTY_WATCHLIST, 예산 > 잔여 409)
3. backend/app/services/portfolio.py summary — Stage 4에서 B가 요청한 가중 매력도(비중 가중 평균)
4. backend/app/services/data_quality.py — 작업 종류별 마지막 성공·실패(사유·티커), 최근 N일 상태별 건수, 격리 행 수, stale_jobs(작업 단위 성공이 TTL×2 초과)
5. backend/app/ingest/__main__.py — [S5-C] status 명령(같은 서비스 사용)
6. backend/tests/test_equal_weight.py, test_data_quality.py

[파트별 확인 — 계획표의 "파트별 확인 지점"으로 그대로 쓴다. 파일마다 만든 직후 돌려 보고(CLAUDE.md 3절 ③), 파트가 끝날 때마다 실제로 실행해서 "여기까지 만든 것"을 보여 주고 아주 쉽게 설명한다(3-1)]
파트 1 (1~2번 균등 배분 계산·엔드포인트) → 볼 것: curl POST preview/equal-weight → 종목별 수량·남는 돈·제외 종목과 사유. 한 종목은 "예산 ÷ 종목 수 ÷ 1주 원화 원가 → 내림" 손계산으로 같은지 확인. 호출 전후 psql로 portfolio_items 행 수가 그대로인 것(저장 안 하는 계산 전용)을 보여 준다. 관심종목이 비면 422, 예산 > 잔여 시드 → 409.
파트 2 (3번 가중 매력도) → 볼 것: summary 응답의 가중 매력도를 (비중 × 점수)의 합으로 손계산해 비교.
파트 3 (4~5번 데이터 품질 서비스·status 명령) → 볼 것: `python -m app.ingest status` 출력을 줄마다 풀이(마지막 성공·실패, 최근 N일 건수, 격리 행 수, stale_jobs). psql ingestion_logs와 숫자가 맞는지 1개 비교.
파트 4 (6번 테스트) → pytest -v 번역.

[건드리지 않을 파일] stats_data_quality.sql·analysis.py(B — B가 내 서비스를 호출), schema(D), frontend(A)
[인터페이스 계약]
- 제공: data_quality 서비스는 D의 껍데기 시그니처(원본) 그대로 — 바꾸지 않는다
[이번 단계에서 뺄 것] 섹터 히트맵·시장 심리 지수(Stage 6), listing
[완료 기준]
  curl -X POST .../portfolios/{id}/preview/equal-weight → 수량·제외 사유, DB에 변화 없음
  docker compose run --rm api python -m app.ingest status
  pytest -q tests/test_equal_weight.py tests/test_data_quality.py

[선행 작업] 없음 — 1·2번 equal-weight, 4번 data_quality.py는 D의 껍데기가 들어 있으니 본문을 원본대로 교체한다(시그니처는 그대로 — B가 이미 이 시그니처로 부르고 있다).
[시작] ① CLAUDE.md 10절대로 최신 코드부터 받는다: git fetch → [브랜치]로 이동(없으면 origin/stage5에서 새로 만듦) → origin/stage5 합치기. 이동한 뒤 CLAUDE.md를 다시 읽고 그 규칙을 따른다(설명은 9절 입문자 기준, 다른 팀원 파일이 없으면 11절대로 묻지 않고 진행).
② CLAUDE.md 2절의 작업 계획표만 출력하라(파트별 확인 지점 포함). 코드는 내가 승인한 뒤 파일 하나씩 진행하고, 파일마다 만든 직후 실제로 돌려서 보여 주며(3절 ③), 파트가 끝날 때마다 "여기까지 만든 것"을 실행해 보여 준다(3-1).
```

---

## 팀원 A — 편집·설정 UI

```
[역할] 너는 StockMind 팀 프로젝트에서 팀원 A(프론트엔드·사용자 경험, 주니어)의 페어 프로그래머다. 레포 루트 CLAUDE.md의 규칙을 반드시 따른다.
[이번 단계] Stage 5 — 고도화 화면
[내 파트] 메모·목표가 편집 → 지수·환율 표시 지표 설정 → 월별 요약 → 균등 배분 패널 → 홈 순위 상위 5 → 모바일 점검
[브랜치] feat/s5-a-edit-settings
[참조 원본] ../ax_class_stockmind/frontend/js/components/{watch-note,metric-picker}.js, js/pages/{home,stock,portfolio}.js, docs/screenshots/{06_mobile_home,07_mobile_stocks,08_mobile_portfolio}.png (읽기 전용) 스크린샷·원본 화면은 참고용 — 배치·디자인·문구 같은 표현은 A가 정해도 된다(CLAUDE.md 1절, PR "원본과 다르게 한 것"에 기록).

[담당 파일 — 이 순서대로]
1. frontend/js/api.js — [S5-A] 구역: putWatchlist·getMonthly·getRanking·previewEqualWeight
2. frontend/js/components/watch-note.js — 카드에서 메모·목표가 편집, 목표가 대비 괴리율 표시
3. frontend/js/components/metric-picker.js — 지수 10개 + 환율 중 표시할 지표 선택(localStorage, try/catch), 한 줄·넘치면 가로 스크롤
4. frontend/js/pages/stock.js — [S5-A] 월별 요약 표(최근 12개월, 진행 중인 달 표시)
5. frontend/js/pages/portfolio.js — [S5-A] 관심종목 균등 배분 미리보기 패널(제외 사유 표시, '모두 담기'로 연결)
6. frontend/js/pages/home.js — [S5-A] 순위 상위 5 (거래량·1개월·1년 수익률 × 국내/미국 탭)
7. 모바일(390px) 홈·리스트·포트폴리오 점검 — css/pages.css [S5-A]

[파트별 확인 — 계획표의 "파트별 확인 지점"으로 그대로 쓴다. 파일마다 만든 직후 돌려 보고(CLAUDE.md 3절 ③), 파트가 끝날 때마다 실제로 실행해서 "여기까지 만든 것"을 보여 주고 아주 쉽게 설명한다(3-1)]
파트 1 (1~2번 api.js·메모·목표가 편집) → 볼 것: 홈 관심종목 카드에서 메모·목표가 수정 → 새로고침해도 유지 → curl GET /watchlist에도 같은 값. 괴리율 표시를 손계산과 비교.
파트 2 (3번 지표 선택) → 볼 것: 지표를 골라 새로고침해도 유지, 개발자 도구 Application 탭 localStorage 값 보여 주기. 많이 고르면 한 줄 가로 스크롤.
파트 3 (4번 월별 요약) → 볼 것: 상세의 최근 12개월 표, 진행 중인 달 표시. curl monthly 값과 한 달 비교.
파트 4 (5번 균등 배분 패널) → 볼 것: 미리보기 → 제외 사유 표시 → '모두 담기' → 요약 갱신.
파트 5 (6~7번 순위·모바일) → 볼 것: 국내/미국 × 거래량·1개월·1년 탭 전환. 기기 모드 390px에서 홈·리스트·포트폴리오 가로 스크롤 없음. 화면별 스크린샷 안내.

[건드리지 않을 파일] backend/ 전부, 공통 css(D)
[이번 단계에서 뺄 것] 상단 검색, 섹터 히트맵·심리 지수, 홈 2열 개편
[완료 기준] 메모 수정 후 새로고침해도 유지 / 지표 설정 유지 / 균등 배분 '모두 담기' 후 요약 갱신 / 모바일 가로 스크롤 없음

[선행 작업] 없음 — B의 PUT watchlist·monthly·ranking, C의 equal-weight 미리보기는 D의 껍데기가 stage5에 있어 ✅ 그대로 쓴다. MOCK을 따로 만들지 않는다. 지금은 예시 값이 나오고, 담당자가 본문을 교체하면 같은 코드 그대로 진짜 값이 나온다.
[시작] ① CLAUDE.md 10절대로 최신 코드부터 받는다: git fetch → [브랜치]로 이동(없으면 origin/stage5에서 새로 만듦) → origin/stage5 합치기. 이동한 뒤 CLAUDE.md를 다시 읽고 그 규칙을 따른다(설명은 9절 입문자 기준, 다른 팀원 파일이 없으면 11절대로 묻지 않고 진행).
② CLAUDE.md 2절의 작업 계획표만 출력하라(파트별 확인 지점 포함). 코드는 내가 승인한 뒤 파일 하나씩 진행하고, 파일마다 만든 직후 실제로 돌려서 보여 주며(3절 ③), 파트가 끝날 때마다 "여기까지 만든 것"을 실행해 보여 준다(3-1).
```

---

## 팀원 D(시니어) — 업종 섹터·유효기간·헬스체크

```
시니어 모드. Stage 5.
[PR] 파트 단위로 넘어온(Ready) PR을 자동 검사 통과 확인 후 도착하는 대로 당일 머지하고, 팀 채팅에 알린다. 진행 중(Draft) PR은 코드만 미리 본다. 받은 요청 메모는 추천안에 OK/다른 지시만 답한다.
[마감] PR 마감 시각에 stage5에서 `git grep -n "TODO(껍데기)"`로 남은 껍데기를 본다. 남은 파일은 D가 인수한다 — 담당자 브랜치의 끝난 커밋까지 머지하고 나머지를 D가 작성한다. 시간이 모자라면 껍데기 그대로 태그를 달고 다음 단계를 연다(앱은 정상 동작). 인수 내역(파일·원래 담당·사유·상태)은 stage5 → main PR 본문 "인수 파트"에 적고, 인수분은 끝나는 대로 stage5에 머지한 뒤 다음 stage로 합친다.
[연결 예정 처리] 마감 후 stage에서 `git grep -n "TODO(연결)"` → 각 PR의 "연결 예정 목록"대로 연결(import를 원본처럼 맨 위로, MOCK 제거, 목록의 테스트 추가) → `pytest -q`·`python team/tools/check_contract.py 5` 통과 → 아래 통합으로.
[선행] 004_watchlist_memo.sql + schema·ORM + 머리말의 "D 껍데기" 전부(`TODO(껍데기): {담당} — {무엇}` 주석, 이름·인자·응답 모양은 원본 그대로) → `pytest -q` 통과 → 커밋 후 배포. 마이그레이션 적용 시연: 기존 DB에 `python -m app.ingest migrate 004_watchlist_memo`.
[내 구현]
1. 006_sector_freshness.sql(+schema: peer_groups.kind, stocks.industry·sic, data_freshness, fundamental_bases)
2. backend/app/ingest/sectors.py(KRX 업종·SIC → 섹터), benchmark 섹터 계층, scoring 중립화가 업종 섹터를 쓰도록 C와 합의
3. backend/app/services/freshness.py — 재무 유효기간·사업보고서 공시 시 무효화, B의 load_financials와 연결
4. /health/db 503(연결 시간 제한), 컨테이너 HEALTHCHECK 교체, 500 응답 요청 ID 유지, 입력 검증 상한 리뷰
5. backend/tests/{test_freshness,test_health}.py, docs/architecture.md
[통합] 마감·인수 후 migrate 004·006 → benchmark --reselect → scores → 화면 확인 → stage5 → main, 태그 v5.0
```
