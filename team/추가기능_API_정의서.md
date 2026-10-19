# 추가 기능 API·계약 정의서

`기능구현_계획.md`(결정 D1~D10, 2026-10-16)를 코드 수준으로 옮긴 문서예요. 기준은 **지금 ax_stockmind 코드**(stage6, 2026-10-19)예요. 구현할 때 이 문서의 이름·시그니처·SQL·응답 모양을 따르고, 구현하다 더 나은 방법이 보이면 이 문서를 먼저 고친 뒤 코드를 바꿔요.

팀 분담·단계별 계약(`stage*.toml`)·껍데기는 쓰지 않아요. D가 Claude와 함께 기능마다 브랜치 하나로 구현해요.

---

## 0. 읽는 법

### 0-1. 계획 단계 ↔ 이 문서

| 계획 단계 | 브랜치(권장) | 이 문서 절 | 상태 |
| --- | --- | --- | --- |
| 0 선행 수정 | `fix/score-universe-sentiment` | 2절 | 확정 |
| 1 안정성 팩터 개편 | `feat/safety-mdd` | 3절 | 확정 |
| 2 실적 시즌 부하 분산 | `feat/ingest-batch-lock` | 4절 | 확정 (D4 값은 임시 100) |
| 3 시장·섹터 점수 | `feat/market-condition` | 5절 | 확정 |
| 4-1 한국 재무 일괄·증분 | `feat/dart-feed` | 6절 | 확정, 일괄 파일 열 이름은 확인 뒤 채움 (6-6) |
| 4-3 우선순위 큐·하루 예산 | `feat/background-ingest` | 7절 | 확정, 미국 순위 소스는 D11 |
| 4-2 미국 재무 일괄 | — | 8절 | D8 결정 뒤 착수 — 인터페이스만 |
| 4-4 노출 종목 확장 | — | 9절 | D5 결정 뒤 착수 — API 필터만 |

각 브랜치는 `main`에서 만들고 PR로 합쳐요. 2단계가 4단계보다 먼저예요.

### 0-2. 표기 규칙

| 표기 | 뜻 |
| --- | --- |
| `Num` | `app/schemas/common.py`의 `Num`(Decimal을 JSON 숫자로). 계산은 `Decimal`, 응답은 숫자 |
| 비율 | 소수(0.0523 = 5.23%). 화면에서 `pct()`로 % 표시 |
| `HALF_UP` | `Decimal.quantize(..., rounding=ROUND_HALF_UP)`. 파이썬 `round()`(짝수 반올림)는 쓰지 않아요 |
| 날짜 | `date`는 `"YYYY-MM-DD"`, 시각은 ISO 8601 |

### 0-3. 공통 규칙 (기존 규칙 그대로)

- 에러 응답은 `{"error": {"code", "message", "detail"}}`. **이 문서의 기능은 새 에러 코드를 만들지 않아요.** 계산할 수 없으면 값 `null` + 라벨 `"데이터 부족"`.
- 조회 API(`GET`)는 외부 소스를 부르지 않아요(DB만). 외부 호출은 `app/ingest/*`·갱신 서비스만.
- 조회 경로에서 DB에 쓰지 않아요. 예외: 기존 `/home/sentiment`의 `ensure_sentiment`(그대로 둠).
- 새 테이블·열은 마이그레이션(`backend/db/migrations/NNN_*.sql`, 멱등) + `schema.sql` + `tests/conftest.py`의 `TABLES`를 같이 바꿔요.
- 테스트는 `docker compose run --rm api pytest -q`가 전부 통과해야 PR을 합쳐요.

---

## 1. 엔드포인트 변경 요약 (docs/06에 반영할 목록)

새 엔드포인트는 없어요. 바뀌는 응답은 아래 셋이에요. 기존 필드는 이름·타입·의미가 그대로예요(1단계 지표 이름 하나만 예외).

| Method | URL | 바뀌는 것 | 단계 |
| --- | --- | --- | --- |
| GET | `/stocks/{market}/{ticker}/analysis` | `attractiveness.metrics[]`의 `debt_ratio` 항목 → `max_drawdown`(같은 자리, 7번째). `attractiveness.fin_basis` 추가 | 1, 2 |
| GET | `/stocks/{market}/{ticker}` | `market_condition` 객체 추가(항상 있음) | 3 |
| GET | `/stocks` | `sector` 쿼리 파라미터, `StockRow.sector` | 4-4 |

`analysis.metrics`(수치 분석 딕셔너리)의 `debt_ratio`·`max_drawdown_1y`는 **그대로** 있어요. 바뀌는 건 매력도 계산 지표 목록(`attractiveness.metrics`)뿐이에요.

---

## 2. 0단계 — 선행 수정

### 2-1. 매력도 계산 대상 (`backend/app/queries/score_metrics.sql`)

지금 SQL은 파라미터를 받지 않아서, `reference_score.py`가 `{"stock_id": id}`를 넘겨도 활성 종목 전체 행이 돌아와요. 유니버스 계산에도 listed 종목이 들어가요.

머리 주석 2행을 아래 2줄로 바꿔요.

```sql
-- 대상: 파라미터 stock_id가 NULL이면 매력도 유니버스(활성 노출 종목 + 비교군, listed 제외)
--       stock_id를 주면 그 종목만(상장 종목 목록의 참고 점수 계산용 — app/services/reference_score.py)
```

`base`의 `stocks` 조인:

```sql
    JOIN stocks st ON st.stock_id = vm.stock_id
     AND CASE WHEN CAST(:stock_id AS int) IS NULL THEN st.is_active AND st.coverage <> 'listed'
              ELSE st.stock_id = :stock_id END
```

`px` CTE에 필터(종목 하나만 계산할 때 전체 일봉 번호 매기기를 피함):

```sql
px AS (                               -- 최신 거래일부터 거꾸로 번호(rn = 1이 t)
    SELECT d.stock_id, d.close, ROW_NUMBER() OVER (PARTITION BY d.stock_id ORDER BY d.trade_date DESC) AS rn
    FROM daily_prices d
    WHERE CAST(:stock_id AS int) IS NULL OR d.stock_id = :stock_id
),
```

`backend/app/services/scoring.py`의 `compute_scores`:

```python
    rows = conn.execute(sql("score_metrics"), {"stock_id": None}).mappings().all()
```

`reference_score.py`는 바꾸지 않아요(이미 `stock_id`를 넘겨요).

### 2-2. 시장 심리 정기 저장 (`backend/app/services/refresh.py`)

시장 심리는 지수 일봉으로 계산해요. 지수를 받는 `INDICES` 작업 바로 뒤에 KR·US를 저장하면, 홈을 열지 않은 날에도 저장값이 최신이에요.

```python
from app.services import sentiment
...
        if job_type == "INDICES":
            result = _summarize(jobs.load_indices(self.engine, self.providers))
            for market in sentiment.INDEX_CODE:      # 시장 심리 저장(홈 방문과 무관) — 상세 시장·섹터 점수의 재료
                try:
                    sentiment.ensure_sentiment(self.engine, market, self.clock())
                except Exception:  # noqa: BLE001 — 심리 계산 실패가 지수 작업 상태를 바꾸지 않는다
                    log.exception("시장 심리 저장 실패(%s)", market)
            return (*result, None)
```

### 2-3. 테스트

| 파일 | 테스트 이름 | 확인하는 것 |
| --- | --- | --- |
| `test_scoring.py` | `test_listed_stocks_are_excluded_from_universe` | listed 종목 1개 추가 → `compute_scores` 뒤 `stock_scores`·`stock_metric_values`에 그 종목 행 없음 |
| `test_scoring.py` | `test_score_metrics_with_stock_id_returns_only_that_stock` | `sql("score_metrics")`에 `stock_id=1` → 모든 행의 `stock_id == 1`, 9행 |
| `test_refresh.py` | `test_refresh_stores_market_sentiment` | 지수 일봉이 충분한 픽스처(시장 심리 테스트와 같은 방식)로 갱신 → `market_sentiment_daily`에 KR 행 |

### 2-4. 완료 기준

1. `pytest -q` 전부 통과
2. 개발 DB `python -m app.ingest scores` 뒤 `SELECT COUNT(*) FROM stock_scores sc JOIN stocks s USING (stock_id) WHERE s.coverage = 'listed'` = 0
3. docs/09 1절 "대상" 문장을 listed 제외로 맞춤

---

## 3. 1단계 — 매력도 안정성 팩터 개편

### 3-1. 바뀌는 것

| 항목 | 전 | 후 |
| --- | --- | --- |
| 안정성 지표 | `debt_ratio`(부채비율, 방향 −1) + `volatility` | `max_drawdown`(1년 최대 낙폭, 방향 **+1**) + `volatility` |
| 안정성 섹터 중립화 | 함 | **안 함** (`z_adj = z_raw`) |
| 다른 팩터 중립화 | 함 | 그대로 |
| `attractiveness.metrics[]` 순서 | …, eps_change_yield, **debt_ratio**, volatility, momentum | …, eps_change_yield, **max_drawdown**, volatility, momentum |

바뀌지 않는 것: DB 스키마(`stock_metric_values.metric`은 VARCHAR), 프리셋 가중치, 응답 모양, 수집 코드, `analysis.metrics.debt_ratio`, `reference_score.py`(METRICS를 따라감), '한눈에 보는 투자 지표' 카드(이미 낙폭을 보여줌).

### 3-2. 파일별 변경

#### `backend/app/services/scoring.py`

`METRICS`에서 `debt_ratio` 한 줄을 **같은 자리에서** 바꿔요. 순서가 API 응답 순서예요(`api/analysis.py`가 `METRICS.items()` 순으로 만듦).

```python
    "max_drawdown":     Metric("safety", "1년 최대 낙폭", 1, "일봉 252개 미만"),
```

- 방향 +1: 낙폭은 음수(−0.391 = −39.1%)라 0에 가까울수록 좋아요.
- 결과로 `NEGATIVE_METRICS == ["volatility"]`.
- 사유가 "252개"인 이유: `views.sql`의 `mdd`는 최근 252거래일이 다 있을 때만 값을 내요. 변동성은 253개라 사유가 달라요.

#### `backend/app/queries/score_metrics.sql`

| 위치 | 바꾸는 것 |
| --- | --- |
| z_fixed 주석 | `-- z_fixed: 정규화 없이 Z를 고정하는 경우(지금 쓰는 지표 없음 — 규칙만 남김). note: 대체 계산·고정 사유` |
| `base` SELECT | `vm.volatility_1y` 뒤에 `vm.max_drawdown_1y,` |
| `inp` SELECT | `b.volatility_1y` 뒤에 `b.max_drawdown_1y,` |
| `VALUES`의 `debt_ratio` 3줄 | 아래 1줄로 (같은 자리) |

```sql
    ('max_drawdown',     'safety',   c.max_drawdown_1y, NULL, NULL),
```

`fy`·`inp`의 `total_debt`는 그대로 둬요.

#### `backend/app/queries/score_neutralize.sql`

머리 주석 끝에 한 줄, `g`에 `mv.factor`, `SET` 조건에 `safety`:

```sql
--   안정성(safety) 지표는 중립화하지 않는다(z_adj = z) — 업종 특성으로 출렁이는 것도 그대로 반영 (docs/09 4절)
WITH g AS (
    SELECT mv.stock_id, mv.metric, mv.factor, mv.z_raw, gm.group_id, mk.country
    ...
UPDATE stock_metric_values t
SET z_adj = CASE WHEN s.factor = 'safety' OR s.group_id IS NULL OR s.n = 1 THEN s.z_raw
                 ELSE s.z_raw - CAST(s.n AS numeric) / (s.n + :k) * s.group_mean END
```

#### `backend/app/queries/score_zscore.sql`

주석 한 줄만:

```sql
--   z_raw가 이미 채워진 행(z_fixed — 지금 쓰는 지표 없음, 고정 규칙이 생기면 재사용)은 통계에서 빼고 건드리지 않는다
```

### 3-3. 응답 예시 — `GET /stocks/NASDAQ/TSLA/analysis`의 `attractiveness.metrics[6]`

```json
{
  "metric": "max_drawdown",
  "label": "1년 최대 낙폭",
  "factor": "safety",
  "direction": 1,
  "raw_value": -0.391,
  "z_raw": -0.31,
  "z_adj": -0.31
}
```

- `factor == "safety"`면 항상 `z_adj == z_raw`(listed 참고 점수는 지금처럼 `z_adj: null`).
- 일봉 252개 미만이면 값이 `null`이고 `data_quality.missing_metrics.max_drawdown == "일봉 252개 미만"`.

### 3-4. 화면 (`frontend/js/pages/stock.js`)

| 위치 | 전 | 후 |
| --- | --- | --- |
| `FACTORS` quality `desc` | `"자본과 매출로 돈을 잘 버는가 (ROE·영업이익률)"` | `"자본과 매출로 돈을 잘 버는가 (최근 연간 기준)"` |
| `FACTORS` safety `desc` | `"빚이 적고 주가 출렁임이 작은가"` | `"주가가 덜 출렁이고 덜 빠지는가"` |
| `rawFmt` | `debt_ratio`면 `배` 분기 | 분기 삭제 |

```js
const rawFmt = (m) => (m.raw_value === null ? DASH
  : pct(m.raw_value, { digits: 1, sign: SIGNED_METRICS.includes(m.metric) }));
```

### 3-5. 테스트 (`backend/tests/test_scoring.py`)

| 위치 | 바꾸는 것 |
| --- | --- |
| `reference_raw`의 `"debt_ratio": …` | `"max_drawdown": _mdd(cl[-252:]) if len(cl) >= 252 else None` |
| 파일 위쪽 헬퍼 | `_mdd(closes)`: `peak = closes[0]; worst = 0.0; for c in closes: peak = max(peak, c); worst = min(worst, c / peak - 1); return worst` |
| `reference_scores`의 자본 ≤ 0 부채비율 고정 블록 | 삭제 |
| `reference_scores`의 `z_adj` 계산 | `METRICS[metric].factor == "safety"`면 `z_adj[s][metric] = z_raw[s][metric]` |
| `test_boundary_cases` | `debt` 읽기 삭제, `assert roe[6] is None and debt[6] == -3` → `assert roe[6] is None` |

새 테스트 2개:

```python
def test_safety_factor_is_not_sector_neutralized(engine, universe):
    """안정성 지표는 z_adj = z_raw, 다른 팩터는 주 그룹(n > 1)이면 중립화가 그대로 걸린다."""

def test_max_drawdown_null_reason_is_short_history(engine, universe):
    """일봉 252개 미만(픽스처 종목 7)이면 낙폭이 없고 사유가 '일봉 252개 미만'. 일봉이 충분한 종목 1은 값이 있다."""
```

### 3-6. 완료 기준

1. `pytest -q tests/test_scoring.py` 통과
2. 개발 DB `python -m app.ingest scores` 뒤 미국·국내 몇 종목 안정성 점수를 아이디어 문서 표와 비교(0단계로 표본이 바뀌었으면 표를 새 값으로)
3. docs/09: 2절 지표 표, 4절 중립화 범위("안정성 제외"), 7절 재계산 결과 + **점수가 새로 생긴 종목 수**, 9절 화면 이름 표
4. 배포 직후 `python -m app.ingest scores` 한 번

---

## 4. 2단계 — 실적 시즌 부하 분산

### 4-1. 동작 한눈에

| 항목 | 내용 |
| --- | --- |
| 잠금 범위 | DART·SEC를 **부르는 동안만**, 회사 1개 단위. DB 쓰기는 잠금 밖 |
| 잠금 키 | 한국 `DART_LOCK_KEY`(7_301_010), 미국 `SEC_LOCK_KEY`(7_301_012, 새로) |
| 잠금 연결 | 반복문 동안 연결 1개로 잠금·해제만 반복 (`LockSession`) |
| 묶음 저장 | `flush_every`(기본 20)개마다 한 트랜잭션. 반복이 끝나거나 예외가 나도 남은 것을 저장 |
| 같은 트랜잭션 | 재무(또는 공시) upsert + `freshness.mark` (+ 공시면 `invalidate_on_annual_report`) |
| 별도 트랜잭션 | `ingestion_logs` — 적재가 롤백돼도 남음 |
| 묶음 저장 실패 | 그 묶음 전체 FAILED 로그, freshness FAILED(1일 뒤 재시도) |
| 하루 재무 예산 | 07:00 비교군 재무 대상은 유효기간이 가장 오래 지난 순 `fin_daily_budget`(100)개. 노출·관심·포트폴리오(`frequent`)는 무관 |
| DART 분당 한도 | 프로세스마다 `WindowLimiter(45, 60.0)` |
| 반환값 | `load_financials`·`load_disclosures`의 반환(`{티커: "SUCCESS"|"FAILED"}`)과 기존 인자는 그대로, `flush_every` 키워드만 추가 |

### 4-2. `backend/app/ingest/store.py`

기존 `upsert`·`advisory_lock`·`JobResult`·`job_log`·`DART_LOCK_KEY`·`BENCHMARK_LOCK_KEY`는 그대로 둬요(`advisory_lock`은 비교군 갱신·테스트가 계속 써요). 추가하는 것:

```python
SEC_LOCK_KEY = 7_301_012          # SEC 호출(미국 재무·기초값·공시) — 회사 1개 단위
LOCK_WAIT_NOTE_SECONDS = 1.0      # 잠금을 이보다 오래 기다렸으면 로그 비고에 남긴다


def provider_lock_key(country: str) -> int:
    """KR → DART_LOCK_KEY, US → SEC_LOCK_KEY. 그 밖의 값은 ValueError."""


def error_text(e: BaseException) -> str:
    """로그·freshness에 남길 실패 사유: f"{type(e).__name__}: {메시지 앞 3줄을 공백으로 이은 것}"[:500].
    SQLAlchemy 오류는 e.orig(DB 메시지)를 쓴다. job_log의 같은 계산도 이 함수로 바꾼다(결과 문자열은 지금과 같다)."""


def default_flush_every() -> int:
    """config/universe.yaml ingest.flush_every (없으면 20)."""


class LockSession:
    """연결 1개를 잡아 두고 advisory lock 잠금·해제를 반복한다.

    with LockSession(engine) as locks:
        with locks.hold(provider_lock_key("KR")) as waited:   # waited: 잠금을 기다린 초
            ...외부 호출...
    """
    def __init__(self, engine: Engine) -> None: ...
    def __enter__(self) -> "LockSession": ...           # engine.connect() 한 번
    def __exit__(self, *exc) -> None: ...               # 잡힌 키를 모두 풀고 연결을 닫는다(예외를 삼키지 않음)

    @contextmanager
    def hold(self, key: int) -> Iterator[float]:
        """pg_advisory_lock → commit → (대기 초) yield → finally pg_advisory_unlock → commit.
        __enter__ 전·__exit__ 뒤에 부르면 RuntimeError."""


@dataclass
class Unit:
    """회사 1개 작업의 결과. 외부 호출은 끝났고 DB에는 아직 쓰지 않은 상태."""
    source: str                       # ingestion_logs.source — "DART" / "SEC"
    job_type: str                     # "FINANCIALS" / "DISCLOSURES"
    stock_id: int
    label: str                        # 티커 (반환 딕셔너리 키, 로그 label)
    country: str                      # "KR" / "US"
    kind: str                         # data_freshness.kind — "financials" / "disclosures"
    started_at: datetime              # UTC
    writes: list[tuple[str, list[dict], list[str]]] = field(default_factory=list)  # (테이블, 행, 충돌 키)
    after: list[Callable[[Connection, "Unit"], None]] = field(default_factory=list)  # upsert 뒤 같은 트랜잭션
    notes: list[str] = field(default_factory=list)
    rows: int = 0                     # ingestion_logs.rows_loaded
    error: str | None = None          # 외부 호출 단계 실패 사유. 있으면 writes·after를 실행하지 않는다
    status: str = "PENDING"           # flush 뒤 "SUCCESS" / "FAILED"


def write_logs(engine: Engine, units: list[Unit]) -> None:
    """Unit마다 ingestion_logs 1행(별도 트랜잭션). error 열·콘솔 로그 형식은 job_log와 같다.
    쓰다가 실패하면 log.exception만 하고 예외를 올리지 않는다."""


class BatchWriter:
    def __init__(self, engine: Engine, flush_every: int,
                 on_flush: Callable[[list[Unit]], None] | None = None) -> None: ...
    flushes: int                      # DB에 실제로 쓴 flush 횟수
    done: list[Unit]                  # 상태가 확정된 Unit 전부 (추가 순서)

    def add(self, unit: Unit) -> None:
        """쌓는다. 쌓인 수가 flush_every 이상이면 flush()."""

    def flush(self) -> list[Unit]:
        """쌓인 Unit을 쓰고 비운다. 비어 있으면 아무것도 하지 않고 []."""
```

`BatchWriter.flush()` 순서:

1. `batch = 쌓인 것`, 목록을 비우고 `now = datetime.now(timezone.utc)`.
2. 트랜잭션 1개에서 `batch` 순서대로: `u.error is None`이면 `writes`를 `upsert` → `after` 실행 → `freshness.mark(..., True, country=u.country, now=now)`. `u.error`가 있으면 `freshness.mark(..., False, error=u.error, now=now)`.
3. 2에서 예외가 나면(롤백): `msg = "묶음 저장 실패: " + error_text(e)`, `error is None`이던 Unit의 `error = msg`, 새 트랜잭션에서 `batch` 전부 FAILED로 `freshness.mark`(이것도 실패하면 `log.exception`만).
4. `u.status = "SUCCESS" if u.error is None else "FAILED"`.
5. `write_logs(engine, batch)`.
6. `flushes += 1`, `done.extend(batch)`.
7. `on_flush([성공 Unit])` — 예외는 `log.exception`만.
8. `batch` 반환.

`store.py`가 `app.services.freshness`를 import해요(freshness는 store를 import하지 않아 순환 없음).

### 4-3. `backend/app/services/freshness.py`

```python
def due(conn: Connection, kind: str, stock_ids: list[int], now: datetime | None = None,
        *, limit: int | None = None) -> list[int]:
    """유효기간이 지났거나 기록이 없는 종목.
    limit=None: 지금과 같다(입력 순서). limit 지정: 기록 없음 → valid_until 오래된 순 → stock_id 순으로 앞 limit개.
    limit <= 0이면 []."""
```

`limit`이 있을 때:

```sql
SELECT s.id
FROM unnest(CAST(:ids AS int[])) AS s(id)
LEFT JOIN data_freshness f ON f.stock_id = s.id AND f.kind = :k
WHERE f.valid_until IS NULL OR f.valid_until <= :now
ORDER BY f.valid_until ASC NULLS FIRST, s.id
LIMIT :limit
```

### 4-4. `backend/config/universe.yaml`

`benchmark:` 블록 끝에 한 줄, 파일 끝에 `ingest:` 블록:

```yaml
  fin_daily_budget: 100   # 07:00 갱신이 하루에 재무를 받는 비교군 종목 수 상한(유효기간이 가장 오래 지난 순). 노출·관심 종목은 무관 (D4 임시값)

# 수집 적재 공통
ingest:
  flush_every: 20         # 재무·공시 적재를 몇 개 회사마다 한 트랜잭션으로 저장할지 (D3)
```

### 4-5. `backend/app/ingest/benchmark.py` — `load_benchmark`

```python
        due_bench = freshness.due(conn, "financials", ids, limit=cfg["fin_daily_budget"])
```

`due_freq`는 그대로예요.

### 4-6. `backend/app/ingest/jobs.py`

import:

```python
from sqlalchemy import Connection, Engine, text
from app.ingest.store import (LOCK_WAIT_NOTE_SECONDS, BatchWriter, LockSession, Unit, default_flush_every, error_text,
                              job_log, provider_lock_key, upsert)
```

`DART_LOCK_KEY`·`advisory_lock`은 jobs.py에서 쓰는 곳이 없어져 지워요(6단계 `load_dart_feed`에서 `DART_LOCK_KEY`를 다시 import).

#### 공개 함수 (지금 인자 + `flush_every`)

```python
def load_financials(engine: Engine, providers: Providers, *, years: int = FIN_YEARS,
                    tickers: list[str] | None = None, stock_ids: list[int] | None = None,
                    flush_every: int | None = None) -> dict[str, str]:
    """FY 재무 years개년 — 국내 DART, 미국 SEC(+yfinance 보완). 잠금은 회사 단위, 저장은 묶음."""
    with engine.connect() as conn:
        refs = stock_refs(conn, tickers, stock_ids=stock_ids)
    return _load_financials(engine, providers, refs, years, flush_every or default_flush_every())


def load_disclosures(engine: Engine, providers: Providers, *, days: int = DISCLOSURE_DAYS,
                     tickers: list[str] | None = None, today: date | None = None,
                     stock_ids: list[int] | None = None, flush_every: int | None = None) -> dict[str, str]:
    """최근 days일 공시 — 국내 DART, 미국 SEC."""
    today = today or date.today()
    with engine.connect() as conn:
        refs = stock_refs(conn, tickers, stock_ids=stock_ids)
    return _load_disclosures(engine, providers, refs, days, today, flush_every or default_flush_every())
```

`hydration.py`·`benchmark.py`·`__main__.py`·`refresh.py`의 호출부는 바꾸지 않아요.

#### 재무 — 반복과 묶음 저장

```python
def _load_financials(engine: Engine, providers: Providers, refs: list, years: int, flush_every: int) -> dict[str, str]:
    def on_flush(units: list[Unit]) -> None:          # 미국: 기초값 저장 뒤 기초값 × 종가 밸류에이션
        ids = [u.stock_id for u in units if any(t == "fundamental_bases" for t, _, _ in u.writes)]
        if ids:
            derive_us_valuations(engine, ids)

    writer = BatchWriter(engine, flush_every, on_flush=on_flush)
    with LockSession(engine) as locks:
        try:
            for ref in refs:
                writer.add(_fetch_financials(providers, locks, ref, years))
        finally:
            writer.flush()
    return {u.label: u.status for u in writer.done}
```

#### 재무 — 회사 1개 (외부 호출만)

```python
def _fetch_financials(providers: Providers, locks: LockSession, ref: StockRef, years: int) -> Unit:
    p = providers.financial(ref.country)
    source = p.source if p else ("DART" if ref.country == "KR" else "SEC")
    u = Unit(source=source, job_type="FINANCIALS", stock_id=ref.stock_id, label=ref.ticker, country=ref.country,
             kind="financials", started_at=datetime.now(timezone.utc))
    try:
        if p is None:
            raise ProviderError(f"{source} 설정 없음(API 키/User-Agent)")
        if ref.country == "KR" and not ref.corp_code or ref.country == "US" and not ref.cik:
            raise ProviderError("corp_code/CIK 미매핑 — master 먼저 실행")
        base = None
        with locks.hold(provider_lock_key(ref.country)) as waited:     # DART·SEC를 부르는 구간만
            fins = p.get_annual_financials(ref, years)
            if ref.country == "US" and ref.cik and providers.us_reference is not None:
                try:
                    base = providers.us_reference.get_valuation_base(ref)
                except ProviderError as e:
                    u.notes.append(f"기초값 실패: {e}")
        if waited >= LOCK_WAIT_NOTE_SECONDS:
            u.notes.append(f"잠금 대기 {waited:.1f}초")
        if ref.country == "US" and providers.us_financial_supplement:     # yfinance 보완은 잠금 밖
            try:
                fins = merge_supplement(fins, providers.us_financial_supplement.get_annual_financials(ref, years))
            except ProviderError as e:
                u.notes.append(f"yfinance 보완 실패: {e}")
            fins = fins[-years:]
        rows = [{"stock_id": ref.stock_id, "period_end": f.period_end, "period_type": f.period_type,
                 **{k: getattr(f, k) for k in FIN_FIELDS},
                 "data_source": f.data_source, "accounting_std": f.accounting_std} for f in fins]
        u.writes.append(("financial_statements", rows, ["stock_id", "period_end", "period_type"]))
        u.rows = len(rows)
        for f in fins:
            missing = [k for k in FIN_FIELDS if getattr(f, k) is None]
            if f.notes or missing:
                u.notes.append(f"{f.period_end.year}: " + ", ".join(f.notes + [f"{m} 없음" for m in missing]))
        if len(fins) < years:
            u.notes.append(f"FY {len(fins)}/{years}개")
        if base is not None:
            if base.shares_outstanding is None and base.dps is None:
                u.notes.append("기초값 없음")
            else:
                u.writes.append(("fundamental_bases", [{
                    "stock_id": ref.stock_id, "shares_outstanding": base.shares_outstanding,
                    "shares_as_of": base.shares_as_of, "dps": base.dps, "dps_period_end": base.dps_period_end,
                    "source": providers.us_reference.source, "updated_at": datetime.now(timezone.utc)}], ["stock_id"]))
    except Exception as e:  # noqa: BLE001 — 회사 하나 실패는 기록하고 다음 회사로
        u.error = error_text(e)
        log.error("FINANCIALS %s 실패: %s", ref.ticker, u.error)
    return u
```

`_load_valuation_base`는 지워요(내용이 `fundamental_bases` 행과 `on_flush`로 옮겨졌어요).

#### 공시 — 반복과 회사 1개

```python
def _load_disclosures(engine: Engine, providers: Providers, refs: list, days: int, today: date,
                      flush_every: int) -> dict[str, str]:
    writer = BatchWriter(engine, flush_every)
    with LockSession(engine) as locks:
        try:
            for ref in refs:
                writer.add(_fetch_disclosures(providers, locks, ref, days, today))
        finally:
            writer.flush()
    return {u.label: u.status for u in writer.done}


def _expire_fin_on_annual_report(conn: Connection, u: Unit) -> None:
    # 받아 둔 재무 뒤에 사업보고서·10-K가 새로 올라왔으면 재무 유효기간을 바로 끝낸다
    if freshness.invalidate_on_annual_report(conn, u.stock_id):
        u.notes.append("새 사업보고서 → 재무 유효기간 만료")


def _fetch_disclosures(providers: Providers, locks: LockSession, ref: StockRef, days: int, today: date) -> Unit:
    p = providers.disclosure(ref.country)
    source = p.source if p else ("DART" if ref.country == "KR" else "SEC")
    u = Unit(source=source, job_type="DISCLOSURES", stock_id=ref.stock_id, label=ref.ticker, country=ref.country,
             kind="disclosures", started_at=datetime.now(timezone.utc))
    try:
        if p is None:
            raise ProviderError(f"{source} 설정 없음(API 키/User-Agent)")
        with locks.hold(provider_lock_key(ref.country)) as waited:
            items = p.get_disclosures(ref, today - timedelta(days=days), today)
        if waited >= LOCK_WAIT_NOTE_SECONDS:
            u.notes.append(f"잠금 대기 {waited:.1f}초")
        rows = [{"stock_id": ref.stock_id, "rcept_no": d.rcept_no, "title": d.title, "report_type": d.report_type,
                 "filed_at": d.filed_at, "url": d.url, "data_source": source} for d in items]
        u.writes.append(("disclosures", rows, ["rcept_no"]))
        u.rows = len(rows)
        u.after.append(_expire_fin_on_annual_report)
    except Exception as e:  # noqa: BLE001
        u.error = error_text(e)
        log.error("DISCLOSURES %s 실패: %s", ref.ticker, u.error)
    return u
```

#### 지금과 달라지는 로그 (의도한 차이)

| 항목 | 전 | 후 |
| --- | --- | --- |
| freshness 실패 사유(재무) | 항상 `"재무 수집 실패"` | 실제 사유(`error_text`) |
| freshness 실패 사유(공시) | 없음(NULL) | 실제 사유 |
| `ingestion_logs.finished_at` | 회사 저장 직후 | 그 회사가 들어간 묶음 저장 직후 |
| 비고 | — | 잠금을 1초 이상 기다리면 `잠금 대기 N.N초` |

### 4-7. `backend/app/providers/dart.py`

```python
# OpenDART는 분당 100회 이상 호출하면 이용이 제한될 수 있다. 잠금이 회사 단위라 프로세스 2개(API 서비스 + Job)가
# 번갈아 부를 수 있어 프로세스마다 절반(45)으로 막는다 → 합계 90 이하 (D2). 프로세스가 3개 이상이 되면 다시 검토
_limiter = WindowLimiter(45, 60.0)
```

### 4-8. 재무 기준 연도 표기 ("재무 기준 FY2025 n개 · FY2024 m개")

실적 시즌에는 같은 날 비교하는 종목 중 일부는 새 연도, 일부는 지난해 재무예요. 이걸 숫자로 보여줘요. 저장된 `stock_scores.data_quality`에 넣으면 지난 점수까지 다시 계산해야 해서 **응답 때 계산**해요.

#### `backend/app/queries/fin_basis.sql` (새)

```sql
-- 매력도 비교 표본의 최신 FY 결산 연도별 종목 수 — 실적 시즌에 새 연도·지난 연도 재무가 섞인 정도 (docs/09)
-- 파라미터: country (KR·US), as_of (stock_metric_values.as_of = 점수 기준일)
-- 표본: 그 기준일에 지표가 계산된 그 국가 종목(노출 + 비교군, listed 제외). FY는 as_of 이하 결산일 중 최신
-- FY가 하나도 없는 종목은 세지 않는다
WITH u AS (
    SELECT DISTINCT mv.stock_id
    FROM stock_metric_values mv
    JOIN stocks s   ON s.stock_id = mv.stock_id
    JOIN markets mk ON mk.market_id = s.market_id
    WHERE mv.as_of = :as_of AND mk.country = :country AND s.coverage <> 'listed'
),
fy AS (
    SELECT u.stock_id, MAX(f.period_end) AS period_end
    FROM u
    JOIN financial_statements f ON f.stock_id = u.stock_id AND f.period_type = 'FY' AND f.period_end <= :as_of
    GROUP BY u.stock_id
)
SELECT CAST(EXTRACT(YEAR FROM fy.period_end) AS int) AS fiscal_year, COUNT(*) AS stocks
FROM fy
GROUP BY 1
ORDER BY 1 DESC
```

#### `backend/app/services/data_quality.py`

```python
def fiscal_year_mix(conn: Connection, country: str, as_of: date) -> list[dict]:
    """매력도 표본의 최신 FY 결산 연도별 종목 수. [{"fiscal_year": 2025, "stocks": 41}, ...] 연도 내림차순.
    as_of에 지표가 없으면 []."""
    return [dict(r) for r in conn.execute(sql("fin_basis"), {"country": country, "as_of": as_of}).mappings()]
```

`fiscal_year`는 결산일의 연도예요(AAPL 2025-09-27 결산 → 2025).

#### `backend/app/api/analysis.py`

```python
class FinBasisOut(Schema):
    fiscal_year: int                 # 최신 FY 결산일의 연도
    stocks: int                      # 그 연도 재무로 비교된 종목 수


class ScoreOut(Schema):
    ...                              # 기존 필드 그대로
    reference_note: str | None = None
    fin_basis: list[FinBasisOut] = []   # 같은 시장 비교 표본의 재무 기준 연도별 종목 수(연도 내림차순)
```

- `_attractiveness` 반환에 `"fin_basis": fiscal_year_mix(db.connection(), country, row["score_as_of"])`.
- `reference_score.py` 반환에 `"fin_basis": fiscal_year_mix(conn, country, as_of)`.
- 점수가 없으면 키를 넣지 않아 기본값 `[]`.

응답 예시 (`attractiveness` 끝):

```json
  "reference": false,
  "reference_note": null,
  "fin_basis": [
    {"fiscal_year": 2025, "stocks": 41},
    {"fiscal_year": 2024, "stocks": 30}
  ]
```

#### 화면 (`stock.js` `renderScore`)

'계산 근거 보기' 안, `데이터 충족도 …` 줄 바로 아래 한 줄. 빈 배열이면 그리지 않아요.

```js
s.fin_basis?.length ? `<p class="subtle">재무 기준 ${s.fin_basis.map((x) => `FY${x.fiscal_year} ${x.stocks}개`).join(" · ")}</p>` : ""
```

### 4-9. 테스트

#### `backend/tests/test_store_batch.py` (새)

| 테스트 이름 | 확인하는 것 |
| --- | --- |
| `test_provider_lock_key_splits_by_country` | KR → 7_301_010, US → 7_301_012, "JP" → ValueError |
| `test_lock_session_reuses_one_connection_and_releases` | `hold` 안에서는 다른 연결의 `pg_try_advisory_lock(key)`가 False, 두 `hold` 사이에는 True |
| `test_batch_writer_flushes_every_n` | 회사 25개, `flush_every=20` → `flushes == 2`, `ingestion_logs` 25행 |
| `test_failed_unit_marks_freshness_failed_and_logs` | `error`가 있는 Unit → writes 실행 안 됨, freshness·로그 FAILED |
| `test_flush_db_error_fails_batch_but_keeps_logs` | 없는 테이블 이름 → 묶음 전체 FAILED, freshness에 SUCCESS 없음, 로그 남음, `error`가 `"묶음 저장 실패: "`로 시작 |
| `test_due_limit_orders_missing_then_oldest` | 기록 없음 2 · 오래된 순 3 → `limit=3`이면 [없음, 없음, 가장 오래된 것], `limit=None`은 입력 순서 |

#### `backend/tests/test_ingest_batch.py` (새)

| 테스트 이름 | 확인하는 것 |
| --- | --- |
| `test_financials_statuses_and_freshness_after_batch` | 종목 3개(1개 corp_code 없음) → 반환 `{티커: 상태}`, 성공 2개 SUCCESS, 실패 1개 FAILED |
| `test_us_valuation_base_saved_and_derived_after_flush` | 미국 종목 → `fundamental_bases` 1행 + `valuation_snapshots` 파생 행 |
| `test_disclosure_annual_report_expires_financials_in_same_batch` | 새 사업보고서 공시 → 재무 유효기간 만료 + 비고 |
| `test_detail_request_waits_only_one_company` | `FakeFinancial(delay=0.3)`로 KR 6개를 스레드에서 시작 → 0.1초 뒤 다른 KR 1개 → 1.0초 안에 끝남 |
| `test_kr_and_us_do_not_share_lock` | KR 묶음 진행 중 US 1개가 잠금 대기 비고 없이 끝남 |

`backend/tests/fakes.py`: `FakeFinancial.__init__(self, source: str, delay: float = 0.0)`, `FakeDisclosure.__init__(self, source: str, delay: float = 0.0)` — 호출마다 `time.sleep(delay)`. 기본값 0이라 기존 테스트는 그대로예요.

#### 그 밖

- `test_data_quality.py`: `test_fiscal_year_mix_counts_latest_fy_per_stock` — KR 3종목(FY2025 2개, FY2024 1개) + listed 1개 + US 1개 → `[{"fiscal_year": 2025, "stocks": 2}, {"fiscal_year": 2024, "stocks": 1}]`
- `test_analysis.py`: `test_analysis_includes_fin_basis` — 점수 있는 종목은 위 함수 결과와 같고, 점수 없는 종목은 `[]`
- 기존 `test_freshness.py`·`test_benchmark.py`·`test_refresh.py`·`test_ingest.py`는 실패 사유 문구를 확인하는 곳 말고는 그대로 통과해야 해요

### 4-10. 완료 기준

1. `pytest -q` 전부 통과
2. 개발 DB `python -m app.ingest financials --tickers 005930 AAPL` → 두 종목 SUCCESS, `ingestion_logs` 2행, `data_freshness` 2행
3. `python -m app.ingest benchmark` 중 다른 창에서 비교군 종목 상세 → `detail_status`가 `loading` → 수십 초 안에 `ready`
4. `docs/architecture.md`의 잠금 설명을 "회사 단위·국가별 키"로

---

## 5. 3단계 — 시장·섹터 점수

### 5-1. 무엇을 하나

종목 상세 '투자 매력도' 카드에서 매력 점수 아래에 "시장·섹터 점수" 게이지를 보여줘요. 매력도와 합치지 않고, 해설·권유 문구도 없어요. 새 외부 호출·새 테이블·새 API·조회 경로 쓰기가 없어요.

### 5-2. 계산 정의

| 재료 | 값 | 0~100 | 비중 |
| --- | --- | --- | --- |
| 시장 | 그 국가 시장 심리 지수 최신 **저장값** (`market_sentiment_daily.score`) | 그대로 | 0.7 |
| 섹터 흐름 | 같은 국가·같은 `stocks.sector` 표본의 5거래일 수익률 중앙값 `r` | `clamp(50 + r × 100 × 5)`, 소수 둘째 자리 HALF_UP | 0.3 |

```
섹터 반영:   score = HALF_UP_정수(0.7 × 시장 + 0.3 × 섹터 흐름)
섹터 미반영: score = HALF_UP_정수(시장)
라벨:       score가 null이면 "데이터 부족", 아니면 BAND_LABELS[min(4, score // 20)]
            BAND_LABELS = ("매우 낮음", "낮음", "보통", "높음", "매우 높음")   ← frontend charts.js BANDS와 같아야 함
```

| 경우 | 판정 | 결과 |
| --- | --- | --- |
| 기준일 `base` | `market_calendar.last_closed_session(country, now)`. None이면 그 국가 기준 지수(`sentiment.INDEX_CODE`)의 `index_daily_prices` 최신 거래일. 그것도 없으면 전부 "데이터 부족" | — |
| 시장 심리 저장값 없음 | `latest_stored`가 None | `score: null`, "데이터 부족" |
| 시장 심리 오래됨 | `sessions_between(country, 심리 거래일, base) > 5`. 달력 판정 불가(None)면 `(base − 심리 거래일).days > 7` | `score: null`, "데이터 부족" (재료값은 그대로 응답) |
| 섹터 없음 | `stocks.sector IS NULL` | 섹터 미반영 (D9) |
| 섹터 표본 부족 | `n < 5` 또는 `sector_r5 IS NULL` | 섹터 미반영 |
| 섹터 표본 | 같은 국가·같은 `sector`, `is_active`, `coverage IN ('featured','benchmark')` — 자기 자신 포함 | — |
| 섹터 기준일 `ref_date` | `base` 이하에서 표본 종목 일봉이 5개 이상 있는 가장 최근 날짜. 그런 날이 없으면(표본 자체가 5개 미만) 표본 일봉이 있는 가장 최근 날짜 — 표본 수 안내용이고 점수에는 쓰지 않아요 | 비교군 일봉은 07:00에만 들어와서 마감 직후엔 하루 전 날짜로 계산돼요 |
| 5일 수익률 | 그 날짜 종가 ÷ 그 종목 자기 일봉 기준 5거래일 전(6번째) 종가 − 1. 둘 중 하나가 없으면 제외/null | — |
| `stock_r5`·`index_r5` 날짜 | 섹터 반영이면 `ref_date`, 아니면 시장 심리 거래일(없으면 `base`) | 툴팁의 세 수익률이 같은 날짜 기준 |

예시: 시장 심리 28.00, `r = −0.024` → 섹터 흐름 `clamp(50 − 12) = 38.00` → `0.7×28 + 0.3×38 = 31.0` → **31, "낮음"**.

### 5-3. `backend/app/queries/sector_flow.sql` (새)

```sql
-- 시장·섹터 점수의 '섹터 흐름' 재료: 같은 국가·같은 업종 섹터(stocks.sector) 표본 종목의 5거래일 수익률 중앙값
-- 파라미터: country (KR·US), sector (stocks.sector 값), as_of (그 국가 마지막 마감 거래일), min_n (최소 표본 수 5)
-- 표본: 활성 노출 종목 + 비교군(listed 제외) — 매력도 섹터 중립화와 같은 섹터 분류. 이 종목 자신도 포함
-- ref_date: as_of 이하에서 일봉이 있는 표본 종목이 min_n개 이상인 가장 최근 날짜
--   (비교군 일봉은 매일 07:00에만 들어와서, 장 마감 직후에는 노출 종목만 그날 일봉이 있다 → 전 거래일로 계산)
-- 수익률 = ref_date 종가 / 그 종목의 5거래일 전 종가 − 1. ref_date 일봉이나 5거래일 전 일봉이 없는 종목은 뺀다
-- 결과는 항상 1행: sector_r5(표본 0개면 NULL), n(수익률을 낸 종목 수), ref_date(없으면 NULL)
WITH peers AS (
    SELECT s.stock_id
    FROM stocks s
    JOIN markets mk ON mk.market_id = s.market_id
    WHERE mk.country = :country AND s.sector = :sector AND s.is_active AND s.coverage IN ('featured', 'benchmark')
),
bars AS (                             -- 연휴가 길어도 6거래일이 들어가도록 30일
    SELECT d.stock_id, d.trade_date, d.close
    FROM daily_prices d
    JOIN peers p ON p.stock_id = d.stock_id
    WHERE d.trade_date <= CAST(:as_of AS date) AND d.trade_date > CAST(:as_of AS date) - 30
),
ref AS (
    SELECT COALESCE(MAX(c.trade_date) FILTER (WHERE c.cnt >= :min_n), MAX(c.trade_date)) AS ref_date
    FROM (SELECT b.trade_date, COUNT(*) AS cnt FROM bars b GROUP BY b.trade_date) c
),
ranked AS (                           -- ref_date부터 거꾸로 번호(rn = 1이 ref_date 이하 최신)
    SELECT b.stock_id, b.trade_date, b.close,
           ROW_NUMBER() OVER (PARTITION BY b.stock_id ORDER BY b.trade_date DESC) AS rn
    FROM bars b
    CROSS JOIN ref
    WHERE b.trade_date <= ref.ref_date
),
r AS (
    SELECT k.stock_id,
           MAX(k.close) FILTER (WHERE k.rn = 1) / NULLIF(MAX(k.close) FILTER (WHERE k.rn = 6), 0) - 1 AS r5
    FROM ranked k
    CROSS JOIN ref
    WHERE k.rn IN (1, 6)
    GROUP BY k.stock_id, ref.ref_date
    HAVING MAX(k.trade_date) FILTER (WHERE k.rn = 1) = ref.ref_date
       AND COUNT(*) FILTER (WHERE k.rn = 6) = 1
)
SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY r.r5) AS sector_r5,
       COUNT(r.r5)                                        AS n,
       (SELECT ref.ref_date FROM ref)                     AS ref_date
FROM r
```

결과 열: `sector_r5`(double precision 또는 NULL), `n`(bigint), `ref_date`(date 또는 NULL).

### 5-4. `backend/app/services/market_condition.py` (새)

```python
"""시장·섹터 점수 — 종목 상세 '투자 매력도' 카드의 위험 표시(0~100). 매력도와 별개이며 투자 권유가 아니다.

  시장       그 국가 시장 심리 지수 최신 저장값(market_sentiment_daily) — 계산·저장은 홈·4시간 갱신이 한다
  섹터 흐름   같은 stocks.sector 표본 종목의 5거래일 수익률 중앙값 → clamp(50 + r × 100 × 5)
  점수       0.7 × 시장 + 0.3 × 섹터 흐름 (섹터가 없거나 표본 5개 미만이면 시장만)
외부 호출·DB 쓰기가 없다. 정의는 docs/09 '시장·섹터 점수' 절.
"""
MARKET_WEIGHT = Decimal("0.7")
SECTOR_WEIGHT = Decimal("0.3")
SECTOR_DAYS = 5                    # 수익률 기간(거래일) — sector_flow.sql의 rn = 6과 짝
SECTOR_SCALE = 5                   # 시장 심리 이동평균 괴리 점수와 같은 배율 → 50이 중립
MIN_SECTOR_SAMPLE = 5
MAX_SENTIMENT_LAG = 5              # 거래일 — 이보다 오래된 시장 심리는 쓰지 않는다
CALENDAR_LAG_DAYS = 7              # 거래소 달력을 못 쓸 때의 달력일 기준
CACHE_TTL = timedelta(hours=1)
BAND_LABELS = ("매우 낮음", "낮음", "보통", "높음", "매우 높음")   # frontend/js/components/charts.js BANDS와 같아야 한다
INSUFFICIENT = sentiment.INSUFFICIENT   # "데이터 부족"


def band_label(score: int | None) -> str:
    """None → "데이터 부족", 0~19 매우 낮음, 20~39 낮음, 40~59 보통, 60~79 높음, 80~100 매우 높음."""


def sector_flow_score(r: Decimal | float | None) -> Decimal | None:
    """5거래일 수익률 → 0~100. clamp(50 + r × 100 × 5), 소수 둘째 자리 HALF_UP. None → None."""


def compute_condition(sentiment: Decimal | float | None, sector_r: Decimal | float | None) -> dict:
    """순수 계산. 반환 {"score": int | None, "label": str, "sector_flow": Decimal | None}.
    sentiment None → score None·"데이터 부족"(sector_flow는 그대로 계산). sector_r None → 시장만."""


def read_sector_flow(conn: Connection, country: str, sector: str, as_of: date) -> tuple[Decimal | None, int, date | None]:
    """sector_flow.sql 실행(캐시 없음). 반환 (sector_r5 — 소수 여섯째 자리 HALF_UP, n, ref_date)."""


def get_condition(engine: Engine, *, stock_id: int, country: str, sector: str | None,
                  now: datetime | None = None) -> dict:
    """상세 응답 market_condition. 항상 MarketConditionOut 모양의 dict, 예외를 올리지 않는다
    (실패하면 log.exception + empty_condition)."""


def empty_condition(country: str, sector: str | None) -> dict:
    """모든 값 null·"데이터 부족"·sector_sample 0. index_code는 sentiment.INDEX_CODE[country]."""


def clear_cache() -> None:
    """섹터 흐름 캐시 비우기 (테스트용)."""
```

`get_condition` 순서:

1. `index_code = sentiment.INDEX_CODE[country]`, `now = now or datetime.now(timezone.utc)`
2. `base` 결정 (5-2 표)
3. `s_row = sentiment.latest_stored(engine, country)`, `stale` 판정
4. `sector`가 있으면 `(sector_r5, n, ref_date)` = 캐시 또는 `read_sector_flow`. `use = n >= MIN_SECTOR_SAMPLE and sector_r5 is not None`
5. `compare = ref_date if use else (s_row["trade_date"] if s_row else base)`
6. `stock_r5`·`index_r5` 계산 (아래 SQL, 소수 여섯째 자리 HALF_UP)
7. `cond = compute_condition(None if (s_row is None or stale) else s_row["score"], sector_r5 if use else None)`
8. 5-5 필드 표대로 반환

캐시: `{(country, sector, base): (저장 시각, 결과)}` + `threading.Lock`. **`n >= MIN_SECTOR_SAMPLE`일 때만** 저장하고, `CACHE_TTL`(1시간)이 지나면 다시 읽어요. 상세는 수집 대기 중 2초마다 다시 불려서 캐시가 필요해요.

```python
STOCK_R5 = text("""
    SELECT MAX(x.close) FILTER (WHERE x.rn = 1) / NULLIF(MAX(x.close) FILTER (WHERE x.rn = 6), 0) - 1
    FROM (SELECT d.trade_date, d.close, ROW_NUMBER() OVER (ORDER BY d.trade_date DESC) AS rn
          FROM daily_prices d WHERE d.stock_id = :s AND d.trade_date <= :d) x
    WHERE x.rn <= 6
    HAVING MAX(x.trade_date) FILTER (WHERE x.rn = 1) = :d AND COUNT(*) FILTER (WHERE x.rn = 6) = 1""")

INDEX_R5 = text("""
    SELECT MAX(x.close) FILTER (WHERE x.rn = 1) / NULLIF(MAX(x.close) FILTER (WHERE x.rn = 6), 0) - 1
    FROM (SELECT p.trade_date, p.close, ROW_NUMBER() OVER (ORDER BY p.trade_date DESC) AS rn
          FROM index_daily_prices p JOIN indices i ON i.index_id = p.index_id
          WHERE i.code = :c AND p.trade_date <= :d) x
    WHERE x.rn <= 6
    HAVING MAX(x.trade_date) FILTER (WHERE x.rn = 1) = :d AND COUNT(*) FILTER (WHERE x.rn = 6) = 1""")
```

조건이 맞지 않으면 행이 없어 `.scalar()`가 None이에요.

### 5-5. 응답 — `GET /api/v1/stocks/{market}/{ticker}`에 `market_condition`

#### 섹터 분류 (`backend/app/ingest/benchmark.py` — 구현하며 추가)

지금 코드에는 `stocks.sector`를 채우는 곳이 없었어요(provider `get_sector_classifications`·`get_sic`와 `sectors.sector_for_krx`·`sector_for_sic`만 있음). `select_benchmark` 끝(`map_ids` 뒤)에서 부르는 함수를 추가해요. 비교군 선정 방식(테마 그룹)은 그대로예요.

```python
SIC_RECHECK_DAYS = 365

def classify_sectors(engine: Engine, providers: Providers, today: date, notes: list[str]) -> None:
    """업종 → stocks.industry·sic·sector. 국내는 활성 종목 전체(KRX 전 종목 조회 1회),
    미국은 노출 종목·비교군 중 SIC를 확인한 지 SIC_RECHECK_DAYS가 지난 종목만. 실패는 비고만 남긴다."""
```

#### `backend/app/queries/stock_detail.sql`

SELECT 첫 줄에 `s.sector`를 추가하고, 머리 주석 "업종은 이후 단계에서 컬럼을 추가한다"를 "업종 섹터(stocks.sector)는 시장·섹터 점수 계산용 — 응답에는 market_condition.sector_name으로 나간다"로 바꿔요.

```sql
SELECT s.stock_id, s.ticker, s.name, s.name_en, s.corp_code, s.cik, s.coverage, s.detail_synced_at, s.sector,
```

`StockDetailOut`에는 `sector` 필드를 따로 만들지 않아요(응답 모델에 없는 키는 빠져요).

#### `backend/app/schemas/api.py`

`StockDetailOut` 바로 위에 추가하고, `StockDetailOut`의 마지막 필드로 넣어요.

```python
class MarketConditionOut(Schema):
    score: int | None                # 0~100 정수. 시장 심리 없음·오래됨이면 null
    label: str                       # 매우 낮음·낮음·보통·높음·매우 높음 / 데이터 부족
    sentiment: Num | None            # 시장 심리 지수 저장값(0~100) — 오래돼도 값은 그대로
    sector_name: str | None          # stocks.sector. 섹터 없음이면 null
    sector_flow: Num | None          # 섹터 흐름 0~100. 섹터 미반영이면 null
    sector_sample: int               # 섹터 수익률을 낸 표본 종목 수(섹터 없음이면 0)
    sector_as_of: date | None        # 섹터 흐름 기준일(ref_date). 미반영이면 null
    index_code: str                  # 비교 지수 (KOSPI · SPX)
    stock_r5: Num | None             # 이 종목 5거래일 수익률(소수)
    sector_r5: Num | None            # 섹터 중앙값 5거래일 수익률. 미반영이면 null
    index_r5: Num | None             # 지수 5거래일 수익률
    as_of: date | None               # 시장 심리 기준일(화면 '추합 기준' 날짜)


class StockDetailOut(Schema):
    ...                              # 기존 필드 그대로
    market_condition: MarketConditionOut   # 시장·섹터 점수 (매력도와 별개, 투자 권유 아님)
```

#### 필드 값 규칙

| 필드 | 섹터 반영 | 섹터 표본 부족 | 섹터 없음 |
| --- | --- | --- | --- |
| `sector_name` | 섹터 이름 | 섹터 이름 | `null` |
| `sector_flow` | 0~100 | `null` | `null` |
| `sector_sample` | n (≥ 5) | n (0~4) | 0 |
| `sector_as_of` | ref_date | `null` | `null` |
| `sector_r5` | 중앙값 | `null` | `null` |
| `stock_r5`·`index_r5` | ref_date 기준 | 시장 심리 기준일 기준 | 시장 심리 기준일 기준 |

#### `backend/app/api/stocks.py`

지금 라우터 인자에 `engine` 하나만 추가해요.

```python
from sqlalchemy import Engine
from app.api.deps import ..., get_engine_dep        # 기존 import 줄에 추가
from app.services.market_condition import get_condition


def stock_detail(market: MarketPath, ticker: TickerPath, user_id: int = Depends(get_current_user_id),
                 preset: dict = Depends(get_preset), db: Session = Depends(get_db),
                 hydrator: Hydrator = Depends(get_hydrator), engine: Engine = Depends(get_engine_dep)):
    ...
    out["detail_status"] = hydrator.request(out["stock_id"], out["coverage"], out.pop("detail_synced_at"))
    out["market_condition"] = get_condition(engine, stock_id=out["stock_id"], country=out["country"],
                                            sector=out.pop("sector"))
    out["fx_stale"] = False
    return out
```

### 5-6. 응답 예시

섹터 반영 (`GET /stocks/KOSPI/005930`, 계산 맞춤 예시):

```json
"market_condition": {
  "score": 31,
  "label": "낮음",
  "sentiment": 28.0,
  "sector_name": "반도체·전자",
  "sector_flow": 38.0,
  "sector_sample": 47,
  "sector_as_of": "2026-10-15",
  "index_code": "KOSPI",
  "stock_r5": -0.031,
  "sector_r5": -0.024,
  "index_r5": -0.018,
  "as_of": "2026-10-16"
}
```

섹터 없음 (금융, 예 `GET /stocks/KOSPI/105560`):

```json
"market_condition": {
  "score": 28, "label": "낮음", "sentiment": 28.0,
  "sector_name": null, "sector_flow": null, "sector_sample": 0, "sector_as_of": null,
  "index_code": "KOSPI", "stock_r5": -0.012, "sector_r5": null, "index_r5": -0.009, "as_of": "2026-10-16"
}
```

시장 심리 오래됨:

```json
"market_condition": {
  "score": null, "label": "데이터 부족", "sentiment": 61.2,
  "sector_name": "반도체·전자", "sector_flow": 38.0, "sector_sample": 47, "sector_as_of": "2026-10-15",
  "index_code": "KOSPI", "stock_r5": -0.031, "sector_r5": -0.024, "index_r5": -0.018, "as_of": "2026-09-30"
}
```

### 5-7. 시장 심리 이름 공개 (`backend/app/services/sentiment.py`)

`_latest_stored` → `latest_stored`로 **이름만** 바꾸고 호출부(`get_sentiment`)도 바꿔요. 시그니처 `latest_stored(engine: Engine, market: str) -> dict | None`, 반환 키(`trade_date, score, label, price_position, ma_gap_score, rsi_score, vix_score, formula_version`)는 그대로예요. 상세 경로는 이 함수만 불러요.

### 5-8. 거래일 수 (`backend/app/services/market_calendar.py`)

```python
def sessions_between(country: str, start: date, end: date) -> int | None:
    """start 다음 날부터 end까지(end 포함)의 거래일 수. start >= end면 0.
    country가 KR·US가 아니거나 달력 범위 밖·판정 실패면 None(경고 로그)."""
```

구현: `len(_calendar(CALENDARS[country]).sessions_in_range(pd.Timestamp(start + timedelta(days=1)), pd.Timestamp(end)))`.

### 5-9. 화면 (`frontend/js/pages/stock.js`, `frontend/css/pages.css`)

데이터: 시장·섹터 점수는 전역 `stock`(상세 응답)의 `market_condition`, 매력 점수는 지금처럼 `/analysis`에서 읽어요. 새 API 호출은 없어요. `renderScore(a)` 안에서 `stock?.market_condition`을 읽어서, 프리셋 변경으로 다시 그려도 그대로 나와요.

시안: `docs/assets/score_panel_sector_mockup.png`. 시안 속 숫자·섹터 이름·범례는 자리 채움이에요. 두 게이지 색이 같을 필요는 없어요.

| 항목 | 내용 |
| --- | --- |
| 게이지 함수 | `gauge(score, { name = "매력도" } = {})` — `aria-label`이 `${name} ${num(score, 1)}점` / 없으면 `${name} 계산 불가`. 시장·섹터는 `{ name: "시장·섹터 점수" }` |
| 제목 | 첫 게이지 위 `매력 점수`, 둘째 게이지 위 `시장·섹터 점수` |
| 라벨 | 둘째 게이지 라벨 글자는 `market_condition.label`, 색 점은 `scoreBand(score)`의 구간 색. 점수 null이면 게이지 빈 상태(–), 라벨 `데이터 부족` |
| 순위·기준일 문장 | 지금 `score-panel__gauge` 안의 `rankText`·`{프리셋} 성향 · {날짜} 기준`을 매력 점수 게이지 **옆**으로 |
| 섹터 문장 — 반영 | `현재 주식의 섹터 분류는 <strong>{sector_name}</strong> 입니다` |
| 섹터 문장 — 표본 부족 | 위 문장 + 다음 줄 `섹터 표본이 적어 시장 심리만 반영했습니다` |
| 섹터 문장 — 섹터 없음 | `섹터 분류가 없어 시장 심리만 반영했습니다` |
| 날짜 줄(작은 글씨) | `지수 및 섹터 정보 추합 : {as_of를 YYYY.MM.DD} 기준`. `sector_as_of`가 있고 `as_of`와 다르면 끝에 ` (섹터 {MM.DD})` |
| 툴팁 | 시장·섹터 게이지에 마우스·키보드 포커스(`tabindex="0"`, `aria-describedby`) — 홈 `.senti__gauge`/`.senti__tip`과 같은 방식 |
| 툴팁 숫자 | 점수·재료는 정수(`Math.round`), 수익률은 `pct(v, { digits: 1, sign: true })`, 값 없음은 `–` |
| 좁은 화면(767px 이하) | 매력 점수 → 시장·섹터 점수 → 레이더 순서로 세로. 390px에서 가로 스크롤 없음 |
| `market_condition`이 없을 때 | 둘째 게이지 행을 그리지 않아요. 콘솔 에러 없음 |

툴팁 (섹터 반영):

```
시장·섹터 점수 31
시장 심리 28 · 섹터 흐름 38 (반도체·전자 47종목)
5거래일 수익률
  이 종목      -3.1%
  섹터 중앙값  -2.4%
  KOSPI       -1.8%
시장 심리 70% + 섹터 흐름 30%, 투자 권유 아님
```

섹터 미반영이면 둘째 줄 `시장 심리 28 · 섹터 미반영`, 섹터 중앙값 줄 없음, 마지막 줄 `시장 심리 100%(섹터 미반영), 투자 권유 아님`. 지수 이름은 `KOSPI` → `KOSPI`, `SPX` → `S&P 500`.

### 5-10. 테스트

#### `backend/tests/test_market_condition.py` (새)

| 테스트 이름 | 확인하는 것 |
| --- | --- |
| `test_sector_flow_score_bounds` | −0.20 → 0.00, −0.10 → 0.00, −0.034 → 33.00, 0 → 50.00, 0.02 → 60.00, 0.10 → 100.00, None → None |
| `test_compute_condition_weights_and_half_up` | (28, −0.024) → 31·"낮음"·38.00 / (Decimal("50.50"), None) → 51·"보통" / (Decimal("49.50"), None) → 50·"보통" |
| `test_band_label_boundaries` | None·0·19·20·39·40·59·60·79·80·100 → 데이터 부족·매우 낮음·매우 낮음·낮음·낮음·보통·보통·높음·높음·매우 높음·매우 높음 |
| `test_compute_condition_without_sentiment` | (None, 0.0) → score None·"데이터 부족"·sector_flow 50.00 |
| `test_sector_flow_sql_median_sample_and_exclusions` | 아래 픽스처 → `sector_r5 == 0.005`, `n == 6`, `ref_date == 기준일` |
| `test_sector_flow_sql_falls_back_to_previous_day` | 기준일 일봉이 있는 표본이 4개뿐 → `ref_date`가 전 거래일 |
| `test_get_condition_without_sector_uses_market_only` | sector None → score = 시장 심리 반올림, sector 필드 null·0 |
| `test_get_condition_small_sector_uses_market_only` | 표본 3개 → `sector_name` 있음, `sector_flow` null, `sector_sample` 3 |
| `test_get_condition_stale_sentiment_is_insufficient` | 심리 거래일이 기준일보다 10거래일 전 → score None, `sentiment`는 있음 |
| `test_get_condition_never_raises` | `read_sector_flow`를 예외로 바꿔도 `empty_condition` 모양 반환 |

픽스처: KR 종목 101~106 `sector='반도체·전자'`(101~103 `featured`, 104~106 `benchmark`), 기준일까지 6거래일 일봉. 5일 수익률 −0.05, −0.02, 0.00, 0.01, 0.03, 0.04 → 중앙값 0.005. 제외 확인: 107 `listed`(+0.50), 108 `featured`인데 기준일 일봉 없음, 미국 109 같은 섹터 이름. 기준일은 `read_sector_flow(conn, "KR", "반도체·전자", 기준일)`로 직접 넘겨요. 각 테스트 시작에 `clear_cache()`.

#### `backend/tests/test_stocks_api.py`

`test_stock_detail_includes_market_condition` — `GET /api/v1/stocks/KOSPI/005930`에 `market_condition`이 있고 키 집합이 정확히 `{"score","label","sentiment","sector_name","sector_flow","sector_sample","sector_as_of","index_code","stock_r5","sector_r5","index_r5","as_of"}`, `index_code == "KOSPI"`. 시장 심리 행이 없으면 `score is None`·`"데이터 부족"`. `market_sentiment_daily`에 (KR, 기준일, 62.00, '탐욕', formula_version 1)을 넣고 다시 부르면 `score == 62`, `label == "높음"`(픽스처 종목 sector NULL → 시장만). 응답에 최상위 `sector` 키가 없는지도 확인해요.

### 5-11. 완료 기준

1. `pytest -q` 전부 통과
2. 개발 DB에서 같은 섹터 종목들의 `sector_flow`·`sector_sample`이 같은지, `sentiment`가 홈 시장 심리 카드 값과 같은지
3. 금융 종목에서 `섹터 분류가 없어 시장 심리만 반영했습니다`
4. 시안 배치, 390px 세로 쌓임·가로 스크롤 없음, 콘솔 에러 0
5. 상세 응답 시간이 눈에 띄게 늘지 않음(캐시 적중 시 쿼리 3개: 심리·종목 r5·지수 r5)
6. `docs/06`(상세 응답 필드·예시), `docs/09`(시장·섹터 점수 절 — 매력도와 별개, 계산식, 미반영 조건) 갱신

---

## 6. 4-1 — 한국 재무 일괄 첫 적재 + 공시 기준점 증분

### 6-1. DB — `backend/db/migrations/008_ingest_cursor.sql`

```sql
-- =====================================================================
-- 공시 목록 증분 수집 기준점 — 멱등.
-- 새로 만드는 DB는 schema.sql에 반영되어 있다.
-- 실행: python -m app.ingest migrate 008_ingest_cursor
-- =====================================================================

-- 소스별 마지막으로 처리한 접수번호. 모두 성공한 뒤에만 옮긴다(중간 실패 시 다음 실행이 같은 지점부터)
CREATE TABLE IF NOT EXISTS ingest_cursor (
  source        VARCHAR(20)  PRIMARY KEY,                    -- 'DART_A001' (DART 사업보고서 목록)
  last_rcept_no CHAR(14)     NOT NULL CHECK (last_rcept_no ~ '^[0-9]{14}$'),
  last_rcept_dt DATE         NOT NULL,
  updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);
```

같은 블록을 `schema.sql`에 넣고 `tests/conftest.py`의 `TABLES` 맨 앞에 `"ingest_cursor"`를 추가해요. `ingestion_logs.job_type` CHECK는 바꾸지 않아요(기존 `FINANCIALS`·`DISCLOSURES`로 기록).

### 6-2. `backend/app/services/freshness.py`

```python
def expire_financials(conn: Connection, stock_ids: list[int], now: datetime | None = None) -> int:
    """새 사업보고서가 확인된 종목의 재무 유효기간을 지금 끝낸다. 기록이 없거나 이미 지난 종목은 그대로. 반환: 바꾼 행 수."""
```

```sql
UPDATE data_freshness SET valid_until = fetched_at
WHERE kind = 'financials' AND stock_id = ANY(:ids) AND valid_until > :now
```

### 6-3. `backend/app/providers/dart.py` · `factory.py` · `tests/fakes.py`

```python
@dataclass(frozen=True)
class FiledReport:
    rcept_no: str                   # 접수번호 14자리 (YYYYMMDD + 일련번호) — 문자열 크기 비교가 시간 순서
    rcept_dt: date
    corp_code: str
    stock_code: str | None          # 비상장이면 None (빈 문자열 → None)
    report_nm: str                  # 공백을 한 칸으로 정리한 제목. 정정은 "[기재정정]사업보고서 (2025.12)" 형태


class DartClient:
    def list_annual_reports(self, start: date, end: date, page_no: int = 1) -> tuple[list[FiledReport], int]:
        """회사 지정 없이 사업보고서(A001) 목록 한 페이지(100건). 정정·첨부 공시 포함. 반환: (목록, total_page).
        status 013(데이터 없음)이면 ([], 0). start~end는 90일 이하로 부른다(초과는 호출 측이 나눔).
        정렬은 접수번호 순이 보장되지 않는다 — 호출 측은 기간 안 전체 페이지를 받는다."""
```

요청: `list.json`, `bgn_de`, `end_de`(YYYYMMDD), `pblntf_ty="A"`, `pblntf_detail_ty="A001"`, `sort="date"`, `sort_mth="desc"`, `page_no`, `page_count=100`. `_get`을 거쳐 `_limiter`·`_throttle`이 그대로 걸려요.

- `factory.py`: `Providers`에 `kr_feed: DartClient | None = None`, `default_providers()`에서 DART 키가 있으면 재무용과 **같은** `DartClient` 인스턴스.
- `fakes.py`: `FakeDartFeed(CallLog)` — `__init__(self, pages: list[tuple[list[FiledReport], int]], fail_on: int | None = None)`, 호출 순서대로 페이지를 돌려주고 `fail_on`번째 호출에서 `ProviderError`. `make_providers(..., kr_feed=None)` 키워드 추가.

### 6-4. `backend/app/ingest/jobs.py` — 공시 증분

```python
FEED_SOURCE = "DART_A001"      # ingest_cursor.source
FEED_OVERLAP_DAYS = 2          # 기준점 날짜보다 이만큼 앞부터 다시 받는다(늦게 반영되는 공시)
FEED_WINDOW_DAYS = 90          # 회사 지정 없는 list.json 조회 기간 상한
FEED_FIRST_DAYS = 7            # 기준점이 없을 때 처음 받는 기간


def load_dart_feed(engine: Engine, providers: Providers, *, today: date | None = None) -> dict:
    """새 사업보고서(정정 포함)를 낸 DB 종목의 재무 유효기간을 끝내고 공시 행을 넣는다. 기준점은 모두 성공한 뒤에만 옮긴다.
    반환: {"status": "SUCCESS"|"FAILED"|"SKIPPED", "pages", "filings", "matched", "expired", "cursor"}"""
```

**실제 API 확인 (2026-10-19)**: 회사 지정이 없으면 조회 기간이 3개월을 넘을 때 status 100("검색기간은 3개월만 가능")이고, `page_count`는 100이 상한이에요. 2026년 3월 한 달 사업보고서 목록은 3,634건(37페이지)이었고, `sort=date&sort_mth=desc`여도 **접수번호 순이 아니에요**(`[첨부추가]`·`[첨부정정]` 공시가 맨 앞에 섞여 날짜가 63번 뒤바뀜). A001 목록에 반기보고서도 섞여 나와요. 그래서 처음 정한 "기준점 이하 번호가 나오면 멈춤"을 버리고 **기간 안 전체 페이지를 받아요**(하루 구간이라 실적 시즌에도 하루 5~10페이지).

동작:

1. `providers.kr_feed`가 None이면 `{"status": "SKIPPED", "pages": 0, "filings": 0, "matched": 0, "expired": 0, "cursor": None}`.
2. `today = today or 서울 날짜`. 기준점 행이 있으면 `last_no, start = last_rcept_no, last_rcept_dt − FEED_OVERLAP_DAYS`, 없으면 `"00000000000000"`, `today − FEED_FIRST_DAYS`.
3. `job_log(engine, source="DART", job_type="DISCLOSURES", label="feed A001")` 안에서 4~8(예외는 FAILED 기록 → 반환 `"FAILED"`, 기준점 그대로).
4. `[start, today]`를 `FEED_WINDOW_DAYS`일씩 나눠 **오래된 구간부터**. 구간마다 `page = 1`부터 `page >= total_page`까지 전부: `LockSession`의 `hold(DART_LOCK_KEY)` 안에서 `list_annual_reports` → `rcept_no > last_no`인 것을 모으기(`rcept_no`로 중복 제거).
5. `"사업보고서" in report_nm`이고 `[첨부추가]`·`[첨부정정]`으로 시작하지 않는 것만 남겨요(`FEED_SKIP_PREFIXES` — 첨부 서류만 바뀌어 재무 수치는 그대로). 기준점은 첨부 공시까지 포함한 가장 큰 접수번호로 옮겨요.
6. `SELECT stock_id, corp_code FROM stocks WHERE corp_code = ANY(:codes) AND is_active`로 DB 종목만.
7. 한 트랜잭션: `disclosures` upsert(`title=report_nm, report_type="정기공시", filed_at=rcept_dt 00:00 서울, url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}", data_source="DART"`, 충돌 키 `["rcept_no"]`) → `expired = freshness.expire_financials(conn, 종목들)` → 기준점 upsert(모은 것이 있으면 가장 큰 `rcept_no`·그 날짜, 없고 행도 없으면 `(f"{start:%Y%m%d}000000", start)`, 없고 행이 있으면 그대로).
8. `res.rows = 고른 공시 수`, 비고 `pages=… filings=… matched=… expired=…`.

#### `_fetch_financials` 빈 응답 규칙

`get_annual_financials`가 빈 목록이면 잠금 블록 바로 다음에 `raise ProviderError("재무 빈 응답")`. 공시 직후 재무 API가 비어 있을 때 최신으로 기록하지 않고 1일 뒤 다시 받으려는 거예요. 빈 응답을 SUCCESS로 기대하던 테스트가 있으면 같이 고쳐요.

### 6-5. `backend/app/ingest/benchmark.py` — `run_benchmark`

`job_log` 블록 안, 선정(`selection_due`) 바로 **앞**에:

```python
            try:                              # 새 사업보고서를 낸 종목의 재무를 먼저 만료시킨다 → 아래 재무 갱신 대상
                out["feed"] = jobs.load_dart_feed(engine, providers, today=today)
            except Exception as e:  # noqa: BLE001 — 실패 사유는 load_dart_feed의 ingestion_logs 행에 남는다
                res.notes.append(f"공시 증분 실패: {e}")
```

### 6-6. `backend/app/ingest/dart_bulk.py` (새) — 첫 적재 (개발 PC, API 호출 없음)

```python
"""OpenDART 재무정보 일괄다운로드(사업보고서) txt → financial_statements. 개발 PC에서 한 번 돌리는 첫 적재 (D10).

계정 규칙은 DART API 적재와 같다: ACCOUNT_MAP(account_id 후보 → account_nm 후보), 연결 우선 → 별도.
"""
ENCODING = "cp949"
REQUIRED_COLUMNS: tuple[str, ...] = ("재무제표종류", "종목코드", "결산기준일", "보고서종류", "항목코드", "항목명", "당기")


@dataclass(frozen=True)
class BulkRow:
    stock_code: str                 # "005930" (괄호 제거)
    period_end: date                # 결산기준일
    consolidated: bool              # 연결재무제표면 True
    statement: str                  # "BS" / "IS" / "CIS"
    account_id: str                 # 항목코드
    account_nm: str                 # 항목명
    amount: Decimal | None          # 당기 금액(쉼표 제거). 빈 칸이면 None


def parse_file(path: Path) -> list[BulkRow]:
    """헤더 이름으로 열을 찾는다. REQUIRED_COLUMNS 중 없는 열이 있으면 ValueError(없는 열 이름 목록)."""


def to_financials(rows: list[BulkRow]) -> dict[str, list[Financial]]:
    """종목코드 → FY 재무 목록(결산일 오름차순). 회사·결산일마다 연결이 있으면 연결만, 없으면 별도만.
    data_source="DART", accounting_std="K-IFRS", period_type="FY", 별도면 notes=["fs_div=OFS"]."""


def load_bulk(engine: Engine, paths: list[Path], *, as_of: date, years: int = 4) -> dict:
    """DB 종목(stocks.ticker, 국내 시장)에 맞는 회사만 최근 years개 FY를 upsert. 회사마다 freshness 기록(BatchWriter).
    기준점: ingest_cursor(DART_A001)가 없거나 last_rcept_dt < as_of이면 (f"{as_of:%Y%m%d}000000", as_of).
    로그: ingestion_logs 1행(source="DART_BULK", job_type="FINANCIALS", label=f"bulk {as_of}").
    반환: {"files", "companies", "rows", "skipped"}"""
```

`source="DART_BULK"`: 7절 하루 예산은 `source='DART'` 행만 세서 일괄 적재가 예산을 먹지 않아요.

CLI(`backend/app/ingest/__main__.py`):

```
python -m app.ingest dart-feed
python -m app.ingest dart-bulk --as-of 2026-10-15 --years 4 FILE [FILE ...]
```

**확인 결과 (2026-10-19, 2023~2025 사업보고서 파일)**

| 항목 | 확인한 것 |
| --- | --- |
| 받는 곳 | 공시정보 활용마당 > 재무정보 일괄다운로드. 연도별 사업보고서(4Q) BS·PL·CF·CE zip. **스크립트로 직접 요청하면 오류 페이지**가 와서 브라우저(또는 Playwright)로 받아요. 파일 이름 예: `2025_4Q_BS_20261008030335.zip`(끝 숫자 = 생성 시각) |
| zip 안 | cp949 탭 구분 txt 여러 개 — 일반·금융기타·보험·은행·증권 × 별도·연결. 손익은 `02_손익계산서`와 `03_포괄손익계산서`(대부분 회사가 '단일 포괄손익계산서'로 냄) 둘 다 필요해요. 그래서 BS zip과 PL zip을 함께 넘겨요 |
| 열 | 재무제표종류 · 종목코드(`[005930]`) · 회사명 · 시장구분 · 업종 · 업종명 · 결산월 · 결산기준일 · 보고서종류 · 통화 · 항목코드 · 항목명 · 당기 · 전기 · 전전기. **손익 파일은 이름 없는 빈 열이 끼어 '당기' 위치가 달라** 헤더 이름으로 찾아요. 금액은 쉼표, 값 없음은 빈 칸이나 `-` |
| 연결/별도 | 재무제표종류 끝이 `- 연결`/`- 별도` (파일 이름에도 `_연결`) |
| statement | 재무제표종류가 `재무상태표`로 시작 → BS, `포괄손익계산서` 포함 → CIS, 그 밖의 `손익계산서` → IS |
| API 대조 | 개발 DB 국내 70종목 × FY2023·2024·2025 × 6개 항목이 API 적재 값과 **전부 같아요**(`DartClient._extract`를 그대로 써서 계정 규칙이 같음) |
| 크기 | 2025 BS 6.7MB·PL 3.8MB(zip), 2,844개 회사. 개발 DB 적재 뒤 20MB(국내 70개 회사 210행 — listed 종목이 들어오면 회사 약 2,500개 × 연도 수) |

`load_bulk`는 정의서 초안의 `BatchWriter` 대신 200개 회사씩 한 트랜잭션으로 넣고 `ingestion_logs`는 요약 1행만 남겨요(회사마다 로그를 남기면 수천 행이 쌓여서).

### 6-7. 테스트

| 파일 | 테스트 이름 | 확인하는 것 |
| --- | --- | --- |
| `test_dart_feed.py` | `test_feed_expires_only_db_stocks_and_moves_cursor` | 목록 3건(DB 종목 1·DB에 없는 회사 1·사업보고서 아닌 제목 1) → 공시 1행, 만료 1, 기준점 = 가장 큰 rcept_no |
| | `test_feed_reads_every_page_even_when_order_is_mixed` | 1페이지에 기준점 이하 번호만 있어도 2페이지까지 받아 새 공시를 찾음 |
| | `test_feed_skips_attachment_only_filings` | `[첨부추가]`는 만료 대상에서 빠지고 `[기재정정]`은 만료, 기준점은 둘 중 큰 번호 |
| | `test_feed_failure_keeps_cursor` | 2번째 호출 실패 → `"FAILED"`, 기준점 그대로, 공시 0행 |
| | `test_feed_splits_long_gap_into_90_day_windows` | 기준점 200일 전 → 구간 3개(오래된 순) |
| | `test_feed_first_run_starts_7_days_back` | 기준점 없음 → `start = today − 7` |
| | `test_empty_financials_are_failed` | 빈 재무 → FAILED, freshness FAILED |
| `test_dart_bulk.py` | `test_parse_requires_columns` | 열 하나 빠진 파일 → ValueError에 열 이름 |
| | `test_consolidated_preferred_over_separate` | 연결·별도 → 연결 값 |
| | `test_load_bulk_is_idempotent_and_seeds_cursor` | 두 번 적재해도 행 수 그대로, 기준점 `as_of` |

테스트용 txt는 `backend/tests/data/dart_bulk_sample_*.txt`(cp949, 확인한 헤더 그대로 5~10행).

---

## 7. 4-3 — 우선순위 백그라운드 적재와 하루 예산

### 7-1. 설정 — `universe.yaml`

```yaml
# 백그라운드 재무 적재(상장 목록 종목을 우선순위대로 미리 받기). 단위: ingestion_logs 행 수(회사 1건 = 1행 ≈ 호출 2~5번)
background:
  dart_calls_per_day: 2000   # 오늘(서울 0시부터) source='DART' 재무·공시 행이 이 수에 닿으면 멈춤 (D12 권하는 시작값)
  sec_calls_per_day: 1000    # source='SEC' 같은 기준
  run_at_kst: "08:00"        # 07:00 비교군 갱신 뒤
```

### 7-2. `backend/app/ingest/background.py` (새)

```python
def used_today(conn: Connection, source: str, now: datetime | None = None) -> int:
    """오늘(서울 0시 이후) ingestion_logs에서 source가 같고 job_type IN ('FINANCIALS','DISCLOSURES')인 행 수."""


def priority_queue(conn: Connection, country: str, limit: int, ranking: dict[str, tuple[Decimal, Decimal]]) -> list[int]:
    """재무 기록(data_freshness kind='financials')이 없는 활성 listed 종목(corp_code·CIK가 있는 것)을 순위대로 limit개.
    ranking: 티커 → (거래대금, 시가총액). 순위에 없는 종목은 맨 뒤(종목 id 순)."""


def run_background(engine: Engine, providers: Providers, *, now: datetime | None = None) -> dict | None:
    """국가마다 남은 예산 = calls_per_day − used_today. 0보다 크면 priority_queue(…, 남은 예산)를
    jobs.load_financials(stock_ids=…, years=benchmark fin_years)로 받는다. 다른 프로세스가 실행 중이면 None.
    반환: {"KR": {"budget", "used", "queued", "statuses"}, "US": {...}}"""
```

- 잠금: `BACKGROUND_LOCK_KEY = 7_301_013`(`wait=False` — 겹치면 건너뜀). 예산이 남지 않으면 순위 조회도 하지 않아요(외부 호출 0).
- 로그: `job_log(source="INTERNAL", job_type="BENCHMARK", label="background")` 1행, 비고는 `백그라운드:`로 시작해요. 스케줄러는 비교군 성공을 `일일:` 비고로만 세서 둘이 섞이지 않아요.
- 스케줄러: `services/scheduler.py`의 `tick`에서 비교군 다음으로 `run_at_kst`(08:00) 이후 하루 1회(`last_background_success`). CLI `python -m app.ingest background`.
- **미국(D11 확정 2026-10-19)**: `rank_us`가 SEC 발행주식수(frames) × 최근 종가(DB, 없으면 yfinance 묶음)로 시가총액을 구해 상위 `us_rank_pool`(1,500)개에 `stocks.cap_rank`(migration 009)를 매겨요. `us_rank_days`(30일)마다만 다시 매기고, 큐는 순위가 있는 listed만 순위대로(`ranked_only`).
  - 측정: 발행주식수 2.1초(5,118개) + 종가 묶음 91~123초(5,641/5,646개) → 1,500위 매김. 상위: NVDA·AAPL·GOOGL·GOOG·MSFT·AMZN…
  - 버린 대안: frames `dei/EntityPublicFloat`(1회 호출) — 값 단위가 회사마다 달라(1위가 Universal Display 6.8조 달러) 쓸 수 없고 listed 5,646개 중 3,387개만 있어요
  - 한계: ADR(TM·ONC 등)은 발행주식수가 원주 기준이라 순위가 부풀어요. 20-F 회사는 US-GAAP 재무가 없어 첫 시도에서 FAILED가 되고, 기록이 생겨 다음 큐에서 빠져요(매일 재시도하지 않음)
- 개발 DB 확인(2026-10-19): `listing` 뒤 국내 listed 2,509개(corp_code 전부), 예산을 5로 잡아 실행 → 거래대금 상위 5개 SUCCESS.

| 우선순위 | 국내 (KR) | 미국 (US) |
| --- | --- | --- |
| 1 | 거래대금(종가 × 거래량) — `providers.kr_bulk.get_bars_by_date(jobs.last_closed_day("KR"))` 1회 호출 | D11 |
| 2 (같은 값) | 시가총액 | — |

큐는 테이블 없이 매번 쿼리로 만들어요. 받은 종목은 freshness 기록이 생겨 다음 큐에서 빠지고, 이후에는 6절 공시 증분으로만 갱신돼요.

### 7-3. 테스트 (`test_background.py`)

| 테스트 이름 | 확인하는 것 |
| --- | --- |
| `test_used_today_counts_only_today_and_source` | 어제 행·다른 source 행은 세지 않음 |
| `test_queue_skips_stocks_with_freshness` | 기록 있는 listed·비활성·featured는 큐에 없음 |
| `test_budget_stops_background` | 예산 5, 오늘 사용 3 → 2개만 받음 |
| `test_kr_queue_orders_by_trading_value_then_cap` | 거래대금 같으면 시가총액 순, 순위에 없는 종목은 맨 뒤 |
| `test_no_budget_left_makes_no_external_calls` | 예산을 다 쓰면 순위 조회·재무 호출 0 |

---

## 8. 4-2 — 미국 재무 일괄 수집 (D8 결정 뒤)

지금 정하는 것은 인터페이스뿐이에요. 방식은 smoke 결과로 정하고 이 절을 채워요.

```python
# backend/app/providers/sec_bulk.py (새) — 방식과 상관없이 이 시그니처를 지킨다
def get_annual_financials_bulk(ciks: set[str], years: int) -> dict[str, list[Financial]]:
    """CIK → FY 재무 목록(결산일 오름차순). sec.py get_annual_financials와 같은 태그 대체 규칙·같은 Financial 모양.
    data_source="SEC". 받지 못한 CIK는 결과에 없음."""
```

- `jobs.merge_supplement`(yfinance 보완) 규칙은 그대로.
- smoke 비교 기준: 받는 크기, 최대 메모리(Cloud Run 1~2GiB), 태그 대체 규칙을 옮길 수 있는지, 호출 수. 결과는 `docs/smoke_test_result.md`.
- 적재는 `BatchWriter`(4-2절), 잠금은 `SEC_LOCK_KEY`를 파일 받는 동안 1회.

---

## 9. 4-4 — 노출 종목 확장 (D5 결정 뒤)

### 9-1. `GET /stocks` — `sector` 필터

| 파라미터 | 타입 | 규칙 |
| --- | --- | --- |
| `sector` | string, 선택, 1~32자 | `stocks.sector`와 정확히 일치. `universe.yaml`의 `sectors[].name`(점수 섹터 9개) 밖이면 422 `VALIDATION_ERROR` |

- 기존 파라미터와 AND. `total`은 필터 뒤 개수.
- `StockRow`에 `sector: str | None`(마지막 필드), `stock_list.sql`에 `s.sector` + `AND (CAST(:sector AS text) IS NULL OR s.sector = :sector)`.

### 9-2. 화면 (`stocks.js`)

- 페이지 나누기: `limit=25`, `offset`, `total`로 페이지 수. URL `?page=`로 새로고침해도 유지.
- 필터: 국가 탭(기존) + 섹터 선택(9개 + "전체"). 섹터 목록은 화면 상수 — 이름은 `universe.yaml sectors[].name`과 같아야 해요.

### 9-3. 노출 규칙

D5 수치가 나오면 `universe.yaml stocks` 확장 또는 "노출 = 시가총액 상위 N" 중 하나를 정해 이 절에 적어요. 영향: `peer_groups`(테마), 첫 적재 시간, DB 용량(무료 500MB).

---

## 10. 결정이 더 필요한 것

| # | 질문 | 권하는 답 | 왜 |
| --- | --- | --- | --- |
| D11 | 미국 listed 우선순위 소스 | **확정**: 상위 1,500개 안에서 시가총액(SEC 발행주식수 × 종가) 순, 30일마다 `stocks.cap_rank`에 저장(migration 009) | 7-2 측정 — 전 종목 종가 묶음 조회 약 2분이라 매일 하지 않아요 |
| D12 | 백그라운드 하루 예산 값 | **확정(시작값)**: DART 2,000행 · SEC 1,000행, 첫 주 `ingestion_logs`로 조정 | DART 키 1개 하루 약 2만 번 중 절반 이하(행당 2~5번) |
| D5 | 노출 종목 수 | 4-1 뒤 측정 | — |
| D8 | 미국 일괄 방식 | smoke 뒤 | — |

---

## 11. 계획 문서에 없던 세부를 이 문서가 정한 것

계획의 결정(D1~D10)은 그대로예요. 아래는 구현 가능하게 정한 세부예요. 다르게 하고 싶으면 여기서 고쳐요.

| # | 항목 | 정한 것 | 이유 |
| --- | --- | --- | --- |
| 1 | 0단계 | 점수 SQL 대상 필터 + 시장 심리 정기 저장 | 지금 코드에서 참고 점수·유니버스가 틀리고, 시장·섹터 점수가 홈 방문에 기대요 |
| 2 | `market_condition` 필드 | 계획 9개 + `sector_sample`·`sector_as_of`·`index_code` | 표본 부족 문장·툴팁(지수 이름, 섹터 날짜)에 필요 |
| 3 | 섹터 기준일 | "표본 5개 이상이 일봉을 가진 가장 최근 날짜(ref_date)" | 비교군 일봉이 07:00에만 들어와서, 마감 거래일로 고정하면 저녁~아침에 섹터가 빠져요 |
| 4 | 캐시 | 1시간 + 표본 5개 이상일 때만 저장 | 07:00 일봉이 들어와도 하루 내내 옛 값이 남는 문제 |
| 5 | 시장 심리 오래됨 | 거래소 달력 거래일 수, 달력을 못 쓰면 달력일 7일 | 휴장일까지 정확히 세려고 |
| 6 | 표본 부족 문구 | `섹터 표본이 적어 시장 심리만 반영했습니다` | 계획은 섹터 없음 문구(D9)만 있었어요 |
| 7 | 섹터 미반영 툴팁 마지막 줄 | `시장 심리 100%(섹터 미반영), 투자 권유 아님` | 비중이 실제와 다르게 보이지 않게 |
| 8 | 점수 반올림 | HALF_UP 정수 | `round`는 50.5 → 50 |
| 9 | 섹터를 상세 응답에 내는 법 | `stock_detail.sql`에만 `s.sector`, 응답은 `market_condition.sector_name` | 같은 값을 두 곳에 내지 않으려고 |
| 10 | FY 기준 표기 위치 | `attractiveness.fin_basis` + '계산 근거' 안 한 줄 | 저장된 `data_quality`에 넣으면 지난 점수까지 다시 계산해야 해요 |
| 11 | 백그라운드 예산 단위 | "ingestion_logs 행 수" | 계획이 "DART 행 수로 계산" |
| 12 | 일괄 적재 로그 source | `DART_BULK` | 예산 계산에서 빼려고 |
| 13 | 공시 증분 로그 | 새 job_type 없이 `DISCLOSURES`/`label="feed A001"` | CHECK 변경(마이그레이션)을 피하려고 |
| 14 | 재무·공시 freshness 실패 사유 | 고정 문구·NULL → 실제 사유 | 묶음 저장 실패와 수집 실패를 구분하려고 |
| 15 | `_load_valuation_base` | 삭제(`fundamental_bases` 행 + `on_flush`로 이동) | 묶음 저장과 "재무 저장 뒤 파생" 순서를 지키려고 |
| 16 | 공시 증분 위치 | `run_benchmark`의 선정 단계 앞 | 지금 `run_benchmark`에 상장 목록 동기화가 없어요 |
| 17 | 첫 실행 공시 증분 범위 | 기준점 없으면 7일 전부터, 일괄 적재가 기준점을 `as_of`로 심음 | 일괄 적재와 증분 사이 빈틈이 없게 |
