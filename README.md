# StockMind

국내(KOSPI·KOSDAQ)·미국(NASDAQ) 의 주식 시세·지수·환율·재무·공시를 수집·전처리해 PostgreSQL에 구조화하고, FastAPI 조회·분석 API와 바닐라 HTML/CSS/JS 로 제공하는 주식 분석 대시보드 형태의 1차 세미프로젝트입니다.
1차 프로젝트에서는 주요 데이터 CRUD 구현에 집중하였고, 인증 구현, 리액트를 활용한 페이지 디자인, 각 기능의 고도화는 차후 진행될 예정입니다.  

> 시세는 **일봉 기준**(장중 실시간 아님)이며, 매력도·모의 포트폴리오를 포함한 모든 정보는 **투자 권유가 아닙니다**. 매력도는 유니버스 안에서 같은 시장끼리 비교한 상대적 위치를 나타내는 팩터 점수이며 수익률 예측이 아닙니다.
>
> 1차는 **로그인 없는 단일 사용자(데모) 모드**로, **로컬·시연 전용**입니다. 인증이 없으므로 외부에 공개된 서버로 배포하지 마세요.

![대시보드 홈](docs/screenshots/01_home.png)

## 주요 기능
> 수집 데이터(시세·지수·환율·재무·공시)는 **조회·분석** 대상이고, 사용자 데이터(모의 포트폴리오·관심종목)는 **CRUD**(생성·조회·수정·삭제) 대상입니다.

| 화면 | 기능 |
|---|---|
| 대시보드 홈 `/` | 투자 성향(위험·성장·균형·가치) 선택, 주요 지수·USD/KRW(30일 스파크라인, 지수 10개 + 환율 중 표시할 지표를 ‘설정’에서 선택 — 한 줄, 넘치면 가로 스크롤), 내 관심종목 카드(매력도 게이지·가격 등락·목표가 대비 괴리율·메모, 카드에서 메모·목표가 편집), 순위 상위 5(거래량·1개월·1년 수익률 × 국내/미국) |
| 주식 리스트 `/stocks` | 시장 탭·거래량/시가총액(원화 환산) 순위·검색·경쟁 그룹 필터, 투자 성향 선택, ★ 관심 토글, 포트폴리오 담기 |
| 종목 상세 `/stocks/{market}/{ticker}` | 가격 차트, 핵심 지표, 매력도(투자 성향 메뉴, 국가 내 순위, 팩터 기여도, 지표 원값·Z), 수치 분석(수익률·변동성·MDD·120일선 괴리율), 월별 요약(최근 12개월 평균·최고·최저·월간 수익률·거래량), FY 재무 추이, 경쟁 종목 비교(그룹 내 순위·평균, 기준일=100 추이), 최근 공시 |
| 모의 포트폴리오 `/portfolio` | 시드 설정, 수량/금액/비중으로 담기(미리보기), 시드 초과 방어, 평가손익과 환율 효과 분리, 비중 차트 |

## 기술 스택
Python 3.12 · FastAPI · SQLAlchemy 2.x(동기) · Pydantic v2 · psycopg 3 · PostgreSQL 16 · Docker Compose(db + api) · pytest · 바닐라 JS(ES Modules, 빌드 없음) · Chart.js(CDN) · Google Fonts

## 1. 설치
DB와 API 서버를 모두 컨테이너로 실행합니다(권장). 필요한 것은 Docker뿐입니다.
```bash
cp .env.example .env          # 아래 환경변수 입력 (DATABASE_URL은 compose가 컨테이너 주소로 덮어씀)
docker compose up -d --build  # db(PostgreSQL 16, localhost:5433) + api(http://localhost:8000), 둘 다 healthcheck
```
- 적재·관리 명령은 컨테이너에서 실행합니다: `docker compose run --rm api python -m app.ingest <명령>` (아래 3절의 `python -m app.ingest …` 앞에 `docker compose run --rm api`를 붙임)
- 개발(소스 수정 즉시 반영): `docker compose -f compose.yml -f compose.dev.yml up -d --build` — `app/`·`config/`·`web/` 등을 bind mount하고 uvicorn `--reload`(Windows용 polling)
- 로그: `docker compose logs -f api` · 중지: `docker compose down` (데이터는 `semi_pgdata` 볼륨에 유지)
- **TLS 검사(백신·사내 프록시) 환경**: 호스트에서 HTTPS가 가로채져 인증서 오류가 나면, 그 루트 인증서(`*.pem`·`*.crt`)를 `certs/`에 두거나 `.env`에 `EXTRA_CA_DIR=<폴더>`를 지정합니다. entrypoint가 시스템 CA 번들에 합쳐 requests·curl_cffi(yfinance)·ssl 모두에 적용합니다. 예) Norton: `C:/ProgramData/Norton/Antivirus/wscert.pem`

로컬 venv로 실행할 수도 있습니다(DB만 컨테이너).
```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
docker compose up -d db
uvicorn app.main:app --reload
```

## 2. 환경변수 (`.env`)
| 변수 | 설명 |
|---|---|
| `DATABASE_URL` / `TEST_DATABASE_URL` | 운영·테스트 DB (기본 포트 5433 — 로컬의 다른 PostgreSQL과 충돌 방지) |
| `PRICE_SOURCE_KR` | 국내 시세·지수·밸류에이션 소스 `pykrx`(기본) / `yfinance` |
| `KRX_ID`, `KRX_PW` | pykrx 1.2.x의 시총·PER/PBR·지수 조회에 필요한 KRX 정보데이터시스템 계정 |
| `REFRESH_TTL_HOURS` | 같은 종류 외부 호출 최소 간격(3~4, 기본 4) |
| `DART_API_KEY` | OpenDART 인증키 |
| `SEC_USER_AGENT` | `"앱이름 이메일"` 형식 (SEC는 API 키가 없고 연락처 포함 User-Agent 필수) |
| `LOG_LEVEL` | 기본 INFO |
| `DEFAULT_USER_ID` | 단일 사용자 모드에서 모든 요청을 처리할 사용자 (기본 1 = demo) |
| `SCHEDULER_ENABLED` | 앱 안 스케줄러 사용 여부 (기본 true — 노출 종목 4시간, 매력도 비교군 1일 갱신) |
| `SCHEDULER_CHECK_MINUTES` | 스케줄러가 할 일을 확인하는 간격(분, 기본 5) |

## 3. 데이터 적재
```bash
python -m app.ingest.smoke            # (선택) 외부 소스 동작 확인 → docs/smoke_test_result.md
python -m app.ingest init-db          # db/schema.sql → indexes.sql → views.sql  (--reset: 스키마 재생성)
python -m app.ingest all              # 아래 1~7 전체 — 화면 노출 25종목 (빈 DB 기준 실측 257초)
python -m app.ingest benchmark        # 매력도 비교군 선정·평시 데이터 + 점수 계산 (첫 실행 약 8분, docs/09)
python -m app.ingest seed-demo        # demo 사용자의 관심종목 8건 + 모의 포트폴리오 2개
python -m app.ingest status           # 테이블별 행 수·기간·최근 실패
```
| 순서 | 명령 | 내용 | 소스 |
|---|---|---|---|
| 1 | `master [--offline]` | universe.yaml → 시장·종목·경쟁 그룹·지수, demo 사용자, DART corp_code·SEC CIK 매핑 | DART, SEC |
| 2 | `prices [--full] [--tickers …]` | 종목 일봉 2년(수정주가), 기본은 증분 | pykrx / yfinance |
| 3 | `indices [--full]` | 지수 일봉 2년 | pykrx / yfinance |
| 4 | `fx [--full]` | USD/KRW 일별 2년 | yfinance |
| 5 | `financials [--years 5]` | FY 5개년 재무(국내 연결) | DART / SEC + yfinance 보완 |
| 6 | `valuation [--full]` | KR 일별 1년, US 스냅샷 | pykrx / yfinance |
| 7 | `disclosures [--days 365]` | 최근 1년 공시(지분공시·Form 4 제외) | DART / SEC |

## 4. 실행
```bash
docker compose up -d          # 로컬 venv라면: uvicorn app.main:app --reload
```
- 화면: http://localhost:8000/ · `/stocks` · `/stocks/KOSPI/005930` · `/portfolio`
- API 문서(Swagger): http://localhost:8000/docs — API는 `/api/v1` 아래
- 헬스체크: `GET /health`(프로세스 생존, DB 미접근) · `GET /health/db`(DB 연결, 실패 시 503 `DB_UNAVAILABLE`). 컨테이너 HEALTHCHECK가 `/health/db`를 쓴다
- 사용자: 인증 없음(단일 사용자·데모 모드). 요청 사용자는 서버의 `get_current_user_id()`가 `DEFAULT_USER_ID`로 정하며, API는 `user_id`를 받지 않습니다. 포트폴리오·관심종목은 소유자만 접근할 수 있고 남의 리소스는 404입니다. 로그인은 2차에서 이 함수를 JWT 검증으로 교체해 도입합니다
- 오류 응답은 `{"error": {"code", "message", "detail"}}`, 모든 응답(500 포함)에 `X-Request-ID` 헤더. 에러 코드 전체는 [docs/06 5절](docs/06_기능_API_정의서.md#5-에러-코드)

### 매력도 비교군 (docs/09 9절)
화면에 보이는 25종목 외에, 점수 비교 표본으로 국가별·섹터별 시가총액 상위 종목(섹터당 최대 10개, 현재 121종목)을 함께 관리합니다.
- 평시에는 점수 계산에 필요한 데이터(일봉 400일·최신 밸류에이션·FY 3개년)만 하루 한 번 갱신합니다.
- 주식 리스트에서 검색하면 비교군 종목도 나오고(배지 "비교군"), 상세를 열거나 관심종목에 담을 때 공시·2년 시세·5개년 재무를 받습니다.
```bash
python -m app.ingest benchmark            # 오늘 갱신(30일마다 다시 선정), --reselect: 지금 다시 선정
python -m app.ingest hydrate 042700       # 비교군 종목 상세 데이터 받기
```

### 갱신 정책 (앱 안 스케줄러)
- 환율·지수·종목 일봉·밸류에이션·점수는 **작업 종류별 `REFRESH_TTL_HOURS`(기본 4시간)에 최대 1회**만 외부 호출합니다.
- 일부 종목만 실패한 작업은 TTL을 시작하지 않고, 30분 뒤 **실패한 종목만** 다시 받습니다(성공한 종목은 TTL당 1회 유지). TTL은 갱신 작업 단위 기록(`ingestion_logs.source = 'REFRESH'`)으로 판단해, 비교군 갱신·상세 수집의 종목 단위 기록이 노출 종목 갱신을 막지 않습니다.
- 증분 일봉은 시장 현지 날짜까지만 요청합니다(한국 오전의 미국은 아직 전날). 주말뿐인 구간은 호출하지 않고, 짧은 구간에서 yfinance가 '데이터 없음'을 내면 휴장일로 봅니다.
- 사이드바 새로고침(`POST /api/v1/market/refresh`)과 `python -m app.ingest refresh`는 TTL 이내 작업을 `SKIPPED`로 기록하고 외부 호출 없이 현재 상태를 돌려줍니다.
- 환율은 TTL이 지났을 때 한 번만 조회해 저장하며(동시 요청은 advisory lock으로 한 번만), 실패하면 마지막 값과 `fx_stale: true`를 응답합니다.
- **앱 안 스케줄러**(`SCHEDULER_ENABLED=true`, 기본): 서버가 떠 있는 동안 5분마다 확인해 노출 종목(+관심종목·포트폴리오 종목)을 4시간 TTL로 갱신하고, 비교군은 매일 07:00(KST) 이후 한 번 갱신합니다. 실패하면 30분(갱신)·60분(비교군) 간격으로만 다시 시도하고, 여러 프로세스가 동시에 돌려도 DB 잠금으로 한 번만 실행됩니다.
- DART는 분당 100회 이상 호출하면 이용이 제한될 수 있어, 60초에 90회 이하로 호출합니다.
- 서버를 띄우지 않을 때는 `SCHEDULER_ENABLED=false`로 두고 `python -m app.ingest refresh` / `benchmark`를 직접 실행합니다.

## 5. 테스트
```bash
docker compose run --rm api pytest -q   # 263 passed (venv라면 pytest -q) — TEST_DATABASE_URL(stockdb_test), 외부 호출 없음(fake provider)
python -m app.ingest explain           # 인덱스 전후 EXPLAIN 비교 → docs/explain_result.md
```
DB 제약·전처리·TTL 갱신(외부 호출 횟수)·분석 SQL 손계산·포트폴리오 명세 시나리오·동시성·화면 흐름을 검증합니다. 결과는 [docs/07](docs/07_테스트_결과서.md).

## 6. 저장소 구조
```
app/
  api/        라우터 — market, stocks, watchlist, portfolios, analysis(분석·통계)
  core/       설정, DB 세션, 오류 형식, 요청 ID 로깅
  models/     SQLAlchemy 모델 (db/schema.sql과 1:1)
  schemas/    Pydantic 요청·응답
  providers/  외부 소스 인터페이스 + pykrx·yfinance·DART·SEC 구현
  services/   환율(TTL·lock)·갱신·포트폴리오 계산·매력도 점수·비교군 상세 수집(hydration)·앱 안 스케줄러
  ingest/     수집·전처리·적재 CLI (python -m app.ingest), 매력도 비교군(benchmark)
  queries/    조회·분석 SQL 원문 (text()로 실행)
web/          index.html · stocks.html · stock.html · portfolio.html, css/(tokens·base·components·pages), js/
db/           schema.sql · indexes.sql · views.sql · init/(테스트 DB 생성) · migrations/(기존 DB 갱신 001~003)
config/       universe.yaml(노출 종목·지수·경쟁 그룹·비교군 후보, 첫 소속 그룹 = 주 그룹) · scoring.yaml(투자 성향 프리셋·축소 계수)
sample_data/  재현용 소량 CSV
docs/         문서 01~09, ASSUMPTIONS, smoke test·EXPLAIN 결과, screenshots/
tests/        pytest
```

## 7. 문서
| 문서 | 내용 |
|---|---|
| [01 프로젝트 기획서](docs/01_프로젝트_기획서.md) | 배경·문제 정의·목적·기능·데이터·개발 환경 |
| [02 요구사항 정의서](docs/02_요구사항_정의서.md) | REQ-ID·중요도·구현 상태(근거 테스트 ID) |
| [03 데이터 조사·정의서](docs/03_데이터_조사_정의서.md) | 출처·원본/DB 컬럼·전처리·적재 결과 |
| [04 도메인 모델 정의서](docs/04_도메인_모델_정의서.md) | 명사 추출 → Entity → 속성 → 관계 |
| [05 ERD 및 DB 설계서](docs/05_ERD_및_DB설계서.md) | ERD·테이블 정의·정규화·의도적 비정규화·인덱스 EXPLAIN·SQL 요소 |
| [06 기능·API 정의서](docs/06_기능_API_정의서.md) | 엔드포인트 표·실제 요청/응답 예시·화면↔API |
| [07 테스트 결과서](docs/07_테스트_결과서.md) | pytest 결과·수동 UI 점검 체크리스트 |
| [08 최종 결과보고서](docs/08_최종_결과보고서.md) | 전체 정리·주요 SQL·문제 해결·회고·발표 흐름 |
| [09 매력도 점수 정의서](docs/09_매력도_점수_정의서.md) | 지표 정의·NULL 사유, 로버스트 Z·섹터 중립화·프리셋·100·Φ, Min-Max 미사용 사유 |
| [ASSUMPTIONS](docs/ASSUMPTIONS.md) | 가정·결정·미확인 사항 |

## 8. 데이터 출처와 이용 조건
| 출처 | 용도 | 비고 |
|---|---|---|
| pykrx (KRX 정보데이터시스템, 비공식) | KR 일봉·지수·시총·PER/PBR (기본) | 1.2.x는 시총·펀더멘털·지수에 KRX 회원 로그인 필요 |
| yfinance (Yahoo Finance, 비공식) | US 일봉·지수·밸류에이션, 환율, KR 대체 소스 | 개인·학습 목적, 원본 재배포 안 함 |
| OpenDART (금융감독원) | KR 재무(연결)·공시 | 인증키 필요, 일일 호출 한도·분당 100회 이상 시 이용 제한 → 60초 90회 이하로 호출 |
| SEC EDGAR | US 재무(XBRL companyfacts)·공시 | API 키 없음, 이메일 포함 User-Agent 필수 |

pykrx·yfinance는 비공식 라이브러리로 사이트 변경 시 동작하지 않을 수 있으며, 데이터 이용 조건은 각 원 사이트(KRX, Yahoo) 약관을 따릅니다. 저장소에는 소량 샘플만 커밋하고 전체 데이터는 적재 스크립트로 생성합니다.

## 9. 한계
- 인증 없음: 1차는 단일 사용자(데모) 모드로 로컬·시연 전용. 로그인은 2차 범위
- 시세는 일봉 기준(장중 실시간 아님). 장 마감 전 당일 봉은 적재하지 않음
- 증분 적재는 과거 수정주가의 소급 조정(배당·분할)을 반영하지 못함 → 필요 시 `prices --full`
- 재무는 KR K-IFRS 연결·US US-GAAP로 회계기준이 다름. 일부 연도·항목은 원천에 값이 없어 NULL(ASSUMPTIONS A-41)
- KRX 제공 PER/EPS의 산정 기준은 DART 연결 재무 기반 계산과 다를 수 있음(A-38)
- 매력도는 비교 표본(노출 25 + 비교군 121종목) 안에서 같은 시장끼리 비교한 상대적 위치(팩터 점수)이며 수익률 예측이 아님. 재무는 최신 FY 1개년 기준(docs/09 8절)
- 비교군 후보 풀은 직접 정의(섹터가 KRX 업종·GICS와 1:1이 아님). 미국 2차전지처럼 적자 소형주가 많은 그룹은 섹터 중립화로 그룹 안 상위 종목 점수가 크게 오를 수 있음 — 시장 특성으로 보고 그대로 둠(ASSUMPTIONS A-107)
- 미구현 선택 기능: 분기 재무, 투자 스타일 체크리스트, 시나리오 API, 관심종목 균등 배분 미리보기, 관심종목 정렬 변경 화면(API는 있음)
