# Stage 6 — 홈 대시보드 개편·상단 검색·마감 (= 원본 완성본)

**단계 목표**: 홈을 2열 대시보드(검색바·투자 성향 한 줄 → 관심종목 컴팩트 + 섹터 히트맵·시장 심리 지수 → 거래량 급증/매력도 순위 탭)로 개편하고, 상장 종목 전체를 상단 검색으로 찾을 수 있게 한다. 홈 위젯은 DB에 저장해 재사용(외부 호출 최소화).
**D 선행 계약**: `005_listed_dividend.sql`(coverage 'listed', valuation_snapshots.dps)·`007_home_widgets.sql`(sector_performance_daily, market_sentiment_daily) + schema 반영. `be/app/api/home.py` 라우터 뼈대(`/home` prefix, 구역 주석)를 먼저 커밋.
**머지 순서**: C → B → A → D 마감
**PR 방식**: 파일마다 커밋·push, 파트 하나 = PR 하나로 끝나는 대로 D에게 넘긴다(CLAUDE.md 6절). 다른 팀원 브랜치는 받지 않는다. stage에 없는 다른 팀원 코드는 원본과 같은 이름으로 🔌 나중에 연결(CLAUDE.md 11절)로 두고, 연결은 D가 단계 통합 때 한다. 시니어는 자동 검사가 통과한 넘김 PR을 머지 순서대로 바로바로 머지한다.

---

## 팀원 C — 섹터 히트맵·시장 심리 지수

```
[역할] 너는 StockMind 팀 프로젝트에서 팀원 C(데이터 수집·분석 로직, 주니어)의 페어 프로그래머다. 레포 루트 CLAUDE.md의 규칙을 반드시 따른다.
[이번 단계] Stage 6 — 홈 위젯 데이터. 계산 결과는 DB에 저장하고 홈은 저장값을 읽는다.
[내 파트] 섹터 등락 수집·저장 → 시장 심리 지수 계산·저장 → 홈 순위 보조 → 엔드포인트 → 테스트
[브랜치] feat/s6-c-home-widgets
[참조 원본] ../ax_class_semiproject/backend/app/services/{sectors,sentiment,home_ranking}.py, api/home.py(/sectors·/sentiment), db/migrations/007_home_widgets.sql, tests/test_home_widgets.py (읽기 전용)

[담당 파일 — 이 순서대로]
1. backend/app/services/sectors.py — 미국 섹터 ETF(XLK…)·KRX 섹터 지수 등락 수집(load_sectors), 30일 지난 행 정리, read_sectors. 가중치는 코드 상수(테이블에 저장 안 하는 이유를 설계 설명에)
2. backend/app/services/sentiment.py — 간이 시장 심리 지수: 지수 RSI·이동평균 괴리·VIX 등 → 0~100, label_for, ensure_sentiment(없는 날만 계산해 저장), get_sentiment
3. backend/app/services/home_ranking.py — 순위 탭 공통 유틸
4. backend/app/api/home.py — [S6-C] 구역: GET /home/sectors, GET /home/sentiment (+ schemas [S6-C])
5. refresh 작업 연결 — 요청 메모 → D (섹터·심리 지수 갱신을 4시간 갱신 흐름에 넣기)
6. backend/tests/test_home_widgets.py

[파트별 확인 — 계획표의 "파트별 확인 지점"으로 그대로 쓴다. 파일마다 만든 직후 돌려 보고(CLAUDE.md 3절 ③), 파트가 끝날 때마다 실제로 실행해서 "여기까지 만든 것"을 보여 주고 아주 쉽게 설명한다(3-1)]
파트 1 (1번 섹터) → 볼 것: load_sectors 실행 → psql로 sector_performance_daily 최근 행(섹터·등락률), read_sectors 출력. 30일 지난 행 정리 전후 행 수.
파트 2 (2번 심리 지수) → 볼 것: ensure_sentiment 두 번 실행 → 두 번째는 '이미 있음'으로 계산하지 않는 로그. 점수와 label_for 결과(예: 62 → '탐욕')를 구성 요소 값과 함께 풀이.
파트 3 (3~4번 순위 유틸·API) → 볼 것: curl `/home/sectors?country=US`, `/home/sentiment?market=KR`. 같은 호출 두 번 → ingestion_logs 행 수가 그대로(외부 호출 없음)인 것을 psql로.
파트 4 (6번 테스트) → pytest -v 번역.

[건드리지 않을 파일] 007 마이그레이션·schema(D), home.py /ranking(B), frontend(A)
[인터페이스 계약] 응답 구조는 원본 home.py·schemas와 동일 — A가 MOCK으로 먼저 개발
[완료 기준]
  curl localhost:8000/api/v1/home/sectors?country=US · /home/sentiment?market=KR
  두 번째 호출은 외부 호출 없음(ingestion_logs 확인) / pytest -q tests/test_home_widgets.py

[선행 작업] 없음 — 007 마이그레이션·home.py 뼈대(D 계약)는 이미 stage6에 있다. 머지 순서 1번이다.
[시작] ① CLAUDE.md 10절대로 최신 코드부터 받는다: git fetch → [브랜치]로 이동(없으면 origin/stage6에서 새로 만듦) → origin/stage6 합치기. 이동한 뒤 CLAUDE.md를 다시 읽고 그 규칙을 따른다(설명은 9절 입문자 기준, 다른 팀원 파일이 없으면 11절대로 묻지 않고 진행).
② CLAUDE.md 2절의 작업 계획표만 출력하라(파트별 확인 지점 포함). 코드는 내가 승인한 뒤 파일 하나씩 진행하고, 파일마다 만든 직후 실제로 돌려서 보여 주며(3절 ③), 파트가 끝날 때마다 "여기까지 만든 것"을 실행해 보여 준다(3-1).
```

---

## 팀원 B — 상장 목록·상단 검색·홈 순위 API

```
[역할] 너는 StockMind 팀 프로젝트에서 팀원 B(백엔드 API·DB, 주니어)의 페어 프로그래머다. 레포 루트 CLAUDE.md의 규칙을 반드시 따른다.
[이번 단계] Stage 6 — 검색·홈 순위
[내 파트] 상장 목록 동기화 → 참고 점수 → 검색 SQL·API → 배당 지표 → 홈 순위 API → 테스트
[브랜치] feat/s6-b-search-ranking
[참조 원본] ../ax_class_semiproject/backend/app/ingest/listing.py, services/reference_score.py, queries/{stock_search,home_volume_surge,home_attractiveness}.sql, api/{stocks,home,analysis}.py, tests/{test_listing,test_home_api}.py, docs/06 /stocks/search (읽기 전용)

[담당 파일 — 이 순서대로]
1. backend/app/ingest/listing.py + __main__.py [S6-B] listing — 국내·미국 상장 보통주 목록 동기화(coverage='listed'), corp_code 매핑, 상장폐지 비활성
2. backend/app/services/reference_score.py + analysis.py [S6-B] — listed 종목 참고 점수(reference: true, reference_note, z_adj null, 순위는 비교군 N개 + 이 종목)
3. backend/app/queries/stock_search.sql + GET /stocks/search — 이름·영문명·티커 부분 일치, 정렬(티커 완전 일치 → 티커 앞 → 이름 앞 → 부분, 같으면 노출·비교군 먼저·짧은 이름 먼저), LIKE 특수문자 이스케이프
4. views.sql [S6-B] — v_stock_metrics 끝에 dps·dividend_yield 열 추가(CREATE OR REPLACE VIEW는 끝에만 추가 가능 — 이유를 설명), analysis 응답에 배당
5. backend/app/queries/home_volume_surge.sql, home_attractiveness.sql + home.py [S6-B] GET /home/ranking
6. backend/tests/test_listing.py, test_home_api.py

[파트별 확인 — 계획표의 "파트별 확인 지점"으로 그대로 쓴다. 파일마다 만든 직후 돌려 보고(CLAUDE.md 3절 ③), 파트가 끝날 때마다 실제로 실행해서 "여기까지 만든 것"을 보여 주고 아주 쉽게 설명한다(3-1)]
파트 1 (1번 상장 목록) → 볼 것: `python -m app.ingest listing` 소요 시간과 결과 → psql로 coverage별(노출·비교군·listed) 종목 수.
파트 2 (2번 참고 점수) → 볼 것: listed 종목 하나로 curl analysis → reference=true·reference_note, 순위가 '비교군 N개 + 이 종목' 기준인 것.
파트 3 (3번 검색) → 볼 것: curl search?q=삼성, ?q=AAPL, ?q=% — 결과 순서를 정렬 규칙 하나하나와 짝지어 설명. %가 '아무거나'로 해석되지 않는 것(이스케이프).
파트 4 (4번 배당 열) → 볼 것: psql로 v_stock_metrics의 dps·dividend_yield, analysis 응답의 배당. 열을 끝에만 추가해야 하는 이유를 실제로 중간에 넣으면 나는 에러 메시지로 보여 준다(트랜잭션 안에서 시도 후 ROLLBACK).
파트 5 (5번 홈 순위) → 볼 것: curl /home/ranking — 거래량 급증·매력도 순위 읽어 주기.
파트 6 (6번 테스트) → pytest -v 번역.

[건드리지 않을 파일] 005 마이그레이션·schema(D), home.py /sectors·/sentiment(C), frontend(A)
[완료 기준]
  docker compose run --rm api python -m app.ingest listing   (약 10초)
  curl "localhost:8000/api/v1/stocks/search?q=삼성" · "?q=AAPL" → 정렬 규칙대로
  curl localhost:8000/api/v1/home/ranking / pytest -q

[선행 작업] 코드상 기다릴 것 없음(머지 순서만 C 다음). home.py는 C와 구역이 다르므로 충돌 시 둘 다 남긴다.
[시작] ① CLAUDE.md 10절대로 최신 코드부터 받는다: git fetch → [브랜치]로 이동(없으면 origin/stage6에서 새로 만듦) → origin/stage6 합치기. 이동한 뒤 CLAUDE.md를 다시 읽고 그 규칙을 따른다(설명은 9절 입문자 기준, 다른 팀원 파일이 없으면 11절대로 묻지 않고 진행).
② CLAUDE.md 2절의 작업 계획표만 출력하라(파트별 확인 지점 포함). 코드는 내가 승인한 뒤 파일 하나씩 진행하고, 파일마다 만든 직후 실제로 돌려서 보여 주며(3절 ③), 파트가 끝날 때마다 "여기까지 만든 것"을 실행해 보여 준다(3-1).
```

---

## 팀원 A — 홈 개편·상단 검색

```
[역할] 너는 StockMind 팀 프로젝트에서 팀원 A(프론트엔드·사용자 경험, 주니어)의 페어 프로그래머다. 레포 루트 CLAUDE.md의 규칙을 반드시 따른다.
[이번 단계] Stage 6 — 홈 대시보드 개편. 원본 최종 홈 화면(docs/screenshots/01_home.png)의 기능(위젯 구성)을 갖추는 것이 목표다. 배치·디자인은 참고하되 A가 정해도 된다.
[내 파트] 검색 컴포넌트 → 홈 레이아웃 2열 → 관심종목 컴팩트/카드 → 섹터 히트맵 → 시장 심리 지수 → 순위 탭 → 지수 카드 다듬기
[브랜치] feat/s6-a-home-redesign
[참조 원본] ../ax_class_semiproject/frontend/js/components/search.js, js/pages/home.js, index.html, css/pages.css, docs/screenshots/{01_home,06_mobile_home}.png (읽기 전용) 스크린샷·원본 화면은 참고용 — 배치·디자인·문구 같은 표현은 A가 정해도 된다(CLAUDE.md 1절, PR "원본과 다르게 한 것"에 기록).

[담당 파일 — 이 순서대로]
1. frontend/js/api.js — [S6-A] 구역: searchStocks·getHomeRanking·getSectors·getSentiment
2. frontend/js/components/search.js — 상단 검색 자동완성(디바운스, 키보드 이동, listed 종목은 '참고' 표시)
3. frontend/index.html + home.js — 최상단 한 줄: 검색바 + 투자 성향, 2열 배치
4. home.js — 관심종목 컴팩트 행 기본, 카드 보기 전환(2줄 제한), 등락 색 통일
5. home.js — 우측: 섹터 히트맵(섹터 단위), 시장 심리 지수 게이지
6. home.js — 하단 순위 탭: 거래량 급증 / 매력도
7. home.js — 지수 카드: 휴장 달력 기반 장 상태 배지(D의 market_calendar 응답 필드), 52주 범위
8. css/pages.css [S6-A], 모바일 1열 전환

[파트별 확인 — 계획표의 "파트별 확인 지점"으로 그대로 쓴다. 파일마다 만든 직후 돌려 보고(CLAUDE.md 3절 ③), 파트가 끝날 때마다 실제로 실행해서 "여기까지 만든 것"을 보여 주고 아주 쉽게 설명한다(3-1)]
파트 1 (1~2번 api.js·상단 검색) → 볼 것: 검색창에 '삼성' 입력 → 자동완성, 방향키·Enter 이동, listed 종목 '참고' 표시. Network 탭에서 글자마다가 아니라 멈춘 뒤 1번만 요청이 나가는 것(디바운스)을 보여 준다.
파트 2 (3~4번 2열 배치·관심종목 컴팩트) → 볼 것: 원본 docs/screenshots/01_home.png와 나란히 놓고 기능이 다 있는지 체크(배치가 다른 건 의도라면 PR "원본과 다르게 한 것"에 기록). 컴팩트 ↔ 카드 전환.
파트 3 (5~6번 히트맵·심리 지수·순위 탭) → 볼 것: 섹터 색이 등락률과 맞는지 curl /home/sectors 값과 비교, 게이지 값, 탭 전환.
파트 4 (7~8번 지수 카드·CSS·모바일) → 볼 것: 장 상태 배지·52주 범위, 기기 모드 390px에서 1열. 검색에서 listed 종목 클릭 → 상세 '데이터 수집 중' 안내. 화면별 스크린샷 안내.

[건드리지 않을 파일] backend/ 전부, 공통 css(D)
[완료 기준] 원본 01_home.png와 레이아웃 일치 / 검색에서 상장 목록 종목 클릭 → 상세(데이터 수집 중 안내) / 모바일 1열 / 콘솔 에러 0

[선행 작업] C의 /home/sectors·/home/sentiment, B의 /stocks/search·/home/ranking, D의 market_calendar 응답 필드(7번). stage에 없으면 🔌 나중에 연결(CLAUDE.md 11절) — 원본 home.py·schemas 응답 모양으로 MOCK 하고 묻지 말고 진행한다(`TODO(연결)` 표시, D가 연결).
[시작] ① CLAUDE.md 10절대로 최신 코드부터 받는다: git fetch → [브랜치]로 이동(없으면 origin/stage6에서 새로 만듦) → origin/stage6 합치기. 이동한 뒤 CLAUDE.md를 다시 읽고 그 규칙을 따른다(설명은 9절 입문자 기준, 다른 팀원 파일이 없으면 11절대로 묻지 않고 진행).
② CLAUDE.md 2절의 작업 계획표만 출력하라(파트별 확인 지점 포함). 코드는 내가 승인한 뒤 파일 하나씩 진행하고, 파일마다 만든 직후 실제로 돌려서 보여 주며(3절 ③), 파트가 끝날 때마다 "여기까지 만든 것"을 실행해 보여 준다(3-1).
```

---

## 팀원 D(시니어) — 장 상태·최종 마감

```
시니어 모드. Stage 6 마감.
[PR] 파트 단위로 넘어온(Ready) PR을 자동 검사 통과 확인 후 머지 순서대로 당일 머지하고, 팀 채팅에 알린다. 진행 중(Draft) PR은 코드만 미리 본다. 받은 요청 메모는 추천안에 OK/다른 지시만 답한다.
[🔌 연결] 이 단계 PR이 모두 머지되면 stage에서 `git grep -n "TODO(연결)"` → 각 PR의 "🔌 연결 목록"대로 연결(import를 원본처럼 맨 위로, MOCK 제거, 목록의 테스트 추가) → `pytest -q`·`python team/tools/check_contract.py 6` 통과 → 아래 통합으로.
[선행] 005·007 마이그레이션 + schema, home.py 뼈대 → 커밋 후 배포.
[내 구현]
1. backend/app/services/market_calendar.py — exchange-calendars 기반 장 상태, /market/indices 응답에 추가
2. refresh에 섹터·심리 지수 연결(C 요청), sample.py export_sample, ingest/smoke.py
3. 문서: docs 01~09·ASSUMPTIONS·explain_result·smoke_test_result·07 테스트 결과서·08 최종 결과보고서, README, 스크린샷 재촬영
4. 최종 확인: diff -r --exclude=.git ../ax_class_semiproject . → 차이 0(또는 문서 표현 차이만)
5. 새 환경에서 README "5분 시작하기" 그대로 재현 → stage6 → main, 태그 v6.0
```
