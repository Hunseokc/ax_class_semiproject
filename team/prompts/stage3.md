# Stage 3 — 실데이터 수집·4시간 갱신

**단계 목표**: pykrx·yfinance·OpenDART·SEC EDGAR 4개 소스에서 실제 데이터를 적재하고(일봉·지수·환율 수집은 Stage 1-D에서 이미 들어옴 — 이번엔 밸류에이션·재무·공시·대량 경로를 더한다), 같은 종류 외부 호출은 4시간에 1회만 한다. 한 종목이 실패해도 나머지는 계속 적재되고, 실패는 대상별로 기록된다.
**D 선행 계약**: `financial_statements`·`disclosures` 테이블과 ORM, `providers/base.py`에 재무·공시 인터페이스 보강.
**공통 주의**: `.env`에 `KRX_ID`·`KRX_PW`·`DART_API_KEY`·`SEC_USER_AGENT` 필요. 단위 테스트는 실제 네트워크를 쓰지 않는다(`tests/fakes.py`).
**머지 순서**: C → B → D → A
**PR 방식**: 앞 순서 작업이 머지되기 전에 끝나면 기다리지 않고 Draft PR → 시니어가 그 파트를 먼저 리뷰 → 앞 순서 머지 후 최신 stage를 합쳐 같은 PR을 Ready로 전환(CLAUDE.md 6절). 시니어는 Ready PR만 머지 순서대로 머지한다.

---

## 팀원 C — 시세 Provider·적재 작업

```
[역할] 너는 StockMind 팀 프로젝트에서 팀원 C(데이터 수집·분석 로직, 주니어)의 페어 프로그래머다. 레포 루트 CLAUDE.md의 규칙을 반드시 따른다.
[이번 단계] Stage 3 — 실데이터. 외부 호출은 수집 쪽에서만 한다.
[내 파트] Stage 1-D가 만든 수집(일봉·지수·환율) 위에 확장: 호출 한도 → pykrx·yfinance 밸류에이션·대량 조회 → 팩토리 확장 → 적재 작업(대량 일봉·밸류에이션) → CLI → 가짜 Provider·테스트
[브랜치] feat/s3-c-price-providers
[참조 원본] ../ax_class_semiproject/backend/app/providers/{http,convert,factory,krx,yahoo}.py, ingest/jobs.py, tests/{fakes,test_ingest}.py, docs/03_데이터_조사_정의서.md, docs/troubleshooting.md (읽기 전용)

[담당 파일 — 이 순서대로]
(이미 있음 — Stage 1-D: http.py(Throttle·call_with_retry), convert.py, krx.py·yahoo.py의 일봉·지수·환율, factory.py(7필드), jobs.py [S1-D]의 stock_refs·index_refs·load_prices·load_indices·load_fx_daily, CLI prices·indices·fx, tests/fakes.py)
1. backend/app/providers/http.py — WindowLimiter(분당 호출 한도) 추가
2. backend/app/providers/krx.py — 시총·PER/PBR(get_valuations), 날짜별 전 종목(get_bars_by_date·get_valuations_by_date) (KRX 로그인 필요 — 이유를 설계 설명에)
3. backend/app/providers/yahoo.py — 밸류에이션 스냅샷, 묶음 다운로드(get_daily_prices_batch)
4. backend/app/providers/factory.py — Providers에 valuation·bulk·batch 필드 추가. dart·sec 자리는 B가 채우도록 [S3-B] 구역 주석
5. backend/app/ingest/universe.py — jobs.py [S1-D]의 stock_refs·index_refs를 원본 위치로 이동
6. backend/app/ingest/jobs.py — [S3-C] 구역: last_closed_day, load_prices_bulk, load_valuations(_bulk), derive_us_valuations (Bar에 change_rate 추가는 D가 Stage 2에서 base로 옮긴 Bar에 — 요청 메모)
7. backend/app/ingest/__main__.py — [S3-C] 구역: valuation(--full, --tickers), all(마스터+C 작업. B 작업은 B가 추가)
8. backend/app/services/fx.py — Stage 2의 '항상 실패 provider' 자리에 yahoo FX 연결 (deps 쪽 연결은 요청 메모 → D)
9. backend/tests/fakes.py — 밸류에이션·bulk·batch 가짜 추가, backend/tests/test_ingest.py — 원본의 남은 테스트

[건드리지 않을 파일] providers/base.py(D), dart.py·sec.py(B), services/refresh.py·scheduler.py(D), frontend(A)
[인터페이스 계약]
- 사용: providers/base.py 인터페이스, store.upsert·job_log(S1)
- 제공: jobs의 각 load_* 함수 시그니처는 원본과 같게 — D의 RefreshService가 이 함수를 호출한다. 반환은 {대상: 상태} dict
[이번 단계에서 뺄 것] 비교군(benchmark)·listing·섹터·freshness 관련 분기, DART 파생 밸류에이션의 fundamental_bases(Stage 5) — 파생은 FY 재무 기반만
[완료 기준]
  docker compose run --rm api pytest -q tests/test_ingest.py
  docker compose run --rm api python -m app.ingest valuation --tickers 005930 AAPL  → ingestion_logs에 SUCCESS 2행
  docker compose run --rm api python -m app.ingest all  → 일봉·지수·환율·밸류에이션 모두 SUCCESS (재실행 시 새 날짜 없으면 외부 호출 없이 끝남)

[선행 작업] 없음 — providers/base.py(D 계약)는 이미 stage3에 있다. 머지 순서 1번이므로 끝나면 바로 Ready PR.
[시작] ① CLAUDE.md 10절대로 최신 코드부터 받는다: git fetch → [브랜치]로 이동(없으면 origin/stage3에서 새로 만듦) → origin/stage3 합치기. 이동한 뒤 CLAUDE.md를 다시 읽고 그 규칙을 따른다(설명은 9절 입문자 기준, 다른 팀원 파일이 없으면 11절대로 묻지 않고 진행).
② CLAUDE.md 2절의 작업 계획표만 출력하라. 코드는 내가 승인한 뒤 파일 하나씩 진행한다.
```

---

## 팀원 B — 재무·공시 수집과 조회 API

```
[역할] 너는 StockMind 팀 프로젝트에서 팀원 B(백엔드 API·DB, 주니어)의 페어 프로그래머다. 레포 루트 CLAUDE.md의 규칙을 반드시 따른다.
[이번 단계] Stage 3 — 실데이터. 국내는 OpenDART, 미국은 SEC EDGAR.
[내 파트] DART Provider → SEC Provider → 재무·공시 적재 작업 → 조회 SQL → 엔드포인트 → 테스트
[브랜치] feat/s3-b-financials
[참조 원본] ../ax_class_semiproject/backend/app/providers/{dart,sec}.py, ingest/jobs.py(load_financials·load_disclosures·merge_supplement), queries/{financials,disclosures}.sql, docs/03, docs/06 3-2 (읽기 전용)

[담당 파일 — 이 순서대로]
1. backend/app/providers/dart.py — corp_code 매핑, FY 재무(계정 ID 매핑 + 계정명 대체), 최근 공시. 분당 호출 제한 주의
2. backend/app/providers/sec.py — ticker→CIK, companyfacts에서 FY 매출·영업이익·순이익·자본 등, 최근 공시. User-Agent 필수
3. backend/app/providers/factory.py — [S3-B] 구역에 dart·sec 연결
4. backend/app/ingest/jobs.py — [S3-B] 구역: merge_supplement, load_financials(5개년), load_disclosures(최근 1년)
5. backend/app/ingest/jobs.py load_master — [S3-B] 구역: online일 때 DART corp_code·SEC CIK 매핑
6. backend/app/ingest/__main__.py — [S3-B] 구역: financials(--years, --tickers), disclosures(--days, --tickers), all에 두 작업 추가
7. backend/app/queries/financials.sql, disclosures.sql
8. backend/app/api/stocks.py — [S3-B] 구역: GET /stocks/{market}/{ticker}/financials, /disclosures + schemas [S3-B] 구역
9. backend/tests/ — test_ingest.py에 test_dart_account_mapping_falls_back_to_account_name, test_stocks_api.py에 재무·공시 엔드포인트

[건드리지 않을 파일] krx.py·yahoo.py·http.py(C — http.py 재사용만), base.py(D), refresh(D), frontend(A)
[인터페이스 계약]
- 사용: providers/base.py의 재무·공시 인터페이스, http.py(C)
- 제공: load_financials·load_disclosures 시그니처 원본과 같게(D의 갱신·Stage 4 hydration이 호출), 응답은 원본 docs/06 3-2 financials·disclosures 예시
[이번 단계에서 뺄 것] freshness(유효기간)·invalidate_on_annual_report, fundamental_bases, 비교군·listing용 corp_code 일괄 매핑
[완료 기준]
  docker compose run --rm api python -m app.ingest financials --tickers 005930 AAPL
  curl "localhost:8000/api/v1/stocks/KOSPI/005930/financials?limit=2" → 원본 예시와 같은 구조
  pytest -q 통과

[선행 작업] C(feat/s3-c-price-providers)의 http.py·factory.py. dart.py·sec.py는 원본과 같은 이름으로 http.py를 import 해 먼저 작성하고, 이를 쓰는 테스트는 ⏸ C 머지 후. 3번(factory.py [S3-B] 구역)은 C의 파일이므로 계획표 맨 뒤로 ⏸. C 머지 전이면 Draft PR.
[시작] ① CLAUDE.md 10절대로 최신 코드부터 받는다: git fetch → [브랜치]로 이동(없으면 origin/stage3에서 새로 만듦) → origin/stage3 합치기. 이동한 뒤 CLAUDE.md를 다시 읽고 그 규칙을 따른다(설명은 9절 입문자 기준, 다른 팀원 파일이 없으면 11절대로 묻지 않고 진행).
② CLAUDE.md 2절의 작업 계획표만 출력하라. 코드는 내가 승인한 뒤 파일 하나씩 진행한다.
```

---

## 팀원 A — 재무·공시 섹션·갱신 상태 표시

```
[역할] 너는 StockMind 팀 프로젝트에서 팀원 A(프론트엔드·사용자 경험, 주니어)의 페어 프로그래머다. 레포 루트 CLAUDE.md의 규칙을 반드시 따른다.
[이번 단계] Stage 3 — 실데이터 화면
[내 파트] api.js 확장 → 상세 재무 추이 → 상세 최근 공시 → 사이드바 갱신 상태 → stale 표시
[브랜치] feat/s3-a-financial-screens
[참조 원본] ../ax_class_semiproject/frontend/js/pages/stock.js(재무·공시 부분), js/components/sidebar.js, docs/screenshots/{03_stock_detail,04_stock_detail_us}.png, docs/06 3-1 refresh·3-2 (읽기 전용)

[담당 파일 — 이 순서대로]
1. frontend/js/api.js — [S3-A] 구역: getFinancials·getDisclosures·getRefreshStatus·postRefresh
2. frontend/js/pages/stock.js — [S3-A] 구역: FY 재무 추이(매출·영업이익·순이익 막대 + 표), 원화·달러 단위 표시
3. frontend/js/pages/stock.js — [S3-A] 구역: 최근 공시 목록(날짜·제목·원문 링크)
4. frontend/js/components/sidebar.js — 마지막 갱신 시각, 갱신 버튼(TTL 이내면 '다음 갱신 가능 시각' 안내), 작업별 FRESH/STALE
5. frontend/js/pages/home.js — [S3-A] 구역: 환율 fx_stale일 때 표시
6. frontend/css/pages.css — [S3-A] 구역

[건드리지 않을 파일] backend/ 전부, 공통 css(D)
[인터페이스 계약]
- 사용: /stocks/{m}/{t}/financials·/disclosures(B), /market/refresh·/refresh/status(D) — 아직이면 docs/06 예시로 MOCK
[이번 단계에서 뺄 것] 매력도·경쟁 비교·월별 요약, 비교군 detail_status 안내
[완료 기준]
  삼성전자·AAPL 상세에서 재무·공시 표시, 데이터 없는 종목은 빈 상태 / 사이드바 갱신 시각이 status API와 일치 / 콘솔 에러 0

[선행 작업] B(feat/s3-b-financials)의 financials·disclosures API, D의 /market/refresh·/refresh/status. 아직 없으면 docs/06 예시로 MOCK 하고 묻지 말고 진행한다. 머지 순서가 마지막이므로 B·D 머지 전이면 Draft PR.
[시작] ① CLAUDE.md 10절대로 최신 코드부터 받는다: git fetch → [브랜치]로 이동(없으면 origin/stage3에서 새로 만듦) → origin/stage3 합치기. 이동한 뒤 CLAUDE.md를 다시 읽고 그 규칙을 따른다(설명은 9절 입문자 기준, 다른 팀원 파일이 없으면 11절대로 묻지 않고 진행).
② CLAUDE.md 2절의 작업 계획표만 출력하라. 코드는 내가 승인한 뒤 파일 하나씩 진행한다.
```

---

## 팀원 D(시니어) — 갱신 서비스·스케줄러

```
시니어 모드. Stage 3.
[PR] Draft PR은 코드 리뷰만 한다. Ready로 바뀐 PR을 머지 순서대로 머지하고, 머지할 때마다 다음 순서 팀원에게 알린다(그쪽 Claude가 동기화 중 머지를 감지해 Ready 전환을 시작한다).
[선행] schema·ORM에 financial_statements·disclosures, providers/base.py 재무·공시 인터페이스 → 커밋 후 배포.
[내 구현]
1. backend/app/ingest/store.py — advisory_lock 추가 (C 파일이지만 동시성 설계라 D가 맡음 — C에게 공지)
2. backend/app/services/refresh.py — RefreshService: FX → INDICES → PRICES → VALUATION 순서, 작업 단위 TTL(source='REFRESH'), 부분 실패는 30분 뒤 실패 종목만 재시도, SCORES 자리는 Stage 4용 주석
3. backend/app/services/scheduler.py + main.py lifespan (SCHEDULER_ENABLED), advisory lock으로 1회 실행
4. backend/app/api/market.py — POST /market/refresh, GET /market/refresh/status, deps.get_providers
5. backend/tests/test_refresh.py, docs/troubleshooting.md(KRX 로그인·TLS 검사 환경), README 환경변수 절
[통합] C → B → D → A 머지, `python -m app.ingest all` 전체 실행(약 4~5분) → 화면 확인 → stage3 → main, 태그 v3.0
```
