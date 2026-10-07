# 06. 기능·API 정의서

- 기준: 실행 중인 서버의 OpenAPI(`/openapi.json`)와 **실제 호출 응답**(생성 시각 2026-10-06T22:11:16+09:00, 운영 DB). 배열은 앞 2개만 표시
- Swagger UI: `http://localhost:8000/docs`

## 1. 공통 규칙
| 항목 | 내용 |
|---|---|
| Base URL | `/api/v1` |
| 인증 | 없음 — **1차는 로컬·시연 전용 단일 사용자(데모) 모드**. 요청 사용자는 서버 의존성 `get_current_user_id()`가 정하며, 1차는 설정값 `DEFAULT_USER_ID`(기본 1 = demo)를 반환한다. 클라이언트는 `user_id`를 보내지 않으며 보내도 무시된다. 설정된 사용자가 DB에 없으면 404 `USER_NOT_FOUND`. 2차에서 이 함수를 JWT 검증으로 교체한다 |
| 소유권 | 포트폴리오·담은 항목·관심종목은 요청 사용자 소유만 조회·변경. 다른 사용자의 리소스는 존재 여부를 드러내지 않도록 없는 리소스와 같은 404(`PORTFOLIO_NOT_FOUND`·`ITEM_NOT_FOUND`·`WATCHLIST_ITEM_NOT_FOUND`) |
| 오류 형식 | `{"error": {"code", "message", "detail"}}` — 404 NOT_FOUND 계열, 409 CONFLICT 계열, 422 VALIDATION_ERROR·업무 검증, 503 FX_UNAVAILABLE |
| 숫자 | 금액·가격은 서버에서 Decimal로 계산, JSON에는 숫자. 비율은 소수(0.0523 = 5.23%) |
| 기준 시각 | 시세 응답은 `as_of`(거래일), 환율은 `rate_at`, 통화는 `currency` |
| 요청 ID | 모든 응답 헤더 `X-Request-ID`, 서버 로그에 같은 ID 기록 |
| 갱신 정책 | 같은 종류 외부 호출은 `REFRESH_TTL_HOURS`(4시간)에 최대 1회. TTL 이내 요청은 저장된 값 사용 |

## 2. 엔드포인트 목록

| 구분 | Method | URL | 기능 | 주요 파라미터 | 성공 / 오류 코드 |
|---|---|---|---|---|---|
| 시장·갱신 | GET | `/market/indices` | 지수별 최신값·등락·최근 30거래일 스파크라인 | - | 200 · 404/409/422 |
| 시장·갱신 | GET | `/market/fx` | USD/KRW 최신값·전일 대비·최근 30일 (TTL 내에는 외부 호출 없음) | - | 200 · 404/409/422 |
| 시장·갱신 | POST | `/market/refresh` | 환율·지수·증분 일봉·밸류에이션·점수 갱신 (작업별 TTL 이내면 SKIPPED) | - | 200 · 404/409/422 |
| 시장·갱신 | GET | `/market/refresh/status` | 갱신 상태 조회 — 외부 호출 없음 (사이드바 '마지막 갱신 시각' 표시용) | - | 200 · 404/409/422 |
| 종목 | GET | `/peer-groups` | 경쟁 그룹 목록 (리스트 필터용) | - | 200 · 404/409/422 |
| 종목 | GET | `/stocks` | 주식 리스트 (거래량/시총 순위, 시장·그룹 필터, 검색) | country, sort, order, group, q, limit, offset | 200 · 404/409/422 |
| 종목 | GET | `/stocks/{market}/{ticker}` | 종목 기본 정보 + 최신 시세·밸류에이션·매력도 | - | 200 · 404/409/422 |
| 종목 | GET | `/stocks/{market}/{ticker}/candles` | 기간 일봉 | range | 200 · 404/409/422 |
| 종목 | GET | `/stocks/{market}/{ticker}/financials` | FY 재무 추이 | limit | 200 · 404/409/422 |
| 종목 | GET | `/stocks/{market}/{ticker}/disclosures` | 최근 공시 | limit | 200 · 404/409/422 |
| 관심종목 | GET | `/watchlist` | 관심종목 카드 목록 (정렬순) | - | 200 · 404/409/422 |
| 관심종목 | POST | `/watchlist` | 관심종목 추가 | body: market, ticker | 201 · 404/409/422 |
| 관심종목 | PATCH | `/watchlist/order` | 관심종목 정렬 순서 변경 | body: items | 200 · 404/409/422 |
| 관심종목 | DELETE | `/watchlist/{market}/{ticker}` | 관심종목 삭제 | - | 204 · 404/409/422 |
| 모의 포트폴리오 | POST | `/portfolios` | 포트폴리오 생성 | body: name, seed_krw | 201 · 404/409/422 |
| 모의 포트폴리오 | GET | `/portfolios` | 사용자의 포트폴리오 목록 | - | 200 · 404/409/422 |
| 모의 포트폴리오 | GET | `/portfolios/{portfolio_id}` | 포트폴리오 단건 | - | 200 · 404/409/422 |
| 모의 포트폴리오 | PUT | `/portfolios/{portfolio_id}` | 이름·시드 수정 (원가 합계 미만 시드는 409) | body: name, seed_krw | 200 · 404/409/422 |
| 모의 포트폴리오 | DELETE | `/portfolios/{portfolio_id}` | 포트폴리오 삭제 (담은 항목 함께 삭제) | - | 204 · 404/409/422 |
| 모의 포트폴리오 | POST | `/portfolios/{portfolio_id}/items` | 종목 담기 (quantity/amount/weight 모드, 시드 초과 409, 수량 0이면 422) | body: mode, value, memo, market, ticker | 201 · 404/409/422 |
| 모의 포트폴리오 | GET | `/portfolios/{portfolio_id}/items` | 담은 종목과 현재 평가 | - | 200 · 404/409/422 |
| 모의 포트폴리오 | PUT | `/portfolios/{portfolio_id}/items/{item_id}` | 담은 종목 수정 (기준가·환율을 현재값으로 갱신) | body: mode, value, memo | 200 · 404/409/422 |
| 모의 포트폴리오 | DELETE | `/portfolios/{portfolio_id}/items/{item_id}` | 담은 종목 삭제 | - | 204 · 404/409/422 |
| 모의 포트폴리오 | GET | `/portfolios/{portfolio_id}/summary` | 요약: 사용·잔여·비중·가중 매력도·평가손익(환 효과 분리) | - | 200 · 404/409/422 |
| 분석 | GET | `/stocks/{market}/{ticker}/analysis` | 수치 분석(v_stock_metrics) + 매력도(팩터별·data_quality) | - | 200 · 404/409/422 |
| 분석 | GET | `/stocks/{market}/{ticker}/peers` | 경쟁 그룹별 비교 표 (그룹 내 RANK·AVG, 구성원 1명 그룹은 비교 대상 없음) | - | 200 · 404/409/422 |
| 분석 | GET | `/stocks/{market}/{ticker}/peers/chart` | 경쟁 그룹 기준일=100 가격 추이 (합집합 날짜 + 휴장일 null) | range, group_id | 200 · 404/409/422 |
| 통계 | GET | `/statistics/overview` | 데이터 개요: 행 수·기간·마지막 갱신 | - | 200 · 404/409/422 |
| 통계 | GET | `/statistics/market-valuation` | 시장별 평균 PER/PBR/ROE (HAVING 표본 수 이상) | min_samples | 200 · 404/409/422 |
| 통계 | GET | `/statistics/peer-group-valuation` | 경쟁 그룹별 평균·최고·최저 지표 | - | 200 · 404/409/422 |
| 통계 | GET | `/statistics/disclosure-frequency` | 기간별 공시 빈도 (월·분기·주) | period, days | 200 · 404/409/422 |

※ `GET /market/refresh/status`, `GET /peer-groups`는 화면 요구로 추가한 엔드포인트(ASSUMPTIONS A-48, A-67)

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
#### `GET /api/v1/stocks/KOSPI/005930/analysis`
응답 `200`:
```json
{
  "market": "KOSPI",
  "ticker": "005930",
  "currency": "KRW",
  "as_of": "2026-10-06",
  "valuation_as_of": "2026-10-06",
  "fin_period_end": "2025-12-31",
  "accounting_std": "K-IFRS",
  "fx_usd_krw": 1339.08,
  "fx_rate_at": "2026-10-06T12:16:55.504460Z",
  "metrics": {
    "return_1w": -0.007273,
    "return_1m": 0.068493,
    "return_3m": -0.141509,
    "return_6m": 0.413775,
    "return_1y": 2.067416,
    "volatility_1y": 0.752514,
    "max_drawdown_1y": -0.428966,
    "ma20": 266925,
    "ma60": 258483.3333,
    "ma120": 271808.3333,
    "ma120_gap": 0.004384,
    "high_52w": 374500,
    "low_52w": 90200,
    "position_52w": 0.642983,
    "volume": 12895120,
    "avg_volume_20d": 16612227,
    "volume_ratio_20d": 0.776243,
    "per": 41.18,
    "pbr": 4.25,
    "eps": 6605,
    "bps": 63997,
    "market_cap": 1590187781376000,
    "market_cap_krw": 1590187781376000,
    "operating_margin": 0.130696,
    "roe": 0.104312,
    "debt_ratio": 0.307843,
    "revenue_yoy": 0.108801,
    "operating_income_yoy": 0.332308
  },
  "attractiveness": {
    "as_of": "2026-10-06",
    "score": 51.75,
    "factors": {
      "valuation": {
        "score": 32.5,
        "weight": 30,
        "available": true
      },
      "growth": {
        "score": 53.33,
        "weight": 25,
        "available": true
      },
      "profitability": {
        "score": 66.67,
        "weight": 25,
        "available": true
      },
      "momentum": {
        "score": 60,
        "weight": 20,
        "available": true
      }
    },
    "data_quality": {
      "partition": "KR",
      "unavailable": {},
      "missing_inputs": []
    },
    "weights_version": "v1"
  },
  "disclaimer": "유니버스(25종목) 안에서 같은 시장끼리 비교한 상대 평가이며 투자 권유가 아닙니다."
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
| | | 내 관심종목 카드 | `GET /watchlist` |
| | | 거래량 상위 5 (국내/미국) | `GET /stocks?country=&sort=volume&limit=5` |
| 주식 리스트 | `/stocks` | 순위 리스트·탭·정렬·검색 | `GET /stocks?country=&sort=&order=&group=&q=` |
| | | 경쟁 그룹 필터 | `GET /peer-groups` |
| | | ★ 토글 | `POST /watchlist`, `DELETE /watchlist/{market}/{ticker}` |
| | | 담기 모달 | `GET /portfolios`, `GET /market/fx`(USD), `POST /portfolios/{id}/items` |
| 종목 상세 | `/stocks/{market}/{ticker}` | 헤더·★·담기 | `GET /stocks/{market}/{ticker}` (+ 위 ★·담기 API) |
| | | 가격 차트 (1M~1Y) | `GET /stocks/{market}/{ticker}/candles?range=` |
| | | 핵심 지표·매력도·수치 분석 | `GET /stocks/{market}/{ticker}/analysis` |
| | | 재무 추이 | `GET /stocks/{market}/{ticker}/financials` |
| | | 경쟁 비교 표·막대 | `GET /stocks/{market}/{ticker}/peers` |
| | | 기준일=100 차트 | `GET /stocks/{market}/{ticker}/peers/chart?range=&group_id=` |
| | | 최근 공시 | `GET /stocks/{market}/{ticker}/disclosures` |
| 모의 포트폴리오 | `/portfolio?id=` | 선택·생성·수정·삭제 | `GET/POST /portfolios`, `PUT/DELETE /portfolios/{id}` |
| | | 요약·비중 차트·담은 목록 | `GET /portfolios/{id}/summary` |
| | | 종목 담기 패널 | `GET /stocks?limit=100`(검색 목록), `GET /market/fx`, `POST /portfolios/{id}/items` |
| | | 항목 수정·삭제 | `PUT/DELETE /portfolios/{id}/items/{item_id}` |
| (보고서·발표) | — | 데이터 개요·통계 | `GET /statistics/*` |

