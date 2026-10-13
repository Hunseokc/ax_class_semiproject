# StockMind

국내(KOSPI·KOSDAQ)·미국(NASDAQ·NYSE) 주식의 시세·지수·환율을 한 DB에 모아, 한 화면에서 같은 기준(원화 환산·일봉)으로 비교해 보는 **주식 분석 대시보드**입니다.

- 흩어진 원천 데이터(pykrx·yfinance)를 수집·전처리해 PostgreSQL 정규화 스키마에 적재합니다.
- FastAPI 조회 API와 바닐라 HTML/CSS/JS 화면으로 보여 줍니다. 조회 API는 외부 소스를 직접 부르지 않고 DB 값만 씁니다.
- 4인 팀(시니어 1 · 주니어 3)이 6단계로 나눠 만들고 있으며, 현재 **Stage 1(MVP, v1.0)** 까지 완료됐습니다.

> 시세는 일봉 기준이며 장중 실시간이 아닙니다. 이 프로젝트의 어떤 정보도 투자 권유가 아닙니다.

## 화면

### 대시보드 홈 — 주요 지수·환율
KOSPI·KOSDAQ·S&P 500·NASDAQ·Dow Jones와 USD/KRW의 최신값, 전일 대비 등락, 1개월·3개월·1년 스파크라인을 보여 줍니다. 그날 장이 열리지 않은 시장은 `직전 거래일` 배지로 구분합니다.

![대시보드 홈](docs/assets/screenshots/home.png)

### 주식 리스트 — 거래량·시가총액 순위
국내·미국 탭, 거래량/시가총액 정렬, 이름·티커 검색, 경쟁 그룹 필터를 지원합니다. `전체` 탭은 시장마다 거래량 단위가 달라 시가총액(원화 환산) 순위만 제공합니다.

![주식 리스트](docs/assets/screenshots/stocks.png)

### 종목 상세 — 가격 차트·핵심 정보
1M·3M·6M·1Y 기간의 종가 추이와 거래량, 시가총액·PER·PBR을 보여 줍니다.

![종목 상세](docs/assets/screenshots/stock_detail.png)

## 기술 스택

| 구분 | 사용 기술 |
|---|---|
| 백엔드 | Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2.x (동기, 원문 SQL `backend/app/queries/*.sql` + `text()`) |
| DB | PostgreSQL 16 — 테이블 10 · VIEW 2 · 보조 인덱스 6 (Stage 1) |
| 수집 | pykrx(국내 시세·지수·밸류에이션), yfinance(미국 시세·지수, USD/KRW) |
| 프론트엔드 | 바닐라 HTML/CSS/JS (ES Modules, 빌드 없음) · Chart.js (CDN) |
| 실행·테스트 | Docker Compose · pytest |

## 아키텍처

```
pykrx · yfinance ──▶ providers/ ──▶ ingest/ (전처리·이상 행 격리·upsert) ──▶ PostgreSQL
                                                                              │
              브라우저 (frontend/) ◀── FastAPI /api/v1 (queries/*.sql) ◀───────┘
```

- **수집과 조회 분리**: 외부 호출은 `python -m app.ingest` 명령에서만 합니다. 화면이 부르는 API는 DB만 읽습니다.
- **재적재 안전(멱등)**: 같은 데이터를 다시 적재해도 행 수가 늘지 않도록 upsert로 넣습니다.
- **이상 행 격리**: 고가<저가, 음수 거래량 같은 행은 DB에 넣지 않고 `backend/data/quarantine/`에 사유와 함께 남깁니다.
- **금액은 `Decimal`/`NUMERIC`**: 가격·비율 계산에 float을 쓰지 않습니다. 해외 종목은 원화 환산값을 함께 제공합니다.
- **일관된 에러 형식**: 모든 오류는 `{"error": {"code", "message", "detail"}}`로 응답합니다.

## 빠르게 실행하기

필요한 것: Docker Desktop

```bash
# 1) 환경 변수 파일 준비
cp .env.example .env

# 2) DB + API 서버 실행 (개발 모드: 소스 수정 시 자동 재시작)
docker compose -f compose.yml -f compose.dev.yml up -d --build

# 3) 스키마 생성 → 종목·지수 마스터 → 샘플 시세 적재
docker compose run --rm api python -m app.ingest init-db
docker compose run --rm api python -m app.ingest master --offline
docker compose run --rm api python -m app.ingest import-sample
```

브라우저에서 http://localhost:8000 을 열면 대시보드가 보입니다. API 문서는 http://localhost:8000/docs 에 있습니다.

### 실제 데이터로 수집하기 (선택)

샘플 대신 실제 시세를 받으려면 아래 명령을 씁니다. 국내 시세를 pykrx로 받을 때는 `.env`에 KRX 회원 계정(`KRX_ID`, `KRX_PW`)이 필요합니다. pykrx가 막히면 `PRICE_SOURCE_KR=yfinance`로 바꿔 `.KS`/`.KQ` 심볼로 받습니다.

```bash
docker compose run --rm api python -m app.ingest prices --full   # 종목 일봉 (특정 종목만: --tickers 005930 AAPL)
docker compose run --rm api python -m app.ingest indices --full  # 지수 일봉
docker compose run --rm api python -m app.ingest fx --full       # USD/KRW 일별 환율
```

대상 종목·지수 목록은 [`backend/config/universe.yaml`](backend/config/universe.yaml)에서 정합니다.

### 테스트

```bash
docker compose run --rm api pytest -q
```

스키마 제약(잘못된 행 거부·CASCADE), ORM↔DDL 일치, 재적재 시 행 수 불변, API 응답·오류 형식을 검증합니다. 테스트는 별도 DB(`stockdb_test`)에서 돌아갑니다.

## API (Stage 1)

| Method | URL | 기능 |
|---|---|---|
| GET | `/health`, `/health/db` | 프로세스·DB 연결 확인 |
| GET | `/api/v1/market/indices` | 지수별 최신값·등락·최근 1년 스파크라인 |
| GET | `/api/v1/market/fx` | USD/KRW 최신값·전일 대비·최근 1년 추이 |
| GET | `/api/v1/peer-groups` | 경쟁 그룹 목록 |
| GET | `/api/v1/stocks` | 주식 리스트 (`country`, `sort`, `order`, `group`, `q`, `limit`, `offset`) |
| GET | `/api/v1/stocks/{market}/{ticker}` | 종목 기본 정보 + 최신 시세·밸류에이션 |
| GET | `/api/v1/stocks/{market}/{ticker}/candles` | 기간 일봉 (`range=1m·3m·6m·1y`) |

요청·응답 예시와 에러 코드는 [docs/06_기능_API_정의서.md](docs/06_기능_API_정의서.md)에 있습니다.

## 폴더 구조

```
ax_stockmind/
├─ backend/
│  ├─ app/
│  │  ├─ api/          라우터 (market, stocks, health)
│  │  ├─ core/         설정·DB 연결·에러·로깅
│  │  ├─ ingest/       수집·적재 CLI (python -m app.ingest)
│  │  ├─ providers/    외부 데이터 소스 어댑터 (pykrx, yfinance)
│  │  ├─ queries/      조회용 원문 SQL
│  │  ├─ models/       ORM (schema.sql과 1:1)
│  │  └─ schemas/      API 요청·응답 모델
│  ├─ db/              schema.sql · indexes.sql · views.sql
│  ├─ config/          universe.yaml (대상 종목·지수)
│  ├─ sample_data/     오프라인 실행용 샘플 CSV
│  └─ tests/
├─ frontend/           index · stocks · stock · portfolio 화면, css/, js/
├─ docs/               기획서·요구사항·데이터 조사·도메인 모델·ERD·API 정의서
└─ team/               팀 작업 가이드·역할 분담·로드맵·단계별 프롬프트
```

## 문서

| 문서 | 내용 |
|---|---|
| [01 프로젝트 기획서](docs/01_프로젝트_기획서.md) | 배경·문제 정의·주요 기능 |
| [02 요구사항 정의서](docs/02_요구사항_정의서.md) | 기능·비기능 요구사항 |
| [03 데이터 조사 정의서](docs/03_데이터_조사_정의서.md) | 데이터 소스·수집 범위·이용 조건 |
| [04 도메인 모델 정의서](docs/04_도메인_모델_정의서.md) | 핵심 개념과 관계 |
| [05 ERD 및 DB 설계서](docs/05_ERD_및_DB설계서.md) | ERD·테이블 정의·인덱스·VIEW·검증 결과 |
| [06 기능·API 정의서](docs/06_기능_API_정의서.md) | 엔드포인트·요청/응답 예시·에러 코드 |

## 개발 로드맵

| 단계 | 결과물 | 상태 |
|---|---|---|
| Stage 0 | 뼈대·개발 환경 | ✅ v0.1 |
| Stage 1 | MVP — 지수·환율 홈, 주식 리스트, 종목 상세, 시세 수집 | ✅ v1.0 |
| Stage 2 | 사용자 기능 — 관심종목·모의 포트폴리오 | |
| Stage 3 | 실데이터 — 재무·공시 포함 4개 소스 수집, 주기적 갱신 | |
| Stage 4 | 분석 — 매력도·경쟁 비교·통계 | |
| Stage 5 | 고도화 — 메모·목표가·통계 확장 | |
| Stage 6 | 홈 대시보드 개편·상단 검색·최종 문서 | |

팀 작업 방식(브랜치·PR 규칙, Claude Code 사용법)은 [team/00_팀_작업_가이드.md](team/00_팀_작업_가이드.md)를 보세요.

## 데이터 이용 조건

- **pykrx**: KRX 정보데이터시스템 비공식 라이브러리입니다. 1.2.x는 시총·펀더멘털·지수 조회에 KRX 회원 로그인이 필요합니다.
- **yfinance**: Yahoo Finance 비공식 라이브러리입니다. 개인·학습 목적으로만 쓰고 원본 데이터를 재배포하지 않습니다. 저장소에는 소량 샘플만 포함합니다.
- OpenDART·SEC EDGAR(재무·공시)는 Stage 3에서 추가됩니다.
