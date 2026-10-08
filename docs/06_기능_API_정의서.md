# 06. 기능·API 정의서

- 기준: 실행 중인 서버의 OpenAPI(`/openapi.json`)와 **실제 호출 응답**(생성 시각 2026-10-06T22:11:16+09:00, 운영 DB). 배열은 앞 2개만 표시
- 매력도 관련 예시(`/analysis`, `/scoring/presets`, 없는 프리셋 422)는 다중 팩터 모델 적용 후 2026-10-07 실제 호출 응답
- Swagger UI: `http://localhost:8000/docs`

## 1. 공통 규칙
| 항목 | 내용 |
|---|---|
| Base URL | `/api/v1` |
| 인증 | 없음 — **1차는 로컬·시연 전용 단일 사용자(데모) 모드**. 요청 사용자는 서버 의존성 `get_current_user_id()`가 정하며, 1차는 설정값 `DEFAULT_USER_ID`(기본 1 = demo)를 반환한다. 클라이언트는 `user_id`를 보내지 않으며 보내도 무시된다. 설정된 사용자가 DB에 없으면 404 `USER_NOT_FOUND`. 2차에서 이 함수를 JWT 검증으로 교체한다 |
| 소유권 | 포트폴리오·담은 항목·관심종목은 요청 사용자 소유만 조회·변경. 다른 사용자의 리소스는 존재 여부를 드러내지 않도록 없는 리소스와 같은 404(`PORTFOLIO_NOT_FOUND`·`ITEM_NOT_FOUND`·`WATCHLIST_ITEM_NOT_FOUND`) |
| 오류 형식 | `{"error": {"code", "message", "detail"}}` — 404 NOT_FOUND 계열, 409 CONFLICT 계열, 422 VALIDATION_ERROR·업무 검증, 503 FX_UNAVAILABLE, 500 INTERNAL_ERROR. 코드 전체는 [5절 에러 코드](#5-에러-코드) |
| 500 처리 | 예상하지 못한 예외는 500 `INTERNAL_ERROR`와 고정 메시지만 응답한다(예외 메시지·스택·SQL·내부 경로는 응답에 넣지 않음). 스택은 서버 로그에 요청 ID와 함께 남고, 응답에도 `X-Request-ID` 헤더가 붙는다 |
| 입력 형식 | 형식·범위가 틀리면 DB 조회 전에 422 `VALIDATION_ERROR`(`detail`에 위치·사유). `market` 영문 2~10자, `ticker` 영숫자로 시작하는 영숫자·`.`·`-` 1~16자, id(`portfolio_id`·`item_id`·`group_id`) 1~2,147,483,647, 이름 1~100자(공백만 불가), `seed_krw`·금액 0 초과 1,000조 원 이하, 수량 정수 1~2,147,483,647, 비중 0 초과 100 이하, 메모 500자, `limit`·`offset`·`range`·`period`는 엔드포인트별 범위·허용 값(Swagger). 근거 ASSUMPTIONS A-112 |
| 숫자 | 금액·가격은 서버에서 Decimal로 계산, JSON에는 숫자. 비율은 소수(0.0523 = 5.23%) |
| 기준 시각 | 시세 응답은 `as_of`(거래일), 환율은 `rate_at`, 통화는 `currency` |
| 요청 ID | 모든 응답 헤더 `X-Request-ID`, 서버 로그에 같은 ID 기록 |
| 갱신 정책 | 같은 종류 외부 호출은 `REFRESH_TTL_HOURS`(4시간)에 최대 1회. TTL 이내 요청은 저장된 값 사용. 일부 대상만 실패하면 30분 뒤 실패한 종목만 다시 받음(A-109) |
| 외부 소스 장애 시 동작 | **조회 API는 외부 소스를 직접 부르지 않고 DB에 저장된 마지막 값을 돌려준다**(시세·지수·밸류에이션·재무·공시·점수). 실패는 대상별로 `ingestion_logs`에 FAILED로 남고 나머지 대상은 계속 적재한다. 데이터의 기준 시점은 응답의 `as_of`로, 갱신 상태는 `GET /market/refresh/status`의 작업별 `FRESH`/`STALE`로 확인한다. 작업별 차이: ① **환율** — 조회 시 TTL이 지났으면 외부 호출, 실패하면 마지막 저장값 + `fx_stale: true`, 저장값도 없으면 503 `FX_UNAVAILABLE`(USD 종목 상세·담기·평가도 같음) ② **국내 밸류에이션** — pykrx 실패 시 DART FY 기반 파생값(`DERIVED`)으로 대체(A-02) ③ **비교군 종목 상세** — 백그라운드 수집 실패 시 `detail_status: failed`, 10분 뒤 다시 시도 ④ **점수** — 계산 실패 시 직전 점수 유지 |

## 2. 엔드포인트 목록

| 구분 | Method | URL | 기능 | 주요 파라미터 | 성공 · 오류(HTTP 상태와 `code`) |
|---|---|---|---|---|---|
| 시장·갱신 | GET | `/market/indices` | 지수별 최신값·등락·최근 30거래일 스파크라인 | - | 200 |
| 시장·갱신 | GET | `/market/fx` | USD/KRW 최신값·전일 대비·최근 30일 (TTL 내에는 외부 호출 없음) | - | 200 · 503 FX_UNAVAILABLE |
| 시장·갱신 | POST | `/market/refresh` | 환율·지수·증분 일봉·밸류에이션·점수 갱신 (작업별 TTL 이내면 SKIPPED) | - | 200 (작업별 실패는 본문 `jobs[].status`) |
| 시장·갱신 | GET | `/market/refresh/status` | 갱신 상태 조회 — 외부 호출 없음 (사이드바 '마지막 갱신 시각' 표시용) | - | 200 |
| 종목 | GET | `/peer-groups` | 경쟁 그룹 목록 (리스트 필터용) | - | 200 |
| 종목 | GET | `/stocks` | 주식 리스트 (거래량/시총 순위, 시장·그룹 필터, 검색, 프리셋별 매력도). 기본은 노출 종목만, q가 있으면 매력도 비교군도(`coverage`) | country, sort, order, group, q, limit, offset, preset | 200 · 422 VALIDATION_ERROR, VOLUME_SORT_REQUIRES_MARKET, UNKNOWN_PRESET |
| 종목 | GET | `/stocks/{market}/{ticker}` | 종목 기본 정보 + 최신 시세·밸류에이션·매력도. 비교군 종목이면 상세 데이터 수집을 예약하고 `detail_status`(ready/loading/failed) | preset | 200 · 404 STOCK_NOT_FOUND · 422 VALIDATION_ERROR, UNKNOWN_PRESET · 503 FX_UNAVAILABLE(USD) |
| 종목 | GET | `/stocks/{market}/{ticker}/candles` | 기간 일봉 | range | 200 · 404 STOCK_NOT_FOUND · 422 VALIDATION_ERROR |
| 종목 | GET | `/stocks/{market}/{ticker}/financials` | FY 재무 추이 | limit | 200 · 404 STOCK_NOT_FOUND · 422 VALIDATION_ERROR |
| 종목 | GET | `/stocks/{market}/{ticker}/disclosures` | 최근 공시 | limit | 200 · 404 STOCK_NOT_FOUND · 422 VALIDATION_ERROR |
| 관심종목 | GET | `/watchlist` | 관심종목 카드 목록 (정렬순, 프리셋별 매력도) | preset | 200 · 404 USER_NOT_FOUND · 422 VALIDATION_ERROR, UNKNOWN_PRESET |
| 관심종목 | POST | `/watchlist` | 관심종목 추가 | body: market, ticker | 201 · 404 STOCK_NOT_FOUND, USER_NOT_FOUND · 409 DUPLICATE_WATCHLIST · 422 VALIDATION_ERROR |
| 관심종목 | PATCH | `/watchlist/order` | 관심종목 정렬 순서 변경 | body: items | 200 · 404 WATCHLIST_ITEM_NOT_FOUND, USER_NOT_FOUND · 422 VALIDATION_ERROR |
| 관심종목 | DELETE | `/watchlist/{market}/{ticker}` | 관심종목 삭제 | - | 204 · 404 STOCK_NOT_FOUND, WATCHLIST_ITEM_NOT_FOUND, USER_NOT_FOUND · 422 VALIDATION_ERROR |
| 모의 포트폴리오 | POST | `/portfolios` | 포트폴리오 생성 | body: name, seed_krw | 201 · 404 USER_NOT_FOUND · 409 DUPLICATE_PORTFOLIO_NAME · 422 VALIDATION_ERROR |
| 모의 포트폴리오 | GET | `/portfolios` | 사용자의 포트폴리오 목록 | - | 200 · 404 USER_NOT_FOUND |
| 모의 포트폴리오 | GET | `/portfolios/{portfolio_id}` | 포트폴리오 단건 | - | 200 · 404 PORTFOLIO_NOT_FOUND · 422 VALIDATION_ERROR |
| 모의 포트폴리오 | PUT | `/portfolios/{portfolio_id}` | 이름·시드 수정 (원가 합계 미만 시드는 409) | body: name, seed_krw | 200 · 404 PORTFOLIO_NOT_FOUND · 409 SEED_BELOW_USED, DUPLICATE_PORTFOLIO_NAME · 422 VALIDATION_ERROR |
| 모의 포트폴리오 | DELETE | `/portfolios/{portfolio_id}` | 포트폴리오 삭제 (담은 항목 함께 삭제) | - | 204 · 404 PORTFOLIO_NOT_FOUND · 422 VALIDATION_ERROR |
| 모의 포트폴리오 | POST | `/portfolios/{portfolio_id}/items` | 종목 담기 (quantity/amount/weight 모드, 시드 초과 409, 수량 0이면 422) | body: mode, value, memo, market, ticker | 201 · 404 PORTFOLIO_NOT_FOUND, STOCK_NOT_FOUND · 409 SEED_EXCEEDED, DUPLICATE_ITEM · 422 VALIDATION_ERROR, QUANTITY_ZERO, NO_PRICE · 503 FX_UNAVAILABLE(USD) |
| 모의 포트폴리오 | GET | `/portfolios/{portfolio_id}/items` | 담은 종목과 현재 평가 | - | 200 · 404 PORTFOLIO_NOT_FOUND · 422 VALIDATION_ERROR · 503 FX_UNAVAILABLE(USD 보유) |
| 모의 포트폴리오 | PUT | `/portfolios/{portfolio_id}/items/{item_id}` | 담은 종목 수정 (기준가·환율을 현재값으로 갱신) | body: mode, value, memo | 200 · 404 PORTFOLIO_NOT_FOUND, ITEM_NOT_FOUND · 409 SEED_EXCEEDED · 422 VALIDATION_ERROR, QUANTITY_ZERO, NO_PRICE · 503 FX_UNAVAILABLE(USD) |
| 모의 포트폴리오 | DELETE | `/portfolios/{portfolio_id}/items/{item_id}` | 담은 종목 삭제 | - | 204 · 404 PORTFOLIO_NOT_FOUND, ITEM_NOT_FOUND · 422 VALIDATION_ERROR |
| 모의 포트폴리오 | GET | `/portfolios/{portfolio_id}/summary` | 요약: 사용·잔여·비중·가중 매력도·평가손익(환 효과 분리) | - | 200 · 404 PORTFOLIO_NOT_FOUND · 422 VALIDATION_ERROR · 503 FX_UNAVAILABLE(USD 보유) |
| 분석 | GET | `/stocks/{market}/{ticker}/analysis` | 수치 분석(v_stock_metrics) + 매력도(프리셋별 점수·팩터 기여도·지표 원값/Z·국가 내 순위·백분위·데이터 충족도) | preset | 200 · 404 STOCK_NOT_FOUND, NO_PRICE · 422 VALIDATION_ERROR, UNKNOWN_PRESET |
| 분석 | GET | `/scoring/presets` | 투자 성향 프리셋(sort_order 순: 위험·성장·균형·가치)과 팩터별 가중치 | - | 200 |
| 분석 | GET | `/stocks/{market}/{ticker}/peers` | 경쟁 그룹별 비교 표 (그룹 내 RANK·AVG, 구성원 1명 그룹은 비교 대상 없음) | - | 200 · 404 STOCK_NOT_FOUND · 422 VALIDATION_ERROR |
| 분석 | GET | `/stocks/{market}/{ticker}/peers/chart` | 경쟁 그룹 기준일=100 가격 추이 (합집합 날짜 + 휴장일 null) | range, group_id | 200 · 404 STOCK_NOT_FOUND, NO_PEER_GROUP, GROUP_NOT_FOUND · 422 VALIDATION_ERROR |
| 통계 | GET | `/statistics/overview` | 데이터 개요: 행 수·기간·마지막 갱신 | - | 200 |
| 통계 | GET | `/statistics/market-valuation` | 시장별 평균 PER/PBR/ROE (HAVING 표본 수 이상) | min_samples | 200 · 422 VALIDATION_ERROR |
| 통계 | GET | `/statistics/peer-group-valuation` | 경쟁 그룹별 평균·최고·최저 지표 | - | 200 |
| 통계 | GET | `/statistics/disclosure-frequency` | 기간별 공시 빈도 (월·분기·주) | period, days | 200 · 422 VALIDATION_ERROR |

※ 오류 열은 엔드포인트별로 실제 발생할 수 있는 상태와 `code`다. 모든 엔드포인트는 예상하지 못한 예외 시 500 `INTERNAL_ERROR`. 코드별 조건은 [5절](#5-에러-코드).

※ `GET /market/refresh/status`, `GET /peer-groups`는 화면 요구로 추가한 엔드포인트(ASSUMPTIONS A-48, A-67)

※ 매력도 비교군(benchmark): 점수 비교 표본으로만 쓰는 종목(docs/09 9절). 경쟁 비교(`/peers`, `/peers/chart`)·통계는 노출 종목(+대상 종목) 기준이고, 관심종목에 추가하면(POST `/watchlist`) 상세 데이터 수집을 예약한다.

※ `preset`: 투자 성향 프리셋 코드(aggressive·growth·balanced·value, 기본 balanced). 없는 코드(옛 quality 포함)는 422 `UNKNOWN_PRESET`(`detail.presets`에 사용 가능한 코드). 경쟁 비교 표(`/peers`)와 포트폴리오 요약의 매력도는 균형 프리셋 기준. 점수 정의는 docs/09.

## 3. 요청·응답 예시 (실제 호출)

### 3-1. 시장·갱신
#### `GET /api/v1/market/indices`
응답 `200`:
```json
{
  "as_of": "2026-10-06",
  "indices": [
    {
      "code": "KOSPI",
      "name": "KOSPI",
      "country": "KR",
      "currency": "KRW",
      "as_of": "2026-10-06",
      "close": 6941.39,
      "prev_close": 7003.74,
      "change": -62.35,
      "change_rate": -0.008902,
      "sparkline": [
        {
          "date": "2026-08-21",
          "close": 6912.95
        },
        "… 외 29개"
      ]
    },
    "… 외 4개"
  ]
}
```
#### `GET /api/v1/market/fx`
응답 `200`:
```json
{
  "pair": "USD/KRW",
  "currency": "KRW",
  "usd_krw": 1339.08,
  "rate_at": "2026-10-06T12:16:55.504460Z",
  "granularity": "SNAPSHOT",
  "fx_stale": false,
  "prev_close": 1342.5601,
  "change": -3.4801,
  "change_rate": -0.002592,
  "history": [
    {
      "date": "2026-08-26",
      "usd_krw": 1381.49
    },
    {
      "date": "2026-08-27",
      "usd_krw": 1383.49
    },
    "… 외 28개"
  ],
  "as_of": "2026-10-06T12:16:55.504460Z"
}
```
#### `GET /api/v1/market/refresh/status`
응답 `200`:
```json
{
  "refreshed_at": "2026-10-06T12:45:18.945590Z",
  "next_refresh_available_at": "2026-10-06T15:50:13.067876Z",
  "ttl_hours": 4.0,
  "jobs": [
    {
      "job_type": "FX",
      "status": "FRESH",
      "detail": null,
      "last_success_at": "2026-10-06T12:16:55.505868Z",
      "counts": {}
    },
    {
      "job_type": "INDICES",
      "status": "FRESH",
      "detail": null,
      "last_success_at": "2026-10-06T11:50:13.067876Z",
      "counts": {}
    },
    "… 외 3개"
  ],
  "basis": "일봉 기준"
}
```
#### `POST /api/v1/market/refresh` — TTL 이내라 모든 작업 SKIPPED (외부 호출 없음)
응답 `200`:
```json
{
  "refreshed_at": "2026-10-06T13:11:16.818338Z",
  "next_refresh_available_at": "2026-10-06T15:50:13.067876Z",
  "ttl_hours": 4.0,
  "jobs": [
    {
      "job_type": "FX",
      "status": "SKIPPED",
      "detail": "TTL 이내 (마지막 성공 2026-10-06T12:16:55.505868+00:00)",
      "last_success_at": "2026-10-06T12:16:55.505868Z",
      "counts": {}
    },
    {
      "job_type": "INDICES",
      "status": "SKIPPED",
      "detail": "TTL 이내 (마지막 성공 2026-10-06T11:50:13.067876+00:00)",
      "last_success_at": "2026-10-06T11:50:13.067876Z",
      "counts": {}
    },
    {
      "job_type": "PRICES",
      "status": "SKIPPED",
      "detail": "TTL 이내 (마지막 성공 2026-10-06T12:00:09.123135+00:00)",
      "last_success_at": "2026-10-06T12:00:09.123135Z",
      "counts": {}
    },
    {
      "job_type": "VALUATION",
      "status": "SKIPPED",
      "detail": "TTL 이내 (마지막 성공 2026-10-06T11:53:35.598216+00:00)",
      "last_success_at": "2026-10-06T11:53:35.598216Z",
      "counts": {}
    },
    {
      "job_type": "SCORES",
      "status": "SKIPPED",
      "detail": "TTL 이내 (마지막 성공 2026-10-06T12:45:18.945590+00:00)",
      "last_success_at": "2026-10-06T12:45:18.945590Z",
      "counts": {}
    }
  ],
  "basis": "일봉 기준"
}
```
### 3-2. 종목
#### `GET /api/v1/stocks?country=KR&sort=volume&limit=2`
응답 `200`:
```json
{
  "total": 16,
  "limit": 2,
  "offset": 0,
  "sort": "volume",
  "order": "desc",
  "preset": "balanced",
  "fx_rate_at": "2026-10-06T12:16:55.504460Z",
  "items": [
    {
      "rank": 1,
      "stock_id": 1,
      "market": "KOSPI",
      "country": "KR",
      "currency": "KRW",
      "ticker": "005930",
      "name": "삼성전자",
      "name_en": "SAMSUNG ELECTRONICS CO,.LTD",
      "as_of": "2026-10-06",
      "close": 273000,
      "change": -3000,
      "change_rate": -0.01087,
      "volume": 12895120,
      "market_cap": 1590187781376000,
      "market_cap_krw": 1590187781376000,
      "score": 51.75,
      "is_watched": true
    },
    {
      "rank": 2,
      "stock_id": 2,
      "market": "KOSPI",
      "country": "KR",
      "currency": "KRW",
      "ticker": "000660",
      "name": "SK하이닉스",
      "name_en": "SK hynix Inc.",
      "as_of": "2026-10-06",
      "close": 1784000,
      "change": -58000,
      "change_rate": -0.031488,
      "volume": 2726173,
      "market_cap": 1295162963145000,
      "market_cap_krw": 1295162963145000,
      "score": 65.17,
      "is_watched": true
    }
  ]
}
```
#### `GET /api/v1/stocks/KOSPI/005930`
응답 `200`:
```json
{
  "stock_id": 1,
  "market": "KOSPI",
  "country": "KR",
  "currency": "KRW",
  "ticker": "005930",
  "name": "삼성전자",
  "name_en": "SAMSUNG ELECTRONICS CO,.LTD",
  "corp_code": "00126380",
  "cik": null,
  "as_of": "2026-10-06",
  "close": 273000,
  "prev_close": 276000,
  "change": -3000,
  "change_rate": -0.01087,
  "volume": 12895120,
  "close_krw": 273000,
  "fx_rate": null,
  "fx_rate_at": null,
  "fx_stale": false,
  "valuation_as_of": "2026-10-06",
  "valuation_source": "PYKRX",
  "per": 41.18,
  "pbr": 4.25,
  "eps": 6605,
  "bps": 63997,
  "market_cap": 1590187781376000,
  "market_cap_krw": 1590187781376000,
  "shares_outstanding": 5846278608,
  "score": 51.75,
  "score_as_of": "2026-10-06",
  "preset": "balanced",
  "groups": [
    {
      "group_id": 1,
      "name": "반도체"
    }
  ],
  "is_watched": true
}
```
#### `GET /api/v1/stocks/NASDAQ/AAPL/candles?range=1m`
응답 `200`:
```json
{
  "market": "NASDAQ",
  "ticker": "AAPL",
  "currency": "USD",
  "range": "1m",
  "as_of": "2026-10-05",
  "candles": [
    {
      "date": "2026-09-08",
      "open": 317.1,
      "high": 320.7,
      "low": 314.9,
      "close": 316.22,
      "volume": 35477100
    },
    {
      "date": "2026-09-09",
      "open": 315.49,
      "high": 319.15,
      "low": 309.9,
      "close": 315.34,
      "volume": 65640000
    },
    "… 외 18개"
  ]
}
```
#### `GET /api/v1/stocks/KOSPI/005930/financials?limit=2`
응답 `200`:
```json
{
  "market": "KOSPI",
  "ticker": "005930",
  "currency": "KRW",
  "as_of": "2025-12-31",
  "items": [
    {
      "period_end": "2024-12-31",
      "period_type": "FY",
      "revenue": 300870903000000,
      "operating_income": 32725961000000,
      "net_income": 33621363000000,
      "total_assets": 514531948000000,
      "total_equity": 391687603000000,
      "total_debt": 112339878000000,
      "operating_margin": 0.108771,
      "roe": 0.085837,
      "data_source": "DART",
      "accounting_std": "K-IFRS"
    },
    {
      "period_end": "2025-12-31",
      "period_type": "FY",
      "revenue": 333605938000000,
      "operating_income": 43601051000000,
      "net_income": 44260956000000,
      "total_assets": 566942110000000,
      "total_equity": 424313255000000,
      "total_debt": 130621773000000,
      "operating_margin": 0.130696,
      "roe": 0.104312,
      "data_source": "DART",
      "accounting_std": "K-IFRS"
    }
  ]
}
```
#### `GET /api/v1/stocks/KOSPI/005930/disclosures?limit=2`
응답 `200`:
```json
{
  "market": "KOSPI",
  "ticker": "005930",
  "as_of": "2026-10-01T15:00:00Z",
  "items": [
    {
      "rcept_no": "20261002800981",
      "title": "최대주주등소유주식변동신고서",
      "report_type": "거래소공시",
      "filed_at": "2026-10-01T15:00:00Z",
      "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261002800981",
      "data_source": "DART"
    },
    {
      "rcept_no": "20260918800754",
      "title": "최대주주등소유주식변동신고서",
      "report_type": "거래소공시",
      "filed_at": "2026-09-17T15:00:00Z",
      "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260918800754",
      "data_source": "DART"
    }
  ]
}
```
### 3-3. 분석·경쟁 비교
#### `GET /api/v1/stocks/KOSPI/005930/analysis?preset=growth`
응답 `200`:
```json
{
  "market": "KOSPI",
  "ticker": "005930",
  "currency": "KRW",
  "as_of": "2026-10-06",
  "valuation_as_of": "2026-10-07",
  "fin_period_end": "2025-12-31",
  "accounting_std": "K-IFRS",
  "fx_usd_krw": 1339.83,
  "fx_rate_at": "2026-10-07T02:18:55.125990Z",
  "metrics": {
    "return_1w": -0.007273,
    "return_1m": 0.068493,
    "return_3m": -0.141509,
    "…": "외 25개 (수치 분석 지표, 이전과 같음)"
  },
  "attractiveness": {
    "as_of": "2026-10-07",
    "preset": {
      "code": "growth",
      "name": "성장",
      "description": "성장성 중심"
    },
    "score": 73.13,
    "composite": 0.4865,
    "factor_coverage": 5,
    "factor_total": 5,
    "rank": {
      "country": "KR",
      "position": 5,
      "total": 16,
      "percentile": 73.3
    },
    "factors": {
      "value": {
        "score": -0.0134,
        "weight": 0.1,
        "effective_weight": 0.1,
        "contribution": -0.0013,
        "available": true
      },
      "quality": {
        "score": 0.0025,
        "weight": 0.2,
        "effective_weight": 0.2,
        "contribution": 0.0005,
        "available": true
      },
      "growth": {
        "score": -0.1287,
        "weight": 0.4,
        "effective_weight": 0.4,
        "contribution": -0.0515,
        "available": true
      },
      "safety": {
        "score": 0.2022,
        "weight": 0.05,
        "effective_weight": 0.05,
        "contribution": 0.0101,
        "available": true
      },
      "momentum": {
        "score": 2.1149,
        "weight": 0.25,
        "effective_weight": 0.25,
        "contribution": 0.5287,
        "available": true
      }
    },
    "metrics": [
      {
        "metric": "earnings_yield",
        "label": "이익수익률 E/P",
        "factor": "value",
        "direction": 1,
        "raw_value": 0.024194139194139194,
        "z_raw": -0.0649,
        "z_adj": 0.1315
      },
      {
        "metric": "book_yield",
        "label": "B/P",
        "factor": "value",
        "direction": 1,
        "raw_value": 0.23442124542124543,
        "z_raw": -0.3197,
        "z_adj": -0.1582
      },
      "… 외 7개"
    ],
    "data_quality": {
      "partition": "KR"
    },
    "method": "지표별로 같은 시장 안 로버스트 Z(중앙값·MAD)를 구해 ±3으로 자르고, 주 경쟁 그룹 평균을 축소 추정으로 빼 섹터 중립화한 뒤 팩터 평균 → 프리셋 가중 평균 → 시장 안에서 다시 표준화해 100·Φ(z)로 0~100 변환합니다."
  },
  "disclaimer": "매력도는 유니버스(25종목) 안에서 같은 시장끼리 비교한 상대적 위치를 나타내는 팩터 점수이며, 수익률 예측이나 투자 권유가 아닙니다."
}
```
#### `GET /api/v1/scoring/presets`
응답 `200`:
```json
{
  "note": "공개된 일반적 투자 스타일을 단순화한 가중치이며 특정 인물의 판단이 아닙니다.",
  "presets": [
    {
      "code": "aggressive",
      "name": "위험",
      "description": "모멘텀·성장 중심",
      "sort_order": 1,
      "is_default": false,
      "weights": {
        "value": 0.05,
        "quality": 0.1,
        "growth": 0.35,
        "safety": 0.1,
        "momentum": 0.4
      }
    },
    {
      "code": "growth",
      "name": "성장",
      "description": "성장성 중심",
      "sort_order": 2,
      "is_default": false,
      "weights": {
        "value": 0.1,
        "quality": 0.2,
        "growth": 0.4,
        "safety": 0.05,
        "momentum": 0.25
      }
    },
    "… 외 2개"
  ]
}
```
#### `GET /api/v1/stocks/KOSPI/005930/peers`
응답 `200`:
```json
{
  "market": "KOSPI",
  "ticker": "005930",
  "accounting_note": "국내 종목 재무는 K-IFRS 연결(DART), 미국 종목은 US-GAAP(SEC)이며 PER·PBR은 각각 KRX·Yahoo 제공값입니다. 회계기준·산정 방식이 달라 국가 간 수치 비교에는 한계가 있습니다.",
  "rank_rule": "값이 있는 구성원끼리 RANK. PER·PBR은 낮을수록(양수만), 나머지는 높을수록 1위",
  "groups": [
    {
      "group_id": 1,
      "name": "반도체",
      "size": 5,
      "has_peers": true,
      "message": null,
      "averages": {
        "return_1m": 0.105495,
        "return_3m": 0.015009,
        "return_1y": 1.75406,
        "per": 61.4841,
        "pbr": 14.4919,
        "roe": 0.315413,
        "operating_margin": 0.345195,
        "revenue_yoy": 0.362657,
        "market_cap_krw": 2861680590488512,
        "score": 56.39
      },
      "members": [
        {
          "stock_id": 21,
          "ticker": "NVDA",
          "name": "NVIDIA",
          "market": "NASDAQ",
          "country": "US",
          "currency": "USD",
          "is_target": false,
          "accounting_std": "US-GAAP",
          "values": {
            "return_1m": 0.038233,
            "return_3m": 0.227569,
            "return_1y": 0.276369,
            "per": 30.2023,
            "pbr": 25.1924,
            "roe": 0.763333,
            "operating_margin": 0.603817,
            "revenue_yoy": 0.654735,
            "market_cap_krw": 7724774625367818,
            "score": 68.44
          },
          "ranks": {
            "return_1m": 4,
            "return_3m": 1,
            "return_1y": 4,
            "per": 2,
            "pbr": 5,
            "roe": 1,
            "operating_margin": 1,
            "revenue_yoy": 1,
            "market_cap_krw": 1,
            "score": 1
          }
        },
        {
          "stock_id": 24,
          "ticker": "AVGO",
          "name": "Broadcom",
          "market": "NASDAQ",
          "country": "US",
          "currency": "USD",
          "is_target": false,
          "accounting_std": "US-GAAP",
          "values": {
            "return_1m": 0.014725,
            "return_3m": 0.007547,
            "return_1y": 0.079308,
            "per": 46.2976,
            "pbr": 17.3599,
            "roe": 0.284481,
            "operating_margin": 0.398892,
            "revenue_yoy": 0.238744,
            "market_cap_krw": 2317262804153795,
            "score": 44.38
          },
          "ranks": {
            "return_1m": 5,
            "return_3m": 3,
            "return_1y": 5,
            "per": 4,
            "pbr": 4,
            "roe": 3,
            "operating_margin": 3,
            "revenue_yoy": 4,
            "market_cap_krw": 2,
            "score": 5
          }
        },
        "… 외 3개"
      ]
    }
  ]
}
```
#### `GET /api/v1/stocks/KOSPI/005930/peers/chart?range=1m`
응답 `200`:
```json
{
  "market": "KOSPI",
  "ticker": "005930",
  "group_id": 1,
  "group_name": "반도체",
  "groups": [
    {
      "group_id": 1,
      "name": "반도체",
      "size": 5
    }
  ],
  "range": "1m",
  "base": 100,
  "dates": [
    "2026-09-07",
    "2026-09-08",
    "2026-09-09",
    "… 외 19개"
  ],
  "series": [
    {
      "stock_id": 1,
      "ticker": "005930",
      "name": "삼성전자",
      "market": "KOSPI",
      "is_target": true,
      "values": [
        100,
        99.8148,
        99.8148,
        "… 외 19개"
      ]
    },
    {
      "stock_id": 2,
      "ticker": "000660",
      "name": "SK하이닉스",
      "market": "KOSPI",
      "is_target": false,
      "values": [
        100,
        100.5609,
        104.0942,
        "… 외 19개"
      ]
    },
    {
      "stock_id": 25,
      "ticker": "AMD",
      "name": "AMD",
      "market": "NASDAQ",
      "is_target": false,
      "values": [
        null,
        100,
        103.0371,
        "… 외 19개"
      ]
    },
    "… 외 2개"
  ],
  "note": "각 종목의 구간 첫 거래일 종가 = 100. 시장별 휴장일이 달라 해당 날짜 값은 null(선 연결 표시)."
}
```
### 3-4. 관심종목 (CRUD)
#### `GET /api/v1/watchlist`
응답 `200`:
```json
{
  "user_id": 1,
  "preset": "balanced",
  "count": 8,
  "items": [
    {
      "sort_order": 1,
      "added_at": "2026-10-06T11:54:52.163535Z",
      "stock_id": 1,
      "market": "KOSPI",
      "country": "KR",
      "currency": "KRW",
      "ticker": "005930",
      "name": "삼성전자",
      "as_of": "2026-10-06",
      "close": 273000,
      "change": -3000,
      "change_rate": -0.01087,
      "score": 51.75
    },
    {
      "sort_order": 2,
      "added_at": "2026-10-06T11:54:52.163535Z",
      "stock_id": 2,
      "market": "KOSPI",
      "country": "KR",
      "currency": "KRW",
      "ticker": "000660",
      "name": "SK하이닉스",
      "as_of": "2026-10-06",
      "close": 1784000,
      "change": -58000,
      "change_rate": -0.031488,
      "score": 65.17
    },
    "… 외 6개"
  ]
}
```
#### `POST /api/v1/watchlist`
요청 본문:
```json
{
  "market": "NASDAQ",
  "ticker": "AMD"
}
```
응답 `201`:
```json
{
  "sort_order": 9,
  "added_at": "2026-10-06T13:11:16.856591Z",
  "stock_id": 25,
  "market": "NASDAQ",
  "country": "US",
  "currency": "USD",
  "ticker": "AMD",
  "name": "AMD",
  "as_of": "2026-10-05",
  "close": 631.75,
  "change": -2.16,
  "change_rate": -0.003407,
  "score": 52.19
}
```
#### `POST /api/v1/watchlist` — 중복 → 409
요청 본문:
```json
{
  "market": "NASDAQ",
  "ticker": "AMD"
}
```
응답 `409`:
```json
{
  "error": {
    "code": "DUPLICATE_WATCHLIST",
    "message": "이미 관심종목에 있습니다",
    "detail": {
      "market": "NASDAQ",
      "ticker": "AMD"
    }
  }
}
```
#### `PATCH /api/v1/watchlist/order`
요청 본문:
```json
{
  "items": [
    {
      "market": "NASDAQ",
      "ticker": "AMD",
      "sort_order": 0
    }
  ]
}
```
응답 `200`:
```json
{
  "user_id": 1,
  "preset": "balanced",
  "count": 9,
  "items": [
    {
      "sort_order": 0,
      "added_at": "2026-10-06T13:11:16.856591Z",
      "stock_id": 25,
      "market": "NASDAQ",
      "country": "US",
      "currency": "USD",
      "ticker": "AMD",
      "name": "AMD",
      "as_of": "2026-10-05",
      "close": 631.75,
      "change": -2.16,
      "change_rate": -0.003407,
      "score": 52.19
    },
    {
      "sort_order": 1,
      "added_at": "2026-10-06T11:54:52.163535Z",
      "stock_id": 1,
      "market": "KOSPI",
      "country": "KR",
      "currency": "KRW",
      "ticker": "005930",
      "name": "삼성전자",
      "as_of": "2026-10-06",
      "close": 273000,
      "change": -3000,
      "change_rate": -0.01087,
      "score": 51.75
    },
    "… 외 7개"
  ]
}
```
#### `DELETE /api/v1/watchlist/NASDAQ/AMD`
응답 `204`:
```json
(본문 없음)
```
### 3-5. 모의 포트폴리오 (CRUD) — 예시용 포트폴리오를 만들고 마지막에 삭제
#### `POST /api/v1/portfolios`
요청 본문:
```json
{
  "name": "API 예시",
  "seed_krw": 10000000
}
```
응답 `201`:
```json
{
  "portfolio_id": 7,
  "user_id": 1,
  "name": "API 예시",
  "currency": "KRW",
  "seed_krw": 10000000,
  "used_krw": 0,
  "remaining_krw": 10000000,
  "item_count": 0,
  "created_at": "2026-10-06T13:11:16.873379Z",
  "updated_at": "2026-10-06T13:11:16.873379Z"
}
```
#### `POST /api/v1/portfolios/7/items`
요청 본문:
```json
{
  "market": "KOSPI",
  "ticker": "005930",
  "mode": "amount",
  "value": 3000000,
  "memo": "금액 모드"
}
```
응답 `201`:
```json
{
  "item_id": 15,
  "portfolio_id": 7,
  "stock_id": 1,
  "market": "KOSPI",
  "ticker": "005930",
  "name": "삼성전자",
  "currency": "KRW",
  "quantity": 10,
  "ref_price": 273000,
  "ref_fx_rate": 1,
  "ref_date": "2026-10-06",
  "cost_krw": 2730000,
  "memo": "금액 모드",
  "created_at": "2026-10-06T13:11:16.878030Z",
  "updated_at": "2026-10-06T13:11:16.878030Z"
}
```
#### `POST /api/v1/portfolios/7/items`
요청 본문:
```json
{
  "market": "NASDAQ",
  "ticker": "AAPL",
  "mode": "weight",
  "value": 30
}
```
응답 `201`:
```json
{
  "item_id": 16,
  "portfolio_id": 7,
  "stock_id": 17,
  "market": "NASDAQ",
  "ticker": "AAPL",
  "name": "Apple",
  "currency": "USD",
  "quantity": 6,
  "ref_price": 332.89,
  "ref_fx_rate": 1339.08,
  "ref_date": "2026-10-05",
  "cost_krw": 2674598.05,
  "memo": null,
  "created_at": "2026-10-06T13:11:16.884093Z",
  "updated_at": "2026-10-06T13:11:16.884093Z"
}
```
#### `POST /api/v1/portfolios/7/items` — 시드 초과 → 409 + 최대 수량
요청 본문:
```json
{
  "market": "KOSPI",
  "ticker": "000660",
  "mode": "quantity",
  "value": 10
}
```
응답 `409`:
```json
{
  "error": {
    "code": "SEED_EXCEEDED",
    "message": "담은 원가 합계가 시드를 넘습니다",
    "detail": {
      "seed_krw": 10000000,
      "used_krw": 5404598.05,
      "remaining_krw": 4595401.95,
      "requested_quantity": 10,
      "requested_cost_krw": 17840000.0,
      "max_quantity": 2,
      "unit_cost_krw": 1784000.0
    }
  }
}
```
#### `POST /api/v1/portfolios/7/items` — 수량 0 → 422 + 최소 금액
요청 본문:
```json
{
  "market": "KOSPI",
  "ticker": "000660",
  "mode": "amount",
  "value": 100000
}
```
응답 `422`:
```json
{
  "error": {
    "code": "QUANTITY_ZERO",
    "message": "계산된 수량이 0주입니다. 금액이나 비중을 늘려 주세요",
    "detail": {
      "min_amount_krw": 1784000,
      "min_weight_pct": 17.84,
      "unit_cost_krw": 1784000.0
    }
  }
}
```
#### `POST /api/v1/portfolios/7/items` — 같은 종목 → 409 + 수정 안내
요청 본문:
```json
{
  "market": "KOSPI",
  "ticker": "005930",
  "mode": "quantity",
  "value": 1
}
```
응답 `409`:
```json
{
  "error": {
    "code": "DUPLICATE_ITEM",
    "message": "이미 담은 종목입니다. 수량을 바꾸려면 수정(PUT)을 사용하세요",
    "detail": {
      "item_id": 15,
      "hint": "PUT /api/v1/portfolios/7/items/15"
    }
  }
}
```
#### `PUT /api/v1/portfolios/7/items/16` — 기준가·환율 현재값으로 갱신
요청 본문:
```json
{
  "mode": "quantity",
  "value": 5,
  "memo": "수량 변경"
}
```
응답 `200`:
```json
{
  "item_id": 16,
  "portfolio_id": 7,
  "stock_id": 17,
  "market": "NASDAQ",
  "ticker": "AAPL",
  "name": "Apple",
  "currency": "USD",
  "quantity": 5,
  "ref_price": 332.89,
  "ref_fx_rate": 1339.08,
  "ref_date": "2026-10-05",
  "cost_krw": 2228831.71,
  "memo": "수량 변경",
  "created_at": "2026-10-06T13:11:16.884093Z",
  "updated_at": "2026-10-06T13:11:16.901825Z"
}
```
#### `PUT /api/v1/portfolios/7` — 원가 합계 미만 시드 → 409
요청 본문:
```json
{
  "name": "API 예시",
  "seed_krw": 1000000
}
```
응답 `409`:
```json
{
  "error": {
    "code": "SEED_BELOW_USED",
    "message": "시드를 현재 담은 원가 합계보다 작게 줄일 수 없습니다",
    "detail": {
      "used_krw": 4958831.71,
      "requested_seed_krw": 1000000
    }
  }
}
```
#### `GET /api/v1/portfolios/7/summary`
응답 `200`:
```json
{
  "portfolio_id": 7,
  "name": "API 예시",
  "currency": "KRW",
  "seed_krw": 10000000,
  "used_krw": 4958831.71,
  "remaining_krw": 5041168.29,
  "usage_rate": 0.495883,
  "items": [
    {
      "item_id": 15,
      "stock_id": 1,
      "market": "KOSPI",
      "country": "KR",
      "currency": "KRW",
      "ticker": "005930",
      "name": "삼성전자",
      "quantity": 10,
      "ref_price": 273000,
      "ref_fx_rate": 1,
      "ref_date": "2026-10-06",
      "memo": "금액 모드",
      "score": 51.75,
      "cost_krw": 2730000,
      "weight": 0.550533,
      "current_price": 273000,
      "price_date": "2026-10-06",
      "current_fx_rate": 1,
      "value_krw": 2730000,
      "pnl_krw": 0,
      "pnl_rate": 0,
      "local_return": 0,
      "fx_return": 0,
      "price_effect_krw": 0,
      "fx_effect_krw": 0,
      "groups": [
        "반도체"
      ]
    },
    {
      "item_id": 16,
      "stock_id": 17,
      "market": "NASDAQ",
      "country": "US",
      "currency": "USD",
      "ticker": "AAPL",
      "name": "Apple",
      "quantity": 5,
      "ref_price": 332.89,
      "ref_fx_rate": 1339.08,
      "ref_date": "2026-10-05",
      "memo": "수량 변경",
      "score": 35.94,
      "cost_krw": 2228831.71,
      "weight": 0.449467,
      "current_price": 332.89,
      "price_date": "2026-10-05",
      "current_fx_rate": 1339.08,
      "value_krw": 2228832,
      "pnl_krw": 0,
      "pnl_rate": 0,
      "local_return": 0,
      "fx_return": 0,
      "price_effect_krw": 0,
      "fx_effect_krw": 0,
      "groups": [
        "빅테크"
      ]
    }
  ],
  "market_weights": [
    {
      "cost_krw": 2730000,
      "weight": 0.550533,
      "country": "KR"
    },
    {
      "cost_krw": 2228831.71,
      "weight": 0.449467,
      "country": "US"
    }
  ],
  "group_weights": [
    {
      "cost_krw": 2730000,
      "weight": 0.550533,
      "group": "반도체"
    },
    {
      "cost_krw": 2228831.71,
      "weight": 0.449467,
      "group": "빅테크"
    }
  ],
  "weighted_score": 44.64,
  "total_value_krw": 4958832,
  "total_pnl_krw": 0,
  "total_pnl_rate": 0,
  "price_effect_krw": 0,
  "fx_effect_krw": 0,
  "fx_rate": 1339.08,
  "fx_rate_at": "2026-10-06T12:16:55.504460Z",
  "fx_stale": false,
  "as_of": "2026-10-06",
  "disclaimer": "모의 계산이며 투자 권유가 아닙니다."
}
```
#### `DELETE /api/v1/portfolios/7/items/15`
응답 `204`:
```json
(본문 없음)
```
#### `DELETE /api/v1/portfolios/7`
응답 `204`:
```json
(본문 없음)
```
### 3-6. 통계
#### `GET /api/v1/statistics/overview`
응답 `200`:
```json
{
  "stocks": 25,
  "peer_groups": 8,
  "daily_prices": 12276,
  "price_from": "2024-10-07",
  "price_to": "2026-10-06",
  "index_daily_prices": 2472,
  "fx_daily": 517,
  "fx_snapshots": 1,
  "valuation_snapshots": 3881,
  "financial_fy": 125,
  "disclosures": 1349,
  "stock_scores": 25,
  "scores_as_of": "2026-10-06",
  "last_refreshed_at": "2026-10-06T12:45:18.945590+00:00",
  "failed_jobs": 1
}
```
#### `GET /api/v1/statistics/market-valuation`
응답 `200`:
```json
{
  "min_samples": 3,
  "markets": [
    {
      "market": "NASDAQ",
      "country": "US",
      "currency": "USD",
      "stocks": 9,
      "per_samples": 9,
      "avg_per": 80.1,
      "min_per": 17.38,
      "max_per": 350.68,
      "avg_pbr": 16.46,
      "avg_roe": 0.4189,
      "total_market_cap_krw": 36989834635994727
    },
    {
      "market": "KOSPI",
      "country": "KR",
      "currency": "KRW",
      "stocks": 15,
      "per_samples": 12,
      "avg_per": 31.38,
      "min_per": 5.81,
      "max_per": 67.75,
      "avg_pbr": 3.51,
      "avg_roe": 0.1003,
      "total_market_cap_krw": 3391496760067950
    }
  ],
  "excluded": [
    {
      "market": "KOSDAQ",
      "stocks": 1
    }
  ],
  "note": "PER·PBR은 양수만 평균. 시총 합계는 원화 환산"
}
```
#### `GET /api/v1/statistics/peer-group-valuation`
응답 `200`:
```json
{
  "groups": [
    {
      "group_id": 4,
      "group_name": "빅테크",
      "members": 3,
      "kr_members": 0,
      "us_members": 3,
      "avg_per": 29.08,
      "min_per": 20.23,
      "max_per": 38.18,
      "avg_pbr": 19.65,
      "avg_roe": 0.6701,
      "min_roe": 0.1889,
      "max_roe": 1.5191,
      "avg_operating_margin": 0.2997,
      "avg_revenue_yoy": 0.122,
      "avg_return_1y": 0.1546,
      "min_return_1y": 0.0235,
      "max_return_1y": 0.2949,
      "total_market_cap_krw": 15358824734219305
    },
    "… 외 7개"
  ]
}
```
#### `GET /api/v1/statistics/disclosure-frequency?period=quarter`
응답 `200`:
```json
{
  "period": "quarter",
  "days": 365,
  "items": [
    {
      "period_start": "2025-10-01",
      "total": 277,
      "dart": 245,
      "sec": 32,
      "periodic_reports": 25,
      "share": 0.2055,
      "cumulative": 277
    },
    {
      "period_start": "2026-01-01",
      "total": 416,
      "dart": 375,
      "sec": 41,
      "periodic_reports": 25,
      "share": 0.3086,
      "cumulative": 693
    },
    "… 외 3개"
  ]
}
```
### 3-7. 공통 오류 응답
#### `GET /api/v1/portfolios/99999999999` — id가 INT 범위 밖 → 422 (이전에는 DB 오류가 500으로 노출)
응답 `422` (2026-10-08 실제 호출):
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "요청 값이 올바르지 않습니다",
    "detail": [
      {
        "loc": ["path", "portfolio_id"],
        "msg": "Input should be less than or equal to 2147483647",
        "type": "less_than_equal"
      }
    ]
  }
}
```
#### `GET /api/v1/stocks/KOSPI/999999` — 없는 종목 → 404
응답 `404`:
```json
{
  "error": {
    "code": "STOCK_NOT_FOUND",
    "message": "종목 KOSPI/999999을(를) 찾을 수 없습니다",
    "detail": null
  }
}
```
#### `GET /api/v1/stocks?sort=volume` — 전체 탭 거래량 정렬 → 422
응답 `422`:
```json
{
  "error": {
    "code": "VOLUME_SORT_REQUIRES_MARKET",
    "message": "시장마다 거래량 단위가 달라 '전체'에서는 거래량 정렬을 할 수 없습니다. 국내/미국 탭을 선택하세요",
    "detail": {
      "allowed_sort_for_all": [
        "market_cap"
      ]
    }
  }
}
```
#### `GET /api/v1/stocks?preset=buffett — 없는 프리셋 → 422`
응답 `422`:
```json
{
  "error": {
    "code": "UNKNOWN_PRESET",
    "message": "알 수 없는 매력도 프리셋입니다: buffett",
    "detail": {
      "presets": [
        "balanced",
        "value",
        "… 외 2개"
      ]
    }
  }
}
```
#### `POST /api/v1/portfolios` — 스키마 검증 → 422
요청 본문:
```json
{
  "name": "x",
  "seed_krw": 0
}
```
응답 `422`:
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "요청 값이 올바르지 않습니다",
    "detail": [
      {
        "loc": [
          "body",
          "seed_krw"
        ],
        "msg": "Input should be greater than 0",
        "type": "greater_than"
      }
    ]
  }
}
```
## 4. 화면 목록과 API 연결
| 화면 | URL | 영역 | 호출 API |
|---|---|---|---|
| 공통 | 모든 화면 | 사이드바 마지막 갱신·새로고침 | `GET /market/refresh/status`, `POST /market/refresh` |
| 대시보드 홈 | `/` | 지수 카드 5개 | `GET /market/indices` |
| | | USD/KRW 카드 | `GET /market/fx` |
| | | 투자 성향 펼침 메뉴(헤더) | `GET /scoring/presets` |
| | | 내 관심종목 카드(카드 클릭 → 상세 `?preset=`) | `GET /watchlist?preset=` |
| | | 거래량 상위 5 (국내/미국) | `GET /stocks?country=&sort=volume&limit=5` |
| 주식 리스트 | `/stocks` | 순위 리스트·탭·정렬·검색 | `GET /stocks?country=&sort=&order=&group=&q=&preset=` |
| | | 투자 성향 펼침 메뉴(헤더) | `GET /scoring/presets` |
| | | 경쟁 그룹 필터 | `GET /peer-groups` |
| | | ★ 토글 | `POST /watchlist`, `DELETE /watchlist/{market}/{ticker}` |
| | | 담기 모달 | `GET /portfolios`, `GET /market/fx`(USD), `POST /portfolios/{id}/items` |
| 종목 상세 | `/stocks/{market}/{ticker}` | 헤더·★·담기 | `GET /stocks/{market}/{ticker}` (+ 위 ★·담기 API) |
| | | 가격 차트 (1M~1Y) | `GET /stocks/{market}/{ticker}/candles?range=` |
| | | 핵심 지표·매력도·수치 분석 | `GET /stocks/{market}/{ticker}/analysis?preset=` |
| | | 투자 성향 펼침 메뉴(매력도 영역) | `GET /scoring/presets` |
| | | 재무 추이 | `GET /stocks/{market}/{ticker}/financials` |
| | | 경쟁 비교 표·막대 | `GET /stocks/{market}/{ticker}/peers` |
| | | 기준일=100 차트 | `GET /stocks/{market}/{ticker}/peers/chart?range=&group_id=` |
| | | 최근 공시 | `GET /stocks/{market}/{ticker}/disclosures` |
| 모의 포트폴리오 | `/portfolio?id=` | 선택·생성·수정·삭제 | `GET/POST /portfolios`, `PUT/DELETE /portfolios/{id}` |
| | | 요약·비중 차트·담은 목록 | `GET /portfolios/{id}/summary` |
| | | 종목 담기 패널 | `GET /stocks?limit=100`(검색 목록), `GET /market/fx`, `POST /portfolios/{id}/items` |
| | | 항목 수정·삭제 | `PUT/DELETE /portfolios/{id}/items/{item_id}` |
| (보고서·발표) | — | 데이터 개요·통계 | `GET /statistics/*` |

## 5. 에러 코드
코드에서 실제로 던지는 `code` 전체(`grep -rn 'code="' app` + `app/core/errors.py` 핸들러). 응답 형식은 모두 `{"error": {"code", "message", "detail"}}`. 재현 테스트 ID는 `docs/07`.

| `code` | HTTP | 발생 조건 | 발생 엔드포인트 | 메시지 예시 | 테스트 |
|---|---|---|---|---|---|
| `VALIDATION_ERROR` | 422 | 요청 파라미터·본문의 타입·형식·범위 위반(1절 입력 형식). `detail`에 `loc`·`msg`·`type` 목록 | 입력이 있는 모든 엔드포인트 | 요청 값이 올바르지 않습니다 | ST-09, PF-05, ERR-09~ERR-20 |
| `NOT_FOUND` | 404 | 정의되지 않은 경로 | - | Not Found | ERR-06 |
| `METHOD_NOT_ALLOWED` | 405 | 경로는 있으나 허용하지 않는 메서드 | - | Method Not Allowed | ERR-06 |
| `HTTP_ERROR` | 그 밖의 4xx·5xx | 프레임워크가 낸 기타 HTTP 예외(현재 라우트에서 직접 내는 곳 없음 — 최후 방어) | - | (예외 메시지) | ERR-07 |
| `INTERNAL_ERROR` | 500 | 처리하지 못한 예외. 응답은 고정 메시지만, 스택은 요청 ID와 함께 서버 로그 | 모든 엔드포인트 | 서버 오류가 발생했습니다 | ERR-08 |
| `STOCK_NOT_FOUND` | 404 | (시장, 티커) 종목 없음 | `/stocks/{market}/{ticker}`·하위, `/watchlist`(POST·DELETE), 담기 | 종목 KOSPI/999999을(를) 찾을 수 없습니다 | ST-06, ERR-09 |
| `USER_NOT_FOUND` | 404 | 요청 사용자(`DEFAULT_USER_ID`)가 DB에 없음 | `/watchlist`, `/portfolios` | 사용자(ID 99)를 찾을 수 없습니다 | WL-03 |
| `PORTFOLIO_NOT_FOUND` | 404 | 포트폴리오 없음 또는 다른 사용자 소유 | `/portfolios/{portfolio_id}`·하위 | 포트폴리오(ID 7)를 찾을 수 없습니다 | USR-02, ERR-10 |
| `ITEM_NOT_FOUND` | 404 | 그 포트폴리오에 항목 없음 또는 다른 사용자 소유 | `/portfolios/{id}/items/{item_id}` | 포트폴리오(ID 1)에 항목(ID 9)이 없습니다 | USR-04, ERR-10 |
| `WATCHLIST_ITEM_NOT_FOUND` | 404 | 요청 사용자의 관심종목에 없는 종목 | `DELETE /watchlist/{market}/{ticker}`, `PATCH /watchlist/order` | 관심종목에 KOSPI/005930이(가) 없습니다 | WL-03, USR-02 |
| `NO_PRICE` | 404 / 422 | 시세가 없는 종목을 분석(404)하거나 담음(422) | `/analysis`, 담기·담은 종목 수정 | 시세가 없어 분석할 수 없습니다 / 시세가 없어 담을 수 없습니다 | ERR-02 |
| `NO_PEER_GROUP` | 404 | 경쟁 그룹에 속하지 않은 종목의 기준일=100 차트 | `/peers/chart` | 이 종목은 경쟁 그룹에 속해 있지 않습니다 | ERR-01 |
| `GROUP_NOT_FOUND` | 404 | `group_id`가 그 종목이 속한 그룹이 아님 | `/peers/chart` | 이 종목은 그룹(ID 2)에 속해 있지 않습니다 | ERR-01 |
| `DUPLICATE_WATCHLIST` | 409 | 이미 관심종목에 있는 종목 추가 | `POST /watchlist` | 이미 관심종목에 있습니다 | WL-02 |
| `DUPLICATE_PORTFOLIO_NAME` | 409 | 같은 사용자의 같은 이름 포트폴리오 | `POST·PUT /portfolios` | 같은 이름의 포트폴리오가 이미 있습니다: 반도체 집중 | PF-07 |
| `DUPLICATE_ITEM` | 409 | 이미 담은 종목을 다시 담기(`detail.item_id`, 수정은 PUT) | 담기 | 이미 담은 종목입니다. 수량을 바꾸려면 수정(PUT)을 사용하세요 | ERR-03 |
| `SEED_EXCEEDED` | 409 | 담은 원가 합계가 시드 초과(`detail.max_quantity` 등) | 담기, 담은 종목 수정 | 담은 원가 합계가 시드를 넘습니다 | PF-02, ERR-13 |
| `SEED_BELOW_USED` | 409 | 시드를 담은 원가 합계보다 작게 수정 | `PUT /portfolios/{id}` | 시드를 현재 담은 원가 합계보다 작게 줄일 수 없습니다 | ERR-03 |
| `QUANTITY_ZERO` | 422 | 금액·비중으로 계산한 수량이 0주(`detail.min_amount_krw` 등) | 담기, 담은 종목 수정 | 계산된 수량이 0주입니다. 금액이나 비중을 늘려 주세요 | PF-04 |
| `INVALID_QUANTITY` | 422 | 수량 모드인데 정수가 아님 — 서비스 계층 방어(API는 스키마가 먼저 `VALIDATION_ERROR`) | (서비스 직접 호출) | 수량은 정수여야 합니다 | ERR-04 |
| `INVALID_MODE` | 422 | 지원하지 않는 담기 모드 — 서비스 계층 방어(API는 스키마가 먼저 `VALIDATION_ERROR`) | (서비스 직접 호출) | 지원하지 않는 모드: shares | ERR-04 |
| `UNKNOWN_PRESET` | 422 | 없는 투자 성향 프리셋(`detail.presets`) | `preset`을 받는 엔드포인트 | 알 수 없는 매력도 프리셋입니다: buffett | SC-13, ERR-19 |
| `VOLUME_SORT_REQUIRES_MARKET` | 422 | 전체 탭(country 없음)에서 거래량 정렬 | `GET /stocks` | 시장마다 거래량 단위가 달라 '전체'에서는 거래량 정렬을 할 수 없습니다 … | ST-03 |
| `FX_UNAVAILABLE` | 503 | 환율 조회 실패 + 저장된 환율 없음 | `/market/fx`, USD 종목 상세·담기·평가 | 환율을 조회할 수 없고 저장된 값도 없습니다 | RF-04, ERR-05 |
