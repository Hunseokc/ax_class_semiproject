# 05. ERD 및 DB 설계서 (Stage 3 범위)

> **상태: Stage 3 확정 (v3.0).** Stage 1 테이블 10개 + Stage 2 사용자 테이블 4개 + Stage 3 재무·공시 테이블 2개, VIEW 2개, 보조 인덱스 10개, 트리거 2개를 실제 DDL 기준으로 담았다. 이후 단계에서 D가 테이블을 추가할 때 이 문서의 해당 절을 함께 확장한다.
> (Stage 4+: 매력도·비교군·섹터 — 의도적 비정규화 5-2, `v_stock_metrics`, EXPLAIN 비교도 그때 채운다. `watchlist_items`의 메모·목표가·`updated_at`은 Stage 5 — 기존 DB는 migration 004.)
> **Stage 4 계약**(매력도 테이블 4개, `peer_group_members.is_primary`, `v_stock_metrics` 컬럼, 마이그레이션 001·002)은 9절, Stage 5-D(006)는 10절, Stage 6(005·007)은 11절에 모았다. 1~8절의 Stage 4·5 반영은 Stage 6 최종 문서에서 한다.

- DDL 원문: `backend/db/schema.sql` → `backend/db/indexes.sql` → `backend/db/views.sql` 순서로 실행 (`python -m app.ingest init-db`가 같은 순서로 적용)
- DBMS: PostgreSQL 16 / 테이블 16개, VIEW 2개, 보조 인덱스 10개, 트리거 2개(updated_at 자동 갱신 — portfolios·portfolio_items)
- 금액·가격은 모두 `NUMERIC` (float 사용 안 함), 시각은 모두 `TIMESTAMPTZ`
- ORM(`backend/app/models/__init__.py`)은 `schema.sql`과 1:1이며 `tests/test_schema.py`가 일치를 검증한다.

## 1. ERD

```mermaid
erDiagram
    markets ||--o{ stocks : "상장"
    markets |o--o{ indices : "대표 지수"
    stocks ||--o{ peer_group_members : ""
    peer_groups ||--o{ peer_group_members : ""
    stocks ||--o{ daily_prices : "일봉"
    stocks ||--o{ valuation_snapshots : "밸류에이션"
    stocks ||--o{ financial_statements : "재무"
    stocks ||--o{ disclosures : "공시"
    indices ||--o{ index_daily_prices : "지수 일봉"
    stocks |o--o{ ingestion_logs : "SET NULL"
    users ||--o{ watchlist_items : ""
    stocks ||--o{ watchlist_items : ""
    users ||--o{ portfolios : "소유"
    portfolios ||--o{ portfolio_items : "담기"
    stocks ||--o{ portfolio_items : "RESTRICT"

    markets {
        smallint market_id PK
        varchar code UK
        char country
        char currency
        varchar timezone
    }
    stocks {
        int stock_id PK
        smallint market_id FK
        varchar ticker
        varchar name
        varchar name_en
        varchar corp_code
        varchar cik
        boolean is_active
    }
    peer_groups {
        int group_id PK
        varchar name UK
        text description
    }
    peer_group_members {
        int group_id PK,FK
        int stock_id PK,FK
    }
    daily_prices {
        int stock_id PK,FK
        date trade_date PK
        numeric open
        numeric high
        numeric low
        numeric close
        bigint volume
    }
    valuation_snapshots {
        int stock_id PK,FK
        date as_of PK
        numeric per
        numeric pbr
        numeric eps
        numeric bps
        numeric market_cap
        bigint shares_outstanding
        varchar source
    }
    financial_statements {
        int fin_id PK
        int stock_id FK
        date period_end
        varchar period_type
        numeric revenue
        numeric operating_income
        numeric net_income
        numeric total_assets
        numeric total_equity
        numeric total_debt
        varchar data_source
        varchar accounting_std
    }
    disclosures {
        int disclosure_id PK
        int stock_id FK
        varchar rcept_no UK
        text title
        varchar report_type
        timestamptz filed_at
        text url
        varchar data_source
    }
    indices {
        smallint index_id PK
        varchar code UK
        varchar name
        smallint market_id FK
        varchar source_symbol
        smallint display_order
    }
    index_daily_prices {
        smallint index_id PK,FK
        date trade_date PK
        numeric open
        numeric high
        numeric low
        numeric close
    }
    fx_rates {
        int fx_id PK
        timestamptz rate_at
        numeric usd_krw
        varchar granularity
        varchar source
    }
    ingestion_logs {
        int log_id PK
        varchar source
        varchar job_type
        int stock_id FK
        varchar status
        int rows_loaded
        text error
        timestamptz started_at
        timestamptz finished_at
    }
    users {
        int user_id PK
        varchar nickname UK
        timestamptz created_at
    }
    watchlist_items {
        int user_id PK,FK
        int stock_id PK,FK
        int sort_order
        timestamptz added_at
    }
    portfolios {
        int portfolio_id PK
        int user_id FK
        varchar name
        numeric seed_krw
        timestamptz created_at
        timestamptz updated_at
    }
    portfolio_items {
        int item_id PK
        int portfolio_id FK
        int stock_id FK
        int quantity
        numeric ref_price
        numeric ref_fx_rate
        date ref_date
        text memo
        numeric cost_krw "GENERATED"
        timestamptz created_at
        timestamptz updated_at
    }
```

`fx_rates`는 FK 관계가 없는 독립 테이블이다(조회 시점에 참조하며, 담은 시점 환율은 `portfolio_items`에 복사 — 5절).

## 2. 테이블 목록

| 영역 | 테이블 | 설명 | PK |
|---|---|---|---|
| 마스터 | markets | 시장(통화·국가·시간대) | market_id |
| 마스터 | stocks | 종목 | stock_id, UQ (market_id, ticker) |
| 마스터 | peer_groups | 경쟁 그룹 | group_id |
| 마스터 | peer_group_members | 종목↔그룹 N:M | (group_id, stock_id) |
| 시계열 | daily_prices | 종목 일봉(수정주가) | (stock_id, trade_date) |
| 시계열 | valuation_snapshots | PER·PBR·시총 스냅샷 | (stock_id, as_of) |
| 시계열 | price_quotes | 현재가 스냅샷(KIS, 관심종목·상세 화면 표시 전용 — 12절) | stock_id |
| 재무 | financial_statements | 재무제표(FY 5개년) | fin_id, UQ (stock_id, period_end, period_type) |
| 공시 | disclosures | 공시 목록(최근 1년) | disclosure_id, UQ (rcept_no) |
| 배경 | indices | 지수 정의 | index_id |
| 배경 | index_daily_prices | 지수 일봉 | (index_id, trade_date) |
| 배경 | fx_rates | USD/KRW | fx_id, UQ (granularity, rate_at) |
| 사용자 | users | 사용자(인증 없음, 기본 사용자 demo는 `master`가 시드, 배포의 게스트는 `guest-…`) | user_id |
| 사용자 | watchlist_items | 관심종목 N:M + 정렬 순서 | (user_id, stock_id) |
| 사용자 | portfolios | 모의 포트폴리오 | portfolio_id, UQ (user_id, name) |
| 사용자 | portfolio_items | 담은 종목 (담은 시점 가격·환율 복사) | item_id, UQ (portfolio_id, stock_id) |
| 운영 | ingestion_logs | 적재·갱신 로그 | log_id |

## 3. 테이블 정의서

#### `markets`

| 컬럼 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| market_id | smallint | N | 자동 증가 | PK | 시장 ID |
| code | varchar(10) | N |  | UQ | KOSPI / KOSDAQ / NASDAQ / NYSE |
| country | char(2) | N |  |  | 국가 (KR/US) |
| currency | char(3) | N |  |  | 통화 (KRW/USD) |
| timezone | varchar(40) | N |  |  | Asia/Seoul / America/New_York |

제약: `CHECK (country IN ('KR','US'))` / `CHECK (currency IN ('KRW','USD'))`

#### `stocks`

| 컬럼 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| stock_id | integer | N | 자동 증가 | PK | 종목 ID |
| market_id | smallint | N |  | UQ(복합), FK→markets | 시장 ID |
| ticker | varchar(16) | N |  | UQ(복합) | 거래소 종목 코드 |
| name | varchar(128) | N |  |  | 이름 |
| name_en | varchar(128) | Y |  |  | 영문 이름 |
| corp_code | varchar(16) | Y |  |  | OpenDART 고유번호 (KR, `master`가 DART 매핑으로 채움 — `--offline`이면 NULL) |
| cik | varchar(10) | Y |  |  | SEC CIK 10자리 (US, `master`가 SEC 매핑으로 채움 — `--offline`이면 NULL) |
| is_active | boolean | N | true |  | 수집·점수 계산 대상 여부 (false면 데이터만 보존) |

제약: `UNIQUE (market_id, ticker)` — 같은 티커라도 시장이 다르면 다른 종목

#### `peer_groups`

| 컬럼 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| group_id | integer | N | 자동 증가 | PK | 경쟁 그룹 ID |
| name | varchar(64) | N |  | UQ | 이름 |
| description | text | Y |  |  | 설명 |

#### `peer_group_members`

| 컬럼 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| group_id | integer | N |  | PK, FK→peer_groups (CASCADE) | 경쟁 그룹 ID |
| stock_id | integer | N |  | PK, FK→stocks (CASCADE) | 종목 ID |
| is_primary | boolean | N | false |  | 매력도 섹터 중립화의 주 그룹 여부 (Stage 4) |

제약(Stage 4): 부분 UNIQUE 인덱스 `CREATE UNIQUE INDEX ux_pgm_primary ON peer_group_members (stock_id) WHERE is_primary` — 종목당 주 그룹 최대 1개

#### `daily_prices`

| 컬럼 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| stock_id | integer | N |  | PK, FK→stocks (CASCADE) | 종목 ID |
| trade_date | date | N |  | PK | 시장 현지 날짜 |
| open / high / low | numeric(18,4) | N |  |  | 시가 / 고가 / 저가 |
| close | numeric(18,4) | N |  |  | 수정주가 |
| volume | bigint | N |  |  | 거래량(주) |

제약: `CHECK (volume >= 0)` / `CHECK (high >= low)` / `CHECK (low > 0)` — 0·음수 가격은 이상 행으로 격리

#### `valuation_snapshots`

| 컬럼 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| stock_id | integer | N |  | PK, FK→stocks (CASCADE) | 종목 ID |
| as_of | date | N |  | PK | 기준일 |
| per / pbr | numeric(18,4) | Y |  |  | 적자·미제공은 NULL |
| eps / bps | numeric(18,4) | Y |  |  | 주당순이익 / 주당순자산 |
| market_cap | numeric(26,0) | Y |  |  | 종목 통화 기준 |
| shares_outstanding | bigint | Y |  |  | 발행(상장)주식수 |
| source | varchar(20) | N |  |  | PYKRX / YFINANCE / DERIVED |

제약: `CHECK (market_cap >= 0)` / `CHECK (shares_outstanding >= 0)` / `CHECK (source IN ('PYKRX','YFINANCE','DERIVED'))`

#### `financial_statements`

| 컬럼 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| fin_id | integer | N | 자동 증가 | PK | 재무 행 ID |
| stock_id | integer | N |  | UQ(복합), FK→stocks (CASCADE) | 종목 ID |
| period_end | date | N |  | UQ(복합) | 결산일 |
| period_type | varchar(4) | N |  | UQ(복합) | FY / Q1~Q4 (현재 FY만 적재) |
| revenue | numeric(24,2) | Y |  |  | 매출액 |
| operating_income | numeric(24,2) | Y |  |  | 영업이익 |
| net_income | numeric(24,2) | Y |  |  | 순이익 (지배기업 소유주 귀속 우선) |
| total_assets | numeric(24,2) | Y |  |  | 자산총계 |
| total_equity | numeric(24,2) | Y |  |  | 자본총계 (지배기업 소유주 귀속 우선) |
| total_debt | numeric(24,2) | Y |  |  | 부채총계 (KR Liabilities / US Liabilities) |
| data_source | varchar(20) | N |  |  | DART / SEC / YFINANCE |
| accounting_std | varchar(20) | Y |  |  | K-IFRS / US-GAAP |

금액은 종목 통화 기준. 계정을 못 찾은 항목은 NULL로 두고, 대체 계정명을 쓴 경우 `ingestion_logs`에 남긴다.

제약: `CHECK (period_type IN ('FY','Q1','Q2','Q3','Q4'))` / `CHECK (data_source IN ('DART','SEC','YFINANCE'))` / `UNIQUE (stock_id, period_end, period_type)`

#### `disclosures`

| 컬럼 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| disclosure_id | integer | N | 자동 증가 | PK | 공시 ID |
| stock_id | integer | N |  | FK→stocks (CASCADE) | 종목 ID |
| rcept_no | varchar(64) | N |  | UQ | DART 접수번호 / SEC accession number |
| title | text | N |  |  | 공시 제목 |
| report_type | varchar(100) | Y |  |  | 공시유형명(DART) / 서식(SEC: 10-K·10-Q·8-K …) |
| filed_at | timestamptz | N |  |  | 접수(제출) 시각 |
| url | text | Y |  |  | 원문 링크 |
| data_source | varchar(20) | N |  |  | DART / SEC |

제약: `CHECK (data_source IN ('DART','SEC'))` / `UNIQUE (rcept_no)` — 재적재 시 접수번호로 upsert

#### `indices`

| 컬럼 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| index_id | smallint | N | 자동 증가 | PK | 지수 ID |
| code | varchar(16) | N |  | UQ | KOSPI / KOSDAQ / SPX / IXIC / DJI |
| name | varchar(64) | N |  |  | 이름 |
| market_id | smallint | Y |  | FK→markets | 시장 ID |
| source_symbol | varchar(32) | N |  |  | 라이브러리 조회용 심볼 (1001, ^GSPC …) |
| display_order | smallint | N | 0 |  | 화면 표시 순서 |

#### `index_daily_prices`

| 컬럼 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| index_id | smallint | N |  | PK, FK→indices (CASCADE) | 지수 ID |
| trade_date | date | N |  | PK | 거래일(현지) |
| open / high / low | numeric(18,4) | Y |  |  | 시가 / 고가 / 저가 |
| close | numeric(18,4) | N |  |  | 종가 |

제약: `CHECK (close > 0)`

#### `fx_rates`

| 컬럼 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| fx_id | integer | N | 자동 증가 | PK | 환율 행 ID |
| rate_at | timestamptz | N |  | UQ(복합) | 환율 기준 시각 |
| usd_krw | numeric(12,4) | N |  |  | 1달러당 원 |
| granularity | varchar(8) | N |  | UQ(복합) | SNAPSHOT(조회 시각) / DAILY(해당 일자 00:00 Asia/Seoul) |
| source | varchar(20) | N | 'YFINANCE' |  | 데이터 출처 |

제약: `CHECK (usd_krw > 0)` / `CHECK (granularity IN ('SNAPSHOT','DAILY'))` / `UNIQUE (granularity, rate_at)`

#### `ingestion_logs`

| 컬럼 | 타입 | NULL | 기본값 | 키 | 설명 |
|---|---|---|---|---|---|
| log_id | integer | N | 자동 증가 | PK | 로그 ID |
| source | varchar(20) | N |  |  | PYKRX / YFINANCE / DART / SEC / INTERNAL / REFRESH(갱신 서비스의 작업 단위 행) |
| job_type | varchar(30) | N |  |  | PRICES / INDICES / FX / VALUATION / FINANCIALS / DISCLOSURES / MASTER (이후 단계에서 확장) |
| stock_id | integer | Y |  | FK→stocks (SET NULL) | 종목 단위 작업일 때만 |
| status | varchar(10) | N |  |  | SUCCESS / FAILED / SKIPPED |
| rows_loaded | integer | N | 0 |  | 적재 행 수 |
| error | text | Y |  |  | 실패 사유 / 격리 행 사유 |
| started_at | timestamptz | N |  |  | 시작 시각 |
| finished_at | timestamptz | Y |  |  | 종료 시각 (`>= started_at`) |

쓰는 값: `MASTER`(INTERNAL `universe` + DART `corp_code`·SEC `cik` 매핑), `PRICES`(PYKRX·YFINANCE, 종목 1건당 1행 또는 국내 대량·미국 묶음 1행), `INDICES`(지수 1건당 1행), `FX`(YFINANCE), `VALUATION`(종목 1건당 1행), `FINANCIALS`·`DISCLOSURES`(DART·SEC, 종목 1건당 1행).
갱신 서비스(`services/refresh.py`)는 작업마다 `source='REFRESH'`·`stock_id` NULL인 작업 단위 행을 따로 남기고, **이 행의 마지막 성공 시각으로만 TTL을 판단**한다(CLI가 남긴 종목 단위 행으로 TTL을 채우지 않음). 일부 종목만 실패한 작업은 FAILED로 남겨 TTL을 시작하지 않는다.

제약: `CHECK (job_type IN ('PRICES','INDICES','FX','VALUATION','FINANCIALS','DISCLOSURES','MASTER'))` / `CHECK (status IN ('SUCCESS','FAILED','SKIPPED'))` / `CHECK (rows_loaded >= 0)` / `CHECK (finished_at IS NULL OR finished_at >= started_at)`

#### `users`

| 컬럼 | 타입 | NULL | 기본값/생성식 | 키 | 설명 |
|---|---|---|---|---|---|
| user_id | integer | N | 자동 증가 | PK | 사용자 ID |
| nickname | character varying(50) | N |  | UQ | 닉네임 |
| created_at | timestamp with time zone | N | now() |  | 생성 시각 |

요청 사용자는 `get_current_user_id`(설정 `DEFAULT_USER_ID`, 기본 1 = demo)가 정한다. 배포(`GUEST_SESSION_ENABLED=true`)에서는 첫 쓰기 요청 때 게스트 행(`nickname = 'guest-' + 16자리 16진수`)을 만들고 demo의 `watchlist_items`·`portfolios`·`portfolio_items`를 복사한다(`app/services/guest.py` — 포트폴리오는 사용자 안에서 이름이 유일하므로 이름으로 원본과 짝지어 항목을 옮긴다). 2차에서 로그인으로 대체한다.

#### `watchlist_items`

| 컬럼 | 타입 | NULL | 기본값/생성식 | 키 | 설명 |
|---|---|---|---|---|---|
| user_id | integer | N |  | PK, FK→users (CASCADE) | 사용자 ID |
| stock_id | integer | N |  | PK, FK→stocks (CASCADE) | 종목 ID |
| sort_order | integer | N | 0 |  | 표시 순서 |
| added_at | timestamp with time zone | N | now() |  | 추가 시각 |
| memo | character varying(200) | Y |  |  | 사용자 메모 (Stage 5) |
| target_price | numeric(20,4) | Y |  | CHECK > 0 | 목표가(종목 통화) (Stage 5) |
| updated_at | timestamp with time zone | N | now() |  | 수정 시각 — 트리거 `trg_watchlist_items_updated_at`가 갱신 (Stage 5) |

메모·목표가·`updated_at`은 Stage 5에서 추가했다. 기존 DB는 `python -m app.ingest migrate 004_watchlist_memo`(멱등, 기존 행 값은 그대로).

#### `portfolios`

| 컬럼 | 타입 | NULL | 기본값/생성식 | 키 | 설명 |
|---|---|---|---|---|---|
| portfolio_id | integer | N | 자동 증가 | PK | 포트폴리오 ID |
| user_id | integer | N |  | UQ(복합), FK→users (CASCADE) | 사용자 ID |
| name | character varying(100) | N |  | UQ(복합) | 이름 |
| seed_krw | numeric(20,0) | N |  |  | 투자 시드(원) |
| created_at | timestamp with time zone | N | now() |  | 생성 시각 |
| updated_at | timestamp with time zone | N | now() |  | 수정 시각(트리거 갱신) |

제약: `CHECK ((seed_krw > (0)::numeric))` / `UNIQUE (user_id, name)`

#### `portfolio_items`

| 컬럼 | 타입 | NULL | 기본값/생성식 | 키 | 설명 |
|---|---|---|---|---|---|
| item_id | integer | N | 자동 증가 | PK | 담은 항목 ID |
| portfolio_id | integer | N |  | UQ(복합), FK→portfolios (CASCADE) | 포트폴리오 ID |
| stock_id | integer | N |  | UQ(복합), FK→stocks (RESTRICT) | 담긴 종목은 삭제 불가 |
| quantity | integer | N |  |  | 수량(정수 주) |
| ref_price | numeric(18,4) | N |  |  | 담은 시점 종가(종목 통화) |
| ref_fx_rate | numeric(12,4) | N | 1 |  | 담은 시점 환율 (KRW 종목은 1) |
| ref_date | date | N |  |  | ref_price의 거래일 |
| memo | text | Y |  |  | 메모 |
| created_at | timestamp with time zone | N | now() |  | 생성 시각 |
| updated_at | timestamp with time zone | N | now() |  | 수정 시각(트리거 갱신) |
| cost_krw | numeric(24,2) | Y | GENERATED: (((quantity)::numeric * ref_price) * ref_fx_rate) |  | 원가(원) |

제약: `CHECK ((quantity > 0))` / `CHECK ((ref_price > (0)::numeric))` / `CHECK ((ref_fx_rate > (0)::numeric))` / `UNIQUE (portfolio_id, stock_id)`. "원가 합계 ≤ 시드"는 행 간 제약이라 CHECK로 걸 수 없어 서비스가 트랜잭션 + 포트폴리오 행 잠금(`SELECT … FOR UPDATE`)으로 보장한다.

## 4. 정규화 (Stage 3 범위)

- **1NF**: 모든 컬럼이 원자값. 배열·쉼표 구분 값 없음.
- **2NF**: 복합 PK 테이블(`daily_prices`, `valuation_snapshots`, `index_daily_prices`, `peer_group_members`, `watchlist_items`)의 비키 컬럼은 PK 전체에 종속. `financial_statements`는 대리키 `fin_id`를 두되 자연키 `(stock_id, period_end, period_type)`를 UNIQUE로 걸어 재무 값이 결산기 전체에 종속되게 한다.
- **3NF — `markets` 분리**: 통화·국가·시간대는 시장 단위 속성이므로 `stocks`에 반복하지 않는다(종목 → 시장 → 통화 이행적 종속 제거).
- **N:M 교차 테이블**: `peer_group_members` (국내·해외 종목 혼합 가능), `watchlist_items` (사용자 ↔ 종목, 속성 `sort_order`·`added_at`).
- **파생값은 저장하지 않음**: 같은 행 값만으로 계산되는 `portfolio_items.cost_krw`는 저장형 생성 컬럼(`GENERATED ALWAYS … STORED`)으로 두어 직접 쓰기를 막는다. 영업이익률·ROE도 저장하지 않고 `financials.sql`이 조회할 때 계산한다.

## 4-1. 의도적 비정규화 — `portfolio_items.ref_price`·`ref_fx_rate`·`ref_date`
- 형태: `daily_prices.close`와 `fx_rates.usd_krw`에서 가져올 수 있는 값을 항목 행에 복사해 둔다.
- 사유: "담은 시점의 가격과 환율"은 **그 시점에 확정된 변하지 않는 사실**이다. 시세 테이블은 수정주가 재계산(배당·분할)으로 과거 종가가 바뀌고, 환율도 SNAPSHOT이 새로 쌓이며 재적재·보정될 수 있다. 참조로만 연결하면 이런 갱신이 일어날 때 이미 담은 원가와 평가손익이 소급해서 바뀐다.
- 정합성: 항목 수정(PUT) 시 기준가·환율을 현재값으로 다시 저장하는 것만 허용한다(명세). `ref_date`로 어느 거래일 종가인지 추적할 수 있다.
- (원본 5-2 매력도 파생 테이블은 Stage 4에서 추가)

## 5. 인덱스 (Stage 3)

| 인덱스 | 대상 | 받치는 조회 | 비고 |
|---|---|---|---|
| (PK) | daily_prices (stock_id, trade_date) | 종목별 기간 일봉, 최신 2행 | 자동 |
| ix_stocks_name | stocks (name) | 이름 정렬·접두 검색 | 부분 일치는 순차 스캔 허용 |
| ix_daily_prices_trade_date | daily_prices (trade_date) | 특정 날짜 전 종목 | PK 선두가 stock_id라 별도 필요 |
| ix_index_prices_trade_date | index_daily_prices (trade_date) | 날짜 기준 전 지수 | |
| ix_fx_granularity_rate_at | fx_rates (granularity, rate_at DESC) | 최신 SNAPSHOT(TTL 판단) | |
| ix_ingestion_logs_job_finished | ingestion_logs (job_type, finished_at DESC) | 작업별 마지막 성공 시각 | |
| ix_peer_members_stock | peer_group_members (stock_id) | 종목 → 소속 그룹 | PK가 group_id 선두라 필요 |
| ix_watchlist_stock | watchlist_items (stock_id) | FK 역방향(CASCADE) | PK가 user_id 선두라 필요 |
| ix_portfolio_items_stock | portfolio_items (stock_id) | FK 역방향(RESTRICT 검사) | UQ가 portfolio_id 선두라 필요 |
| ix_fin_stock_type_end | financial_statements (stock_id, period_type, period_end DESC) | 종목별 최신 FY N건 (`financials.sql`) | UQ는 period_end가 period_type보다 앞이라 필터 후 정렬에 불리 |
| ix_disclosures_stock_filed | disclosures (stock_id, filed_at DESC) | 종목별 최근 공시 N건 (`disclosures.sql`) | |

(`valuation_snapshots (stock_id, as_of DESC)`는 PK 역방향 스캔과 중복이라 만들지 않는다.)

FK 컬럼 중 별도 인덱스가 없는 것은 PK·UNIQUE의 선두 컬럼으로 이미 인덱싱된다: `stocks.market_id`(UNIQUE 선두), `portfolios.user_id`(UNIQUE 선두), `portfolio_items.portfolio_id`(UNIQUE 선두), `financial_statements.stock_id`(UNIQUE 선두), `disclosures.stock_id`(`ix_disclosures_stock_filed` 선두), 복합 PK의 선두 컬럼들. `indices.market_id`(10행), `ingestion_logs.stock_id`는 행 수가 적어 생략했다.

## 6. VIEW (Stage 1~3)
| VIEW | 내용 | 주요 SQL 요소 | 사용처 |
|---|---|---|---|
| v_latest_price | 종목별 최신 종가·전일 종가·등락·등락률·거래량 | LATERAL, 서브쿼리 LIMIT 2, LAG, NULLIF | `stock_list.sql`, `stock_detail.sql` |
| v_fx_latest | 최신 USD/KRW 1행 (최신 rate_at, 동시각이면 SNAPSHOT 우선) | ORDER BY, LIMIT | `/stocks`의 `fx_rate_at`, 상세의 USD 원화 환산 |

환율 서비스(FxService)와 4시간 갱신이 넣은 SNAPSHOT이 있으면 그 행이, 없으면 `fx` 수집이 넣은 최신 DAILY 행이 나온다.

## 7. 검증 결과 (Stage 1~3)
| 검증 | 결과 |
|---|---|
| DDL 적용 (schema → indexes → views, 테스트 DB 카탈로그 조회) | 테이블 16, VIEW 2, 보조 인덱스 10, 트리거 2 |
| ORM ↔ DDL 컬럼 일치, Stage 1~3 외 테이블 없음 | `test_orm_matches_schema`, `test_tables_are_stage1_to_3_only` 통과 |
| 제약 위반 18건(고가<저가, 음수 거래량, 가격 0, PK·UNIQUE 중복, 없는 FK, 잘못된 국가·통화·granularity·job_type, 환율 0, 종료<시작 등) 거부, 종목 삭제 시 CASCADE | `test_constraints_reject_bad_rows`, `test_delete_cascades` 통과 |
| Stage 2 제약 위반 8건(관심종목 중복, 없는 사용자 FK, 시드 0, 포트폴리오 이름 중복, 수량 0, 담은 가격 0, 항목 종목 중복, 담긴 종목 삭제 RESTRICT) 거부, 사용자 삭제 시 CASCADE·`updated_at` 트리거 | `test_constraints_reject_bad_rows`(26건), `test_user_delete_cascades_and_updated_at_trigger` 통과 |
| Stage 3 제약 위반 5건(잘못된 결산 구분, 잘못된 재무 source, 재무 결산기 중복, 공시 접수번호 중복, 잘못된 공시 source) 거부 | `test_constraints_reject_bad_rows`(31건) 통과 |
| 같은 데이터 재적재 시 행 수 불변(upsert) | `test_ingest.py`의 샘플·전체 재적재, `test_load_financials_and_disclosures_upsert_and_are_idempotent` 통과 |
| 갱신 TTL·잠금·부분 실패 재시도 | `test_refresh.py` 9건 통과 (TTL 이내 외부 호출 0, 동시 요청 직렬화, 실패 종목만 30분 뒤 재시도) |
| 전체 테스트 (2026-10-15, v3.0) | `pytest -q` 194 passed |
| 실제 수집 적재 (2026-10-13, 개발 DB) | 25종목 `daily_prices` 12,276행, 지수 10개 4,960행, USD/KRW DAILY 516행, `ingestion_logs` 성공 41 / 실패 0 |
| 실제 수집 적재 (2026-10-15, 개발 DB — 4시간 자동 갱신 운영 후) | `valuation_snapshots` 25종목 3,913행(2025-10-15~2026-10-14), `financial_statements` 125행(25종목 × FY 5개년, DART 80 · SEC 45), `disclosures` 1,361행(DART 1,183 · SEC 178), USD/KRW DAILY 518 · SNAPSHOT 2 |

## 8. 이후 단계에서 채울 절

- 매력도 테이블·`v_stock_metrics`·마이그레이션 001·002 — Stage 4 (계약은 9절) / 비교군(`stocks.coverage`·`detail_synced_at`, 003) — Stage 4-D / 업종 섹터·데이터 유효기간(006) — Stage 5-D (10절)
- 인덱스 전후 `EXPLAIN (ANALYZE)` 비교, 분석 쿼리와 SQL 요소 정리 — Stage 5

## 9. Stage 4 — 매력도 (D 계약)

계산 정의는 `개발산출물/09_매력도_점수_정의서.md`(C). 새로 만드는 DB는 `schema.sql`에 반영되어 있고, 이미 적재된 DB는 마이그레이션으로 바꾼다.

### 9-1. 마이그레이션
| 파일 | 내용 | 실행 |
|---|---|---|
| `backend/db/migrations/001_scoring_v2.sql` | `peer_group_members.is_primary` + `ux_pgm_primary`, `scoring_presets`·`scoring_weights`·`stock_metric_values`·`stock_scores` 생성 | `python -m app.ingest migrate 001_scoring_v2` |
| `backend/db/migrations/002_presets.sql` | 프리셋 4종(aggressive·growth·balanced·value)과 가중치 20행 — 멱등 | `python -m app.ingest migrate 002_presets` |

둘 다 적용한 뒤 `python -m app.ingest scores`로 점수를 다시 만든다. `ingestion_logs.job_type` CHECK에는 `SCORES`가 추가된다(`schema.sql`). 마이그레이션 파일은 원본 그대로라 이 CHECK는 바꾸지 않으므로, 기존 DB는 `init-db --reset` → `master --offline` → `import-sample` → `seed-demo`로 다시 만든다(CLAUDE.md 10절).

### 9-2. 테이블 정의서

#### `scoring_presets`

| 컬럼 | 타입 | NULL | 기본값/생성식 | 키 | 설명 |
|---|---|---|---|---|---|
| preset_id | smallint | N | 자동 증가 | PK | 프리셋 ID |
| code | character varying(20) | N |  | UQ | aggressive / growth / balanced / value |
| name | character varying(50) | N |  |  | 화면 이름 (위험·성장·균형·가치) |
| description | text | Y |  |  | 설명 |
| sort_order | smallint | N | 0 |  | 화면 표시 순서 (위험 1 → 가치 4) |

`backend/config/scoring.yaml`에서 적재(init-db·migrate·scores 실행 시). 프리셋별 가중치 합 = 1은 행 간 제약이라 적재 시 검증한다.

#### `scoring_weights`

| 컬럼 | 타입 | NULL | 기본값/생성식 | 키 | 설명 |
|---|---|---|---|---|---|
| preset_id | smallint | N |  | PK, FK→scoring_presets (CASCADE) | 프리셋 ID |
| factor | character varying(12) | N |  | PK | value / quality / growth / safety / momentum |
| weight | numeric(4,3) | N |  |  | 가중치 0~1 |

제약: `CHECK (((factor)::text = ANY ((ARRAY['value'::character varying, 'quality'::character varying, 'growth'::character varying, 'safety'::character varying, 'momentum'::character varying])::text[])))` / `CHECK (((weight >= (0)::numeric) AND (weight <= (1)::numeric)))`

#### `stock_metric_values`

| 컬럼 | 타입 | NULL | 기본값/생성식 | 키 | 설명 |
|---|---|---|---|---|---|
| stock_id | integer | N |  | PK, FK→stocks (CASCADE) | 종목 ID |
| as_of | date | N |  | PK | 기준일 |
| metric | character varying(24) | N |  | PK | 지표 (earnings_yield, book_yield, roe … 9종, 개발산출물/09 2절) |
| factor | character varying(12) | N |  |  | 소속 팩터 |
| raw_value | numeric | Y |  |  | 지표 원값, 계산 불가면 NULL |
| z_raw | numeric(8,4) | Y |  |  | 국가 내 로버스트 Z(방향 반영, ±3 클리핑) |
| z_adj | numeric(8,4) | Y |  |  | 주 그룹 축소 추정으로 섹터 중립화한 Z |

제약: `CHECK (((factor)::text = ANY ((ARRAY['value'::character varying, 'quality'::character varying, 'growth'::character varying, 'safety'::character varying, 'momentum'::character varying])::text[])))`

#### `stock_scores`

| 컬럼 | 타입 | NULL | 기본값/생성식 | 키 | 설명 |
|---|---|---|---|---|---|
| stock_id | integer | N |  | PK, FK→stocks (CASCADE) | 종목 ID |
| as_of | date | N |  | PK | 기준일 |
| preset_id | smallint | N |  | PK, FK→scoring_presets | 프리셋 ID |
| value_score | numeric(8,4) | Y |  |  | 가치 팩터 점수(유효 지표 z_adj 평균, Z 단위) |
| quality_score | numeric(8,4) | Y |  |  | 퀄리티 팩터 점수 |
| growth_score | numeric(8,4) | Y |  |  | 성장 팩터 점수 |
| safety_score | numeric(8,4) | Y |  |  | 안정성 팩터 점수 |
| momentum_score | numeric(8,4) | Y |  |  | 모멘텀 팩터 점수 |
| composite | numeric(8,4) | Y |  |  | 유효 팩터 가중 평균(재정규화), 유효 팩터 < 3이면 NULL |
| score | numeric(5,2) | Y |  |  | 0~100 = 100·Φ(국가 내 표준화한 composite) |
| factor_coverage | smallint | N |  |  | 유효 팩터 수 0~5 |
| data_quality | jsonb | N | '{}'::jsonb |  | 계산 불가 지표·팩터와 사유, 대체 계산 메모 |

제약: `CHECK (((factor_coverage >= 0) AND (factor_coverage <= 5)))` / `CHECK (((score >= (0)::numeric) AND (score <= (100)::numeric)))`

### 9-3. 의도적 비정규화 — `stock_metric_values`·`stock_scores` (매력도 파생 테이블)
- 형태: `v_stock_metrics`·`valuation_snapshots`·`financial_statements`·`daily_prices`에서 계산할 수 있는 지표 원값·Z(`stock_metric_values`)와 프리셋별 점수(`stock_scores`)를 as_of별로 저장한다.
- 사유: 매력도는 같은 시장 전체의 중앙값·MAD, 주 그룹 평균, 국가 내 재표준화를 거치는 상대 점수라서 종목 1개를 보여 줘도 유니버스 전체를 계산해야 한다. 리스트·관심종목·포트폴리오 요약에서 반복 조회되고, 상세 화면은 점수의 근거(지표 원값·z_raw·z_adj)를 설명해야 하므로 결과를 저장한다. 지표 Z는 프리셋과 무관해 한 번만 저장하고, 프리셋별로는 가중합·변환 결과만 저장한다.
- 정합성: **재생성 가능한 파생 테이블**이다. `python -m app.ingest scores`·`POST /market/refresh`가 해당 `as_of`의 두 테이블을 한 트랜잭션에서 DELETE 후 INSERT로 다시 만든다. 가중치는 `scoring_weights`에서 읽으므로 점수 행이 어떤 프리셋으로 계산됐는지 `preset_id`로 추적된다.

### 9-4. `v_stock_metrics` 컬럼 계약 (B가 `views.sql`에 작성, C가 입력으로 씀 — 이름·순서 변경 금지)
종목별 최신 지표 1행. 비율은 소수(0.05 = 5%), 데이터가 부족하면 NULL. 원본의 끝 열 `dps`·`dividend_yield`(배당, migration 005)는 Stage 5+에서 붙인다(`CREATE OR REPLACE VIEW`는 끝에 붙인 열만 허용).

| # | 컬럼 | 타입 | 내용 |
|---|---|---|---|
| 1 | stock_id | integer | 종목 ID |
| 2 | market | varchar | 시장 코드 |
| 3 | country | char(2) | KR / US |
| 4 | currency | char(3) | KRW / USD |
| 5 | as_of | date | 기준일(종목별 최신 거래일) |
| 6 | close | numeric | 최신 종가 |
| 7 | change_rate | numeric | 전일 대비 등락률 |
| 8~12 | return_1w, return_1m, return_3m, return_6m, return_1y | numeric | 기간 수익률 |
| 13 | volatility_1y | numeric | 연환산 변동성 |
| 14 | max_drawdown_1y | numeric | 1년 최대 낙폭 |
| 15~17 | ma20, ma60, ma120 | numeric | 이동평균 |
| 18 | ma120_gap | numeric | 120일선 괴리율 |
| 19~21 | high_52w, low_52w, position_52w | numeric | 52주 고가·저가·위치 |
| 22 | volume | bigint | 최신 거래량 |
| 23 | avg_volume_20d | numeric | 직전 20거래일 평균 거래량 |
| 24 | volume_ratio_20d | numeric | 거래량 비율 |
| 25 | valuation_as_of | date | 최신 밸류에이션 기준일 |
| 26~29 | per, pbr, eps, bps | numeric | 최신 밸류에이션 |
| 30 | market_cap | numeric | 시가총액(종목 통화) |
| 31 | market_cap_krw | numeric | 시가총액 원화 환산 |
| 32 | fx_usd_krw | numeric | 환산에 쓴 USD/KRW |
| 33 | fx_rate_at | timestamptz | 환율 시각 |
| 34 | fin_period_end | date | 최신 FY 결산일 |
| 35 | accounting_std | varchar | 회계 기준 |
| 36 | operating_margin | numeric | 영업이익률 |
| 37 | roe | numeric | ROE |
| 38 | debt_ratio | numeric | 부채비율 |
| 39 | revenue_yoy | numeric | 매출 YoY |
| 40 | operating_income_yoy | numeric | 영업이익 YoY |

계산 규칙 (데이터 부족 시 NULL):
| 지표 | 정의 | NULL 조건 |
|---|---|---|
| return_1w~1y | 최신 종가 / (기준일 − 기간 이전 가장 가까운 거래일 종가) − 1 | 해당 날짜 이전 데이터 없음 |
| volatility_1y | 최근 252개 일수익률 `STDDEV_SAMP × √252` | 일수익률 252개 미만 |
| max_drawdown_1y | 최근 252거래일 `MIN(close / 누적 MAX(close) − 1)` | 252거래일 미만 |
| ma20/60/120 | 최근 N거래일 종가 평균 | N거래일 미만 |
| ma120_gap | 종가 / ma120 − 1 | ma120 NULL |
| high/low_52w, position_52w | 최근 1년 일중 고가 최대·저가 최소, (종가 − 저가)/(고가 − 저가) | 1년 전 데이터 없음, 고가=저가 |
| volume_ratio_20d | 최신 거래량 / 직전 20거래일(최신일 제외) 평균 | 21거래일 미만, 평균 0 |
| market_cap_krw | 시총 × (USD면 최신 환율, KRW면 1) | 밸류에이션 없음 |
| operating_margin | 영업이익 / 매출 | 매출 0·NULL |
| roe | 순이익 / 자본 | 자본 ≤ 0·NULL |
| debt_ratio | 부채총계 / 자본 | 자본 0·NULL |
| revenue_yoy, operating_income_yoy | (당기 − 전기) / \|전기\| | 전기 0·NULL, 직전 FY 결산일이 330~400일 전이 아님 |

### 9-5. 검증
| 검증 | 결과 |
|---|---|
| 원본 대비 schema·ORM·import 계약 | `python team/tools/check_contract.py 4` 통과 (차이는 `team/contracts/stage4.toml`에 적힌 것만) |
| ORM ↔ DDL 일치, Stage 1~4 외 테이블 없음 | `test_orm_matches_schema`, `test_tables_are_stage1_to_4_only` 통과 (Stage 5부터 `test_tables_are_stage1_to_5_only`) |
| Stage 4 제약 위반 6건(점수 101, 유효 팩터 6개, 가중치 1 초과, 없는 팩터, 프리셋 code 중복, 종목당 주 그룹 2개) 거부, 종목 삭제 시 지표값·점수 CASCADE, 프리셋 삭제 시 가중치 CASCADE | `test_constraints_reject_bad_rows`, `test_delete_cascades` 통과 |


## 10. Stage 5-D — 업종 섹터·데이터 유효기간 (D 계약)

새로 만드는 DB는 `schema.sql`에 반영되어 있고, 이미 적재된 DB는 마이그레이션으로 바꾼다.

### 10-1. 마이그레이션
| 파일 | 내용 | 실행 |
|---|---|---|
| `backend/db/migrations/006_sector_freshness.sql` | `stocks.industry·sic·sector·industry_checked_at`, `peer_groups.kind`(theme/sector), `data_freshness`, `fundamental_bases` 생성, 값이 모두 빈 국내 밸류에이션 행 정리 — 멱등 | `python -m app.ingest migrate 006_sector_freshness` → `python -m app.ingest benchmark --reselect` |

기존 그룹은 모두 `kind = 'theme'`(화면 경쟁 비교용)이 된다. 업종 섹터 그룹(`kind = 'sector'`)은 비교군 선정 때 만들어지고, 그 `is_primary` 구성원이 매력도 섹터 중립화 표본이다. 화면 경쟁 비교·그룹 통계(`peers.sql`·`stock_groups.sql`·`stats_overview.sql`·`stats_peer_group_valuation.sql`)는 테마 그룹만 쓴다.

### 10-2. 테이블·컬럼 정의서

#### `stocks` 추가 컬럼

| 컬럼 | 타입 | NULL | 기본값/생성식 | 키 | 설명 |
|---|---|---|---|---|---|
| industry | character varying(64) | Y |  |  | 국내 KRX 업종명 / 미국 SEC SIC 설명 |
| sic | smallint | Y |  |  | 미국 SEC SIC 코드 |
| sector | character varying(32) | Y |  |  | `config/universe.yaml` sectors 매핑 결과. NULL = 매핑 없음·금융 등 제외 업종 |
| industry_checked_at | timestamp with time zone | Y |  |  | 업종을 마지막으로 확인한 시각(미국 SIC는 1년마다 다시 확인) |

#### `peer_groups` 추가 컬럼

| 컬럼 | 타입 | NULL | 기본값/생성식 | 키 | 설명 |
|---|---|---|---|---|---|
| kind | character varying(10) | N | 'theme' | CHECK IN (theme, sector) | theme = 화면 경쟁 비교 / sector = 매력도 섹터 중립화 |

#### `data_freshness`

| 컬럼 | 타입 | NULL | 기본값/생성식 | 키 | 설명 |
|---|---|---|---|---|---|
| stock_id | integer | N |  | PK, FK→stocks (CASCADE) | 종목 ID |
| kind | character varying(16) | N |  | PK, CHECK IN (financials, disclosures, price_history) | 데이터 종류 |
| fetched_at | timestamp with time zone | N |  |  | 마지막 시도 시각 |
| valid_until | timestamp with time zone | N |  | CHECK ≥ fetched_at | 이 시각 전에는 다시 받지 않는다 |
| status | character varying(10) | N |  | CHECK IN (SUCCESS, FAILED) | 마지막 시도 결과 |
| error | text | Y |  |  | 실패 사유 |

일봉은 이 표와 관계없이 항상 빠진 날짜만 증분으로 받는다(`price_history`는 2년 백필 여부만 정한다).

#### `fundamental_bases`

| 컬럼 | 타입 | NULL | 기본값/생성식 | 키 | 설명 |
|---|---|---|---|---|---|
| stock_id | integer | N |  | PK, FK→stocks (CASCADE) | 종목 ID |
| shares_outstanding | bigint | Y |  | CHECK > 0 | 발행주식수 |
| shares_as_of | date | Y |  |  | 발행주식수 기준일 |
| dps | numeric(18,4) | Y |  | CHECK ≥ 0 | 최근 FY 주당 배당(선언 기준), NULL = 공시값 없음 |
| dps_period_end | date | Y |  |  | 배당 기준 결산일 |
| source | character varying(20) | N |  |  | 데이터 출처 |
| updated_at | timestamp with time zone | N | now() |  | 수정 시각 |

미국 종목 PER·PBR·시가총액을 '기초값 × 종가'로 계산할 때 쓴다. SEC companyfacts에서 재무와 같은 호출로 받고, 유효기간은 `data_freshness.financials`를 따른다.

### 10-3. 검증
| 검증 | 결과 |
|---|---|
| 원본 대비 schema·ORM·import 계약 | `python team/tools/check_contract.py 5` 통과 |
| ORM ↔ DDL 일치, Stage 1~5 외 테이블 없음 | `test_orm_matches_schema`, `test_tables_are_stage1_to_5_only` 통과 |
| Stage 5-D 제약 위반 4건(그룹 kind, 유효기간 < 시도 시각, 유효기간 kind, 발행주식수 0) 거부 | `test_constraints_reject_bad_rows` 통과 |

## 11. Stage 6 — 상장 목록·배당·홈 위젯 (D 계약)

새로 만드는 DB는 `schema.sql`에 반영되어 있고, 이미 적재된 DB는 마이그레이션으로 바꾼다.

### 11-1. 마이그레이션
| 파일 | 내용 | 실행 |
|---|---|---|
| `backend/db/migrations/005_listed_dividend.sql` | `stocks.coverage`에 `listed`(상장 보통주 목록) 허용, `valuation_snapshots.dps`(CHECK ≥ 0) — 멱등 | `python -m app.ingest migrate 005_listed_dividend` (상장 목록 적재는 B의 `listing`) |
| `backend/db/migrations/007_home_widgets.sql` | `sector_performance_daily`, `market_sentiment_daily` 생성, `ingestion_logs.job_type`에 `SECTORS_US`·`SECTORS_KR` — 멱등 | `python -m app.ingest migrate 007_home_widgets` |

### 11-2. 테이블·컬럼 정의서

#### `valuation_snapshots` 추가 컬럼

| 컬럼 | 타입 | NULL | 기본값/생성식 | 키 | 설명 |
|---|---|---|---|---|---|
| dps | numeric(18,4) | Y |  | CHECK ≥ 0 | 주당배당금(연간, 종목 통화). 0 = 무배당, NULL = 미제공 |

#### `sector_performance_daily` (섹터 히트맵, 캐시 성격 — 30일 지난 행은 갱신 작업이 정리)

| 컬럼 | 타입 | NULL | 기본값/생성식 | 키 | 설명 |
|---|---|---|---|---|---|
| id | bigint | N | bigserial | PK | |
| market | character(2) | N |  | UNIQUE①, CHECK IN (KR, US) | 시장 |
| sector_code | character varying(16) | N |  | UNIQUE① | 미국 섹터 ETF 티커(XLK…) / KRX 섹터 지수 코드 |
| sector_name | character varying(40) | N |  |  | 섹터 이름 |
| trade_date | date | N |  | UNIQUE① | 거래일 |
| change_pct | numeric(8,4) | Y |  |  | 전일 대비 %(1.23 = 1.23%) |
| fetched_at | timestamp with time zone | N | now() |  | 수집 시각 |

가중치(타일 크기)는 저장하지 않고 코드 상수(`app/services/sectors.py`)로 둔다.

#### `market_sentiment_daily` (시장 심리 지수 — StockMind 간이 계산, 0~100 높을수록 탐욕)

| 컬럼 | 타입 | NULL | 기본값/생성식 | 키 | 설명 |
|---|---|---|---|---|---|
| id | bigint | N | bigserial | PK | |
| market | character(2) | N |  | UNIQUE①, CHECK IN (KR, US) | 시장 |
| trade_date | date | N |  | UNIQUE① | 기준 지수(KOSPI·S&P 500)의 거래일 |
| score | numeric(5,2) | N |  | CHECK 0~100 | 종합 점수 |
| label | character varying(10) | N |  |  | 점수 구간 이름 |
| price_position · ma_gap_score · rsi_score · vix_score | numeric(5,2) | Y |  | CHECK 0~100 | 구성요소 점수(52주 위치·이동평균 괴리·RSI·VIX — VIX는 미국만) |
| formula_version | smallint | N |  |  | 계산식 버전 |
| computed_at | timestamp with time zone | N | now() |  | 계산 시각 |

## 12. 추가 기능 — 현재가 스냅샷 (`price_quotes`)

관심종목 카드와 종목 상세 헤더의 가격만 장중 현재가로 보여 주기 위한 표다. 매력도·차트·포트폴리오 평가·거래량 급증 등 분석 값은 계속 `daily_prices`(일봉)만 쓴다 — 장중 값을 일봉 표에 섞으면 거래량·수익률 계산이 틀어진다.

| 파일 | 내용 | 실행 |
|---|---|---|
| `backend/db/migrations/011_price_quotes.sql` | `price_quotes` 생성, `ingestion_logs.job_type`에 `QUOTES` — 멱등 | `python -m app.ingest migrate 011_price_quotes` |

| 컬럼 | 타입 | NULL | 기본값/생성식 | 키 | 설명 |
|---|---|---|---|---|---|
| stock_id | integer | N |  | PK, FK → stocks (CASCADE) | 종목당 1행(마지막 값으로 덮어씀) |
| price | numeric(18,4) | N |  | CHECK > 0 | 현재가(종목 통화) |
| prev_close | numeric(18,4) | Y |  | CHECK > 0 | 전일 종가(KIS 기준가) |
| change | numeric(18,4) | Y |  |  | price − prev_close |
| change_rate | numeric(10,6) | Y |  |  | 비율(0.0123 = +1.23%) |
| quoted_at | timestamp with time zone | N |  |  | 받은 시각 |
| source | character varying(20) | N | 'KIS' |  | 출처 |

- 채우는 곳: 갱신 작업 `QUOTES`(1시간, 누군가의 관심종목에 담긴 종목) · `GET /stocks/{market}/{ticker}/quote`(상세 화면을 열 때, 같은 종목은 1분 안 재사용)
- 관심종목 목록(`watchlist.sql`)은 `quoted_at`이 마지막 일봉의 장 마감(서울 15:30·뉴욕 16:00) 뒤일 때만 가격 칸을 현재가로 바꾼다 — 장중에 받은 값이 그날 확정 종가를 덮지 않게 한다
