# Stage 3 — 실데이터 수집·4시간 갱신

**단계 목표**: pykrx·yfinance·OpenDART·SEC EDGAR 4개 소스에서 실제 데이터를 적재하고(일봉·지수·환율 수집은 Stage 1-D에서 이미 들어옴 — 이번엔 밸류에이션·재무·공시·대량 경로를 더한다), 같은 종류 외부 호출은 4시간에 1회만 한다. 한 종목이 실패해도 나머지는 계속 적재되고, 실패는 대상별로 기록된다.
**D 선행 계약**: `financial_statements`·`disclosures` 테이블과 ORM, `providers/base.py`에 재무·공시 인터페이스 보강.
**공통 주의**: `.env`에 `KRX_ID`·`KRX_PW`·`DART_API_KEY`·`SEC_USER_AGENT` 필요. 단위 테스트는 실제 네트워크를 쓰지 않는다(`tests/fakes.py`).
**머지 순서**: C → B → D → A
**PR 방식**: 파일마다 커밋·push, 파트 하나 = PR 하나로 끝나는 대로 D에게 넘긴다(CLAUDE.md 6절). 다른 팀원 브랜치는 받지 않는다. stage에 없는 다른 팀원 코드는 원본과 같은 이름으로 [연결 예정](CLAUDE.md 11절)로 두고, 연결은 D가 단계 통합 때 한다. 시니어는 자동 검사가 통과한 넘김 PR을 머지 순서대로 바로바로 머지한다.

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

[파트별 확인 — 계획표의 "파트별 확인 지점"으로 그대로 쓴다. 파일마다 만든 직후 돌려 보고(CLAUDE.md 3절 ③), 파트가 끝날 때마다 실제로 실행해서 "여기까지 만든 것"을 보여 주고 아주 쉽게 설명한다(3-1)]
파트 1 (1번 WindowLimiter) → 볼 것: 작은 한도(예: 1초에 2번)로 만든 리미터로 4번 호출하고 호출 시각을 찍어, 3번째부터 기다렸다 나가는 모습을 보여 준다. "외부 사이트에 너무 자주 묻지 않게 줄 세우는 장치"로 설명.
파트 2 (2~4번 KRX·Yahoo 밸류에이션·팩토리) → 볼 것: 실제 네트워크로 005930·AAPL 밸류에이션 한 번씩 받아 시총·PER·PBR 출력(외부 호출이니 1~2종목만). get_providers()로 만든 Providers의 필드(valuation·bulk·batch…)를 출력해 무엇이 어디에 연결됐는지 보여 준다. KRX 로그인이 없으면 어떤 에러가 나는지도 보여 준다.
파트 3 (5~7번 위치 이동·적재 작업·CLI) → 볼 것: `python -m app.ingest valuation --tickers 005930 AAPL` → psql로 valuation_snapshots 2행·ingestion_logs SUCCESS 2행. 같은 명령 재실행 → 새로 받을 게 없으면 외부 호출 없이 끝나는 로그. `all` 실행 시간·단계별 로그를 읽어 준다.
파트 4 (8번 환율 연결) → 볼 것: FxService가 이제 진짜 환율을 받아 fx_stale=false로 나오는 것. Stage 2(항상 실패 → 저장값)와 전후 비교.
파트 5 (9번 가짜 Provider·테스트) → pytest -v. "가짜 Provider = 인터넷 없이도 늘 같은 답을 주는 연습 상대"로 설명하고, 테스트가 실제 네트워크를 안 쓰는 것을 보여 준다.

[건드리지 않을 파일] providers/base.py(D), dart.py·sec.py(B), services/refresh.py·scheduler.py(D), frontend(A)
[인터페이스 계약]
- 사용: providers/base.py 인터페이스, store.upsert·job_log(S1)
- 제공: jobs의 각 load_* 함수 시그니처는 원본과 같게 — D의 RefreshService가 이 함수를 호출한다. 반환은 {대상: 상태} dict
[이번 단계에서 뺄 것] 비교군(benchmark)·listing·섹터·freshness 관련 분기, DART 파생 밸류에이션의 fundamental_bases(Stage 5) — 파생은 FY 재무 기반만
[완료 기준]
  docker compose run --rm api pytest -q tests/test_ingest.py
  docker compose run --rm api python -m app.ingest valuation --tickers 005930 AAPL  → ingestion_logs에 SUCCESS 2행
  docker compose run --rm api python -m app.ingest all  → 일봉·지수·환율·밸류에이션 모두 SUCCESS (재실행 시 새 날짜 없으면 외부 호출 없이 끝남)

[선행 작업] 없음 — providers/base.py(D 계약)는 이미 stage3에 있다. 머지 순서 1번이다.
[시작] ① CLAUDE.md 10절대로 최신 코드부터 받는다: git fetch → [브랜치]로 이동(없으면 origin/stage3에서 새로 만듦) → origin/stage3 합치기. 이동한 뒤 CLAUDE.md를 다시 읽고 그 규칙을 따른다(설명은 9절 입문자 기준, 다른 팀원 파일이 없으면 11절대로 묻지 않고 진행).
② CLAUDE.md 2절의 작업 계획표만 출력하라(파트별 확인 지점 포함). 코드는 내가 승인한 뒤 파일 하나씩 진행하고, 파일마다 만든 직후 실제로 돌려서 보여 주며(3절 ③), 파트가 끝날 때마다 "여기까지 만든 것"을 실행해 보여 준다(3-1).
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

[파트별 확인 — 계획표의 "파트별 확인 지점"으로 그대로 쓴다. 파일마다 만든 직후 돌려 보고(CLAUDE.md 3절 ③), 파트가 끝날 때마다 실제로 실행해서 "여기까지 만든 것"을 보여 주고 아주 쉽게 설명한다(3-1)]
파트 1 (1~2번 DART·SEC Provider) → 볼 것: 실제 호출로 005930의 FY 매출·영업이익·순이익 최근 연도, AAPL의 같은 값을 출력(1종목씩만). 계정 ID가 없어 계정명으로 대체된 항목이 있으면 짚어 준다. .env에 DART_API_KEY·SEC_USER_AGENT가 없으면 어떤 에러가 나는지 보여 주고 설정법 안내.
파트 2 (4~6번 적재 작업·CLI) → 볼 것: `financials --tickers 005930 AAPL`, `disclosures --days 30 --tickers 005930` → psql로 financial_statements(종목·연도별 행)·disclosures 행 수와 예시 3행, ingestion_logs. 재실행해도 행 수가 그대로(멱등).
파트 3 (7~8번 조회 SQL·API) → 볼 것: curl `/stocks/KOSPI/005930/financials?limit=2`, `/disclosures` — docs/06 예시와 칸 이름을 나란히 비교. 없는 종목 404. /docs에서 직접 해 보기.
파트 4 (9번 테스트, [연결 예정] 3번 factory는 D가 연결) → pytest -v 번역. 3번은 연결 예정 목록에 적어 둔다(D가 연결한 뒤 get_providers()로 확인).

[건드리지 않을 파일] krx.py·yahoo.py·http.py(C — http.py 재사용만), base.py(D), refresh(D), frontend(A)
[인터페이스 계약]
- 사용: providers/base.py의 재무·공시 인터페이스, http.py(C)
- 제공: load_financials·load_disclosures 시그니처 원본과 같게(D의 갱신·Stage 4 hydration이 호출), 응답은 원본 docs/06 3-2 financials·disclosures 예시
[이번 단계에서 뺄 것] freshness(유효기간)·invalidate_on_annual_report, fundamental_bases, 비교군·listing용 corp_code 일괄 매핑
[완료 기준]
  docker compose run --rm api python -m app.ingest financials --tickers 005930 AAPL
  curl "localhost:8000/api/v1/stocks/KOSPI/005930/financials?limit=2" → 원본 예시와 같은 구조
  pytest -q 통과

[선행 작업] C(feat/s3-c-price-providers)의 http.py·factory.py. stage에 없으면 dart.py·sec.py를 원본과 같은 이름으로 [연결 예정](CLAUDE.md 11절) — 이를 쓰는 테스트는 연결 예정 목록에 적는다(D가 연결 후 추가). 3번(factory.py [S3-B] 구역)은 C의 파일이므로 연결 예정 목록에 적는다(D가 연결).
[시작] ① CLAUDE.md 10절대로 최신 코드부터 받는다: git fetch → [브랜치]로 이동(없으면 origin/stage3에서 새로 만듦) → origin/stage3 합치기. 이동한 뒤 CLAUDE.md를 다시 읽고 그 규칙을 따른다(설명은 9절 입문자 기준, 다른 팀원 파일이 없으면 11절대로 묻지 않고 진행).
② CLAUDE.md 2절의 작업 계획표만 출력하라(파트별 확인 지점 포함). 코드는 내가 승인한 뒤 파일 하나씩 진행하고, 파일마다 만든 직후 실제로 돌려서 보여 주며(3절 ③), 파트가 끝날 때마다 "여기까지 만든 것"을 실행해 보여 준다(3-1).
```

---

## 팀원 A — 재무·공시 섹션·갱신 상태 표시

```
[역할] 너는 StockMind 팀 프로젝트에서 팀원 A(프론트엔드·사용자 경험, 주니어)의 페어 프로그래머다. 레포 루트 CLAUDE.md의 규칙을 반드시 따른다.
[이번 단계] Stage 3 — 실데이터 화면
[내 파트] api.js 확장 → 상세 재무 추이 → 상세 최근 공시 → 사이드바 갱신 상태 → stale 표시
[브랜치] feat/s3-a-financial-screens
[참조 원본] ../ax_class_semiproject/frontend/js/pages/stock.js(재무·공시 부분), js/components/sidebar.js, docs/screenshots/{03_stock_detail,04_stock_detail_us}.png, docs/06 3-1 refresh·3-2 (읽기 전용) 스크린샷·원본 화면은 참고용 — 배치·디자인·문구 같은 표현은 A가 정해도 된다(CLAUDE.md 1절, PR "원본과 다르게 한 것"에 기록).

[담당 파일 — 이 순서대로]
1. frontend/js/api.js — [S3-A] 구역: getFinancials·getDisclosures·getRefreshStatus·postRefresh
2. frontend/js/pages/stock.js — [S3-A] 구역: FY 재무 추이(매출·영업이익·순이익 막대 + 표), 원화·달러 단위 표시
3. frontend/js/pages/stock.js — [S3-A] 구역: 최근 공시 목록(날짜·제목·원문 링크)
4. frontend/js/components/sidebar.js — 마지막 갱신 시각, 갱신 버튼(TTL 이내면 '다음 갱신 가능 시각' 안내), 작업별 FRESH/STALE
5. frontend/js/pages/home.js — [S3-A] 구역: 환율 fx_stale일 때 표시
6. frontend/css/pages.css — [S3-A] 구역

[파트별 확인 — 계획표의 "파트별 확인 지점"으로 그대로 쓴다. 파일마다 만든 직후 돌려 보고(CLAUDE.md 3절 ③), 파트가 끝날 때마다 실제로 실행해서 "여기까지 만든 것"을 보여 주고 아주 쉽게 설명한다(3-1)]
파트 1 (1번 api.js) → 볼 것: Console에서 getFinancials('KOSPI','005930') 등을 직접 불러 응답 보기(MOCK인지 진짜인지 말해 준다).
파트 2 (2~3번 재무 추이·최근 공시) → 볼 것: /stocks/KOSPI/005930 과 /stocks/NASDAQ/AAPL 에서 막대·표·단위(원화/달러) 차이, 공시 제목 클릭 → 원문 열림. 데이터 없는 종목에서 빈 상태 문구. 원본 스크린샷 03·04와 나란히 비교.
파트 3 (4번 사이드바) → 볼 것: 사이드바의 마지막 갱신 시각을 curl /market/refresh/status 값과 나란히 비교. 갱신 버튼 클릭 → Network 탭의 POST /market/refresh → TTL 이내면 '다음 갱신 가능 시각' 안내.
파트 4 (5~6번 환율 stale·CSS) → 볼 것: MOCK에서 fx_stale=true로 바꿔 홈에 표시가 뜨는 것, 원래대로 돌리면 사라지는 것. 화면별 스크린샷 안내.

[건드리지 않을 파일] backend/ 전부, 공통 css(D)
[인터페이스 계약]
- 사용: /stocks/{m}/{t}/financials·/disclosures(B), /market/refresh·/refresh/status(D) — 아직이면 docs/06 예시로 MOCK
[이번 단계에서 뺄 것] 매력도·경쟁 비교·월별 요약, 비교군 detail_status 안내
[완료 기준]
  삼성전자·AAPL 상세에서 재무·공시 표시, 데이터 없는 종목은 빈 상태 / 사이드바 갱신 시각이 status API와 일치 / 콘솔 에러 0

[선행 작업] B(feat/s3-b-financials)의 financials·disclosures API, D의 /market/refresh·/refresh/status. stage에 없으면 [연결 예정](CLAUDE.md 11절) — docs/06 예시로 MOCK 하고 묻지 말고 진행한다(`TODO(연결)` 표시, D가 연결).
[시작] ① CLAUDE.md 10절대로 최신 코드부터 받는다: git fetch → [브랜치]로 이동(없으면 origin/stage3에서 새로 만듦) → origin/stage3 합치기. 이동한 뒤 CLAUDE.md를 다시 읽고 그 규칙을 따른다(설명은 9절 입문자 기준, 다른 팀원 파일이 없으면 11절대로 묻지 않고 진행).
② CLAUDE.md 2절의 작업 계획표만 출력하라(파트별 확인 지점 포함). 코드는 내가 승인한 뒤 파일 하나씩 진행하고, 파일마다 만든 직후 실제로 돌려서 보여 주며(3절 ③), 파트가 끝날 때마다 "여기까지 만든 것"을 실행해 보여 준다(3-1).
```

---

## 팀원 D(시니어) — 갱신 서비스·스케줄러

```
시니어 모드. Stage 3.
[PR] 파트 단위로 넘어온(Ready) PR을 자동 검사 통과 확인 후 머지 순서대로 당일 머지하고, 팀 채팅에 알린다. 진행 중(Draft) PR은 코드만 미리 본다. 받은 요청 메모는 추천안에 OK/다른 지시만 답한다.
[연결 예정 처리] 이 단계 PR이 모두 머지되면 stage에서 `git grep -n "TODO(연결)"` → 각 PR의 "연결 예정 목록"대로 연결(import를 원본처럼 맨 위로, MOCK 제거, 목록의 테스트 추가) → `pytest -q`·`python team/tools/check_contract.py 3` 통과 → 아래 통합으로.
[선행] schema·ORM에 financial_statements·disclosures, providers/base.py 재무·공시 인터페이스 → 커밋 후 배포.
[내 구현]
1. backend/app/ingest/store.py — advisory_lock 추가 (C 파일이지만 동시성 설계라 D가 맡음 — C에게 공지)
2. backend/app/services/refresh.py — RefreshService: FX → INDICES → PRICES → VALUATION 순서, 작업 단위 TTL(source='REFRESH'), 부분 실패는 30분 뒤 실패 종목만 재시도, SCORES 자리는 Stage 4용 주석
3. backend/app/services/scheduler.py + main.py lifespan (SCHEDULER_ENABLED), advisory lock으로 1회 실행
4. backend/app/api/market.py — POST /market/refresh, GET /market/refresh/status, deps.get_providers
5. backend/tests/test_refresh.py, docs/troubleshooting.md(KRX 로그인·TLS 검사 환경), README 환경변수 절
[통합] C → B → D → A 머지, `python -m app.ingest all` 전체 실행(약 4~5분) → 화면 확인 → stage3 → main, 태그 v3.0
```
