# 구축 및 운영 가이드

새 운영자가 프로젝트를 넘겨받았다고 가정하고 아래 세 가지를 설명한다.
- 처음 서비스를 실행하는 방법
- 정상 동작을 확인하는 방법
- 문제가 생겼을 때 가장 먼저 확인할 것

출력 예시는 2026-10-22에 실제로 실행한 결과다. 구성은 `architecture.md`(배포 구성은 1-1절), 대표 장애는 `troubleshooting.md`에 있다.

| 환경 | 주소 | 구성 |
|---|---|---|
| 로컬 | http://localhost:8000 (`.env`의 `API_PORT`) | Docker Compose — `db`(PostgreSQL 16) + `api`(FastAPI + 앱 안 스케줄러) |
| 배포 | https://stockmind-538269380647.asia-northeast3.run.app | Google Cloud 프로젝트 `stockmind-512107`, 리전 `asia-northeast3` — Cloud Run 서비스 `stockmind` + Cloud Run Jobs 3개 + Cloud Scheduler + Supabase PostgreSQL + Secret Manager |

## ① 실행 전 준비

| 준비물 | 확인 방법 | 비고 |
|---|---|---|
| Docker Desktop(Compose v2) | `docker compose version` | DB·API를 모두 컨테이너로 실행한다. 호스트에 Python·PostgreSQL을 설치할 필요가 없다 |
| Git | `git --version` | |
| 환경 변수 파일 | `cp .env.example .env` | `COMPOSE_FILE=compose.yml:compose.dev.yml` 두 줄이 있어야 지금 소스로 실행된다 |
| (실데이터 수집 시) 키 | `.env`의 `DART_API_KEY`, `SEC_USER_AGENT`(이메일 포함), `KRX_ID`·`KRX_PW`(pykrx) 또는 `KIS_API_KEY`·`KIS_API_SECRET`(`PRICE_SOURCE_KR=kis`) | 키가 없어도 샘플 데이터로 화면·API를 볼 수 있다 |
| (배포 시) gcloud CLI | `gcloud auth list` — 프로젝트 `stockmind-512107` 권한 | 비밀 값은 Secret Manager에 있다(`DATABASE_URL`·`SESSION_SECRET`·`DART_API_KEY`·`KRX_ID`·`KRX_PW`·`KIS_API_KEY`·`KIS_API_SECRET`) |

- LLM API 키는 필요 없다. 1차 프로젝트는 LLM을 쓰지 않는다.
- 포트가 겹치면 `.env`에서 `DB_PORT`(기본 5433)·`API_PORT`(기본 8000)를 바꾼다.

## ② 서비스 실행 (로컬)

```bash
cp .env.example .env                                         # 1) 환경 변수
docker compose up -d --build                                 # 2) DB + API (개발 모드: 소스 수정 시 자동 재시작)
docker compose run --rm api python -m app.ingest init-db     # 3) 스키마(테이블 26·VIEW 4·인덱스) + 투자 성향 프리셋
docker compose run --rm api python -m app.ingest master --offline   #    시장·종목·지수 마스터 + demo 사용자
docker compose run --rm api python -m app.ingest import-sample      #    샘플 시세·지수·환율·밸류에이션
docker compose run --rm api python -m app.ingest seed-demo          # 4) (선택) 데모 관심종목 8건 + 포트폴리오 2개
```

실데이터로 채우려면 키를 넣은 뒤 `python -m app.ingest all`을 실행한다(빈 DB 기준 수 분). 비교군은 `benchmark`, 상장 목록은 `listing`으로 받는다. 명령 전체는 `python -m app.ingest --help`로 볼 수 있다.

## ③ 실행 상태 확인

```bash
docker compose ps
curl -i http://localhost:8000/health
curl http://localhost:8000/health/db
```

정상이면 이렇게 나온다:
```text
stockmind_api   Up … (healthy)          ← 컨테이너 HEALTHCHECK(/health/db)가 통과했다는 뜻
stockmind_db    Up … (healthy)

HTTP/1.1 200 OK
x-request-id: bbe065fbeff8              ← 모든 응답에 붙는 요청 ID. 서버 로그에서 같은 ID로 찾는다
{"status":"ok"}                         ← /health: 프로세스가 살아 있음 (DB에 접근하지 않음)

{"status":"ok","db":"ok"}               ← /health/db: DB에 SELECT 1까지 성공
```

| 결과 | 뜻 | 먼저 볼 것 |
|---|---|---|
| `/health` 연결 거부 | API 프로세스가 안 떠 있음 | `docker compose ps`, `docker compose logs api` |
| `/health` 200인데 `/health/db`가 503 `DB_UNAVAILABLE` | API는 살아 있고 DB 연결만 실패(연결 제한 10초) | `docker compose ps db`, `.env`의 `DATABASE_URL` |

배포도 같은 주소로 확인한다(2026-10-22 실제 응답):
```bash
curl https://stockmind-538269380647.asia-northeast3.run.app/health      # {"status":"ok"}
curl https://stockmind-538269380647.asia-northeast3.run.app/health/db   # {"status":"ok","db":"ok"}
```

## ④ 서비스 정상 동작 확인

**API가 실제 데이터를 돌려주는지**:
```bash
curl -s "http://localhost:8000/api/v1/stocks/KOSPI/005930" | python -m json.tool | head
curl -s "http://localhost:8000/api/v1/stocks/KOSPI/999999"      # 없는 종목
```
```text
"ticker": "005930", "name": "삼성전자", "as_of": "2026-10-22", "close": …   ← 종목 정보와 최신 종가
{"error":{"code":"STOCK_NOT_FOUND","message":…,"detail":null}}              ← 없는 종목은 404와 오류 형식
```
- 응답 칸 이름과 예시는 `06_기능_API_정의서.md` 3절과 같아야 한다.
- 브라우저 `http://localhost:8000/docs`(Swagger)에서 버튼으로 직접 호출해 볼 수 있다.

**대시보드에 실제 데이터가 보이는지**(브라우저):

| 주소 | 보이면 정상 |
|---|---|
| `/` | 지수·USD/KRW 카드에 숫자와 스파크라인, 관심종목, 섹터 히트맵, 시장 심리 지수 |
| `/stocks` | 종목 25개씩 순위, 탭·정렬·섹터 필터가 동작 |
| `/stocks/KOSPI/005930` | 가격 차트, 투자 매력도 게이지 |
| `/portfolio` | 포트폴리오 요약과 비중 차트 |

개발자 도구(F12) → Console 탭에 빨간 오류가 없어야 한다.

**자동 확인(테스트)**:
```bash
docker compose run --rm api pytest -q        # 2026-10-26: 550 passed in 63s
```

## ⑤ 로그 확인

| 무엇 | 로컬 | 배포 |
|---|---|---|
| 백엔드(API) 로그 | `docker compose logs -f api` | `gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="stockmind"' --project stockmind-512107 --freshness 1h --limit 50` (또는 콘솔 Cloud Run → stockmind → 로그) |
| 수집 작업 로그 | 위와 같음(앱 안 스케줄러) | `gcloud run jobs executions list --job stockmind-refresh --region asia-northeast3 --project stockmind-512107` → 실행별 로그는 콘솔 Cloud Run → 작업 |
| 적재 결과 기록 | DB `ingestion_logs`, `python -m app.ingest status` | 같은 명령을 Job으로, 또는 `GET /api/v1/statistics/data-quality` |
| 이상 행(격리) | `backend/data/quarantine/*.csv` | 컨테이너 안 `/srv/data/quarantine` |
| 프론트엔드 로그 | 브라우저 F12 → Console(오류), Network(어떤 API를 불렀고 몇 번 상태인지) | 같음 |

- 로그의 한 줄은 `시각 수준 [요청ID] 모듈: 내용` 형식이다(`backend/app/core/logging.py`). 요청과 관계없는 로그(수집 작업 등)는 요청 ID 자리가 `[-]`다.
- 500 오류는 응답의 `X-Request-ID` 헤더 값으로 로그에서 스택을 찾는다(응답 본문에는 내부 정보를 넣지 않는다).

## ⑥ 데이터 갱신 확인

```bash
docker compose run --rm api python -m app.ingest refresh   # 화면 '새로고침'(POST /market/refresh)과 같은 작업
docker compose run --rm api python -m app.ingest status    # 테이블별 행 수·기간·최근 실패·데이터 품질
```
`status` 출력(2026-10-22 개발 DB, 핵심만):
```text
daily_prices                             45126  (2024-10-14 ~ 2026-10-22)   ← 일봉 행 수와 기간. 끝 날짜가 마지막 거래일이면 최신
index_daily_prices                       4538  (2024-10-14 ~ 2026-10-22)
fx_rates SNAPSHOT                        10
financial_statements FY                  20896
최근 실패:
   FINANCIALS TRNZ 2026-10-20 09:05:50 ProviderError: 재무 빈 응답            ← 종목 단위 실패(나머지 적재는 계속됨)
데이터 품질 (최근 7일): 성공 1210 / 실패 74 / 부분 실패 1 / 건너뜀 64 / 격리 311행
   오래된 갱신 작업 없음 (기준 TTL×2 = 8시간, 주가·지수·환율 2시간)        ← 이 줄이 나오면 갱신이 제때 돌고 있음
```

- **TTL 안**에서 다시 갱신하면 외부 호출 없이 `SKIPPED`가 된다. 이것이 정상이다(주가·지수·환율 1시간, 그 밖 4시간). 장 마감 전에는 일봉·지수를 전날까지만 요청한다.
- 갱신 상태는 `GET /api/v1/market/refresh/status`의 작업별 `FRESH`/`STALE`과 `last_success_at`으로 본다. 화면 사이드바의 '마지막 갱신' 시각도 이 값이다.
- 갱신 뒤 대시보드를 새로 고치면 지수 카드 기준일·종가가 바뀐다.
- **배포의 갱신 주기**(Cloud Scheduler, 서울 시간):

| 작업 | 실행 시각 | 명령 |
|---|---|---|
| `stockmind-refresh` | 매시 5분 | `python -m app.ingest refresh` |
| `stockmind-benchmark` | 매일 07:00 | `python -m app.ingest benchmark` |
| `stockmind-background` | 매일 08:00 | `python -m app.ingest background` |

  배포 서비스는 `SCHEDULER_ENABLED=false`라 앱 안 스케줄러가 돌지 않고, 이 Job들이 갱신한다. 실행 기록 예: `stockmind-refresh-nkvg7 2026-10-22T07:06:02Z 성공 1`.

## ⑦ 재배포 또는 업데이트

**로컬**: 코드를 받으면 `docker compose up -d --build`.
- 스키마가 바뀐 경우(`backend/db/migrations/` 새 파일)는 `python -m app.ingest migrate <이름>`을 실행한다(05 8절).
- 데이터를 처음부터 다시 만들 때는 `init-db --reset` → `master --offline` → `import-sample` → `seed-demo` 순서다. `--reset`은 DB를 통째로 비운다.

**배포**: 서비스와 Jobs는 같은 이미지(`asia-northeast3-docker.pkg.dev/stockmind-512107/stockmind/api:<커밋>-<MMDDHHMM>`)를 쓴다.
- 지금 배포된 이미지: 서비스·Jobs 3개 모두 `api:33419c8-10271544`(2026-10-27, 매력도 모델 v2.2 — 수정 2 PR #117~#119).
- Cloud Build는 쓰지 않는다. 로컬에서 빌드해 올린다.

```bash
TAG=$(git rev-parse --short HEAD)-$(date +%m%d%H%M)
IMG=asia-northeast3-docker.pkg.dev/stockmind-512107/stockmind/api:$TAG
docker build -f backend/Dockerfile -t $IMG .                 # 1) 이미지 빌드(빌드 컨텍스트 = 저장소 루트)
docker push $IMG                                             # 2) Artifact Registry에 올리기
gcloud run deploy stockmind --image $IMG --region asia-northeast3 --project stockmind-512107   # 3) 서비스 새 리비전
for j in refresh benchmark background; do                    # 4) Jobs도 같은 이미지로
  gcloud run jobs update stockmind-$j --image $IMG --region asia-northeast3 --project stockmind-512107
done
# 5) 스키마가 바뀌었으면 배포 DB에 migrate 실행(같은 이미지로 일회성 Job 또는 로컬에서 DATABASE_URL을 배포 DB로)
```

**2차 적용 기록 (2026-10-26)** — 로그인(#107)·테마 분류(#109)를 처음 배포할 때 한 일. 같은 상황(010 이하 DB)이면 이 순서를 따른다.
1. 배포 DB에 `migrate 012_themes` → `migrate 011_auth` (**012가 먼저** — 05 8절, troubleshooting 3)
2. 업종 코드 복사: 로컬 DB의 `stocks.ksic·sic·industry·industry_checked_at`(4,089행)을 CSV로 내보내 배포 DB에 시장+티커로 UPDATE → `benchmark --reselect`의 DART KSIC 수집(약 1시간)을 건너뜀
3. `master --offline`(테마 38개·주 테마)
4. 이미지 push → 로그인 비밀값 3개에 런타임 서비스 계정 `secretAccessor` 부여 → `gcloud run deploy stockmind --image … --update-secrets JWT_SECRET=JWT_SECRET:latest,REDIS_URL=REDIS_URL:latest,GOOGLE_CLIENT_ID=GOOGLE_CLIENT_ID:latest` → Jobs 3개 `--image`
5. `benchmark --reselect`(배포 DB 대상) — 비교군 636종목·점수. 미국 ADR 20종목은 재무 빈 응답으로 점수 없음(정상 — 09 8절)
6. 원자재 지수 5종은 다음 `stockmind-refresh`(매시 5분)가 2년치를 받는다

**3차 적용 기록 (2026-10-27)** — 매력도 모델 v2(09 정의서, 검토 장부 D-002~D-017). 배포 DB 작업은 로컬 접속 없이 Job을 일회성 인자로 실행했다:
`gcloud run jobs execute stockmind-benchmark --args="python,-m,app.ingest,<명령>,…" --region asia-northeast3 --project stockmind-512107 --wait`
1. 이미지 push → `gcloud run deploy stockmind` → Jobs 3개 `--image` (명령은 하나씩 — 한 줄로 묶으면 Claude Code 자동 모드 권한 검사에 막힐 수 있다)
2. `migrate 013_scores_v2`(stock_scores as_of 인덱스)
3. `financials --years 3 --tickers 000120 086280 010060 121600 316140 001720 XOM CLX EMN EXP GTX OSK AEIS`(DART FY2024 누락·SEC 태그 보완·XOM 이전 CIK)
4. `master --offline` — **테마 설정(scoring none·새 테마)은 이 명령의 sync_themes로만 peer_groups에 들어간다.** `benchmark`만 돌리면 지주회사가 계속 general로 남는다
5. `benchmark --reselect` — 지주회사·상품 신탁이 표본에서 빠지고 v2 점수 계산
6. 확인: SK스퀘어·GLD는 점수 없이 테마 사유, HLN은 `score_null_code = no_financials`, MU 가치 17/277·결산 시점 배지, 다우기술 금융 2/30

**4차 적용 기록 (2026-10-27)** — 매력도 모델 v2.2(수정 2: D-018 V1·D-020 테마 위치·D-019 RN). 스키마 변경 없음(migrate 불필요).
1. 이미지 push → `gcloud run deploy stockmind`(리비전 stockmind-00016-9sp) → Jobs 3개 `--image`
2. `gcloud run jobs execute stockmind-benchmark --args="python,-m,app.ingest,scores" … --wait` — 배포 DB 점수 v2.2 재계산
3. 확인(API): 모델 `v2.2-2026-10-27`, MU 가치 12/277(개발 DB와 같음), 한일홀딩스 가치 42/300, 가치 함정 신호 z_adj ≤ 0, NVDA 테마 위치에 주가 흐름(반도체 3/32)
4. sanity 목록(`개발산출물/`)은 이미지에 없어(.dockerignore) 배포 DB 전체 sanity는 돌리지 않았다 — 5차부터 이미지에 넣는다
- Claude Code 자동 모드: 허용 규칙이 Bash(`*gcloud* run deploy stockmind *` 등)이면 Bash 도구로, **파이프 없이** 한 명령씩 실행해야 규칙에 맞는다(`| tail`이 붙으면 명령이 둘로 나뉘어 막힘, PowerShell 도구 호출은 Bash 규칙에 안 맞음).

**5차 적용 절차 (수정 3 — 매력도 v2.3~v2.5, 검토 장부 D-024~D-030)** — PR #122~#125를 차례로 머지한 main으로 한 번에 배포한다. 스키마 변경 2개(014·015).
1. 이미지 push → `gcloud run deploy stockmind --image $IMG …` → Jobs 3개 `--image`(명령은 하나씩)
2. `gcloud run jobs execute stockmind-benchmark --args="python,-m,app.ingest,migrate,014_fin_currency" … --wait`, 같은 방식으로 `migrate,015_sanity_runs`
3. `master,--offline` — 주 테마 직접 지정(D-024)·지주회사 테마 3종목(D-025)이 peer_groups·주 테마에 들어간다
4. `financials,--years,3,--tickers,241560` — 두산밥캣 USD 재무를 원화로 다시 받기(D-026)
5. `scores` — 모델 v2.5 재계산
6. **sanity Job 만들기**(한 번): 같은 이미지로
   `gcloud run jobs create stockmind-sanity --image $IMG --region asia-northeast3 --project stockmind-512107 --args="python,-m,app.ingest,sanity,--save,--env,deploy" --set-secrets DATABASE_URL=DATABASE_URL:latest --max-retries 0`
   — required 실패가 있으면 종료 코드 1이라 실행이 '실패'로 남는다(재시도하지 않음). 결과 표는 배포 DB `sanity_runs`, 전체 보고는 Job 로그.
7. `gcloud run jobs execute stockmind-sanity --region asia-northeast3 --project stockmind-512107 --wait` → 배포 DB에서 `DEPLOY-sanity-ran`이 통과로 남는다. 매일 07:00 `stockmind-benchmark`(점수 재계산) 뒤에 돌도록 Cloud Scheduler `stockmind-sanity`를 07:40으로 만든다(`gcloud scheduler jobs create http …` — 기존 Job 스케줄러와 같은 방식).
8. 확인: `/api/v1/stocks/KOSPI/001450/analysis`의 `attractiveness.financial_profile`(금융 업종 비교), 홈 금융 탭, 모델 `v2.5-2026-10-27`, `SELECT environment, as_of, passed, known_fail, target_fail, unverified, required_fail FROM sanity_runs ORDER BY run_id DESC LIMIT 1`.
- 다음 `benchmark --reselect`(30일 주기) 때 지주회사 테마로 옮긴 3종목(한국앤컴퍼니·한화·다우기술)이 비교 표본에서 빠진다.

**6차 적용 절차 (수정 4 — 매력도 v2.6~v2.7, 검토_장부 D-039~D-042)** — PR A(수집)·B(표본·시총·분류)·C(계산 규칙)를 머지한 main으로 한 번에 배포한다. 스키마 변경 2개(016·017). 이 배포 뒤의 07:00 계산 직후 덤프가 기준 스냅샷 S1이다(D-041).
1. 이미지 push → `gcloud run deploy stockmind --image $IMG …` → Jobs 4개(refresh·benchmark·background·sanity) `--image`(명령은 하나씩)
2. `migrate,016_fin_collection` → `migrate,017_us_cap`
3. `master,--offline` — 결제·핀테크 테마·HON·비에이치아이·NEU 직접 지정이 peer_groups·주 테마에 들어간다
4. **재무 한 경로 재수집**(D-039): `financials,--scope,sample,--country,US`(SEC — 약 10분) → `financials,--scope,sample,--country,KR,--part,1/2`와 `--part,2/2`를 **차례로**(DART — 한 회사 보고서 약 20~25개, 분당 45회라 각각 약 1.5시간. 한 Job 실행 시간 상한 안에 들어가게 나눈다). 다시 받은 종목의 옛 결산기 행(수정 1 이전 미국 영업이익, 20-F 재무)은 이때 지워진다
5. 미국 시가총액 순위(yfinance 시총·ADR 비율): `python,-c,from app.core.db import get_engine; from app.ingest.background import rank_us; from app.providers.factory import default_providers; print(rank_us(get_engine(), default_providers(), force=True))` (개발 DB 실측 34분 — yfinance가 401이면 60초 쉬고 남은 종목을 한 번 더 부른다. 로그 '시가총액 끝내 실패'가 있으면 다시 실행)
6. `benchmark,--reselect` — V·MA 등 결제사가 표본에 들어오고 거래정지 종목이 빠진다. 새로 뽑힌 종목은 재무를 API로 받는다(일괄 경로 값은 만료)
7. `scores` → `stockmind-sanity` 실행 → 결과 `sanity_runs`. 매시 `stockmind-refresh`는 이제 점수를 다시 계산하지 않는다(SCORES SKIPPED)
8. 다음 날 07:00 `stockmind-benchmark` 완료 ~ 07:40 `stockmind-sanity` 사이에 배포 DB 덤프 → **S1**(이름을 장부 '기준 스냅샷' 행에). 2주 이상 뒤 같은 시각 덤프 → S2
- DART 하루 한도(키 1개 약 2만 회): 4번 재수집이 약 7,000~8,000회를 쓰므로 같은 날 `background`(listed 재무) 예산을 0으로 두거나 다음 날로 미룬다.

> 이 절차는 2026-10-22 배포 상태(이미지 태그 형식, Cloud Build 미사용, 서비스·Job이 같은 이미지)를 조회해 맞춘 것이다. 레포에는 배포 스크립트가 없으므로, 실제로 쓰던 명령과 다르면 이 절을 고친다.

**배포 뒤 확인**(v1 → v2):
1. `/health`·`/health/db`가 200이다.
2. `gcloud run revisions list --service stockmind --region asia-northeast3 --project stockmind-512107`에서 새 리비전이 100% 트래픽을 받는다.
3. `/api/v1/stocks/KOSPI/005930`이 데이터를 돌려준다.
4. 대시보드 홈에 지수·관심종목이 보인다.
5. 다음 정각 5분 뒤 `stockmind-refresh` 실행이 성공한다.
6. (2차) `/login` 화면이 열리고 `POST /api/v1/auth/refresh`(쿠키 없이)가 401 `REFRESH_INVALID`를 준다. `/api/v1/peer-groups`가 테마 38개를 준다.

- 설정만 바꿀 때는 이미지를 다시 만들 필요가 없다. 예: KRX 장애 시 국내 소스를 KIS로 바꾸기(재배포 1~2분, 되돌릴 때는 `=pykrx`):
  ```bash
  gcloud run services update stockmind --region asia-northeast3 --project stockmind-512107 --update-env-vars PRICE_SOURCE_KR=kis
  ```
  Jobs도 같은 값을 쓰게 `gcloud run jobs update stockmind-<작업> --update-env-vars PRICE_SOURCE_KR=kis …`로 맞춘다.

## ⑧ 장애 발생 시 기본 점검 순서

| 순서 | 점검 | 명령·위치 | 정상 / 비정상일 때 |
|---|---|---|---|
| 1 | 백엔드 서버 상태 | `curl …/health`, `docker compose ps` / Cloud Run 리비전 상태 | 200이 아니면 서버 로그(5)부터 |
| 2 | DB 연결 | `curl …/health/db` | 503 `DB_UNAVAILABLE`이면 DB 컨테이너·`DATABASE_URL`·Supabase 연결 수(풀 5+3, Job 2+1 — 한도 15) |
| 3 | 외부 데이터 소스 응답 (이 프로젝트는 LLM 대신 수집 소스) | `GET /api/v1/statistics/data-quality`의 작업별 `last_failure_reason`, `python -m app.ingest status`의 '최근 실패' | KRX 로그인 오류(`JSONDecodeError`·`KRX 로그인 진단` 로그)면 troubleshooting 2의 KIS 전환. 환율 실패는 마지막 값 + `fx_stale: true`로 화면은 유지 |
| 4 | Application Log | ⑤의 로그 명령, 응답의 `X-Request-ID`로 검색 | 500은 스택이 로그에 있음 |
| 5 | 프론트엔드 콘솔 | 브라우저 F12 Console·Network | 빨간 오류, 4xx·5xx 응답 확인. 배포에서 쓰기 직후 `PORTFOLIO_NOT_FOUND`는 게스트 전환(08 14절 25번) |
| 6 | 환경 변수·키 | 로컬 `.env`, 배포 `gcloud run services describe stockmind --region asia-northeast3 --project stockmind-512107` | `GUEST_SESSION_ENABLED=true`면 `SESSION_SECRET` 필수, `SEC_USER_AGENT`에 이메일, 소스별 키 |
| 7 | 데이터 적재 상태 | `python -m app.ingest status`, `GET /api/v1/market/refresh/status`, Job 실행 기록 | '오래된 갱신 작업'이 있거나 Job 실패가 이어지면 해당 Job 로그 확인 후 수동 실행 `gcloud run jobs execute stockmind-refresh --region asia-northeast3 --project stockmind-512107` |

- 조회 API는 외부 소스를 직접 부르지 않는다. 그래서 수집이 멈춰도 화면은 마지막으로 저장된 값을 보여 준다(5xx 없음).
- 그래서 **화면만 보면 장애가 드러나지 않을 수 있다.** 3·7번(데이터 품질·갱신 상태)을 주기적으로 본다.
