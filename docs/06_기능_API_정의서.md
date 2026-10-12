# 06. 기능·API 정의서 (초안 — Stage 1 범위)

> **상태: Stage 0 초안.** Stage 1 범위의 공통 규칙·엔드포인트 계약·화면·에러 코드만 담았다.
> 요청·응답 **실제 호출 예시**(3-1 시장, 3-2 종목)는 Stage 1 통합 때 D가 실행 결과로 채운다. 응답 JSON 형태는 원본 최종본의 3-1·3-2 예시에서 **매력도(`score`)·`coverage`·`detail_status`·`sector`·`industry` 필드를 뺀 모양**이다.
> 이후 단계(관심종목·포트폴리오·재무·공시·매력도·분석·통계·홈 위젯)는 해당 단계에서 이 문서에 추가한다.

- Swagger UI: `http://localhost:8000/docs`

## 1. 공통 규칙
| 항목 | 내용 |
|---|---|
| Base URL | `/api/v1` (헬스체크 `/health`·`/health/db`만 루트) |
| 인증 | 없음 — 로컬·시연 전용 단일 사용자(데모) 모드. 사용자 의존성은 Stage 2에서 추가 |
| 오류 형식 | `{"error": {"code", "message", "detail"}}` — 404 NOT_FOUND 계열, 409 CONFLICT 계열, 422 VALIDATION_ERROR, 503, 500 INTERNAL_ERROR. 코드 전체는 [5절](#5-에러-코드) |
| 500 처리 | 예상하지 못한 예외는 500 `INTERNAL_ERROR`와 고정 메시지만 응답한다(예외 메시지·스택·SQL·내부 경로는 응답에 넣지 않음). 스택은 서버 로그에 요청 ID와 함께 남고, 응답에도 `X-Request-ID` 헤더가 붙는다 |
| 입력 형식 | 형식·범위가 틀리면 DB 조회 전에 422 `VALIDATION_ERROR`(`detail`에 위치·사유). `market` 영문 2~10자, `ticker` 영숫자로 시작하는 영숫자·`.`·`-` 1~16자, `limit`·`offset`·`range`는 엔드포인트별 범위·허용 값(Swagger) |
| 숫자 | 금액·가격은 서버에서 Decimal로 계산, JSON에는 숫자(정수면 int, 아니면 float). 비율은 소수(0.0523 = 5.23%) |
| 기준 시각 | 시세 응답은 `as_of`(거래일), 환율은 `rate_at`, 통화는 `currency` |
| 요청 ID | 모든 응답 헤더 `X-Request-ID`, 서버 로그에 같은 ID 기록 |
| 외부 소스 | **조회 API는 외부 소스를 직접 부르지 않고 DB에 저장된 값만 돌려준다.** 외부 호출은 수집(`app.ingest`)·갱신 서비스에서만 한다 |

## 2. 엔드포인트 목록 (Stage 0~1)

| 구분 | Method | URL | 기능 | 주요 파라미터 | 성공 · 오류(HTTP 상태와 `code`) | 단계 |
|---|---|---|---|---|---|---|
| 헬스체크 | GET | `/health` (루트) | 프로세스 생존 확인 — DB에 접근하지 않음 | - | 200 | 0 |
| 헬스체크 | GET | `/health/db` (루트) | DB 연결 확인(`SELECT 1`). 컨테이너 HEALTHCHECK가 사용 | - | 200 · 503 DB_UNAVAILABLE | 0 |
| 시장 | GET | `/market/indices` | 지수별 최신값·등락·스파크라인(DB 값만) | - | 200 | 1-B |
| 시장 | GET | `/market/fx` | USD/KRW 최신값·전일 대비·DAILY 추이(DB 값만, 외부 호출은 Stage 2~3 FxService) | - | 200 | 1-B |
| 종목 | GET | `/peer-groups` | 경쟁 그룹 목록 (리스트 필터용) | - | 200 | 1-B |
| 종목 | GET | `/stocks` | 주식 리스트 (거래량/시총 순위, 시장·그룹 필터) | country, sort, order, group, limit, offset | 200 · 422 VALIDATION_ERROR, VOLUME_SORT_REQUIRES_MARKET | 1-B |
| 종목 | GET | `/stocks/{market}/{ticker}` | 종목 기본 정보 + 최신 시세·밸류에이션 | - | 200 · 404 STOCK_NOT_FOUND · 422 VALIDATION_ERROR | 1-B |
| 종목 | GET | `/stocks/{market}/{ticker}/candles` | 기간 일봉 | range | 200 · 404 STOCK_NOT_FOUND · 422 VALIDATION_ERROR | 1-B |

※ 오류 열은 엔드포인트별로 실제 발생할 수 있는 상태와 `code`다. 모든 엔드포인트는 예상하지 못한 예외 시 500 `INTERNAL_ERROR`.

## 3. 요청·응답 예시 (실제 호출)
### 3-0. 헬스체크 (Stage 0 실제 호출)
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
#### `GET /health/db` — DB가 응답하지 않을 때 → 503 (연결 시간 제한 10초 이내)
응답 `503`:
```json
{"error": {"code": "DB_UNAVAILABLE", "message": "DB에 연결할 수 없습니다", "detail": null}}
```
이때 `GET /health`는 200 — 프로세스는 살아 있고 DB만 문제임을 구분한다.

### 3-1. 시장 — Stage 1 통합 때 채움
### 3-2. 종목 — Stage 1 통합 때 채움

## 4. 화면 목록과 API 연결 (Stage 1)
| 화면 | URL | 영역 | 호출 API |
|---|---|---|---|
| 공통 | 모든 화면 | 사이드바(대시보드·주식 리스트·모의 포트폴리오) | 없음 (마지막 갱신 시각은 Stage 3) |
| 대시보드 홈 | `/` | 지수·환율 카드 | `GET /market/indices`, `GET /market/fx` |
| 주식 리스트 | `/stocks` | 순위 리스트·탭·정렬 | `GET /stocks?country=&sort=&order=&group=` |
| | | 경쟁 그룹 필터 | `GET /peer-groups` |
| 종목 상세 | `/stocks/{market}/{ticker}` | 기본 정보·핵심 지표 | `GET /stocks/{market}/{ticker}` |
| | | 가격 차트 (1M~1Y) | `GET /stocks/{market}/{ticker}/candles?range=` |
| 모의 포트폴리오 | `/portfolio` | 빈 셸 (Stage 2) | - |

## 5. 에러 코드 (Stage 0~1)
응답 형식은 모두 `{"error": {"code", "message", "detail"}}`. 도메인 에러 코드는 각 단계에서 `backend/app/core/errors.py`에 추가하면서 이 표도 함께 갱신한다.

| `code` | HTTP | 발생 조건 | 발생 엔드포인트 | 메시지 예시 | 단계 |
|---|---|---|---|---|---|
| `VALIDATION_ERROR` | 422 | 요청 파라미터·본문의 타입·형식·범위 위반. `detail`에 `loc`·`msg`·`type` 목록 | 입력이 있는 모든 엔드포인트 | 요청 값이 올바르지 않습니다 | 0 |
| `NOT_FOUND` | 404 | 정의되지 않은 경로 | - | Not Found | 0 |
| `METHOD_NOT_ALLOWED` | 405 | 경로는 있으나 허용하지 않는 메서드 | - | Method Not Allowed | 0 |
| `HTTP_ERROR` | 400 등 | 프레임워크가 낸 기타 HTTP 예외 | 본문을 받는 엔드포인트 | There was an error parsing the body | 0 |
| `INTERNAL_ERROR` | 500 | 처리하지 못한 예외. 응답은 고정 메시지만, 스택은 요청 ID와 함께 서버 로그 | 모든 엔드포인트 | 서버 오류가 발생했습니다 | 0 |
| `DB_UNAVAILABLE` | 503 | `SELECT 1` 실패(연결 거부·시간 초과 등). 접속 정보는 응답에 넣지 않고 로그에만 | `GET /health/db` | DB에 연결할 수 없습니다 | 0 |
| `STOCK_NOT_FOUND` | 404 | (시장, 티커) 종목 없음 | `/stocks/{market}/{ticker}`·하위 | 종목 KOSPI/999999을(를) 찾을 수 없습니다 | 1-B |
| `VOLUME_SORT_REQUIRES_MARKET` | 422 | 전체 탭(country 없음)에서 거래량 정렬 — 시장마다 거래량 단위가 다름 | `GET /stocks` | 시장마다 거래량 단위가 달라 '전체'에서는 거래량 정렬을 할 수 없습니다 | 1-B |
