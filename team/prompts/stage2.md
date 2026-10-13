# Stage 2 — 사용자 기능: 관심종목·모의 포트폴리오 CRUD

**단계 목표**: 단일 데모 사용자가 관심종목을 추가·정렬·삭제하고, 시드 안에서 국내·미국 종목을 담아 원화 기준 평가손익(환율 효과 분리)을 본다.
**D 선행 계약(단계 시작 전 커밋됨)**: `users`·`watchlist_items`(memo·target_price 없음)·`portfolios`·`portfolio_items` 테이블과 ORM, `deps.get_current_user_id()`, `providers/base.py` 보강(FxProvider는 Stage 1-D에 있음 — Bar·FxPoint를 preprocess에서 base로 이동).
**머지 순서**: C → B → A → D 통합
**PR 방식**: 앞 순서 작업이 머지되기 전에 끝나면 기다리지 않고 Draft PR → 시니어가 그 파트를 먼저 리뷰 → 앞 순서 머지 후 최신 stage를 합쳐 같은 PR을 Ready로 전환(CLAUDE.md 6절). 시니어는 Ready PR만 머지 순서대로 머지한다.

---

## 팀원 C — 환율 서비스·모의 포트폴리오

```
[역할] 너는 StockMind 팀 프로젝트에서 팀원 C(데이터 수집·분석 로직, 주니어)의 페어 프로그래머다. 레포 루트 CLAUDE.md의 규칙을 반드시 따른다.
[이번 단계] Stage 2 — 사용자 기능. 모의 포트폴리오는 "시드 안에서 담아보는 계산기 겸 장바구니"다(거래 원장 아님).
[내 파트] 환율 TTL 서비스 → 포트폴리오 계산 서비스 → 포트폴리오 API → 테스트
[브랜치] feat/s2-c-portfolio
[참조 원본] ../ax_class_semiproject/backend/app/services/{fx,portfolio}.py, api/portfolios.py, docs/06 3-5, docs/05 5-1(의도적 비정규화) (읽기 전용)

[담당 파일 — 이 순서대로]
1. backend/app/services/__init__.py, backend/app/services/fx.py — FxService: TTL(4시간) 안이면 DB값, 지났으면 provider 호출, 실패 시 마지막 저장값 + fx_stale, 저장값도 없으면 503 FX_UNAVAILABLE.
   이번 단계는 실제 provider가 없다 → providers/base.py의 FxProvider 인터페이스에 맞추고, 런타임에는 '항상 실패하는 provider'를 주입해 저장값으로 동작. (실제 연결은 Stage 3)
2. backend/app/services/portfolio.py — q()(Decimal 반올림), RefQuote(1주 원화 원가), quantity_for(quantity/amount/weight 모드 → 정수 수량), PortfolioService(create·list·get·update·delete·add_item·update_item·delete_item·valued_items·summary)
   - 담는 시점의 ref_price·ref_fx_rate·ref_date를 항목에 복사 저장(의도적 비정규화 — 이유를 설계 설명에 꼭 포함)
   - 시드 초과 409 SEED_EXCEEDED(+최대 수량), 수량 0이면 422 QUANTITY_ZERO, 이름 중복 409
   - summary: 사용·잔여·비중·평가손익을 가격 효과/환율 효과로 분리
3. backend/app/queries/portfolio_items_valued.sql — 항목별 현재가·현재 환율 평가
4. backend/app/api/portfolios.py — 원본 엔드포인트 중 preview/equal-weight 제외 전부. 소유자 확인은 deps.get_current_user_id 사용
5. backend/app/schemas/api.py — [S2-C] 구역, backend/app/main.py — [S2-C] 라우터 등록
6. backend/app/api/market.py — [S2-C] 구역: GET /market/fx를 FxService로 교체 (B의 기존 코드는 이 엔드포인트만 교체, 나머지 건드리지 않음)
7. backend/tests/test_fx_service.py, backend/tests/test_portfolio.py

[건드리지 않을 파일] schema.sql·models·deps의 get_current_user_id(D), watchlist(B), frontend(A)
[인터페이스 계약]
- 사용: portfolios·portfolio_items 테이블, v_latest_price·v_fx_latest(B), get_current_user_id(D)
- 제공: /api/v1/portfolios/* 응답 = 원본 docs/06 3-5 예시 형태(가중 매력도 필드는 null). A가 이 형태로 화면 개발
[이번 단계에서 뺄 것] preview_equal_weight, 가중 매력도 계산, watchlist 관련 코드
[완료 기준]
  docker compose run --rm api pytest -q tests/test_portfolio.py tests/test_fx_service.py
  curl로: 포트폴리오 생성 → amount 모드로 NASDAQ/AAPL 담기 → 시드 초과 409 → summary에 환율 효과 필드

[선행 작업] 없음 — D의 선행 계약과 Stage 1 결과물(v_latest_price·v_fx_latest·market.py)은 이미 stage2에 있다. 머지 순서 1번이므로 끝나면 바로 Ready PR.
[시작] ① CLAUDE.md 10절대로 최신 코드부터 받는다: git fetch → [브랜치]로 이동(없으면 origin/stage2에서 새로 만듦) → origin/stage2 합치기. 이동한 뒤 CLAUDE.md를 다시 읽고 그 규칙을 따른다(설명은 9절 입문자 기준, 다른 팀원 파일이 없으면 11절대로 묻지 않고 진행).
② CLAUDE.md 2절의 작업 계획표만 출력하라. 코드는 내가 승인한 뒤 파일 하나씩 진행한다.
```

---

## 팀원 B — 관심종목 CRUD

```
[역할] 너는 StockMind 팀 프로젝트에서 팀원 B(백엔드 API·DB, 주니어)의 페어 프로그래머다. 레포 루트 CLAUDE.md의 규칙을 반드시 따른다.
[이번 단계] Stage 2 — 사용자 기능
[내 파트] 관심종목 조회 SQL → API(GET·POST·PATCH order·DELETE) → 테스트
[브랜치] feat/s2-b-watchlist
[참조 원본] ../ax_class_semiproject/backend/app/api/watchlist.py, queries/watchlist.sql, tests/test_watchlist_api.py, docs/06 3-4 (읽기 전용)

[담당 파일 — 이 순서대로]
1. backend/app/queries/watchlist.sql — 사용자 관심종목 카드(정렬순, 최신가·등락). 매력도·메모·목표가·target_gap 컬럼 제외
2. backend/app/schemas/api.py — [S2-B] 구역 (WatchlistItemOut, WatchlistAddIn, WatchlistOrderIn)
3. backend/app/api/watchlist.py — GET /watchlist, POST /watchlist(중복 409 DUPLICATE_WATCHLIST), PATCH /watchlist/order, DELETE /watchlist/{market}/{ticker}
   - 모든 핸들러는 deps.get_current_user_id()로 사용자 확정 (요청에 user_id 받지 않음)
4. backend/app/main.py — [S2-B] 라우터 등록
5. backend/tests/test_watchlist_api.py — 추가·중복·정렬·삭제·없는 종목 404

[건드리지 않을 파일] schema.sql·models·get_current_user_id(D), portfolio·fx(C), frontend(A)
[인터페이스 계약]
- 사용: watchlist_items 테이블, get_current_user_id(D), resolve_stock(S1)
- 제공: /api/v1/watchlist 응답 = 원본 docs/06 3-4 예시에서 score·memo·target_price·target_gap 제외
[이번 단계에서 뺄 것] PUT(메모·목표가) — Stage 5, preset 파라미터·매력도, 비교군 상세 수집 예약(hydration)
[완료 기준]
  docker compose run --rm api pytest -q tests/test_watchlist_api.py
  curl POST /api/v1/watchlist {"market":"KOSPI","ticker":"005930"} → 201, 같은 요청 → 409

[선행 작업] 코드상 기다릴 것 없음(머지 순서만 C 다음). C(feat/s2-c-portfolio)가 머지 전이면 Draft PR → C 머지 후 최신 stage2를 합치고 테스트 재실행 → Ready. schemas/api.py·main.py 충돌은 서로 다른 구역이므로 둘 다 남긴다.
[시작] ① CLAUDE.md 10절대로 최신 코드부터 받는다: git fetch → [브랜치]로 이동(없으면 origin/stage2에서 새로 만듦) → origin/stage2 합치기. 이동한 뒤 CLAUDE.md를 다시 읽고 그 규칙을 따른다(설명은 9절 입문자 기준, 다른 팀원 파일이 없으면 11절대로 묻지 않고 진행).
② CLAUDE.md 2절의 작업 계획표만 출력하라. 코드는 내가 승인한 뒤 파일 하나씩 진행한다.
```

---

## 팀원 A — 관심 토글·담기 모달·포트폴리오 화면

```
[역할] 너는 StockMind 팀 프로젝트에서 팀원 A(프론트엔드·사용자 경험, 주니어)의 페어 프로그래머다. 레포 루트 CLAUDE.md의 규칙을 반드시 따른다.
[이번 단계] Stage 2 — 사용자 기능 화면
[내 파트] api.js 확장 → ★ 관심 토글 → 담기 모달 → 포트폴리오 페이지 → 홈 관심종목 카드
[브랜치] feat/s2-a-user-screens
[참조 원본] ../ax_class_semiproject/frontend/js/components/{watch,add-to-portfolio}.js, js/pages/portfolio.js, docs/screenshots/{05_portfolio,09_add_modal,08_mobile_portfolio}.png, docs/06 3-4·3-5 (읽기 전용)

[담당 파일 — 이 순서대로]
1. frontend/js/api.js — [S2-A] 구역: watchlist·portfolios 호출 함수
2. frontend/js/components/watch.js — ★ 토글(낙관적 업데이트, 실패 시 되돌림)
3. frontend/js/components/add-to-portfolio.js — 담기 모달: 포트폴리오 선택, 수량/금액/비중 모드, 미리보기(예상 수량·원화 금액), 409 시드 초과 시 최대 수량 안내
4. frontend/portfolio.html + frontend/js/pages/portfolio.js — 포트폴리오 목록·생성·시드 수정·삭제, 항목 표(수정·삭제), 요약(사용·잔여·평가손익·환율 효과), 비중 차트
5. frontend/js/pages/stocks.js·stock.js — [S2-A] 구역에 ★·담기 버튼 연결
6. frontend/js/pages/home.js — [S2-A] 구역에 관심종목 카드(가격·등락) + 정렬 변경
7. frontend/css/pages.css — [S2-A] 구역

[건드리지 않을 파일] backend/ 전부, 공통 css(D)
[인터페이스 계약]
- 사용: /api/v1/watchlist*, /api/v1/portfolios* (B·C가 아직이면 docs/06 예시로 MOCK)
- USD 종목은 원화 환산값을 서버가 주므로 화면에서 환율 계산하지 않는다
[이번 단계에서 뺄 것] 매력도 게이지, 메모·목표가 편집(watch-note), 균등 배분 미리보기, 순위표
[완료 기준]
  리스트 ★ → 홈 카드 표시 → 정렬 변경 유지 → 포트폴리오 생성 → USD 종목 금액 모드 담기 → 시드 초과 메시지 → 요약 갱신
  모바일 폭(390px)에서 포트폴리오 페이지 가로 스크롤 없음

[선행 작업] B(feat/s2-b-watchlist)의 /watchlist, C(feat/s2-c-portfolio)의 /portfolios. 아직 없으면 docs/06 3-4·3-5 예시로 MOCK 하고 묻지 말고 진행한다. B·C 머지 전이면 Draft PR → 머지 후 MOCK 제거·완료 기준 실행 → Ready.
[시작] ① CLAUDE.md 10절대로 최신 코드부터 받는다: git fetch → [브랜치]로 이동(없으면 origin/stage2에서 새로 만듦) → origin/stage2 합치기. 이동한 뒤 CLAUDE.md를 다시 읽고 그 규칙을 따른다(설명은 9절 입문자 기준, 다른 팀원 파일이 없으면 11절대로 묻지 않고 진행).
② CLAUDE.md 2절의 작업 계획표만 출력하라. 코드는 내가 승인한 뒤 파일 하나씩 진행한다.
```

---

## 팀원 D(시니어) — 사용자 확정·소유자 검사·데모

```
시니어 모드. Stage 2.
[PR] Draft PR은 코드 리뷰만 한다. Ready로 바뀐 PR을 머지 순서대로 머지하고, 머지할 때마다 다음 순서 팀원에게 알린다(그쪽 Claude가 동기화 중 머지를 감지해 Ready 전환을 시작한다).
[선행] stage2 브랜치는 stage1 머지·팀 키트(CLAUDE.md 9~11절) 수정이 모두 들어간 main에서 만든다. schema.sql·models에 users·watchlist_items(memo·target_price 제외)·portfolios·portfolio_items, deps.get_current_user_id, providers/base.py → stage2에 커밋 후 프롬프트 배포.
[통합 중]
1. backend/app/ingest/demo.py + CLI seed-demo (데모 사용자·관심종목·포트폴리오)
2. 소유자 검사: 남의 포트폴리오·항목 접근 시 404 — backend/tests/test_ownership.py, test_current_user.py
3. 에러 코드 표(docs/06 5절)에 Stage 2 코드 추가, docs/05 사용자 테이블·비정규화 절
4. 통합 시나리오 수동 실행 → stage2 → main, 태그 v2.0
```
