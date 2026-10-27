# 06. 기능·API 정의서

- 기준: 실행 중인 서버의 OpenAPI(`/openapi.json`)와 **실제 호출 응답**. 배열은 앞 2개만 표시
- 엔드포인트 목록(2절)·에러 코드(5절)는 2026-10-26 코드 기준으로 맞췄다(OpenAPI 경로 46개·메서드 55개 — 2차 로그인 12개 포함, `backend/app/api/*.py`, 에러 코드는 `backend/app/core/errors.py`·서비스의 `code=`와 1:1)
- 예시 응답은 호출 시각을 제목에 적었다. 표시가 없는 예시는 2026-10-06~12 호출이며, 2026-10-22 지금 서버로 다시 불러 **응답 칸 이름이 그대로임을 확인**했다(값만 그때 기준). 응답 칸이 늘어난 4개(`/stocks` 목록·종목 상세·`/analysis`·`/watchlist`)는 2026-10-22에 다시 호출해 바꿨다
- Swagger UI: `http://localhost:8000/docs` (로컬 `.env`의 `API_PORT`를 바꿨다면 그 포트) / 배포: `https://stockmind-538269380647.asia-northeast3.run.app/docs`

## 1. 공통 규칙
| 항목 | 내용 |
|---|---|
| Base URL | `/api/v1` (헬스체크 `/health`·`/health/db`만 루트, A-114) |
| 인증 | **2차 로그인(2026-10-26 배포)**: `Authorization: Bearer <access token>`(JWT HS256 15분, `POST /auth/login`·`/signup`·`/google`·`/refresh`가 본문으로 줌)이 있으면 그 계정이 요청 사용자다. refresh token(14일)은 httpOnly 쿠키 `stockmind_refresh`(Path `/api/v1/auth`, SameSite=Strict)로만 오가고 쓸 때마다 바뀐다(Redis에 해시만). 로그인하지 않았으면 아래 1차 규칙 그대로 — 단 배포 게스트는 포트폴리오를 보기만 하고 저장은 401 `AUTH_REQUIRED`. 1차 규칙: 요청 사용자는 서버 의존성 `get_current_user_id()`가 정한다. 클라이언트는 `user_id`를 보내지 않으며 보내도 무시된다. **로컬**: 설정값 `DEFAULT_USER_ID`(기본 1 = demo). **배포**(`GUEST_SESSION_ENABLED=true`): 서명된 세션 쿠키 `stockmind_session`(HttpOnly·Secure·SameSite=Lax, 1년)로 브라우저마다 게스트를 나눈다 — 쿠키가 없을 때 조회(GET·HEAD·OPTIONS)는 demo 화면, 첫 쓰기 요청에서 demo의 관심종목·포트폴리오를 복사한 게스트(`guest-…`)를 만든다. DB에 없는 사용자를 가리키는 옛 쿠키는 무시. 설정된 사용자가 DB에 없으면 404 `USER_NOT_FOUND` |
| 소유권 | 포트폴리오·담은 항목·관심종목은 요청 사용자 소유만 조회·변경. 다른 사용자의 리소스는 존재 여부를 드러내지 않도록 없는 리소스와 같은 404(`PORTFOLIO_NOT_FOUND`·`ITEM_NOT_FOUND`·`WATCHLIST_ITEM_NOT_FOUND`) |
| 오류 형식 | `{"error": {"code", "message", "detail"}}` — 404 NOT_FOUND 계열, 409 CONFLICT 계열, 422 VALIDATION_ERROR·업무 검증, 503 FX_UNAVAILABLE, 500 INTERNAL_ERROR. 코드 전체는 [5절 에러 코드](#5-에러-코드) |
| 500 처리 | 예상하지 못한 예외는 500 `INTERNAL_ERROR`와 고정 메시지만 응답한다(예외 메시지·스택·SQL·내부 경로는 응답에 넣지 않음). 스택은 서버 로그에 요청 ID와 함께 남고, 응답에도 `X-Request-ID` 헤더가 붙는다 |
| 입력 형식 | 형식·범위가 틀리면 DB 조회 전에 422 `VALIDATION_ERROR`(`detail`에 위치·사유). `market` 영문 2~10자, `ticker` 영숫자로 시작하는 영숫자·`.`·`-` 1~16자, id(`portfolio_id`·`item_id`·`group_id`) 1~2,147,483,647, 이름 1~100자(공백만 불가), `seed_krw`·금액 0 초과 1,000조 원 이하, 수량 정수 1~2,147,483,647, 비중 0 초과 100 이하, 메모 500자, `limit`·`offset`·`range`·`period`는 엔드포인트별 범위·허용 값(Swagger). 근거 ASSUMPTIONS A-112 |
| 숫자 | 금액·가격은 서버에서 Decimal로 계산, JSON에는 숫자. 비율은 소수(0.0523 = 5.23%) |
| 기준 시각 | 시세 응답은 `as_of`(거래일), 환율은 `rate_at`, 통화는 `currency` |
| 요청 ID | 모든 응답 헤더 `X-Request-ID`, 서버 로그에 같은 ID 기록 |
| 갱신 정책 | 같은 종류 외부 호출은 TTL에 최대 1회 — 주가·지수·환율은 `REFRESH_FAST_TTL_HOURS`(1시간), 그 밖(밸류에이션·섹터·점수 등)은 `REFRESH_TTL_HOURS`(4시간). TTL 이내 요청은 저장된 값 사용. 장 마감 전에는 일봉·지수를 전날까지만 요청한다. 일부 대상만 실패하면 30분 뒤 실패한 종목만 다시 받음(A-109). 서버가 떠 있는 동안 앱 안 스케줄러가 주기적으로 갱신한다 |
| 외부 소스 장애 시 동작 | **조회 API는 외부 소스를 직접 부르지 않고 DB에 저장된 마지막 값을 돌려준다**(시세·지수·밸류에이션·재무·공시·점수). 실패는 대상별로 `ingestion_logs`에 FAILED로 남고 나머지 대상은 계속 적재한다. 데이터의 기준 시점은 응답의 `as_of`로, 갱신 상태는 `GET /market/refresh/status`의 작업별 `FRESH`/`STALE`로 확인한다. 작업별 차이: ① **환율** — 조회 시 TTL이 지났으면 외부 호출, 실패하면 마지막 저장값 + `fx_stale: true`, 저장값도 없으면 503 `FX_UNAVAILABLE`(USD 종목 상세·담기·평가도 같음) ② **국내 밸류에이션** — pykrx(또는 `PRICE_SOURCE_KR=kis`면 KIS) 실패 시 DART FY 기반 파생값(`DERIVED`)으로 대체(A-02) ③ **비교군 종목 상세** — 백그라운드 수집 실패 시 `detail_status: failed`, 10분 뒤 다시 시도 ④ **점수** — 계산 실패 시 직전 점수 유지 |

## 2. 엔드포인트 목록

| 구분 | Method | URL | 기능 | 주요 파라미터 | 성공 · 오류(HTTP 상태와 `code`) |
|---|---|---|---|---|---|
| 헬스체크 | GET | `/health` (루트) | 프로세스 생존 확인 — DB에 접근하지 않음 | - | 200 |
| 헬스체크 | GET | `/health/db` (루트) | DB 연결 확인(`SELECT 1`). 컨테이너 HEALTHCHECK가 사용 | - | 200 · 503 DB_UNAVAILABLE |
| 시장·갱신 | GET | `/market/indices` | 지수별 최신값·등락·최근 1년 스파크라인·52주 범위(종가 기준, 1년치 있을 때만)·장 상태 `session_status`(거래소 휴장 달력: today·holiday·previous_session). 원자재 선물(WTI·금·구리·알루미늄·열연)도 같은 목록에 `category: "commodity"`·`unit`($/톤 등)으로 들어 있다(지수는 `category: "index"`, `unit: null`) | - | 200 |
| 시장·갱신 | GET | `/market/fx` | USD/KRW 최신값·전일 대비·최근 1년 DAILY·52주 범위 (TTL 내에는 외부 호출 없음) | - | 200 · 503 FX_UNAVAILABLE |
| 시장·갱신 | POST | `/market/refresh` | 환율·지수·섹터 등락률(SECTORS_US·SECTORS_KR)·증분 일봉·밸류에이션·점수 갱신 (작업별 TTL 이내면 SKIPPED) | - | 200 (작업별 실패는 본문 `jobs[].status`) |
| 시장·갱신 | GET | `/market/refresh/status` | 갱신 상태 조회 — 외부 호출 없음 (사이드바 '마지막 갱신 시각' 표시용) | - | 200 |
| 대시보드 홈 | GET | `/home/ranking` | 시장 주목 종목 TOP N — `volume_surge`: 당일 거래량 ÷ 직전 20거래일 평균(배수), `attractiveness`: 프리셋별 최신 매력도 점수. 대상 = 노출 종목 + 매력도 비교군 + 관심종목(전 종목 스캔 없음), `is_watched`로 ★ 표시. `family=financial`은 금융 묶음에 종합 점수가 없어 빈 목록(2026-10-27, D-028 — 금융 탭은 `/home/financial-peers`) | kind (volume_surge·attractiveness, 필수), country (KR·US, 기본 KR), family (general·financial, 기본 general), limit (1~20, 기본 5), preset | 200 · 422 VALIDATION_ERROR, UNKNOWN_PRESET |
| 대시보드 홈 | GET | `/home/financial-peers` | 금융 탭(D-028) — 하위 업종(주 테마 은행·카드·보험·증권·자산운용)마다 비교 표본 종목의 P/B(종가 ÷ BPS)·ROE(최근 3개 FY 평균)·P/E와 ROE 대비 P/B 위치(`gap` 음수 = 같은 ROE의 동종사보다 장부가 대비 쌈). P/B·ROE가 있는 종목 8개 이상이면 회귀선(`method: regression`, `slope`·`intercept`), 아니면 중앙값(`median_roe`·`median_pb`). 이름순이며 순위가 아니다(참고 정보) | country (KR·US, 기본 KR) | 200 · 422 VALIDATION_ERROR |
| 대시보드 홈 | GET | `/home/sectors` | 섹터 히트맵 — 저장된 섹터 전일 대비 등락률(%)만 읽음(수집은 갱신 작업). 가장 최근 거래일 기준, 그날 값이 없는 섹터는 `change_pct: null`, 저장값이 없으면 `available: false` | country (KR·US, 기본 KR) | 200 · 422 VALIDATION_ERROR |
| 대시보드 홈 | GET | `/home/sentiment` | 시장 심리 지수(StockMind 간이 계산, CNN Fear & Greed 아님) — 저장된 KOSPI·S&P 500·VIX 일봉으로 계산·저장, 외부 호출 없음. 점수·라벨·구성요소, 직전 거래일·5거래일 전 값 | country (KR·US, 기본 KR) | 200 · 422 VALIDATION_ERROR |
| 종목 | GET | `/peer-groups` | 테마 목록 (리스트 필터용) — `config/universe.yaml themes` 38개. 그룹마다 부모 섹터 `sector`, 구성원 수 `size`(노출 종목 + 비교군). 섹터 순서 → 이름 순 | - | 200 |
| 종목 | GET | `/stocks` | 주식 리스트 (거래량/시총 순위, 시장·테마 그룹·업종 섹터 필터, 검색, 프리셋별 매력도). 노출 종목 + 매력도 비교군(`coverage`로 구분), 상장 목록(listed)은 제외. 화면은 25개씩 페이지 | country, sort, order, group, sector (`config/universe.yaml` 섹터 이름, 그 외 422), q, limit, offset, preset | 200 · 422 VALIDATION_ERROR, VOLUME_SORT_REQUIRES_MARKET, UNKNOWN_PRESET |
| 종목 | GET | `/stocks/search` | 상단 검색 자동완성 — 노출 종목·비교군·상장 종목 목록(listed) 전체에서 이름·영문명·티커 부분 일치. 정렬: 티커 완전 일치 → 티커 앞부분 → 이름 앞부분 → 부분 일치(같으면 노출·비교군 먼저, 짧은 이름 먼저). LIKE 특수문자는 글자 그대로, 비활성(상장폐지) 제외 | q (1~50자, 필수), limit (1~20, 기본 8) | 200 · 422 VALIDATION_ERROR |
| 종목 | GET | `/stocks/{market}/{ticker}` | 종목 기본 정보 + 최신 시세·밸류에이션·매력도. 비교군·상장 목록 종목이면 상세 데이터 수집을 예약하고 `detail_status`(ready/loading/failed). 상장 목록 종목은 처음 열 때 시세가 없어 `close` 등이 null. `groups`는 소속 테마(주 테마 먼저, `is_primary`), **`theme`**은 주 테마(이름·부모 섹터·점수 묶음 `family`·원자재 연동 여부, 분류되지 않은 업종이면 null), **`commodity`**는 원자재 연동 테마 종목만 — 연결 원자재와 그 가격의 1년 등락·52주 위치(지수와 같은 저장값, 무료 시세가 없는 원자재면 `code: null`)와 안내 문구. **`market_condition`**: 시장·섹터 점수(0~100, 매력도와 별개인 위험 표시) — 0.7 × 시장 심리 지수(최신 저장값) + 0.3 × 섹터 흐름(같은 업종 섹터 표본의 5거래일 수익률 중앙값). 섹터가 없거나 표본이 5개 미만이면 시장만 쓴다. 정의는 09 '시장·섹터 점수', 구현 `app/services/market_condition.py`(외부 호출·DB 쓰기 없음) | preset | 200 · 404 STOCK_NOT_FOUND · 422 VALIDATION_ERROR, UNKNOWN_PRESET · 503 FX_UNAVAILABLE(USD) |
| 종목 | GET | `/stocks/{market}/{ticker}/candles` | 기간 일봉 | range | 200 · 404 STOCK_NOT_FOUND · 422 VALIDATION_ERROR |
| 종목 | GET | `/stocks/{market}/{ticker}/financials` | FY 재무 추이 | limit | 200 · 404 STOCK_NOT_FOUND · 422 VALIDATION_ERROR |
| 종목 | GET | `/stocks/{market}/{ticker}/disclosures` | 최근 공시 | limit | 200 · 404 STOCK_NOT_FOUND · 422 VALIDATION_ERROR |
| 관심종목 | GET | `/watchlist` | 관심종목 카드 목록 (정렬순, 프리셋별 매력도, 메모·목표가·목표가 대비 괴리율 `target_gap`) | preset | 200 · 404 USER_NOT_FOUND · 422 VALIDATION_ERROR, UNKNOWN_PRESET |
| 관심종목 | POST | `/watchlist` | 관심종목 추가 | body: market, ticker | 201 · 404 STOCK_NOT_FOUND, USER_NOT_FOUND · 409 DUPLICATE_WATCHLIST · 422 VALIDATION_ERROR |
| 관심종목 | PATCH | `/watchlist/order` | 관심종목 정렬 순서 변경 | body: items | 200 · 404 WATCHLIST_ITEM_NOT_FOUND, USER_NOT_FOUND · 422 VALIDATION_ERROR |
| 관심종목 | PUT | `/watchlist/{market}/{ticker}` | 메모·목표가 수정 — 보낸 필드만 변경, `null`이면 지움, 빈 본문 422. 목표가는 종목 통화 기준, 응답에 `target_gap` = (목표가 − 현재가) / 현재가 | body: memo (200자), target_price (> 0, 소수 4자리) | 200 · 404 STOCK_NOT_FOUND, WATCHLIST_ITEM_NOT_FOUND, USER_NOT_FOUND · 422 VALIDATION_ERROR |
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
| 모의 포트폴리오 | POST | `/portfolios/{portfolio_id}/preview/equal-weight` | 관심종목(또는 지정 종목) 균등 배분 미리보기 — **저장하지 않는 계산 전용**. 예산 ÷ 대상 종목 수 = 균등 몫, 1주 원가로 나눠 내림한 정수 수량(담기 금액 모드와 같은 환산)·원화 금액·실제 비중, 남는 금액, 제외 종목과 사유(ALREADY_IN_PORTFOLIO·NO_PRICE·PRICE_ABOVE_SHARE) | body(선택): stocks [{market, ticker}] (생략 시 관심종목 전체), budget_krw (생략 시 잔여 시드) | 200 · 404 PORTFOLIO_NOT_FOUND, STOCK_NOT_FOUND · 409 SEED_EXCEEDED(예산 > 잔여 시드, 잔여 시드 0) · 422 VALIDATION_ERROR, EMPTY_WATCHLIST · 503 FX_UNAVAILABLE(USD) |
| 분석 | GET | `/stocks/{market}/{ticker}/analysis` | 수치 분석(v_stock_metrics, 배당 `dps`·`dividend_yield` 포함) + 매력도(프리셋별 점수·팩터 기여도·지표 원값/Z·국가 내 순위·백분위·데이터 충족도·레이더용 주 그룹 평균 `peer_average`). 순위는 같은 국가·같은 점수 묶음(`rank.family` — financial이면 금융끼리). 상장 목록 종목은 `reference: true` 참고 점수(`reference_note`, 주 테마가 있으면 `z_adj`도 계산, 순위는 비교군 N개 + 이 종목). 리츠·부동산 테마는 점수 없이 `unscored_reason`. **금융 묶음**(2026-10-27, D-028)은 `score`·`rank`·`factors` 없이 `data_quality.score_null_code = financial_profile`과 `financial_profile`(같은 하위 업종 안 P/B·ROE·P/E·위치 — `/home/financial-peers`의 그룹 하나 + `target` = 이 종목 행) | preset | 200 · 404 STOCK_NOT_FOUND, NO_PRICE · 422 VALIDATION_ERROR, UNKNOWN_PRESET |
| 분석 | GET | `/scoring/presets` | 투자 성향 프리셋(sort_order 순: 위험·성장·균형·가치)과 팩터별 가중치 | - | 200 |
| 분석 | GET | `/stocks/{market}/{ticker}/peers` | 경쟁 그룹별 비교 표 (그룹 내 RANK·AVG, 구성원 1명 그룹은 비교 대상 없음) | - | 200 · 404 STOCK_NOT_FOUND · 422 VALIDATION_ERROR |
| 분석 | GET | `/stocks/{market}/{ticker}/peers/chart` | 경쟁 그룹 기준일=100 가격 추이 (합집합 날짜 + 휴장일 null) | range, group_id | 200 · 404 STOCK_NOT_FOUND, NO_PEER_GROUP, GROUP_NOT_FOUND · 422 VALIDATION_ERROR |
| 통계 | GET | `/statistics/overview` | 데이터 개요: 행 수·기간·마지막 갱신 | - | 200 |
| 통계 | GET | `/statistics/market-valuation` | 시장별 평균 PER/PBR/ROE (HAVING 표본 수 이상) | min_samples | 200 · 422 VALIDATION_ERROR |
| 통계 | GET | `/statistics/peer-group-valuation` | 경쟁 그룹별 평균·최고·최저 지표 | - | 200 |
| 통계 | GET | `/statistics/disclosure-frequency` | 기간별 공시 빈도 (월·분기·주) | period, days | 200 · 422 VALIDATION_ERROR |
| 통계 | GET | `/statistics/monthly` | 종목 월별 집계: 거래일 수·평균 종가·최고/최저·월초 대비 월말 수익률·거래량 합계/평균 (date_trunc + GROUP BY, FIRST_VALUE/LAST_VALUE 윈도우). 진행 중인 달은 `is_partial: true` | market, ticker (필수), months (1~24, 기본 12) | 200 · 404 STOCK_NOT_FOUND · 422 VALIDATION_ERROR |
| 통계 | GET | `/statistics/ranking` | 지표별 TOP N 랭킹(노출 종목). `v_stock_metrics` + `RANK() OVER` — 같은 값은 같은 순위(1, 1, 3), 지표값 없는 종목 제외. 수익률은 소수, 거래량은 주, 시총은 원화 환산 | metric (return_1m·return_3m·return_1y·volume·market_cap_krw, 필수), country (KR·US, 비우면 전체), order (desc·asc), limit (1~50, 기본 10) | 200 · 422 VALIDATION_ERROR, VOLUME_SORT_REQUIRES_MARKET(전체 + volume) |
| 통계 | GET | `/statistics/data-quality` | 데이터 품질 현황: 작업 종류별 마지막 성공·실패(사유·대상 티커), 최근 N일 상태별 건수(success·failed는 대상 단위, partial은 갱신 실행 단위, skipped)·격리 행 수, 오래된 4시간 갱신 작업(`stale_jobs`, 작업 단위 성공이 TTL×2 초과). `python -m app.ingest status`와 같은 기준(`backend/app/services/data_quality.py`) | days (1~90, 기본 7) | 200 · 422 VALIDATION_ERROR |
| 로그인 | GET | `/auth/config` | 로그인 화면 설정 — Google 클라이언트 ID(없으면 null → Google 버튼 숨김) | - | 200 |
| 로그인 | GET | `/auth/me` | 내 계정. 토큰 없이 부르면 `logged_in: false` | Authorization(선택) | 200 · 401 INVALID_TOKEN, TOKEN_EXPIRED |
| 로그인 | POST | `/auth/signup` | 가입(이메일·비밀번호 8자 이상·닉네임 2~20자). 이 브라우저의 게스트 관심종목을 이어 쓴다. access token + refresh 쿠키 | body: email, password, nickname | 201 · 409 EMAIL_TAKEN, NICKNAME_TAKEN · 422 VALIDATION_ERROR · 503 AUTH_STORE_UNAVAILABLE |
| 로그인 | POST | `/auth/login` | 이메일·비밀번호 로그인 | body: email, password | 200 · 401 INVALID_CREDENTIALS · 429 TOO_MANY_LOGIN_ATTEMPTS |
| 로그인 | POST | `/auth/google` | Google ID token 로그인(처음이면 가입, 같은 이메일 계정이면 연결) | body: credential | 200 · 401 INVALID_GOOGLE_TOKEN · 503 GOOGLE_LOGIN_DISABLED |
| 로그인 | POST | `/auth/refresh` | refresh 쿠키로 access token 다시 받기(refresh 교체) | 쿠키 `stockmind_refresh` | 200 · 401 REFRESH_INVALID, REFRESH_REUSED, REFRESH_RETRY |
| 로그인 | POST | `/auth/logout` | 이 기기 로그아웃(refresh 폐기·쿠키 삭제) | - | 204 |
| 로그인 | POST | `/auth/logout-all` | 모든 기기에서 로그아웃 | Authorization | 204 · 401 AUTH_REQUIRED |
| 로그인 | PUT | `/auth/password` | 비밀번호 변경·설정(Google 전용 계정은 현재 비밀번호 없이 설정). 다른 기기는 로그아웃 | Authorization, body: current_password, new_password | 204 · 401 AUTH_REQUIRED, INVALID_PASSWORD |
| 로그인 | DELETE | `/auth/me` | 탈퇴 — 관심종목·포트폴리오·설정까지 삭제(비밀번호가 없는 Google 전용 계정은 비밀번호 없이) | Authorization, body: password | 204 · 401 AUTH_REQUIRED, INVALID_PASSWORD |
| 로그인 | GET | `/auth/me/preferences` | 내 설정(theme·preset·metrics·watch_view·home_portfolio) | Authorization | 200 · 401 AUTH_REQUIRED |
| 로그인 | PUT | `/auth/me/preferences` | 내 설정 저장(보낸 칸만, null은 지움) | Authorization, body | 200 · 401 AUTH_REQUIRED · 422 VALIDATION_ERROR |

※ 오류 열은 엔드포인트별로 실제 발생할 수 있는 상태와 `code`다. 모든 엔드포인트는 예상하지 못한 예외 시 500 `INTERNAL_ERROR`. 코드별 조건은 [5절](#5-에러-코드).

※ `GET /market/refresh/status`, `GET /peer-groups`는 화면 요구로 추가한 엔드포인트(ASSUMPTIONS A-48, A-67). `GET /stocks/search`는 상단 검색용(2026-10-12)

※ 상장 종목 목록(listed): 검색용 이름·티커 마스터(`python -m app.ingest listing`, 비교군 일일 갱신 때 함께). 주식 리스트(`/stocks`)에는 나오지 않고 상단 검색에서만 찾는다. 매력도 유니버스·통계·경쟁 비교에는 넣지 않는다.

※ 매력도 비교군(benchmark): 점수 비교 표본으로만 쓰는 종목(개발산출물/09 11절 — 국가·테마별 시가총액 상위). 경쟁 비교(`/peers`, `/peers/chart`)·통계는 노출 종목(+대상 종목) 기준이고, 관심종목에 추가하면(POST `/watchlist`) 상세 데이터 수집을 예약한다.

※ `preset`: 투자 성향 프리셋 코드(aggressive·growth·balanced·value, 기본 balanced). 없는 코드(옛 quality 포함)는 422 `UNKNOWN_PRESET`(`detail.presets`에 사용 가능한 코드). 경쟁 비교 표(`/peers`)와 포트폴리오 요약의 매력도는 균형 프리셋 기준. 점수 정의는 개발산출물/09.

## 3. 요청·응답 예시 (실제 호출)
### 3-0. 헬스체크 (2026-10-08 실제 호출)
#### `GET /health`
응답 `200`:
```json
{"status": "ok"}
```
#### `GET /health/db`
응답 `200`:
```json
{"status": "ok", "db": "ok"}
```
#### `GET /health/db` — DB 컨테이너를 멈춘 상태(`docker stop stockmind_db`) → 503 (약 4초, 연결 시간 제한 10초 이내)
응답 `503`:
```json
{"error": {"code": "DB_UNAVAILABLE", "message": "DB에 연결할 수 없습니다", "detail": null}}
```
이때 `GET /health`는 200 — 프로세스는 살아 있고 DB만 문제임을 구분한다.


### 3-1. 시장·갱신
#### `GET /api/v1/market/indices` — 최근 1년 스파크라인(화면에서 1개월·3개월·1년으로 자름), 52주 범위, 장 상태
응답 `200`:
```json
{
  "as_of": "2026-10-09",
  "indices": [
    {
      "code": "KOSPI",
      "name": "KOSPI",
      "country": "KR",
      "currency": "KRW",
      "category": "index",
      "unit": null,
      "as_of": "2026-10-08",
      "close": 6625.93,
      "prev_close": 6803.9,
      "change": -177.97,
      "change_rate": -0.026157,
      "sparkline": [
        {
          "date": "2025-10-10",
          "close": 3610.6
        },
        "… 외 243개"
      ],
      "high_52w": 9114.55,
      "low_52w": 3561.81,
      "position_52w": 0.551821,
      "session_status": "previous_session"
    },
    "… 외 9개"
  ]
}
```
#### `GET /api/v1/market/fx`
응답 `200`:
```json
{
  "pair": "USD/KRW",
  "currency": "KRW",
  "usd_krw": 1333.98,
  "rate_at": "2026-10-12T13:18:24.886505+09:00",
  "granularity": "SNAPSHOT",
  "fx_stale": false,
  "prev_close": 1342.99,
  "change": -9.01,
  "change_rate": -0.006709,
  "history": [
    {
      "date": "2025-10-13",
      "usd_krw": 1429.03
    },
    {
      "date": "2025-10-14",
      "usd_krw": 1426.0699
    },
    "… 외 257개"
  ],
  "as_of": "2026-10-12T13:18:24.886505+09:00",
  "high_52w": 1554.48,
  "low_52w": 1333.98,
  "position_52w": 0
}
```
#### `GET /api/v1/market/refresh/status`
응답 `200`:
```json
{
  "refreshed_at": "2026-10-12T15:08:35.130869+09:00",
  "next_refresh_available_at": "2026-10-12T17:18:25.035205+09:00",
  "ttl_hours": 4.0,
  "jobs": [
    {
      "job_type": "FX",
      "status": "FRESH",
      "detail": null,
      "last_success_at": "2026-10-12T13:18:25.035205+09:00",
      "counts": {}
    },
    {
      "job_type": "INDICES",
      "status": "FRESH",
      "detail": null,
      "last_success_at": "2026-10-12T13:18:39.418969+09:00",
      "counts": {}
    },
    "… 외 5개"
  ],
  "basis": "일봉 기준"
}
```
#### `POST /api/v1/market/refresh` — TTL 이내라 모든 작업 SKIPPED (외부 호출 없음)
응답 `200`:
```json
{
  "refreshed_at": "2026-10-12T06:27:31.141007Z",
  "next_refresh_available_at": "2026-10-12T17:18:25.035205+09:00",
  "ttl_hours": 4.0,
  "jobs": [
    {
      "job_type": "FX",
      "status": "SKIPPED",
      "detail": "TTL 이내 — 마지막 성공 2026-10-12T13:18:25.035205+09:00",
      "last_success_at": "2026-10-12T13:18:25.035205+09:00",
      "counts": {}
    },
    {
      "job_type": "INDICES",
      "status": "SKIPPED",
      "detail": "TTL 이내 — 마지막 성공 2026-10-12T13:18:39.418969+09:00",
      "last_success_at": "2026-10-12T13:18:39.418969+09:00",
      "counts": {}
    },
    {
      "job_type": "SECTORS_US",
      "status": "SKIPPED",
      "detail": "TTL 이내 — 마지막 성공 2026-10-12T15:08:17.965561+09:00",
      "last_success_at": "2026-10-12T15:08:17.965561+09:00",
      "counts": {}
    },
    {
      "job_type": "SECTORS_KR",
      "status": "SKIPPED",
      "detail": "TTL 이내 — 마지막 성공 2026-10-12T15:08:35.130869+09:00",
      "last_success_at": "2026-10-12T15:08:35.130869+09:00",
      "counts": {}
    },
    {
      "job_type": "PRICES",
      "status": "SKIPPED",
      "detail": "TTL 이내 — 마지막 성공 2026-10-12T13:18:55.994997+09:00",
      "last_success_at": "2026-10-12T13:18:55.994997+09:00",
      "counts": {}
    },
    {
      "job_type": "VALUATION",
      "status": "SKIPPED",
      "detail": "TTL 이내 — 마지막 성공 2026-10-12T13:19:22.821645+09:00",
      "last_success_at": "2026-10-12T13:19:22.821645+09:00",
      "counts": {}
    },
    {
      "job_type": "SCORES",
      "status": "SKIPPED",
      "detail": "TTL 이내 — 마지막 성공 2026-10-12T13:19:24.072844+09:00",
      "last_success_at": "2026-10-12T13:19:24.072844+09:00",
      "counts": {}
    }
  ],
  "basis": "일봉 기준"
}
```
### 3-2. 종목
#### `GET /api/v1/stocks?country=KR&sort=volume&limit=2` — 2026-10-22 실제 호출
응답 `200`:
```json
{
  "total": 70,
  "limit": 2,
  "offset": 0,
  "sort": "volume",
  "order": "desc",
  "preset": "balanced",
  "fx_rate_at": "2026-10-22T16:34:29.378443+09:00",
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
      "as_of": "2026-10-22",
      "close": 214500,
      "change": -9000,
      "change_rate": -0.040268,
      "volume": 11000328,
      "market_cap": 1306643268888000,
      "market_cap_krw": 1306643268888000,
      "score": 74.55,
      "is_watched": true,
      "sector": "반도체·전자",
      "coverage": "featured"
    },
    {
      "rank": 2,
      "stock_id": 240,
      "market": "KOSPI",
      "country": "KR",
      "currency": "KRW",
      "ticker": "018880",
      "name": "한온시스템",
      "name_en": null,
      "as_of": "2026-10-21",
      "close": 3845,
      "change": -60,
      "change_rate": -0.015365,
      "volume": 4726464,
      "market_cap": 3945936409990,
      "market_cap_krw": 3945936409990,
      "score": 19.14,
      "is_watched": false,
      "sector": "산업재",
      "coverage": "benchmark"
    }
  ]
}
```
#### `GET /api/v1/stocks/KOSPI/005930` — 2026-10-22 실제 호출
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
  "as_of": "2026-10-22",
  "close": 214500,
  "prev_close": 223500,
  "change": -9000,
  "change_rate": -0.040268,
  "volume": 11000328,
  "close_krw": 214500,
  "fx_rate": null,
  "fx_rate_at": null,
  "fx_stale": false,
  "valuation_as_of": "2026-10-21",
  "valuation_source": "PYKRX",
  "per": 33.84,
  "pbr": 3.49,
  "eps": 6605,
  "bps": 63997,
  "market_cap": 1306643268888000,
  "market_cap_krw": 1306643268888000,
  "shares_outstanding": 5846278608,
  "score": 74.55,
  "score_as_of": "2026-10-22",
  "preset": "balanced",
  "groups": [
    {
      "group_id": 1,
      "name": "반도체",
      "is_primary": true
    },
    {
      "group_id": 4,
      "name": "하드웨어·통신장비",
      "is_primary": false
    },
    "… 외 1개"
  ],
  "is_watched": true,
  "coverage": "featured",
  "detail_status": "ready",
  "market_condition": {
    "score": 29,
    "label": "낮음",
    "sentiment": 22.1,
    "sector_name": "반도체·전자",
    "sector_flow": 44,
    "sector_sample": 7,
    "sector_as_of": "2026-10-22",
    "index_code": "KOSPI",
    "stock_r5": 0.033735,
    "sector_r5": -0.012,
    "index_r5": -0.003682,
    "as_of": "2026-10-22"
  },
  "theme": {
    "name": "반도체",
    "sector": "반도체·전자",
    "family": "general",
    "commodity_linked": false
  },
  "commodity": null
}
```
원자재 연동 테마 종목(예: `NYSE/AA`)의 `commodity`:
```json
{
  "code": "ALUMINUM",
  "name": "알루미늄",
  "unit": "$/톤",
  "as_of": "2026-10-23",
  "close": 3268.5,
  "change_1y": 0.214,
  "position_52w": 0.82,
  "note": "원자재 가격을 따라 이익이 크게 바뀌는 업종입니다. 원자재 가격이 높을 때는 이익도 높아 주가가 싸 보일 수 있습니다. 매력도의 저평가는 최근 3년 평균 이익으로 계산했습니다."
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
#### `GET /api/v1/stocks/KOSPI/005930/analysis?preset=growth` — 2026-10-22 실제 호출
응답 `200`:
```json
{
  "market": "KOSPI",
  "ticker": "005930",
  "currency": "KRW",
  "as_of": "2026-10-22",
  "valuation_as_of": "2026-10-21",
  "fin_period_end": "2025-12-31",
  "accounting_std": "K-IFRS",
  "fx_usd_krw": 1321.48,
  "fx_rate_at": "2026-10-22T16:34:29.378443+09:00",
  "metrics": {
    "return_1w": 0.033735,
    "return_1m": -0.227027,
    "return_3m": -0.176583,
    "…": "외 27개 (v_stock_metrics 수치 분석 지표, 7절)"
  },
  "attractiveness": {
    "as_of": "2026-10-22",
    "preset": {
      "code": "growth",
      "name": "성장",
      "description": "성장성 중심"
    },
    "score": 75.65,
    "composite": 0.3751,
    "factor_coverage": 5,
    "factor_total": 5,
    "rank": {
      "country": "KR",
      "family": "general",
      "position": 15,
      "total": 70,
      "percentile": 79.7
    },
    "factors": {
      "value": {
        "score": 0.048,
        "weight": 0.1,
        "effective_weight": 0.1,
        "contribution": 0.0048,
        "available": true
      },
      "quality": {
        "score": -0.3735,
        "weight": 0.2,
        "effective_weight": 0.2,
        "contribution": -0.0747,
        "available": true
      },
      "growth": {
        "score": 0.0164,
        "weight": 0.4,
        "effective_weight": 0.4,
        "contribution": 0.0066,
        "available": true
      },
      "safety": {
        "score": 0.2159,
        "weight": 0.05,
        "effective_weight": 0.05,
        "contribution": 0.0108,
        "available": true
      },
      "momentum": {
        "score": 1.7107,
        "weight": 0.25,
        "effective_weight": 0.25,
        "contribution": 0.4277,
        "available": true
      }
    },
    "metrics": [
      {
        "metric": "earnings_yield",
        "label": "이익수익률 E/P",
        "factor": "value",
        "direction": 1,
        "raw_value": 0.030792540792540794,
        "z_raw": 0.0193,
        "z_adj": 0.0821
      },
      {
        "metric": "book_yield",
        "label": "B/P",
        "factor": "value",
        "direction": 1,
        "raw_value": 0.29835431235431237,
        "z_raw": -0.3957,
        "z_adj": 0.0139
      },
      "… 외 7개"
    ],
    "data_quality": {
      "partition": "KR"
    },
    "method": "지표별로 같은 시장 안 로버스트 Z(중앙값·MAD)를 구해 ±3으로 자르고, 주 경쟁 그룹 평균을 축소 추정으로 빼 섹터 중립화한 뒤 팩터 평균 → 프리셋 가중 평균 → 시장 안에서 다시 표준화해 100·Φ(z)로 0~100 변환합니다.",
    "peer_average": {
      "group_name": "반도체",
      "size": 10,
      "factors": {
        "value": -0.1181,
        "quality": 0.5293,
        "growth": 0.1013,
        "safety": -0.8708,
        "momentum": 0.6447
      }
    },
    "reference": false,
    "reference_note": null,
    "fin_basis": [
      {
        "fiscal_year": 2025,
        "stocks": 70
      }
    ]
  },
  "disclaimer": "매력도는 노출 종목과 매력도 비교군 안에서 같은 시장끼리 비교한 상대적 위치를 나타내는 팩터 점수이며, 수익률 예측이나 투자 권유가 아닙니다."
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
#### `GET /api/v1/watchlist` — 2026-10-22 실제 호출
응답 `200`:
```json
{
  "user_id": 1,
  "preset": "balanced",
  "count": 8,
  "items": [
    {
      "sort_order": 1,
      "added_at": "2026-10-15T15:45:57.826858+09:00",
      "stock_id": 1,
      "market": "KOSPI",
      "country": "KR",
      "currency": "KRW",
      "ticker": "005930",
      "name": "삼성전자",
      "as_of": "2026-10-22",
      "close": 214500,
      "change": -9000,
      "change_rate": -0.040268,
      "score": 74.55,
      "memo": null,
      "target_price": null,
      "target_gap": null,
      "updated_at": "2026-10-16T09:28:25.132654+09:00"
    },
    {
      "sort_order": 2,
      "added_at": "2026-10-15T15:45:57.826858+09:00",
      "stock_id": 2,
      "market": "KOSPI",
      "country": "KR",
      "currency": "KRW",
      "ticker": "000660",
      "name": "SK하이닉스",
      "as_of": "2026-10-22",
      "close": 1218000,
      "change": -70000,
      "change_rate": -0.054348,
      "score": 97.44,
      "memo": null,
      "target_price": null,
      "target_gap": null,
      "updated_at": "2026-10-16T09:28:25.132654+09:00"
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
#### `PUT /api/v1/watchlist/NASDAQ/AAPL` — 메모·목표가 수정 (2026-10-08 실제 호출, 확인 후 `null`로 되돌림)
요청: `{"target_price": 400, "memo": "curl 확인"}` → 현재가 $336.67 대비 괴리율 (400 − 336.67) / 336.67 = 0.188107
응답 `200`:
```json
{
  "sort_order": 5,
  "added_at": "2026-10-07T01:09:49.680628Z",
  "stock_id": 17,
  "market": "NASDAQ",
  "country": "US",
  "currency": "USD",
  "ticker": "AAPL",
  "name": "Apple",
  "as_of": "2026-10-07",
  "close": 336.67,
  "change": 3.04,
  "change_rate": 0.009112,
  "score": 56.16,
  "memo": "curl 확인",
  "target_price": 400,
  "target_gap": 0.188107,
  "updated_at": "2026-10-08T07:35:47.568050Z"
}
```
`{}` → 422 `VALIDATION_ERROR`(바꿀 값 없음), `{"target_price": 0}` → 422, 관심종목이 아닌 `KOSPI/000660` → 404 `WATCHLIST_ITEM_NOT_FOUND`, 없는 `KOSPI/999999` → 404 `STOCK_NOT_FOUND`.

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
#### `POST /api/v1/portfolios/1/preview/equal-weight` — 균등 배분 미리보기 (2026-10-08 실제 호출, 저장되지 않음)
요청: `{"budget_krw": 3000000}` · 관심종목 6개 중 이미 담은 AAPL·NVDA는 제외 → 4종목 × 750,000원. 호출 전후 `portfolio_items` 9행·원가 합계 그대로임을 확인.
응답 `200`:
```json
{
  "portfolio_id": 1,
  "seed_krw": 30000000,
  "used_krw": 15189368.4,
  "remaining_krw": 14810631.6,
  "budget_krw": 3000000,
  "target_count": 4,
  "share_krw": 750000,
  "items": [
    {
      "market": "NASDAQ",
      "ticker": "MSFT",
      "name": "Microsoft",
      "currency": "USD",
      "price": 529.76,
      "price_date": "2026-10-07",
      "fx_rate": 1338.08,
      "unit_cost_krw": 708861.26,
      "quantity": 1,
      "cost_krw": 708861.26,
      "weight": 0.371472
    },
    {
      "market": "NASDAQ",
      "ticker": "AMZN",
      "name": "Amazon",
      "currency": "USD",
      "price": 259.92,
      "price_date": "2026-10-07",
      "fx_rate": 1338.08,
      "unit_cost_krw": 347793.75,
      "quantity": 2,
      "cost_krw": 695587.51,
      "weight": 0.364516
    },
    {
      "market": "NASDAQ",
      "ticker": "AVGO",
      "name": "Broadcom",
      "currency": "USD",
      "price": 376.51,
      "price_date": "2026-10-07",
      "fx_rate": 1338.08,
      "unit_cost_krw": 503800.5,
      "quantity": 1,
      "cost_krw": 503800.5,
      "weight": 0.264012
    }
  ],
  "total_cost_krw": 1908249.27,
  "leftover_krw": 1091750.73,
  "skipped": [
    {
      "market": "NASDAQ",
      "ticker": "AAPL",
      "name": "Apple",
      "reason": "ALREADY_IN_PORTFOLIO",
      "message": "이미 담은 종목입니다(수량 변경은 담은 종목 수정)",
      "unit_cost_krw": null,
      "share_krw": null
    },
    {
      "market": "NASDAQ",
      "ticker": "NVDA",
      "name": "NVIDIA",
      "reason": "ALREADY_IN_PORTFOLIO",
      "message": "이미 담은 종목입니다(수량 변경은 담은 종목 수정)",
      "unit_cost_krw": null,
      "share_krw": null
    },
    {
      "market": "NASDAQ",
      "ticker": "META",
      "name": "Meta Platforms",
      "reason": "PRICE_ABOVE_SHARE",
      "message": "1주 원가가 균등 몫보다 큽니다",
      "unit_cost_krw": 965170.48,
      "share_krw": 750000
    }
  ],
  "fx_rate": 1338.08,
  "fx_rate_at": "2026-10-08T06:09:54.257939Z",
  "saved": false
}
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
#### `GET /api/v1/statistics/monthly?market=KOSPI&ticker=005930&months=2` — 월별 집계 (2026-10-08 실제 호출)
`months=2` → 지난달과 이번 달. 이번 달(10월)은 진행 중이라 `is_partial: true`, `monthly_return`은 10월 첫 거래일 종가 274,500 대비 마지막 거래일 종가 269,000 = −2.0036%.
응답 `200`:
```json
{
  "market": "KOSPI",
  "ticker": "005930",
  "name": "삼성전자",
  "currency": "KRW",
  "months": 2,
  "today": "2026-10-08",
  "items": [
    {
      "month": "2026-09",
      "trading_days": 20,
      "first_date": "2026-09-01",
      "last_date": "2026-09-30",
      "avg_close": 263825,
      "max_high": 286500,
      "min_low": 243000,
      "first_close": 261000,
      "last_close": 269500,
      "monthly_return": 0.032567,
      "total_volume": 337498673,
      "avg_volume": 16874934,
      "is_partial": false
    },
    {
      "month": "2026-10",
      "trading_days": 4,
      "first_date": "2026-10-01",
      "last_date": "2026-10-07",
      "avg_close": 273125,
      "max_high": 279500,
      "min_low": 264500,
      "first_close": 274500,
      "last_close": 269000,
      "monthly_return": -0.020036,
      "total_volume": 54551646,
      "avg_volume": 13637912,
      "is_partial": true
    }
  ]
}
```

#### `GET /api/v1/statistics/ranking?metric=return_1y&limit=3` — 1년 수익률 상위 3 (2026-10-08 실제 호출)
국가 구분 없이(전체) 원화·달러 종목을 같은 수익률(소수)로 비교. `total`은 1년 수익률이 있는 노출 종목 수.
응답 `200`:
```json
{
  "metric": "return_1y",
  "country": null,
  "order": "desc",
  "limit": 3,
  "total": 25,
  "items": [
    {
      "rank": 1,
      "stock_id": 2,
      "market": "KOSPI",
      "country": "KR",
      "currency": "KRW",
      "ticker": "000660",
      "name": "SK하이닉스",
      "value": 3.336283,
      "as_of": "2026-10-07"
    },
    {
      "rank": 2,
      "stock_id": 25,
      "market": "NASDAQ",
      "country": "US",
      "currency": "USD",
      "ticker": "AMD",
      "name": "AMD",
      "value": 2.053567,
      "as_of": "2026-10-07"
    },
    {
      "rank": 3,
      "stock_id": 1,
      "market": "KOSPI",
      "country": "KR",
      "currency": "KRW",
      "ticker": "005930",
      "name": "삼성전자",
      "value": 2.022472,
      "as_of": "2026-10-07"
    }
  ]
}
```

#### `GET /api/v1/statistics/data-quality?days=1` — 데이터 품질 현황 (2026-10-08 실제 호출, `jobs`는 PRICES·FINANCIALS만 발췌)
PRICES의 마지막 실패는 수정(d6097e3) 전 아침 기록(미국 장 전 날짜 요청). `stale`은 4시간 갱신 작업만 판단하고 그 밖(FINANCIALS 등)은 `null`.
응답 `200`:
```json
{
  "days": 1,
  "since": "2026-10-07T07:39:31.858870Z",
  "generated_at": "2026-10-08T07:39:31.858870Z",
  "ttl_hours": 4.0,
  "stale_after_hours": 8.0,
  "totals": {
    "success": 500,
    "failed": 60,
    "partial": 0,
    "skipped": 9,
    "quarantined_rows": 176
  },
  "jobs": [
    {
      "job_type": "FINANCIALS",
      "last_success_at": "2026-10-07T05:40:52.472834Z",
      "last_failure_at": null,
      "last_failure_reason": null,
      "last_failure_target": null,
      "quarantined_rows": 0,
      "counts": {
        "success": 0,
        "failed": 0,
        "partial": 0,
        "skipped": 0
      },
      "stale": null
    },
    {
      "job_type": "PRICES",
      "last_success_at": "2026-10-08T06:10:37.230523Z",
      "last_failure_at": "2026-10-08T01:51:09.978884Z",
      "last_failure_reason": "ProviderError: yfinance history AMD: YFPricesMissingError: $AMD: Data doesn't exist for startDate = 1791432000, endDate = 1791518400",
      "last_failure_target": "AMD",
      "quarantined_rows": 164,
      "counts": {
        "success": 258,
        "failed": 46,
        "partial": 0,
        "skipped": 2
      },
      "stale": false
    }
  ],
  "stale_jobs": []
}
```

### 3-7. 대시보드 홈 (외부 호출 없음 — DB만 사용)
#### `GET /api/v1/home/ranking?kind=volume_surge&country=KR&limit=5` — 거래량 급증(배수)
응답 `200`:
```json
{
  "kind": "volume_surge",
  "country": "KR",
  "preset": null,
  "items": [
    {
      "rank": 1,
      "stock_id": 7,
      "market": "KOSPI",
      "country": "KR",
      "currency": "KRW",
      "ticker": "373220",
      "name": "LG에너지솔루션",
      "value": 3.181,
      "as_of": "2026-10-08",
      "is_watched": true
    },
    {
      "rank": 2,
      "stock_id": 14,
      "market": "KOSPI",
      "country": "KR",
      "currency": "KRW",
      "ticker": "012450",
      "name": "한화에어로스페이스",
      "value": 2.4753,
      "as_of": "2026-10-08",
      "is_watched": false
    },
    "… 외 3개"
  ]
}
```
#### `GET /api/v1/home/ranking?kind=attractiveness&country=US&limit=5` — 매력도 순위(균형 프리셋)
응답 `200`:
```json
{
  "kind": "attractiveness",
  "country": "US",
  "preset": "balanced",
  "items": [
    {
      "rank": 1,
      "stock_id": 21,
      "market": "NASDAQ",
      "country": "US",
      "currency": "USD",
      "ticker": "NVDA",
      "name": "NVIDIA",
      "value": 95.28,
      "as_of": "2026-10-12",
      "is_watched": true
    },
    {
      "rank": 2,
      "stock_id": 19,
      "market": "NASDAQ",
      "country": "US",
      "currency": "USD",
      "ticker": "GOOGL",
      "name": "Alphabet",
      "value": 92.39,
      "as_of": "2026-10-12",
      "is_watched": false
    },
    "… 외 3개"
  ]
}
```
#### `GET /api/v1/home/sectors?country=KR` — 코스피 200 섹터 지수 11개 (가중치는 타일 크기용 근사치)
응답 `200`:
```json
{
  "country": "KR",
  "available": true,
  "as_of": "2026-10-08",
  "session_status": "previous_session",
  "fetched_at": "2026-10-12T15:08:17.969736+09:00",
  "sectors": [
    {
      "code": "1155",
      "name": "정보기술",
      "weight": 35.0,
      "change_pct": -3.4975
    },
    {
      "code": "1156",
      "name": "금융",
      "weight": 12.0,
      "change_pct": -3.1413
    },
    "… 외 9개"
  ]
}
```
#### `GET /api/v1/home/sentiment?country=US` — S&P 500 + VIX 기준
응답 `200`:
```json
{
  "market": "US",
  "index_code": "SPX",
  "formula_version": 1,
  "as_of": "2026-10-09",
  "session_status": "previous_session",
  "score": 79.25,
  "label": "탐욕",
  "components": {
    "price_position": 99.5,
    "ma_gap_score": 69.91,
    "rsi_score": 59.93,
    "vix_score": 87.65
  },
  "previous": {
    "trade_date": "2026-10-08",
    "score": 76.27,
    "label": "탐욕"
  },
  "week_ago": {
    "trade_date": "2026-10-02",
    "score": 75.49,
    "label": "탐욕"
  }
}
```
### 3-8. 공통 오류 응답
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
### 3-9. 로그인 (2026-10-26 로컬 실제 호출 — 예시 계정은 마지막에 탈퇴)
#### `POST /api/v1/auth/signup`
요청: `{"email": "doc-example@example.com", "password": "example-pass-1234", "nickname": "docexample"}` → 응답 `201` (+ `Set-Cookie: stockmind_refresh=…; Path=/api/v1/auth; HttpOnly; Secure; SameSite=Strict`, 14일)
```json
{
  "access_token": "eyJhbGciOi…",
  "token_type": "bearer",
  "expires_in": 900,
  "user": {
    "logged_in": true,
    "user_id": 17,
    "nickname": "docexample",
    "email": "doc-example@example.com",
    "has_password": true,
    "has_google": false
  }
}
```
같은 이메일로 다시 가입 → `409`:
```json
{"error": {"code": "EMAIL_TAKEN", "message": "이미 가입된 이메일이에요", "detail": null}}
```
#### `POST /api/v1/auth/login` — 비밀번호가 틀림 → `401`
```json
{"error": {"code": "INVALID_CREDENTIALS", "message": "이메일 또는 비밀번호가 맞지 않아요", "detail": null}}
```
#### `PUT /api/v1/auth/me/preferences` (Authorization: Bearer …) — 요청 `{"theme": "dark", "preset": "value"}` → `200`
```json
{"theme": "dark", "preset": "value", "metrics": null, "watch_view": null, "home_portfolio": null}
```
#### `POST /api/v1/auth/refresh` (쿠키만) → `200`, 새 access token + 새 refresh 쿠키. 쿠키가 없으면 `401`:
```json
{"error": {"code": "REFRESH_INVALID", "message": "로그인이 필요해요", "detail": null}}
```
#### `DELETE /api/v1/auth/me` — 요청 `{"password": "example-pass-1234"}` → `204`. 그 뒤 같은 토큰으로 `/auth/me` → `401 INVALID_TOKEN`

## 4. 화면 목록과 API 연결
| 화면 | URL | 영역 | 호출 API |
|---|---|---|---|
| 공통 | 모든 화면 | 사이드바 마지막 갱신·새로고침 | `GET /market/refresh/status`, `POST /market/refresh` |
| 공통 | 모든 화면 | 상단 검색바(자동완성 → 종목 상세) | `GET /stocks/search?q=&limit=8` |
| 대시보드 홈 | `/` | 지수·환율 카드(카드 위 선택 상자에서 지수 10개 + 원자재 5개 + 환율 중 선택, 기본 6개) — 스파크라인 기간 1개월·3개월·1년, 52주 위치 바, 장 상태 배지, 한 줄 시장 요약 | `GET /market/indices` |
| | | USD/KRW 카드 | `GET /market/fx` |
| | | 투자 성향 펼침 메뉴(상단 검색바 줄) | `GET /scoring/presets` |
| | | 내 관심종목 — 컴팩트 행(기본, 최대 8)·카드(3열×2줄) 보기, 클릭 → 상세 `?preset=`, 목표가·괴리율·메모 표시, 관심종목 등락 요약 | `GET /watchlist?preset=` |
| | | 관심종목 편집 버튼 → 메모·목표가 모달 | `PUT /watchlist/{market}/{ticker}` |
| | | 섹터 히트맵(국내/미국) | `GET /home/sectors?country=` |
| | | 시장 심리 지수(국내/미국) | `GET /home/sentiment?country=` |
| | | 시장 주목 종목 TOP 5 — 거래량 급증·매력도 순위 × 국내/미국 카드 4장 | `GET /home/ranking?kind=&country=&limit=5&preset=` |
| | | 내 포트폴리오 — 비중 도넛·범례(선택한 포트폴리오는 브라우저에 기억) | `GET /portfolios`, `GET /portfolios/{id}/summary` |
| 주식 리스트 | `/stocks` | 순위 리스트(노출 + 비교군, 25개씩 페이지)·탭·정렬·검색·업종 섹터 필터 | `GET /stocks?country=&sort=&order=&group=&sector=&q=&limit=25&offset=&preset=` |
| | | 투자 성향 펼침 메뉴(헤더) | `GET /scoring/presets` |
| | | 테마 필터 | `GET /peer-groups` |
| | | ★ 토글 | `POST /watchlist`, `DELETE /watchlist/{market}/{ticker}` |
| | | 담기 모달 | `GET /portfolios`, `GET /market/fx`(USD), `POST /portfolios/{id}/items` |
| 종목 상세 | `/stocks/{market}/{ticker}` | 헤더·★·담기 — 주 테마(채운 배지)·보조 테마(테두리 배지)·원자재 연동 배지, 시장·섹터 점수 아래 연결 원자재의 가격·1년 위치 | `GET /stocks/{market}/{ticker}` (`groups`·`theme`·`commodity`) (+ 위 ★·담기 API) |
| | | 가격 차트 (1M~1Y) | `GET /stocks/{market}/{ticker}/candles?range=` |
| | | 투자 매력도(게이지·레이더·요소별 카드·계산 근거)·핵심 정보(시총·배당수익률·52주)·투자 지표 상세(접힘) | `GET /stocks/{market}/{ticker}/analysis?preset=` |
| | | 상장 목록·비교군 종목 수집 대기(2초마다, 일봉이 먼저 오면 가격·매력도부터 표시) | `GET /stocks/{market}/{ticker}` |
| | | 투자 성향 펼침 메뉴(매력도 영역) | `GET /scoring/presets` |
| | | 월별 요약(최근 12개월 표, 접힘 — 펼칠 때 호출) | `GET /statistics/monthly?market=&ticker=&months=12` |
| | | 재무 추이 | `GET /stocks/{market}/{ticker}/financials` |
| | | 경쟁 비교 표·막대 | `GET /stocks/{market}/{ticker}/peers` |
| | | 기준일=100 차트 | `GET /stocks/{market}/{ticker}/peers/chart?range=&group_id=` |
| | | 최근 공시 | `GET /stocks/{market}/{ticker}/disclosures` |
| 모의 포트폴리오 | `/portfolio?id=` | 선택·생성·수정·삭제 | `GET/POST /portfolios`, `PUT/DELETE /portfolios/{id}` |
| | | 요약·비중 차트·담은 목록 | `GET /portfolios/{id}/summary` |
| | | 종목 담기 패널 | `GET /stocks?limit=100`(검색 목록), `GET /market/fx`, `POST /portfolios/{id}/items` |
| | | 관심종목 균등 배분 미리보기 → 결과 모달 · '모두 담기' | `POST /portfolios/{id}/preview/equal-weight` → 종목별 `POST /portfolios/{id}/items` |
| | | 항목 수정·삭제 | `PUT/DELETE /portfolios/{id}/items/{item_id}` |
| 로그인 (2차) | `/login` | 이메일 가입·로그인, Google 로그인 버튼 | `GET /auth/config`, `POST /auth/signup`·`/login`·`/google` |
| 공통 (2차) | 모든 화면 | access token 만료(401 TOKEN_EXPIRED) 시 자동 갱신 후 다시 요청, 로그인하면 화면 설정을 계정과 맞춤 | `POST /auth/refresh`, `GET·PUT /auth/me/preferences` |
| 설정 | `/settings` | 계정(로그인 안내 / 비밀번호 변경·설정 · 모든 기기 로그아웃 · 탈퇴) — 2차 | `GET /auth/me`, `PUT /auth/password`, `POST /auth/logout-all`, `DELETE /auth/me` |
| 설정 | `/settings` | 화면 테마(라이트 기본 / 다크) — 브라우저 localStorage `stockmind:theme`, 각 화면 head의 인라인 스크립트가 첫 그리기 전에 적용 | (API 없음) |
| (보고서·발표) | — | 데이터 개요·통계 | `GET /statistics/*` |

## 5. 에러 코드
코드에서 실제로 던지는 `code` 전체(`grep -rn 'code="' app` + `backend/app/core/errors.py` 핸들러). 응답 형식은 모두 `{"error": {"code", "message", "detail"}}`. 재현 테스트 ID는 `개발산출물/07`.

| `code` | HTTP | 발생 조건 | 발생 엔드포인트 | 메시지 예시 | 테스트 |
|---|---|---|---|---|---|
| `VALIDATION_ERROR` | 422 | 요청 파라미터·본문의 타입·형식·범위 위반(1절 입력 형식). `detail`에 `loc`·`msg`·`type` 목록 | 입력이 있는 모든 엔드포인트 | 요청 값이 올바르지 않습니다 | ST-09, PF-05, ERR-09~ERR-20 |
| `NOT_FOUND` | 404 | 정의되지 않은 경로 | - | Not Found | ERR-06 |
| `METHOD_NOT_ALLOWED` | 405 | 경로는 있으나 허용하지 않는 메서드 | - | Method Not Allowed | ERR-06 |
| `HTTP_ERROR` | 400 등 | 프레임워크가 낸 기타 HTTP 예외. 실제 예: 본문이 UTF-8이 아니어서 해석하지 못함(400 "There was an error parsing the body"). JSON 문법 오류는 422 `VALIDATION_ERROR`(`json_invalid`) | 본문을 받는 엔드포인트 | There was an error parsing the body | ERR-07 |
| `INTERNAL_ERROR` | 500 | 처리하지 못한 예외. 응답은 고정 메시지만, 스택은 요청 ID와 함께 서버 로그 | 모든 엔드포인트 | 서버 오류가 발생했습니다 | ERR-08 |
| `STOCK_NOT_FOUND` | 404 | (시장, 티커) 종목 없음 | `/stocks/{market}/{ticker}`·하위, `/watchlist`(POST·DELETE), 담기, `/statistics/monthly` | 종목 KOSPI/999999을(를) 찾을 수 없습니다 | ST-06, ERR-09, AN-14 |
| `EMPTY_WATCHLIST` | 422 | 균등 배분 미리보기에서 종목을 지정하지 않았는데 관심종목이 0개 | `POST /portfolios/{id}/preview/equal-weight` | 관심종목이 없습니다. 종목을 지정하거나 관심종목을 추가하세요 | PF-18 |
| `USER_NOT_FOUND` | 404 | 요청 사용자(`DEFAULT_USER_ID`)가 DB에 없음 | `/watchlist`, `/portfolios` | 사용자(ID 99)를 찾을 수 없습니다 | WL-03 |
| `PORTFOLIO_NOT_FOUND` | 404 | 포트폴리오 없음 또는 다른 사용자 소유 | `/portfolios/{portfolio_id}`·하위 | 포트폴리오(ID 7)를 찾을 수 없습니다 | USR-02, ERR-10 |
| `ITEM_NOT_FOUND` | 404 | 그 포트폴리오에 항목 없음 또는 다른 사용자 소유 | `/portfolios/{id}/items/{item_id}` | 포트폴리오(ID 1)에 항목(ID 9)이 없습니다 | USR-04, ERR-10 |
| `WATCHLIST_ITEM_NOT_FOUND` | 404 | 요청 사용자의 관심종목에 없는 종목 | `PUT·DELETE /watchlist/{market}/{ticker}`, `PATCH /watchlist/order` | 관심종목에 KOSPI/005930이(가) 없습니다 | WL-03, USR-02, WL-12 |
| `NO_PRICE` | 404 / 422 | 시세가 없는 종목을 분석(404)하거나 담음(422) | `/analysis`, 담기·담은 종목 수정 | 시세가 없어 분석할 수 없습니다 / 시세가 없어 담을 수 없습니다 | ERR-02 |
| `NO_PEER_GROUP` | 404 | 경쟁 그룹에 속하지 않은 종목의 기준일=100 차트 | `/peers/chart` | 이 종목은 경쟁 그룹에 속해 있지 않습니다 | ERR-01 |
| `GROUP_NOT_FOUND` | 404 | `group_id`가 그 종목이 속한 그룹이 아님 | `/peers/chart` | 이 종목은 그룹(ID 2)에 속해 있지 않습니다 | ERR-01 |
| `DUPLICATE_WATCHLIST` | 409 | 이미 관심종목에 있는 종목 추가 | `POST /watchlist` | 이미 관심종목에 있습니다 | WL-02 |
| `DUPLICATE_PORTFOLIO_NAME` | 409 | 같은 사용자의 같은 이름 포트폴리오 | `POST·PUT /portfolios` | 같은 이름의 포트폴리오가 이미 있습니다: 반도체 집중 | PF-07 |
| `DUPLICATE_ITEM` | 409 | 이미 담은 종목을 다시 담기(`detail.item_id`, 수정은 PUT) | 담기 | 이미 담은 종목입니다. 수량을 바꾸려면 수정(PUT)을 사용하세요 | ERR-03 |
| `SEED_EXCEEDED` | 409 | 담은 원가 합계가 시드 초과(`detail.max_quantity` 등) | 담기, 담은 종목 수정, 균등 배분 미리보기(예산 > 잔여 시드·잔여 시드 0) | 담은 원가 합계가 시드를 넘습니다 | PF-02, ERR-13, PF-17 |
| `SEED_BELOW_USED` | 409 | 시드를 담은 원가 합계보다 작게 수정 | `PUT /portfolios/{id}` | 시드를 현재 담은 원가 합계보다 작게 줄일 수 없습니다 | ERR-03 |
| `QUANTITY_ZERO` | 422 | 금액·비중으로 계산한 수량이 0주(`detail.min_amount_krw` 등) | 담기, 담은 종목 수정 | 계산된 수량이 0주입니다. 금액이나 비중을 늘려 주세요 | PF-04 |
| `INVALID_QUANTITY` | 422 | 수량 모드인데 정수가 아님 — 서비스 계층 방어(API는 스키마가 먼저 `VALIDATION_ERROR`) | (서비스 직접 호출) | 수량은 정수여야 합니다 | ERR-04 |
| `INVALID_MODE` | 422 | 지원하지 않는 담기 모드 — 서비스 계층 방어(API는 스키마가 먼저 `VALIDATION_ERROR`) | (서비스 직접 호출) | 지원하지 않는 모드: shares | ERR-04 |
| `UNKNOWN_PRESET` | 422 | 없는 투자 성향 프리셋(`detail.presets`) | `preset`을 받는 엔드포인트 | 알 수 없는 매력도 프리셋입니다: buffett | SC-13, ERR-19 |
| `VOLUME_SORT_REQUIRES_MARKET` | 422 | 전체 탭(country 없음)에서 거래량 정렬 | `GET /stocks`, `GET /statistics/ranking?metric=volume` | 시장마다 거래량 단위가 달라 '전체'에서는 거래량 정렬을 할 수 없습니다 … | ST-03, AN-20 |
| `DB_UNAVAILABLE` | 503 | `SELECT 1` 실패(연결 거부·시간 초과 등). 접속 정보는 응답에 넣지 않고 로그에만 | `GET /health/db` | DB에 연결할 수 없습니다 | HL-03, HL-04 |
| `FX_UNAVAILABLE` | 503 | 환율 조회 실패 + 저장된 환율 없음 | `/market/fx`, USD 종목 상세·담기·평가 | 환율을 조회할 수 없고 저장된 값도 없습니다 | RF-04, ERR-05 |
| `AUTH_REQUIRED` | 401 | 로그인이 필요한 기능을 토큰 없이 호출, 게스트가 포트폴리오를 저장 | `/auth/logout-all`·`/password`·`DELETE /auth/me`·`/me/preferences`, 배포 게스트의 `POST·PUT·DELETE /portfolios…` | 로그인이 필요해요 | AUTH-14 |
| `INVALID_TOKEN` | 401 | Authorization 형식 오류·위조·탈퇴한 사용자 | Authorization을 받는 모든 엔드포인트 | 로그인 정보가 올바르지 않아요 | AUTH-02·03·09 |
| `TOKEN_EXPIRED` | 401 | access token 만료(15분) → 화면이 `/auth/refresh` 후 다시 요청 | 같음 | 로그인이 만료됐어요 | AUTH-02·09 |
| `INVALID_CREDENTIALS` | 401 | 이메일·비밀번호 불일치(없는 이메일도 같은 응답·같은 시간) | `POST /auth/login` | 이메일 또는 비밀번호가 맞지 않아요 | AUTH-07 |
| `INVALID_PASSWORD` | 401 | 비밀번호 변경·탈퇴의 현재 비밀번호 불일치 | `PUT /auth/password`, `DELETE /auth/me` | 비밀번호가 맞지 않아요 | AUTH-15·16 |
| `INVALID_GOOGLE_TOKEN` | 401 | Google ID token 서명·aud·iss·email_verified 검증 실패 | `POST /auth/google` | Google 로그인 정보를 확인하지 못했어요 | AUTH-20 |
| `REFRESH_INVALID` | 401 | refresh 쿠키 없음·만료·폐기, 탈퇴한 계정 | `POST /auth/refresh` | 로그인이 필요해요 | AUTH-10·11 |
| `REFRESH_REUSED` | 401 | 이미 교체된 refresh token을 30초 뒤 다시 씀(탈취로 보고 그 기기의 토큰 모두 폐기) | `POST /auth/refresh` | 보안을 위해 이 기기는 로그아웃됐어요 | AUTH-10 |
| `REFRESH_RETRY` | 401 | 교체 30초 안에 옛 토큰이 다시 옴(탭 두 개 동시 요청) — 쿠키는 그대로, 화면이 다시 시도 | `POST /auth/refresh` | 잠시 후 다시 시도해 주세요 | AUTH-10 |
| `EMAIL_TAKEN` · `NICKNAME_TAKEN` · `ACCOUNT_TAKEN` | 409 | 이미 가입된 이메일 / 쓰고 있는 닉네임 / 동시 가입 경합 | `POST /auth/signup`, `POST /auth/google` | 이미 가입된 이메일이에요 | AUTH-06 |
| `TOO_MANY_LOGIN_ATTEMPTS` | 429 | 15분 동안 실패가 이메일당 5회·IP당 20회 초과(`detail.retry_after_minutes`) | `POST /auth/login` | 로그인 시도가 너무 많아요. 15분 뒤에 다시 시도해 주세요 | AUTH-08 |
| `GOOGLE_LOGIN_DISABLED` | 503 | `GOOGLE_CLIENT_ID` 없음 | `POST /auth/google` | Google 로그인이 설정되지 않았어요 | AUTH-21 |
| `AUTH_STORE_UNAVAILABLE` | 503 | Redis(refresh token·시도 제한 저장소) 연결 실패 | 가입·로그인·refresh·로그아웃 | 로그인 서버에 잠시 연결할 수 없어요 | — |
