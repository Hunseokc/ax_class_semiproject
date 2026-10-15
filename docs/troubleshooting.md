# 트러블슈팅 보고서

`docs/08` 14절의 문제 중 영향이 컸던 건을 같은 양식으로 정리한다(단계마다 추가). 발생 일시·담당자는 git 기록(`git log`)에서 확인할 수 있는 범위만 적고, 기록이 없는 항목은 "확인 필요"로 둔다.

| # | 문제 | 08 14절 | 분류 |
|---|---|---|---|
| 1 | pykrx가 시총·펀더멘털·지수를 빈 결과로 돌려줌 | 1번 | 외부 데이터 소스 |

---

## 1. pykrx 시총·펀더멘털·지수 빈 결과

### 발생 일시·담당자·영향 범위
- **발생 일시**: 확인 필요 — 1단계 smoke test 중 발견. 해결이 담긴 첫 커밋은 `a57b684`(2026-10-06 23:06, 초기 구현), 재실행 결과 기록은 `bedec97`(2026-10-07 10:36, `docs/smoke_test_result.md`)
- **담당자**: Hunseokc (커밋 작성자)
- **영향 범위**: 국내 밸류에이션(시총·PER·PBR·EPS·BPS) 전 종목, 국내 지수(KOSPI·KOSDAQ). 일봉·종목명은 정상이라 "부분적으로만 실패"해 발견이 늦어질 수 있는 유형

### 문제 상황
- **기능**: 국내 밸류에이션 적재(`valuation`), 지수 적재(`indices`)
- **영향**: 시총·PER/PBR이 비어 매력도의 가치 팩터와 원화 환산 시총 순위를 계산할 수 없음
- **오류 메시지**: 시총·펀더멘털은 예외 없이 빈 DataFrame, 지수는 `KeyError: '지수명'` (ASSUMPTIONS A-01)

### 원인 분석
- **직접 원인**: pykrx 1.2.x는 KRX 정보데이터시스템의 시총·펀더멘털·지수 화면에 **회원 로그인**이 필요하다. 로그인하지 않으면 해당 엔드포인트가 빈 응답을 준다.
- **근본 원인**: pykrx는 **import 시점**에 `os.environ`의 `KRX_ID`/`KRX_PW`를 읽는다. `.env`에 값을 넣어도 pydantic-settings가 읽을 뿐 환경변수로 내보내지 않으면 pykrx는 로그인하지 못한다(A-04). 또한 비공식 라이브러리라 사이트 정책 변화가 그대로 영향을 준다.
- **확인 방법**: `python -m app.ingest.smoke`로 로그인 없음/있음 두 경우의 실제 응답을 비교(`docs/smoke_test_result.md`), pykrx 소스 `website/comm/auth.py`에서 환경변수 읽는 시점 확인

### 해결 과정
1. smoke test로 로그인 여부에 따른 응답 차이를 실측해 원인을 로그인으로 좁힘
2. `export_krx_credentials()`(`backend/app/core/config.py`)로 `.env` 값을 **pykrx import 전에** 환경변수로 내보내도록 함
3. 로그인 세션 만료(1시간)는 pykrx가 자동 재로그인함을 소스로 확인(A-05)
4. 장애 대비: `PRICE_SOURCE_KR=yfinance`로 국내 소스를 바꿀 수 있게 하고(A-03), pykrx 실패 시 DART FY 기반 파생 밸류에이션(`DERIVED`)으로 대체(A-02)

### 해결 결과
- **정상화**: 로그인 후 일봉·시총·펀더멘털·지수가 모두 동작(2026-10-08 깨끗한 DB 재현에서 적재 실패 0건)
- **재발 확인 방법**: `python -m app.ingest.smoke` 재실행, `GET /api/v1/statistics/data-quality`에서 VALUATION·INDICES의 `last_failure_reason`, `python -m app.ingest status`의 최근 실패

### 재발 방지
- **코드**: `export_krx_credentials()` 호출을 pykrx import 경로 앞에 고정, 소스 전환(`PRICE_SOURCE_KR`)·DERIVED 폴백 유지
- **점검 항목**: README 환경변수 표에 `KRX_ID`·`KRX_PW`를 pykrx 사용 시 **필수**로 표시, 장애 시 점검 순서에 "KRX 로그인" 포함(README 운영 가이드)
- **문서**: ASSUMPTIONS A-01~A-05, `docs/03` 1절, `docs/smoke_test_result.md`
