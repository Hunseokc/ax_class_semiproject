# Stage 1 — MVP: 실제 시세 수집 + 리스트·상세·지수

**단계 목표**: pykrx·yfinance로 실제 시세(일봉)·지수·환율을 수집해 DB에 넣고(수집이 안 되면 `backend/sample_data/*.csv`로 대체), 주식 리스트·종목 상세·홈 지수 카드가 실제 DB 데이터를 보여준다.
**병렬 개발 방법**: B·A는 C를 기다리지 않는다. B는 테스트용 픽스처(conftest)로, A는 원본 `docs/06` 3-1·3-2의 예시 JSON을 목 데이터로 먼저 개발한다.
**머지 순서**: C → D(수집) → B → A → D 통합
**범위 변경(10/13)**: 실제 시세 수집(시세·지수·환율)을 Stage 3에서 당겨 D가 맡는다. C의 전처리·저장 함수(clean_bars·clean_fx·upsert·job_log)를 그대로 쓴다. 재무·밸류에이션 수집, 4시간 갱신, advisory lock은 Stage 3 유지. B의 API는 계속 DB만 조회한다.

---

## 팀원 C — 유니버스·샘플 데이터 적재

```
[역할] 너는 StockMind 팀 프로젝트에서 팀원 C(데이터 수집·분석 로직, 주니어)의 페어 프로그래머다. 레포 루트 CLAUDE.md의 규칙을 반드시 따른다.
[이번 단계] Stage 1 — MVP. 외부 API 없이 CSV 샘플만으로 DB를 채운다.
[내 파트] 유니버스 설정 → 마스터 적재(오프라인) → 전처리 → 샘플 CSV 적재 CLI
[브랜치] feat/s1-c-sample-ingest
[참조 원본] ../ax_class_semiproject/backend/ (읽기 전용)

[담당 파일 — 이 순서대로]
1. backend/config/universe.yaml — 원본에서 markets·indices(10개)·fx·stocks(노출 25종목)·peer_groups(테마 그룹)만. 비교군(benchmark) 후보 목록은 뺀다.
2. backend/app/ingest/__init__.py, backend/app/ingest/universe.py — YAML을 읽어 데이터클래스로 돌려주는 로더
3. backend/app/ingest/preprocess.py — 일봉·환율 정제(중복 제거, 이상 행 격리 + 사유). 원본 clean_bars·clean_fx 기준
4. backend/app/ingest/store.py — upsert(ON CONFLICT), job_log(ingestion_logs 1행 기록), 격리 CSV 저장. advisory_lock은 Stage 3이니 뺀다
5. backend/app/ingest/jobs.py — init_db(schema.sql·views.sql·indexes.sql 실행), load_master(offline=True 경로만: markets·stocks·indices·peer_groups 적재)
6. backend/app/ingest/sample.py — import_sample만 (export_sample은 Stage 6)
7. backend/sample_data/{stocks,daily_prices,index_daily_prices,fx_rates,valuation_snapshots}.csv — 원본 CSV에서 Stage 1 스키마 컬럼만
8. backend/app/ingest/__main__.py — 하위 명령 init-db, master --offline, import-sample 만
9. backend/tests/test_ingest.py — test_clean_bars_quarantines_with_reason, test_clean_bars_drops_unfinished_session, test_clean_fx_quarantines_spike, 샘플 재적재 멱등 테스트

[건드리지 않을 파일] backend/db/schema.sql·models(D 소유 — 컬럼이 필요하면 요청 메모), api/, frontend/
[인터페이스 계약]
- 사용: schema.sql의 Stage 1 테이블 (D가 커밋해 둠)
- 제공: CLI `python -m app.ingest init-db | master --offline | import-sample` 실행 후 모든 Stage 1 테이블에 행이 있음. B·A가 이 명령으로 로컬 DB를 채운다.
[이번 단계에서 뺄 것] Provider(pykrx·yfinance·DART·SEC) 호출, DART corp_code·SEC CIK 매핑, 비교군·listed, 섹터, 점수, refresh, demo
[완료 기준]
  docker compose run --rm api python -m app.ingest init-db
  docker compose run --rm api python -m app.ingest master --offline
  docker compose run --rm api python -m app.ingest import-sample
  docker compose run --rm api pytest -q tests/test_ingest.py
  → 위 명령 두 번 연속 실행해도 행 수가 같다(멱등)

[시작] 지금은 CLAUDE.md 2절의 작업 계획표만 출력하라. 코드는 내가 승인한 뒤 파일 하나씩 진행한다.
```

---

## 팀원 B — 조회 VIEW·종목·시장 API

```
[역할] 너는 StockMind 팀 프로젝트에서 팀원 B(백엔드 API·DB, 주니어)의 페어 프로그래머다. 레포 루트 CLAUDE.md의 규칙을 반드시 따른다.
[이번 단계] Stage 1 — MVP. DB에 저장된 값만 읽는 조회 API를 만든다.
[내 파트] VIEW → SQL 파일 → 경로 검증 → 라우터 → 응답 스키마 → 테스트
[브랜치] feat/s1-b-stock-api
[참조 원본] ../ax_class_semiproject/backend/, ../ax_class_semiproject/docs/06_기능_API_정의서.md (3-1, 3-2 예시) (읽기 전용)

[담당 파일 — 이 순서대로]
1. backend/db/views.sql — v_latest_price(종목별 최신 종가·전일 대비), v_fx_latest. v_stock_metrics는 Stage 4라 뺀다
2. backend/app/queries/stock_list.sql — 리스트(시장 필터·거래량/시총 정렬·검색·그룹 필터·페이지). 매력도 JOIN 제외
3. backend/app/queries/stock_detail.sql, candles.sql, stock_groups.sql
4. backend/app/queries/market_indices.sql(최신값·등락·최근 30거래일 스파크라인), fx_daily_recent.sql
5. backend/app/api/deps.py — [S1-B] 구역에 MarketPath·TickerPath, resolve_stock(없으면 404 STOCK_NOT_FOUND)
6. backend/app/schemas/api.py — [S1-B] 구역에 StockListOut·StockDetailOut·CandleOut·IndexOut·FxOut 등
7. backend/app/api/stocks.py — GET /stocks, GET /stocks/{market}/{ticker}, GET /stocks/{market}/{ticker}/candles, GET /peer-groups
8. backend/app/api/market.py — GET /market/indices, GET /market/fx (DB 최신값만. TTL 외부 호출은 Stage 2에서 C가 교체)
9. backend/app/main.py — [S1-B] 구역에 라우터 등록 1~2줄
10. backend/tests/test_stocks_api.py — 정렬·필터·검증 422·없는 종목 404

[건드리지 않을 파일] schema.sql·models(D), ingest/(C), frontend/(A)
[인터페이스 계약]
- 사용: Stage 1 테이블, C의 샘플 데이터(로컬 확인용). 테스트는 conftest 픽스처로 독립 실행
- 제공: 응답 JSON 필드는 원본 docs/06 3-1·3-2 예시와 같은 이름·타입. A가 이 예시로 목업 개발 중이므로 필드명을 바꾸면 PR에 반드시 표시
[이번 단계에서 뺄 것] preset·score·attractiveness 필드, coverage·detail_status, /stocks/search, financials·disclosures, refresh 엔드포인트, analysis·peers·statistics
[완료 기준]
  docker compose run --rm api pytest -q tests/test_stocks_api.py
  curl "localhost:8000/api/v1/stocks?country=KR&sort=volume&limit=2"  → 원본 docs/06 3-2 첫 예시와 같은 구조
  curl localhost:8000/api/v1/market/indices

[시작] 지금은 CLAUDE.md 2절의 작업 계획표만 출력하라. 코드는 내가 승인한 뒤 파일 하나씩 진행한다.
```

---

## 팀원 A — 화면 3개 (리스트·상세·홈 지수)

```
[역할] 너는 StockMind 팀 프로젝트에서 팀원 A(프론트엔드·사용자 경험, 주니어)의 페어 프로그래머다. 레포 루트 CLAUDE.md의 규칙을 반드시 따른다.
[이번 단계] Stage 1 — MVP. 바닐라 JS(ES Modules, 빌드 없음) + Chart.js(CDN)로 화면 3개를 만든다.
[내 파트] 주식 리스트 → 종목 상세(기본 정보·핵심 지표·가격 차트) → 홈 지수·환율 카드
[브랜치] feat/s1-a-screens
[참조 원본] ../ax_class_semiproject/frontend/, ../ax_class_semiproject/docs/screenshots/{01_home,02_stocks,03_stock_detail}.png, docs/06 3-1·3-2 예시 JSON (읽기 전용)

[담당 파일 — 이 순서대로]
1. frontend/js/api.js — [S1-A] 구역에 getStocks·getStock·getCandles·getPeerGroups·getIndices·getFx
   (B의 API가 아직 없으면 같은 모양의 목 응답을 돌려주는 MOCK 플래그를 둔다 — 통합 전에 제거)
2. frontend/js/components/charts.js — 가격 라인 차트·스파크라인
3. frontend/stocks.html + frontend/js/pages/stocks.js — 시장 탭·거래량/시총 정렬·검색어·그룹 필터·페이지
4. frontend/stock.html + frontend/js/pages/stock.js — 헤더(이름·가격·등락), 핵심 지표(PER·PBR·시총), 기간 선택 가격 차트
5. frontend/index.html + frontend/js/pages/home.js — 지수 5개 + USD/KRW 카드(값·등락·30일 스파크라인)
6. frontend/css/pages.css — [S1-A] 구역에 위 화면 전용 스타일

[건드리지 않을 파일] backend/ 전부, css/tokens·base·components.css(D 소유 — 공통 스타일이 필요하면 요청 메모)
[인터페이스 계약]
- 사용: GET /api/v1/stocks, /stocks/{market}/{ticker}, /candles, /peer-groups, /market/indices, /market/fx (응답은 원본 docs/06 예시 형태)
- 로딩·빈 상태·오류 상태는 공통 ui.js의 load() 사용
[이번 단계에서 뺄 것] 매력도 게이지·투자 성향 메뉴, ★ 관심 토글, 담기 버튼, 상단 검색, 재무·공시·경쟁 비교·월별 요약, 관심종목 카드, 순위표, 지표 선택 설정
[완료 기준]
  MOCK 끄고 B의 API로 3개 화면 정상 표시 / 존재하지 않는 종목 URL에서 오류 상태 표시 / 브라우저 콘솔 에러 0
  원본 스크린샷과 레이아웃이 같은 방향(이번 단계 요소만)

[시작] 지금은 CLAUDE.md 2절의 작업 계획표만 출력하라. 코드는 내가 승인한 뒤 파일 하나씩 진행한다.
```

---

## 팀원 D(시니어) — 실제 시세 수집

```
시니어 모드. Stage 1 수집. 브랜치 feat/s1-d-collectors (origin/stage1에서 분기 — C 머지 완료 → Ready PR)
1. backend/app/core/config.py(price_source_kr·krx_id/pw·export_krx_credentials), .env.example
2. backend/app/providers/{__init__,base,http,convert,krx,yahoo,factory}.py — 일봉·지수·환율만 (Bar·FxPoint는 preprocess에서 re-export)
3. backend/app/ingest/jobs.py [S1-D] — stock_refs·index_refs, load_prices·load_indices·load_fx_daily
4. backend/app/ingest/__main__.py [S1-D] — prices [--full] [--tickers], indices [--full], fx [--full]
5. backend/tests/fakes.py, backend/tests/test_ingest.py [S1-D]
[이번 단계에서 뺄 것] 밸류에이션·재무·공시 수집, bulk·batch 경로, refresh·스케줄러, advisory_lock, CLI all
[완료 기준]
  docker compose run --rm api python -m app.ingest prices --tickers 005930 AAPL  → ingestion_logs에 SUCCESS 2행
  같은 명령 재실행 → 새로 받을 날짜가 없으면 외부 호출 없이 '최신 상태'
  docker compose run --rm api pytest -q tests/test_ingest.py
[대체] 수집 실패 시 PRICE_SOURCE_KR=yfinance, 그래도 안 되면 import-sample
```

---

## 팀원 D(시니어) — 통합

```
시니어 모드. Stage 1 통합.
1. stage1 브랜치에 C → D(수집) → B → A 순서로 PR 머지, 충돌 해결.
2. A의 MOCK 플래그 제거 확인, main.py 라우터 등록 확인.
3. 통합 시나리오 실행: init-db → master --offline → prices·indices·fx(실패 시 import-sample) → /stocks → 상세 → 홈.
4. backend/tests/test_integration.py 뼈대(샘플 적재 후 주요 API 200).
5. docs/05·06에 Stage 1 범위 반영. 원본과 파일별 diff 요약 — 의도적으로 뺀 부분 외 차이는 fix 커밋.
6. stage1 → main, 태그 v1.0.
```
