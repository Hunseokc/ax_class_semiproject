# 추가 기능 API·계약 정의서

`04_기능구현_계획.md`(결정 D1~D10, 2026-10-16)를 코드 수준의 약속으로 옮긴 문서예요. 두 곳에서 써요.

1. **원본(이 저장소)** — 계획의 1~4단계를 구현할 때 이 문서의 이름·시그니처·SQL·응답 모양을 그대로 따라요.
2. **팀 저장소(ax_stockmind)** — 원본에 구현이 끝나면 D가 이 문서로 `team/prompts/stage7.md`·`stage8.md`와 `team/contracts/stage7.toml`·`stage8.toml`을 만들어요. A·B·C의 Claude는 이 문서의 "약속"을 원본과 함께 정답으로 삼아요.

이 문서가 정하지 않은 것(배치·색·간격·문구 일부)은 CLAUDE.md 1절의 **표현**이라 담당자가 정해도 돼요. 이 문서에 코드 블록·표로 적힌 이름·인자·반환값·필드·SQL 파라미터·결과 열·상수 값·파일 경로·문구(따옴표로 적은 것)는 **약속**이라 바꾸면 안 돼요.

---

## 0. 읽는 법

### 0-1. 계획 단계 ↔ 팀 단계

| 계획 단계 (`04_기능구현_계획.md`) | 팀 단계 | 이 문서 절 | 상태 |
| --- | --- | --- | --- |
| 1단계 안정성 팩터 개편 | Stage 7 — 파트 7-1 | 3절 | 전부 확정 |
| 2단계 실적 시즌 부하 분산 | Stage 7 — 파트 7-2 | 4절 | 전부 확정 (D4 값은 임시 100) |
| 3단계 시장·섹터 점수 | Stage 7 — 파트 7-3 | 5절 | 전부 확정 |
| 4-1 한국 재무 일괄·증분 | Stage 8 — 파트 8-1 | 6절 | 계약 확정, 일괄 파일 열 이름은 확인 뒤 채움 (6-1-6) |
| 4-3 우선순위 큐·하루 예산 | Stage 8 — 파트 8-2 | 7절 | 계약 확정, 미국 순위 소스는 결정 필요 (D11) |
| 4-2 미국 재무 일괄 | Stage 8 — 파트 8-3 | 8절 | **D8 결정 뒤 착수** — 인터페이스만 확정 |
| 4-4 노출 종목 확장 | Stage 8 — 파트 8-4 | 9절 | **D5 결정 뒤 착수** — API 필터 계약만 확정 |
| 5절 별도 트랙(KIS·Cloud Run) | 이 문서 범위 밖 | — | — |

Stage 7은 Stage 6(v6.0, 원본과 diff 0) 위에서 시작해요. Stage 8은 Stage 7(v7.0)이 `main`에 들어간 뒤 시작해요(계획 "2단계 잠금 구조가 먼저").

### 0-2. 표기 규칙

| 표기 | 뜻 |
| --- | --- |
| `Num` | `app/schemas/common.py`의 `Num`(Decimal을 JSON 숫자로). 계산은 `Decimal`, 응답은 숫자 |
| 비율 | 소수(0.0523 = 5.23%). 화면에서 `pct()`로 % 표시 |
| `HALF_UP` | `Decimal.quantize(..., rounding=ROUND_HALF_UP)`. 파이썬 `round()`(짝수 반올림)를 쓰지 않아요 |
| 날짜 | `date`는 `"YYYY-MM-DD"`, 시각은 ISO 8601(UTC 또는 오프셋 포함) |
| **[D 선행]** | 단계 시작 전에 D가 `stage{N}`에 먼저 넣는 것. 다른 사람은 ✅ 있음으로 써요 |
| **[껍데기]** | D가 이름·인자·응답 모양만 갖춰 예시 값으로 넣어 둔 것. 위에 `TODO(껍데기): {담당} — {무엇}` 주석. 담당자가 본문만 교체 |
| `[S7-B]` | 공유 파일 안의 구역 주석 `# ── [S7-B] {기능} ──` (JS는 `// ── [S7-A] … ──`). 그 구역 아래에만 추가 |

### 0-3. 모든 단계 공통 약속 (기존 규칙 재확인)

- 에러 응답은 `{"error": {"code", "message", "detail"}}`. **이 문서의 기능은 새 에러 코드를 만들지 않아요.** 계산할 수 없으면 에러 대신 값 `null` + 라벨 `"데이터 부족"`으로 돌려줘요.
- 조회 API(`GET`)는 외부 소스를 부르지 않아요(DB만). 외부 호출은 `app/ingest/*`·갱신 서비스만.
- 조회 경로에서 DB에 쓰지 않아요. 예외: 기존 `/home/sentiment`의 `ensure_sentiment`(그대로 둠).
- 새 테이블·열·CHECK 변경은 마이그레이션 파일(`backend/db/migrations/NNN_*.sql`, 멱등) + `schema.sql` 반영을 **D만** 해요.
- 커밋은 파일 하나(또는 파일 + 짝 테스트) 단위, 메시지 `feat(scope): 한국어 요약`.
- 테스트는 `docker compose run --rm api pytest -q`가 전부 통과해야 PR을 넘길 수 있어요.

---

## 1. 담당과 파일 소유 (충돌 없이 합치기 위한 표)

한 파일의 같은 함수를 두 사람이 고치지 않도록 나눴어요. 이 표에 없는 파일은 고치지 않아요(필요하면 요청 메모).

### 1-1. Stage 7

| 파일 | 담당 | 파트 | 무엇을 |
| --- | --- | --- | --- |
| `backend/app/ingest/store.py` | D | 7-2 [D 선행] | `SEC_LOCK_KEY`·`provider_lock_key`·`error_text`·`LockSession`·`Unit`·`BatchWriter`·`write_logs`·`default_flush_every` |
| `backend/app/services/freshness.py` | D | 7-2 [D 선행] | `due(..., limit=)` |
| `backend/app/services/market_calendar.py` | D | 7-3 [D 선행] | `sessions_between` |
| `backend/config/universe.yaml` | D | 7-2 [D 선행] | `benchmark.fin_daily_budget`, `ingest.flush_every` |
| `backend/app/schemas/api.py` | D | 7-3 [D 선행] | `MarketConditionOut`, `StockDetailOut.market_condition` |
| `backend/app/api/stocks.py` | D | 7-3 [D 선행] | `stock_detail`에 `market_condition` 연결 (본문은 C의 서비스) |
| `backend/app/services/market_condition.py` | D → C | 7-3 | D가 [껍데기]로 만들고 C가 본문 교체 |
| `backend/app/api/analysis.py` (`ScoreOut.fin_basis`·`FinBasisOut`) | D → B | 7-2 | D가 필드·[껍데기] 예시 값, B가 실제 값으로 교체 |
| `backend/app/services/data_quality.py` (`fiscal_year_mix`) | D → C | 7-2 | D가 [껍데기], C가 본문 |
| `backend/app/ingest/benchmark.py` (`load_benchmark`) | D | 7-2 | 하루 재무 예산 적용 |
| `backend/tests/test_store_batch.py` (새) | D | 7-2 | store 계약 테스트 |
| `docs/06_기능_API_정의서.md` | D | 7-3 | 응답 필드·예시 |
| `backend/app/services/scoring.py` | C | 7-1 | `METRICS` |
| `backend/app/queries/score_metrics.sql`·`score_neutralize.sql`·`score_zscore.sql` | C | 7-1 | 낙폭·안정성 중립화 끄기·주석 |
| `backend/tests/test_scoring.py` | C | 7-1 | 기대값·새 테스트 2개 |
| `docs/09_매력도_점수_정의서.md` | C | 7-1·7-3 | 지표 표·중립화 범위·재계산 결과·시장·섹터 점수 절 |
| `backend/app/services/sentiment.py` | C | 7-3 | `_latest_stored` → `latest_stored` (이름만) |
| `backend/app/queries/sector_flow.sql` (새) | C | 7-3 | 섹터 흐름 SQL |
| `backend/app/queries/fin_basis.sql` (새) | C | 7-2 | FY 기준 연도별 종목 수 |
| `backend/tests/test_market_condition.py` (새) | C | 7-3 | 순수 계산·SQL·서비스 |
| `backend/tests/test_data_quality.py` | C | 7-2 | `fiscal_year_mix` 테스트 추가 |
| `backend/app/ingest/jobs.py` (`load_financials`·`_load_financials`·`load_disclosures`·`_load_disclosures` + 새 `_fetch_financials`·`_fetch_disclosures`) | B | 7-2 | 회사 단위 잠금 + 묶음 저장 |
| `backend/app/providers/dart.py` (`_limiter`) | B | 7-2 | `WindowLimiter(45, 60.0)` |
| `backend/app/api/analysis.py` (`_attractiveness`), `backend/app/services/reference_score.py` | B | 7-2 | `fin_basis` 실제 값 |
| `backend/tests/fakes.py` | B | 7-2 | `[S7-B]` 구역: `FakeFinancial`·`FakeDisclosure`에 `delay` |
| `backend/tests/test_ingest_batch.py` (새) | B | 7-2 | 잠금·묶음 저장 통합 테스트 |
| `backend/tests/test_analysis.py` | B | 7-2 | `fin_basis` 테스트 추가 |
| `backend/tests/test_stocks_api.py` | B | 7-3 | 상세 응답 `market_condition` 테스트 추가 |
| `frontend/js/pages/stock.js` | A | 7-1·7-2·7-3 | 문구·낙폭 표기·게이지 2행·툴팁·FY 기준 줄 |
| `frontend/css/pages.css` | A | 7-3 | `[S7-A]` 구역 |

### 1-2. Stage 8

| 파일 | 담당 | 파트 | 무엇을 |
| --- | --- | --- | --- |
| `backend/db/migrations/008_ingest_cursor.sql` (새), `backend/db/schema.sql`, `backend/tests/conftest.py`(`TABLES`) | D | 8-1 [D 선행] | `ingest_cursor` |
| `backend/app/services/freshness.py` | D | 8-1 [D 선행] | `expire_financials` |
| `backend/app/ingest/benchmark.py` (`run_benchmark`) | D | 8-1 | 07:00 작업 앞에 공시 증분 |
| `backend/app/ingest/background.py` (새), `backend/config/universe.yaml`(`background`) | D | 8-2 | 우선순위 큐·예산 |
| `backend/app/ingest/__main__.py` | D(`background`) · B(`dart-feed`·`dart-bulk`) | 8-1·8-2 | 각자 구역 `[S8-D]`·`[S8-B]` |
| `backend/app/providers/dart.py` | B | 8-1 | `FiledReport`, `DartClient.list_annual_reports` |
| `backend/app/providers/factory.py` | B | 8-1 | `[S8-B]` 구역: `Providers.kr_feed` |
| `backend/app/ingest/jobs.py` (`load_dart_feed`, `_fetch_financials` 빈 응답 규칙) | B | 8-1 | 증분 |
| `backend/app/ingest/dart_bulk.py` (새) | B | 8-1 | 일괄 txt 적재 |
| `backend/tests/fakes.py` | B | 8-1 | `[S8-B]` 구역: `FakeDartFeed` |
| `backend/tests/test_dart_feed.py`·`test_dart_bulk.py` (새) | B | 8-1 | |
| `backend/tests/test_background.py` (새) | D | 8-2 | |
| 8-3·8-4 파일 | C·A·B | 8-3·8-4 | 결정 뒤 이 표에 추가 |

---

## 2. 엔드포인트 변경 요약 (docs/06에 반영할 목록)

새 엔드포인트는 없어요. 바뀌는 응답은 아래 셋이에요. 기존 필드는 이름·타입·의미가 그대로예요(7-1의 지표 이름 하나만 예외).

| Method | URL | 바뀌는 것 | 파트 |
| --- | --- | --- | --- |
| GET | `/stocks/{market}/{ticker}/analysis` | `attractiveness.metrics[]`의 `debt_ratio` 항목이 `max_drawdown` 항목으로 바뀜(같은 자리, 7번째). `attractiveness.fin_basis` 추가 | 7-1, 7-2 |
| GET | `/stocks/{market}/{ticker}` | `market_condition` 객체 추가(항상 있음, null 아님) | 7-3 |
| GET | `/stocks` | (Stage 8-4, D5 뒤) `sector` 쿼리 파라미터 추가 | 8-4 |

`analysis`의 `metrics`(수치 분석 지표 딕셔너리)에 있는 `debt_ratio`·`max_drawdown_1y`는 **그대로** 있어요. 바뀌는 건 매력도 계산 지표 목록(`attractiveness.metrics`)뿐이에요.

---

## 3. 파트 7-1 — 매력도 안정성 팩터 개편 (계획 1단계)

### 3-1. 바뀌는 약속

| 항목 | 전 | 후 |
| --- | --- | --- |
| 안정성 지표 | `debt_ratio`(부채비율, 방향 −1) + `volatility` | `max_drawdown`(1년 최대 낙폭, 방향 **+1**) + `volatility` |
| 안정성 섹터 중립화 | 함 | **안 함** (`z_adj = z_raw`) |
| 다른 팩터 중립화 | 함 | 그대로 함 |
| `attractiveness.metrics[]` 순서 | earnings_yield, book_yield, roe, operating_margin, revenue_yoy, eps_change_yield, **debt_ratio**, volatility, momentum | earnings_yield, book_yield, roe, operating_margin, revenue_yoy, eps_change_yield, **max_drawdown**, volatility, momentum |

바뀌지 않는 것: DB 스키마(`stock_metric_values.metric`은 VARCHAR라 새 이름이 그대로 들어감), 프리셋 가중치(`scoring.yaml`), 응답 모양(키·타입), 수집 코드, `analysis.metrics.debt_ratio`(투자 지표 상세의 부채비율), `reference_score.py`(METRICS를 그대로 따라감).

### 3-2. 파일별 명세 (C)

#### `backend/app/services/scoring.py`

`METRICS`에서 `debt_ratio` 한 줄을 아래 한 줄로 **같은 자리에서** 바꿔요. 순서가 API 응답 순서예요.

```python
    "max_drawdown":     Metric("safety", "1년 최대 낙폭", 1, "일봉 252개 미만"),
```

- 방향 +1인 이유: 낙폭은 음수(−0.391 = −39.1%)라 0에 가까울수록(값이 클수록) 좋아요.
- 결과로 `NEGATIVE_METRICS == ["volatility"]`가 돼요(코드는 그대로, 값만 바뀜).
- NULL 사유가 "252개"인 이유: `v_stock_metrics.max_drawdown_1y`는 최근 252거래일이 다 있을 때만 값을 내요(`views.sql` `mdd`). 변동성은 253개(수익률 252개)라 사유가 달라요.

#### `backend/app/queries/score_metrics.sql`

| 위치 | 바꾸는 것 |
| --- | --- |
| 5행 주석 | `-- z_fixed: 정규화 없이 Z를 고정하는 경우(지금 쓰는 지표 없음 — 규칙만 남김). note: 대체 계산·고정 사유` |
| `base` SELECT | `vm.volatility_1y` 뒤에 `vm.max_drawdown_1y,` 추가 |
| `inp` SELECT | `b.volatility_1y` 뒤에 `b.max_drawdown_1y,` 추가 |
| `VALUES`의 `debt_ratio` 3줄 | 아래 1줄로 교체 (같은 자리) |

```sql
    ('max_drawdown',     'safety',   c.max_drawdown_1y, NULL, NULL),
```

`fy`·`inp`의 `total_debt`는 지우지 않아요(다른 영향 없음, 변경 최소화).

#### `backend/app/queries/score_neutralize.sql`

머리 주석 6행 아래에 한 줄 추가, `g`에 `mv.factor` 추가, `SET` 조건에 `safety` 추가. 결과 전문:

```sql
-- 매력도 2단계-2: 섹터 중립화(축소 추정) → stock_metric_values.z_adj
-- 파라미터: as_of, k (config/scoring.yaml shrinkage_k)
--   z_adj = z − n / (n + k) × (같은 국가·같은 주 그룹 안 z 평균)
--   n = 같은 국가의 주 그룹 구성원 중 그 지표의 z가 있는 종목 수. 그룹 평균에는 자기 자신도 포함된다
--   z는 국가 안에서 표준화한 값이라, 다른 국가 구성원의 z와 섞어 평균 내지 않는다
--   주 그룹이 없거나 n = 1이면 z_adj = z. z_adj는 다시 자르지 않는다
--   안정성(safety) 지표는 중립화하지 않는다(z_adj = z) — 업종 특성으로 출렁이는 것도 그대로 반영 (docs/09 4절)
WITH g AS (
    SELECT mv.stock_id, mv.metric, mv.factor, mv.z_raw, gm.group_id, mk.country
    FROM stock_metric_values mv
    JOIN stocks s   ON s.stock_id = mv.stock_id
    JOIN markets mk ON mk.market_id = s.market_id
    LEFT JOIN peer_group_members gm ON gm.stock_id = mv.stock_id AND gm.is_primary
    WHERE mv.as_of = :as_of AND mv.z_raw IS NOT NULL
),
s AS (
    SELECT g.*,
           COUNT(*)      OVER (PARTITION BY g.group_id, g.country, g.metric) AS n,
           AVG(g.z_raw)  OVER (PARTITION BY g.group_id, g.country, g.metric) AS group_mean
    FROM g
)
UPDATE stock_metric_values t
SET z_adj = CASE WHEN s.factor = 'safety' OR s.group_id IS NULL OR s.n = 1 THEN s.z_raw
                 ELSE s.z_raw - CAST(s.n AS numeric) / (s.n + :k) * s.group_mean END
FROM s
WHERE t.as_of = :as_of AND t.stock_id = s.stock_id AND t.metric = s.metric
```

#### `backend/app/queries/score_zscore.sql`

6행 주석만 바꿔요. 코드(`mv.z_raw IS NULL` 조건)는 그대로 둬요.

```sql
--   z_raw가 이미 채워진 행(z_fixed — 지금 쓰는 지표 없음, 고정 규칙이 생기면 재사용)은 통계에서 빼고 건드리지 않는다
```

### 3-3. 응답 예시 변화 — `GET /stocks/NASDAQ/TSLA/analysis`

`attractiveness.metrics[]`의 7번째 항목이 이렇게 돼요(값은 2026-10-16 미리 계산값, 참고용).

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

- `factor == "safety"`인 항목은 항상 `z_adj == z_raw`예요(상장 목록 참고 점수는 지금처럼 `z_adj: null`).
- 일봉 252개 미만이면 `raw_value`·`z_raw`·`z_adj`가 `null`이고 `data_quality.missing_metrics.max_drawdown == "일봉 252개 미만"`.

### 3-4. 화면 (A — `frontend/js/pages/stock.js`)

| 위치 | 전 | 후 (약속 — 문구 그대로) |
| --- | --- | --- |
| `FACTORS`의 quality `desc` | `"자본과 매출로 돈을 잘 버는가 (ROE·영업이익률)"` | `"자본과 매출로 돈을 잘 버는가 (최근 연간 기준)"` |
| `FACTORS`의 safety `desc` | `"빚이 적고 주가 출렁임이 작은가"` | `"주가가 덜 출렁이고 덜 빠지는가"` |
| `rawFmt` | `debt_ratio`면 `배` 표기 분기 | 분기 삭제. 낙폭은 기본 % 표기, 부호 옵션 없음(음수는 `-39.1%`) |

`rawFmt` 결과 전문:

```js
const rawFmt = (m) => (m.raw_value === null ? DASH
  : pct(m.raw_value, { digits: 1, sign: SIGNED_METRICS.includes(m.metric) }));
```

`SIGNED_METRICS`는 그대로(`["revenue_yoy", "eps_change_yield", "momentum"]`). '투자 지표 상세'의 부채비율·MDD 표시는 그대로예요.

### 3-5. 테스트 (C — `backend/tests/test_scoring.py`)

| 위치 | 바꾸는 것 |
| --- | --- |
| `reference_raw` 230행 `"debt_ratio": …` | `"max_drawdown": _mdd(cl[-252:]) if len(cl) >= 252 else None` 로 교체 (같은 자리) |
| 파일 위쪽 헬퍼 | `_mdd(closes)` 추가 — 누적 최고가 대비 낙폭의 최솟값: `peak = closes[0]; worst = 0.0; for c in closes: peak = max(peak, c); worst = min(worst, c / peak - 1); return worst` |
| `reference_scores` 255~257행 | 자본 ≤ 0 부채비율 고정 블록 삭제 |
| `reference_scores`의 `z_adj` 계산 | `METRICS[metric].factor == "safety"`면 `z_adj[s][metric] = z_raw[s][metric]` (중립화 건너뜀) |
| `test_boundary_cases` 321·328행 | `debt` 읽기 삭제. `assert roe[6] is None and debt[6] == -3` → `assert roe[6] is None` |

새 테스트 2개 (이름 그대로):

```python
def test_safety_factor_is_not_sector_neutralized(engine, universe):
    """안정성 지표는 z_adj = z_raw, 다른 팩터는 주 그룹(n > 1)이면 중립화가 그대로 걸린다."""
    # compute_scores(engine, as_of=D) 뒤
    # ① factor = 'safety' AND z_raw IS NOT NULL인 모든 행: z_adj == z_raw
    # ② 주 그룹 반도체(1, 2)의 roe: z_adj != z_raw  (중립화가 다른 팩터에는 살아 있음)

def test_max_drawdown_null_reason_is_short_history(engine, universe):
    """일봉 252개 미만(픽스처 종목 7: 100개)이면 낙폭이 없고 사유가 '일봉 252개 미만'."""
    # sc = scores_by(conn) → sc[7]["data_quality"]["missing_metrics"]["max_drawdown"] == "일봉 252개 미만"
    # 일봉 300개인 종목 1은 max_drawdown raw_value가 있음
```

### 3-6. 완료 기준

1. `pytest -q tests/test_scoring.py` 통과 (기존 전부 + 새 2개)
2. 개발 DB `python -m app.ingest scores` 뒤 미국·국내 몇 종목 안정성 화면 점수가 `04_기능구현_아이디어.md` "바꾸면 이렇게 돼요" 표(TSLA 75 → 41 등)와 같음
3. `docs/09` 갱신: 2절 지표 표(부채비율 행 → 1년 최대 낙폭 행), 4절 중립화 범위("안정성 제외"), 7절 프리셋별 순위 재계산 결과 + **점수가 새로 생긴 종목 수**(재무가 없어도 안정성 팩터가 생겨 `factor_coverage`가 3에 닿는 종목), 화면 이름 표의 설명 문구
4. 배포(또는 stage → main) 직후 `python -m app.ingest scores` 한 번 실행 — 그 전까지 상장 종목 참고 점수는 낙폭 비교값이 없어 안정성이 빠져 보여요

---

## 4. 파트 7-2 — 실적 시즌 부하 분산 (계획 2단계)

### 4-1. 동작 약속 한눈에

| 약속 | 내용 |
| --- | --- |
| 잠금 범위 | DART·SEC를 **부르는 동안만**, 회사 1개 단위로 잠가요. DB 쓰기는 잠금 밖 |
| 잠금 키 | 한국 = `DART_LOCK_KEY`(7_301_010), 미국 = `SEC_LOCK_KEY`(7_301_012, 새로) |
| 잠금 연결 | 반복문 동안 연결 1개를 잡아 두고 잠금·해제만 반복 (`LockSession`) |
| 묶음 저장 | 회사 `flush_every`(기본 20)개마다 한 트랜잭션. 반복이 끝나거나 예외가 나도 남은 것을 저장 |
| 같은 트랜잭션 | 재무(또는 공시) 행 upsert + `freshness.mark` (+ 공시면 `invalidate_on_annual_report`) |
| 별도 트랜잭션 | `ingestion_logs` 행 — 적재가 롤백돼도 남아요 |
| 묶음 저장 실패 | 그 묶음의 모든 회사를 FAILED로 로그, freshness도 FAILED(1일 뒤 재시도) |
| 하루 재무 예산 | 07:00 비교군 갱신의 **비교군** 재무 대상은 유효기간이 가장 오래 지난 순 `fin_daily_budget`(100)개까지. 노출·관심·포트폴리오 종목(`frequent`)은 예산과 무관 |
| DART 분당 한도 | 프로세스마다 `WindowLimiter(45, 60.0)` — API 서비스 + Job 2개가 합쳐 90 이하 |
| 반환값 | `load_financials`·`load_disclosures`의 반환(`{티커: "SUCCESS"|"FAILED"}`)과 인자는 그대로 (`flush_every` 키워드만 추가) |

### 4-2. `backend/app/ingest/store.py` [D 선행]

기존 `upsert`·`advisory_lock`·`JobResult`·`job_log`·`DART_LOCK_KEY`·`BENCHMARK_LOCK_KEY`는 그대로 남아요(`advisory_lock`은 비교군·테스트가 계속 써요). 추가하는 이름과 시그니처는 아래가 전부예요.

```python
SEC_LOCK_KEY = 7_301_012          # SEC 호출(미국 재무·기초값·공시) — 회사 1개 단위
LOCK_WAIT_NOTE_SECONDS = 1.0      # 잠금을 이보다 오래 기다렸으면 로그 비고에 남긴다


def provider_lock_key(country: str) -> int:
    """KR → DART_LOCK_KEY, US → SEC_LOCK_KEY. 그 밖의 값은 ValueError."""


def error_text(e: BaseException) -> str:
    """로그·freshness에 남길 실패 사유. 형식: f"{type(e).__name__}: {메시지 앞 3줄을 공백으로 이은 것}"[:500]
    SQLAlchemy 오류는 SQL 전문 대신 e.orig(DB 메시지)를 쓴다. job_log도 이 함수를 쓰도록 바꾼다(결과 문자열은 지금과 같다)."""


def default_flush_every() -> int:
    """config/universe.yaml ingest.flush_every (없으면 20)."""


class LockSession:
    """연결 1개를 잡아 두고 advisory lock 잠금·해제를 반복한다(회사마다 새 연결을 열지 않음).

    with LockSession(engine) as locks:
        with locks.hold(provider_lock_key("KR")) as waited:   # waited: 잠금을 기다린 초(float)
            ...외부 호출...
    """
    def __init__(self, engine: Engine) -> None: ...
    def __enter__(self) -> "LockSession": ...           # engine.connect() 한 번
    def __exit__(self, *exc) -> None: ...               # 아직 잡힌 키가 있으면 모두 풀고 연결을 닫는다(예외를 삼키지 않음)

    @contextmanager
    def hold(self, key: int) -> Iterator[float]:
        """SELECT pg_advisory_lock(:k) → commit → (대기 초) yield → finally pg_advisory_unlock(:k) → commit.
        __enter__ 전·__exit__ 뒤에 부르면 RuntimeError."""


@dataclass
class Unit:
    """회사 1개 작업의 결과. 외부 호출은 끝났고 DB에는 아직 쓰지 않은 상태."""
    source: str                       # ingestion_logs.source — "DART" / "SEC"
    job_type: str                     # "FINANCIALS" / "DISCLOSURES"
    stock_id: int
    label: str                        # 티커 (반환 딕셔너리 키, 로그 label)
    country: str                      # "KR" / "US" — freshness.mark의 country
    kind: str                         # data_freshness.kind — "financials" / "disclosures"
    started_at: datetime              # UTC
    writes: list[tuple[str, list[dict], list[str]]] = field(default_factory=list)  # (테이블, 행, 충돌 키) — 이 순서로 upsert
    after: list[Callable[[Connection, "Unit"], None]] = field(default_factory=list)  # upsert 뒤 같은 트랜잭션에서 실행
    notes: list[str] = field(default_factory=list)
    rows: int = 0                     # ingestion_logs.rows_loaded
    error: str | None = None          # 외부 호출 단계 실패 사유. 있으면 writes·after를 실행하지 않는다
    status: str = "PENDING"           # flush 뒤 "SUCCESS" / "FAILED"


def write_logs(engine: Engine, units: list[Unit]) -> None:
    """Unit마다 ingestion_logs 1행(별도 트랜잭션). job_log와 같은 형식:
    error 열 = 실패 사유 + (" | " + 비고들) 또는 비고들("; "로 이음) 또는 NULL, finished_at = 지금.
    쓰다가 실패하면 log.exception만 하고 예외를 올리지 않는다. 콘솔 로그 줄도 job_log와 같은 형식."""


class BatchWriter:
    def __init__(self, engine: Engine, flush_every: int,
                 on_flush: Callable[[list[Unit]], None] | None = None) -> None: ...
    flushes: int                      # DB에 실제로 쓴 flush 횟수 (테스트용)
    done: list[Unit]                  # 상태가 확정된 Unit 전부 (추가 순서)

    def add(self, unit: Unit) -> None:
        """쌓는다. 쌓인 수가 flush_every 이상이면 flush()."""

    def flush(self) -> list[Unit]:
        """쌓인 Unit을 쓰고 비운다. 비어 있으면 아무것도 하지 않고 [] (flushes도 그대로)."""
```

`BatchWriter.flush()` 동작 (순서 그대로):

1. `batch = 쌓인 것`, 쌓인 목록을 비워요. `now = datetime.now(timezone.utc)`.
2. 트랜잭션 1개(`engine.begin()`)에서 `batch` 순서대로:
   - `u.error is None`: `writes`를 순서대로 `upsert(conn, 테이블, 행, 충돌 키)` → `after`의 함수를 순서대로 `fn(conn, u)` → `freshness.mark(conn, u.kind, u.stock_id, True, country=u.country, now=now)`
   - `u.error`가 있으면: `freshness.mark(conn, u.kind, u.stock_id, False, country=u.country, error=u.error, now=now)`
3. 2에서 예외가 나면(롤백됨): `msg = "묶음 저장 실패: " + error_text(e)`. `error is None`이던 Unit의 `error = msg`. 새 트랜잭션에서 `batch` 전부 `freshness.mark(..., False, error=u.error)` — 이것도 실패하면 `log.exception`만.
4. `u.status = "SUCCESS" if u.error is None else "FAILED"`.
5. `write_logs(engine, batch)`.
6. `flushes += 1`, `done.extend(batch)`.
7. `on_flush`가 있으면 `on_flush([u for u in batch if u.status == "SUCCESS"])`. 예외는 `log.exception`만(상태는 바꾸지 않음).
8. `batch`를 반환해요.

`store.py`가 `app.services.freshness`를 import해요(순환 없음 — freshness는 store를 import하지 않음).

### 4-3. `backend/app/services/freshness.py` [D 선행]

`due`에 키워드 인자 `limit` 하나만 추가해요.

```python
def due(conn: Connection, kind: str, stock_ids: list[int], now: datetime | None = None,
        *, limit: int | None = None) -> list[int]:
    """유효기간이 지났거나 기록이 없는 종목.
    limit=None: 지금과 똑같다(입력 순서 유지).
    limit 지정: 기록 없음 → valid_until 오래된 순 → stock_id 순으로 정렬해 앞 limit개. limit <= 0이면 []."""
```

`limit`이 있을 때의 SQL:

```sql
SELECT s.id
FROM unnest(CAST(:ids AS int[])) AS s(id)
LEFT JOIN data_freshness f ON f.stock_id = s.id AND f.kind = :k
WHERE f.valid_until IS NULL OR f.valid_until <= :now
ORDER BY f.valid_until ASC NULLS FIRST, s.id
LIMIT :limit
```

### 4-4. `backend/config/universe.yaml` [D 선행]

`benchmark:` 블록 끝에 한 줄, 파일 끝에 `ingest:` 블록을 추가해요.

```yaml
  fin_daily_budget: 100   # 07:00 갱신이 하루에 재무를 받는 비교군 종목 수 상한(유효기간이 가장 오래 지난 순). 노출·관심 종목은 예산과 무관 (D4 임시값 — 첫 배포 뒤 BENCHMARK 실행 시간을 보고 확정)

# 수집 적재 공통
ingest:
  flush_every: 20         # 재무·공시 적재를 몇 개 회사마다 한 트랜잭션으로 저장할지 (D3). 상세 수집(회사 1개)은 결과가 같다
```

### 4-5. `backend/app/ingest/benchmark.py` — `load_benchmark` (D)

한 줄만 바꿔요.

```python
        due_bench = freshness.due(conn, "financials", ids, limit=cfg["fin_daily_budget"])
```

`due_freq`(노출·관심·포트폴리오)는 `limit` 없이 그대로예요.

### 4-6. `backend/app/ingest/jobs.py` (B)

import 줄 변경:

```python
from app.ingest.store import (LOCK_WAIT_NOTE_SECONDS, BatchWriter, LockSession, Unit, default_flush_every, error_text,
                              job_log, provider_lock_key, upsert)
```

`from sqlalchemy import Connection, Engine, text`로 `Connection`도 가져와요. `DART_LOCK_KEY`·`advisory_lock` import는 jobs.py에서 쓰는 곳이 없어지므로 지워요(8-1에서 `load_dart_feed`를 만들 때 `DART_LOCK_KEY`를 다시 import해요).

#### 시그니처 (공개 함수 2개 — 키워드 `flush_every`만 추가)

```python
def load_financials(engine: Engine, providers: Providers, *, years: int = FIN_YEARS,
                    tickers: list[str] | None = None, scope: str = "frequent",
                    stock_ids: list[int] | None = None, flush_every: int | None = None) -> dict[str, str]:
    with engine.connect() as conn:
        refs = stock_refs(conn, tickers, scope=scope, stock_ids=stock_ids)
    return _load_financials(engine, providers, refs, years, flush_every or default_flush_every())


def load_disclosures(engine: Engine, providers: Providers, *, days: int = DISCLOSURE_DAYS,
                     tickers: list[str] | None = None, today: date | None = None, scope: str = "frequent",
                     stock_ids: list[int] | None = None, flush_every: int | None = None) -> dict[str, str]:
    today = today or date.today()
    with engine.connect() as conn:
        refs = stock_refs(conn, tickers, scope=scope, stock_ids=stock_ids)
    return _load_disclosures(engine, providers, refs, days, today, flush_every or default_flush_every())
```

`hydration.py`·`benchmark.py`·`__main__.py`의 호출부는 바꾸지 않아요(키워드 기본값으로 동작).

#### 재무 — 반복과 묶음 저장

```python
def _load_financials(engine: Engine, providers: Providers, refs: list, years: int, flush_every: int) -> dict[str, str]:
    def on_flush(units: list[Unit]) -> None:          # 미국: 재무·기초값 저장 뒤 기초값 × 종가 밸류에이션
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

#### 재무 — 회사 1개 (외부 호출만, DB 쓰기 없음)

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

기존 `_load_valuation_base` 함수는 쓰는 곳이 없어지므로 지워요(같은 내용이 위 `fundamental_bases` 행과 `on_flush`로 옮겨졌어요).

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

`StockRef`·`ProviderError`·`timedelta`는 jobs.py에 이미 import돼 있어요.

#### 지금과 달라지는 로그 (의도된 차이)

| 항목 | 전 | 후 |
| --- | --- | --- |
| freshness 실패 사유(재무) | 항상 `"재무 수집 실패"` | 실제 사유(`error_text`) |
| `ingestion_logs.started_at` | 회사 시작 시각 | 같음(`Unit.started_at`) |
| `ingestion_logs.finished_at` | 회사 저장 직후 | 그 회사가 들어간 묶음 저장 직후 |
| 비고 | — | 잠금을 1초 이상 기다리면 `잠금 대기 N.N초` |

### 4-7. `backend/app/providers/dart.py` (B)

```python
# OpenDART는 분당 100회 이상 호출하면 이용이 제한될 수 있다. 회사 단위 잠금이라 프로세스 2개(API 서비스 + Job)가
# 번갈아 부를 수 있어 프로세스마다 절반(45)으로 막는다 → 합계 90 이하 (D2). 프로세스가 3개 이상이 되면 다시 검토
_limiter = WindowLimiter(45, 60.0)
```

### 4-8. 재무 기준 연도 표기 (계획 2단계 "FY2025 n개 / FY2024 m개")

실적 시즌에는 같은 날 비교하는 종목 중 일부는 새 연도, 일부는 지난해 재무예요. 이를 숫자로 보여 줘요.

#### `backend/app/queries/fin_basis.sql` (C, 새)

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

#### `backend/app/services/data_quality.py` (D [껍데기] → C)

```python
def fiscal_year_mix(conn: Connection, country: str, as_of: date) -> list[dict]:
    """매력도 표본의 최신 FY 결산 연도별 종목 수. [{"fiscal_year": 2025, "stocks": 41}, ...] 연도 내림차순.
    as_of에 지표가 없으면 []."""
    return [dict(r) for r in conn.execute(sql("fin_basis"), {"country": country, "as_of": as_of}).mappings()]
```

[껍데기] 본문(D): `return [{"fiscal_year": 2025, "stocks": 41}, {"fiscal_year": 2024, "stocks": 30}]` + `# TODO(껍데기): C — fin_basis.sql 실행`.

`fiscal_year`는 결산일의 **연도**예요(AAPL 2025-09-27 결산 → 2025).

#### `backend/app/api/analysis.py` (D 필드·[껍데기] → B 값)

```python
class FinBasisOut(Schema):
    fiscal_year: int                 # 최신 FY 결산일의 연도
    stocks: int                      # 그 연도 재무로 비교된 종목 수


class ScoreOut(Schema):
    ...                              # 기존 필드 그대로
    reference_note: str | None = None
    fin_basis: list[FinBasisOut] = []   # 같은 시장 비교 표본의 재무 기준 연도별 종목 수(연도 내림차순)
```

- `FinBasisOut`은 `ScoreOut` 바로 위에 둬요.
- B: `_attractiveness` 반환 딕셔너리에 `"fin_basis": fiscal_year_mix(db.connection(), country, row["score_as_of"])`. `reference_score` 반환에 `"fin_basis": fiscal_year_mix(conn, country, as_of)`. 점수가 없을 때(`as_of`가 없음)는 키를 넣지 않아 기본값 `[]`.
- [껍데기](D): `_attractiveness`에 `"fin_basis": [{"fiscal_year": 2025, "stocks": 41}, {"fiscal_year": 2024, "stocks": 30}]` + `# TODO(껍데기): B — data_quality.fiscal_year_mix 연결`.

응답 예시 (`GET /stocks/KOSPI/005930/analysis`의 `attractiveness` 끝):

```json
  "reference": false,
  "reference_note": null,
  "fin_basis": [
    {"fiscal_year": 2025, "stocks": 41},
    {"fiscal_year": 2024, "stocks": 30}
  ]
```

#### 화면 (A — `stock.js`)

'계산 근거 보기' 접힘 안, `데이터 충족도 …` 줄 바로 아래에 한 줄. `fin_basis`가 빈 배열이면 줄을 그리지 않아요.

```
재무 기준 FY2025 41개 · FY2024 30개
```

형식 약속: `"재무 기준 " + fin_basis.map(x => `FY${x.fiscal_year} ${x.stocks}개`).join(" · ")`.

### 4-9. 테스트

#### `backend/tests/test_store_batch.py` (D, 새)

| 테스트 이름 | 확인하는 것 |
| --- | --- |
| `test_provider_lock_key_splits_by_country` | KR → 7_301_010, US → 7_301_012, "JP" → ValueError |
| `test_lock_session_reuses_one_connection_and_releases` | `hold` 두 번 사이에 다른 연결의 `pg_try_advisory_lock(key)`가 True(풀려 있음), `hold` 안에서는 False |
| `test_batch_writer_flushes_every_n` | 회사 25개, `flush_every=20` → `flushes == 2`, `ingestion_logs` 25행 |
| `test_failed_unit_marks_freshness_failed_and_logs` | `error`가 있는 Unit → writes 실행 안 됨, freshness FAILED, 로그 FAILED |
| `test_flush_db_error_fails_batch_but_keeps_logs` | writes에 없는 테이블 이름 → 묶음 전체 FAILED, freshness에 SUCCESS 없음, 로그 행은 남음, `error`가 `"묶음 저장 실패: "`로 시작 |
| `test_due_limit_orders_missing_then_oldest` | 기록 없음 2 · 오래된 순 3 → `limit=3`이면 [없음, 없음, 가장 오래된 것], `limit=None`은 입력 순서 |

#### `backend/tests/test_ingest_batch.py` (B, 새)

| 테스트 이름 | 확인하는 것 |
| --- | --- |
| `test_financials_statuses_and_freshness_after_batch` | 종목 3개(그중 1개 corp_code 없음) → 반환 `{티커: 상태}`, 성공 2개 freshness SUCCESS, 실패 1개 FAILED |
| `test_us_valuation_base_saved_and_derived_after_flush` | 미국 종목 → `fundamental_bases` 1행 + `valuation_snapshots` 파생 행 |
| `test_disclosure_annual_report_expires_financials_in_same_batch` | 기존 `test_new_annual_report_expires_financials`와 같은 상황을 `load_disclosures`로 → 재무 유효기간 만료 + 비고 |
| `test_detail_request_waits_only_one_company` | `FakeFinancial(delay=0.3)`로 KR 6개 `load_financials`를 스레드에서 시작 → 0.1초 뒤 다른 KR 종목 `load_financials(stock_ids=[x])` → 1.0초 안에 끝남(묶음 전체 ≈ 1.8초를 기다리지 않음) |
| `test_kr_and_us_do_not_share_lock` | KR 묶음 진행 중 US 1개 요청이 KR 잠금을 기다리지 않음(잠금 대기 비고 없음) |

`backend/tests/fakes.py` `[S7-B]`: `FakeFinancial.__init__(self, source: str, delay: float = 0.0)`, `FakeDisclosure.__init__(self, source: str, delay: float = 0.0)` — 호출마다 `time.sleep(delay)`. 기본값 0이라 기존 테스트는 그대로예요.

#### 그 밖

- C `test_data_quality.py`: `test_fiscal_year_mix_counts_latest_fy_per_stock` — KR 3종목(FY2025 2개, FY2024 1개) + listed 1개(세지 않음) + US 1개(세지 않음) → `[{"fiscal_year": 2025, "stocks": 2}, {"fiscal_year": 2024, "stocks": 1}]`
- B `test_analysis.py`: `test_analysis_includes_fin_basis` — 점수 있는 종목 `fin_basis`가 위 함수 결과와 같고, 점수 없는 종목은 `[]`
- 기존 `test_freshness.py`·`test_benchmark.py`·`test_refresh.py`는 수정 없이 통과해야 해요(인자·반환이 그대로라서). 통과하지 않으면 계약 위반이에요.

### 4-10. 완료 기준

1. `pytest -q` 전부 통과
2. 개발 DB에서 `python -m app.ingest financials --tickers 005930 AAPL` → 두 종목 SUCCESS, `ingestion_logs` 2행, `data_freshness` 2행
3. `python -m app.ingest benchmark` 실행 중 다른 터미널에서 비교군 종목 상세를 열면 `detail_status`가 `loading` → 수십 초 안에 `ready` (전에는 비교군 재무가 끝날 때까지 대기)
4. `docs/architecture.md`의 잠금 설명을 "회사 단위·국가별 키"로 고쳐요(D)

---

## 5. 파트 7-3 — 시장·섹터 점수 (계획 3단계)

### 5-1. 무엇을 하나

종목 상세 '투자 매력도' 카드에서 매력 점수 아래에 "시장·섹터 점수" 게이지 하나를 보여 줘요. 매력도가 높아도 시장·섹터가 약한 날이면 숫자로 드러나게 하는 위험 표시예요.

- 코드·API 이름 `market_condition`, 화면 이름 **"시장·섹터 점수"**
- 매력도와 합치지 않아요. 해설·권유 문구("구매 비권장" 등)는 없어요
- 새 외부 호출·새 테이블·새 API가 없어요. 조회 경로에서 쓰기도 없어요
- 홈의 시장 심리 카드는 그대로예요

### 5-2. 계산 정의 (D1·D7·D9 확정 + 이 문서에서 정한 세부)

| 재료 | 값 | 0~100 | 비중 |
| --- | --- | --- | --- |
| 시장 | 그 종목 국가의 시장 심리 지수 최신 **저장값** (`market_sentiment_daily.score`) | 그대로 | 0.7 |
| 섹터 흐름 | 같은 국가·같은 `stocks.sector` 표본 종목의 최근 5거래일 수익률 중앙값 `r` | `clamp(50 + r × 100 × 5)` 소수 둘째 자리 HALF_UP | 0.3 |

```
섹터 반영:   score = HALF_UP_정수(0.7 × 시장 + 0.3 × 섹터 흐름)
섹터 미반영: score = HALF_UP_정수(시장)
라벨:       score가 null이면 "데이터 부족", 아니면 BAND_LABELS[min(4, score // 20)]
            BAND_LABELS = ("매우 낮음", "낮음", "보통", "높음", "매우 높음")   ← frontend ui.js BANDS와 같아야 함
```

| 경우 | 판정 | 결과 |
| --- | --- | --- |
| 기준일 `base` | `market_calendar.last_closed_session(country, now)`. None이면 그 국가 기준 지수(`sentiment.INDEX_CODE`)의 `index_daily_prices` 최신 거래일. 그것도 없으면 전부 "데이터 부족" | — |
| 시장 심리 저장값 없음 | `latest_stored`가 None | `score: null`, `label: "데이터 부족"` |
| 시장 심리가 오래됨 | `sessions_between(country, 심리 거래일, base) > 5`. 달력 판정 불가(None)면 달력일 `(base − 심리 거래일).days > 7` | `score: null`, `label: "데이터 부족"` (재료값은 그대로 응답) |
| 섹터 없음 | `stocks.sector IS NULL` (금융·매핑 없음) | 섹터 미반영 (D9) |
| 섹터 표본 부족 | `sector_flow.sql`의 `n < 5` 또는 `sector_r5 IS NULL` | 섹터 미반영 |
| 섹터 표본 | 같은 국가, 같은 `sector`, `is_active`, `coverage IN ('featured','benchmark')` — 자기 자신 포함, listed 제외 | — |
| 섹터 기준일 `ref_date` | `base` 이하에서 표본 종목 일봉이 5개 이상 있는 가장 최근 날짜 (5-3 SQL) | 비교군 일봉은 매일 07:00에만 들어와서, 마감 직후에는 하루 전 날짜로 계산돼요 |
| 5일 수익률 | 그 날짜 종가 ÷ 그 종목의 5거래일 전(자기 일봉 기준 6번째) 종가 − 1. 그 날짜 일봉이나 5거래일 전 일봉이 없으면 제외/null | — |
| `stock_r5`·`index_r5` 비교 날짜 | 섹터 반영이면 `ref_date`, 아니면 시장 심리 거래일(없으면 `base`) | 툴팁의 세 수익률이 같은 날짜 기준 |

예시 (계산 맞춤): 시장 심리 28.00, 섹터 중앙값 `r = −0.024` → 섹터 흐름 `clamp(50 − 12) = 38.00` → `0.7×28 + 0.3×38 = 19.6 + 11.4 = 31.0` → **31, "낮음"**.

### 5-3. `backend/app/queries/sector_flow.sql` (C, 새)

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
    SELECT MAX(c.trade_date) AS ref_date
    FROM (SELECT b.trade_date FROM bars b GROUP BY b.trade_date HAVING COUNT(*) >= :min_n) c
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

결과 열 약속: `sector_r5`(double precision 또는 NULL), `n`(bigint), `ref_date`(date 또는 NULL).

### 5-4. `backend/app/services/market_condition.py` (D [껍데기] → C)

```python
"""시장·섹터 점수 — 종목 상세 '투자 매력도' 카드의 위험 표시(0~100). 매력도와 별개이며 투자 권유가 아니다.

  시장       그 국가 시장 심리 지수 최신 저장값(market_sentiment_daily) — 계산·저장은 홈·갱신 작업이 한다
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
BAND_LABELS = ("매우 낮음", "낮음", "보통", "높음", "매우 높음")   # frontend/js/components/ui.js BANDS와 같아야 한다
INSUFFICIENT = "데이터 부족"        # sentiment.INSUFFICIENT와 같은 값


def band_label(score: int | None) -> str:
    """None → "데이터 부족", 0~19 → "매우 낮음", 20~39 → "낮음", 40~59 → "보통", 60~79 → "높음", 80~100 → "매우 높음"."""


def sector_flow_score(r: Decimal | float | None) -> Decimal | None:
    """5거래일 수익률 → 0~100. clamp(50 + r × 100 × 5), 소수 둘째 자리 HALF_UP. None → None.
    −0.10 이하 → 0.00, 0 → 50.00, +0.10 이상 → 100.00."""


def compute_condition(sentiment: Decimal | float | None, sector_r: Decimal | float | None) -> dict:
    """순수 계산(DB 없음). 반환 {"score": int | None, "label": str, "sector_flow": Decimal | None}.
    sentiment None → score None·"데이터 부족"(sector_flow는 그대로 계산). sector_r None → 시장만."""


def read_sector_flow(conn: Connection, country: str, sector: str, as_of: date) -> tuple[Decimal | None, int, date | None]:
    """sector_flow.sql 실행(캐시 없음). 반환 (sector_r5 — 소수 여섯째 자리 HALF_UP, n, ref_date)."""


def get_condition(engine: Engine, *, stock_id: int, country: str, sector: str | None,
                  now: datetime | None = None) -> dict:
    """상세 응답 market_condition. 항상 MarketConditionOut 모양의 dict를 돌려주고 예외를 올리지 않는다
    (실패하면 log.exception + empty_condition)."""


def empty_condition(country: str, sector: str | None) -> dict:
    """모든 값 null·"데이터 부족"·sector_sample 0. index_code는 sentiment.INDEX_CODE[country]."""


def clear_cache() -> None:
    """섹터 흐름 캐시 비우기 (테스트용)."""
```

`get_condition` 순서 (그대로):

1. `index_code = sentiment.INDEX_CODE[country]`, `now = now or datetime.now(timezone.utc)`
2. `base` 결정 (5-2 표)
3. `s_row = sentiment.latest_stored(engine, country)`, `stale` 판정 (5-2 표)
4. `sector`가 있으면 `(sector_r5, n, ref_date) = 캐시 또는 read_sector_flow(conn, country, sector, base)`. `use = n >= MIN_SECTOR_SAMPLE and sector_r5 is not None`
5. `compare = ref_date if use else (s_row["trade_date"] if s_row else base)`
6. `stock_r5`, `index_r5` 계산 (아래 SQL, 소수 여섯째 자리 HALF_UP)
7. `cond = compute_condition(None if (s_row is None or stale) else s_row["score"], sector_r5 if use else None)`
8. 반환 (5-5 필드 표)

캐시: 모듈 딕셔너리 `{(country, sector, base): (저장 시각, (sector_r5, n, ref_date))}` + `threading.Lock`. **`n >= MIN_SECTOR_SAMPLE`일 때만 저장**하고, 저장 시각이 `CACHE_TTL`(1시간)보다 오래되면 다시 읽어요. 상세는 수집 대기 중 2초마다 다시 불려서 캐시가 필요해요.

`stock_r5`·`index_r5` SQL (서비스 안 `text()` 상수 — sentiment.py와 같은 방식):

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

[껍데기](D): `get_condition`이 아래 5-6의 "보통" 예시 dict를 그대로 돌려주고 `# TODO(껍데기): C — 본문`. 다른 함수·상수는 C가 만들어요.

### 5-5. 응답 — `GET /api/v1/stocks/{market}/{ticker}`에 `market_condition` 추가

#### `backend/app/schemas/api.py` [D 선행]

`StockDetailOut` 바로 위에 추가하고, `StockDetailOut`의 마지막 필드(`detail_status` 다음)로 넣어요.

```python
class MarketConditionOut(Schema):
    score: int | None                # 0~100 정수. 시장 심리 없음·오래됨이면 null
    label: str                       # 매우 낮음·낮음·보통·높음·매우 높음 / 데이터 부족
    sentiment: Num | None            # 시장 심리 지수 저장값(0~100) — 오래돼도 값은 그대로 준다
    sector_name: str | None          # stocks.sector. 금융 등 섹터 없음이면 null
    sector_flow: Num | None          # 섹터 흐름 0~100. 섹터 미반영이면 null
    sector_sample: int               # 섹터 수익률을 낸 표본 종목 수(미반영이면 표본 부족 수 또는 0)
    sector_as_of: date | None        # 섹터 흐름 기준일(ref_date). 미반영이면 null
    index_code: str                  # 비교 지수 (KOSPI · SPX)
    stock_r5: Num | None             # 이 종목 5거래일 수익률(소수)
    sector_r5: Num | None            # 섹터 중앙값 5거래일 수익률(소수). 미반영이면 null
    index_r5: Num | None             # 지수 5거래일 수익률(소수)
    as_of: date | None               # 시장 심리 기준일(화면 '추합 기준' 날짜)


class StockDetailOut(Schema):
    ...                              # 기존 필드 그대로
    detail_status: str
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

#### `backend/app/api/stocks.py` [D 선행]

```python
from sqlalchemy import Engine, text
from app.api.deps import ..., get_engine_dep        # 기존 import 줄에 추가
from app.services.market_condition import get_condition


def stock_detail(market: MarketPath, ticker: TickerPath, user_id: int = Depends(get_current_user_id),
                 preset: dict = Depends(get_preset), db: Session = Depends(get_db),
                 fx_service: FxService = Depends(get_fx_service), hydrator: Hydrator = Depends(get_hydrator),
                 engine: Engine = Depends(get_engine_dep)):
    ...
    out["detail_status"] = hydrator.request(out["stock_id"], out["coverage"], out.pop("detail_synced_at"))
    out["market_condition"] = get_condition(engine, stock_id=out["stock_id"], country=out["country"], sector=out["sector"])
    if out["currency"] == "USD":
        ...
```

### 5-6. 응답 예시

섹터 반영 (`GET /stocks/KOSPI/005930`, 값은 계산 맞춤 예시):

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

시장 심리 오래됨·없음:

```json
"market_condition": {
  "score": null, "label": "데이터 부족", "sentiment": 61.2,
  "sector_name": "반도체·전자", "sector_flow": 38.0, "sector_sample": 47, "sector_as_of": "2026-10-15",
  "index_code": "KOSPI", "stock_r5": -0.031, "sector_r5": -0.024, "index_r5": -0.018, "as_of": "2026-09-30"
}
```

[껍데기] 예시(D가 그대로 반환): 위 첫 번째("섹터 반영") 객체.

### 5-7. 시장 심리 이름 공개 (C — `backend/app/services/sentiment.py`)

`_latest_stored` → `latest_stored`로 **이름만** 바꾸고, 같은 파일의 호출부(`get_sentiment`) 한 곳도 바꿔요. 시그니처 `latest_stored(engine: Engine, market: str) -> dict | None`, 반환 키(`trade_date, score, label, price_position, ma_gap_score, rsi_score, vix_score, formula_version`)는 그대로예요. 상세 경로는 이 함수만 불러요(`ensure_sentiment`·`get_sentiment`를 부르지 않음 — 계산·저장 금지).

### 5-8. 거래일 수 (D — `backend/app/services/market_calendar.py`) [D 선행]

```python
def sessions_between(country: str, start: date, end: date) -> int | None:
    """start 다음 날부터 end까지(end 포함)의 거래일 수. start >= end면 0.
    country가 KR·US가 아니거나 달력 범위 밖·판정 실패면 None(경고 로그)."""
```

구현: `_calendar(CALENDARS[country]).sessions_in_range(pd.Timestamp(start + timedelta(days=1)), pd.Timestamp(end))`의 길이.

### 5-9. 화면 (A — `frontend/js/pages/stock.js`, `frontend/css/pages.css`)

데이터: 시장·섹터 점수는 **상세 응답**(`stock.market_condition`, 이미 받아 둔 전역 `stock`)에서, 매력 점수는 지금처럼 `/analysis`에서 읽어요. 새 API 호출은 없어요. `renderScore(a)` 안에서 `stock?.market_condition`을 읽어요(프리셋 변경으로 `renderScore`가 다시 불려도 그대로 그려져야 해요).

시안: `docs/assets/score_panel_sector_mockup.png`. 시안 속 숫자·섹터 이름·범례는 자리 채움이에요. 두 게이지 색이 같을 필요는 없어요(표현).

#### 약속 (문구·동작)

| 항목 | 약속 |
| --- | --- |
| 게이지 함수 | `gauge(score, { name = "매력도" } = {})` — `aria-label`이 `${name} ${num(score, 1)}점` / 점수 없으면 `${name} 계산 불가`. 매력 점수는 `name` 기본값, 시장·섹터는 `{ name: "시장·섹터 점수" }` |
| 제목 | 첫 게이지 위 `매력 점수`, 둘째 게이지 위 `시장·섹터 점수` |
| 라벨 | 둘째 게이지 라벨 글자는 `market_condition.label` 그대로, 색 점은 `scoreBand(score)`의 구간 색. 점수 null이면 게이지는 빈 상태(–), 라벨 `데이터 부족` |
| 순위·기준일 문장 | 매력 점수 게이지 **옆**으로 옮김(지금 문장 그대로: `…비교군 N개 중 M위`, `{프리셋} 성향 · {날짜} 기준`) |
| 섹터 문장 — 반영 | `현재 주식의 섹터 분류는 <strong>{sector_name}</strong> 입니다` |
| 섹터 문장 — 표본 부족 | 위 문장 + 다음 줄 `섹터 표본이 적어 시장 심리만 반영했습니다` |
| 섹터 문장 — 섹터 없음 | `섹터 분류가 없어 시장 심리만 반영했습니다` (D9) |
| 날짜 줄(작은 글씨) | `지수 및 섹터 정보 추합 : {as_of를 YYYY.MM.DD} 기준`. `sector_as_of`가 있고 `as_of`와 다르면 끝에 ` (섹터 {MM.DD})` |
| 툴팁 위치 | 시장·섹터 점수 게이지에 마우스를 올리거나 키보드 포커스(`tabindex="0"`) — 홈 `senti__gauge`와 같은 방식 |
| 툴팁 내용 | 아래 블록 그대로. 숫자 형식: 점수·재료는 정수(`Math.round`), 수익률은 `pct(v, { digits: 1, sign: true })`, 값 없음은 `–` |
| 배치 | 왼쪽 위 매력 점수 + 옆 문장, 왼쪽 아래 시장·섹터 점수 + 옆 문장, 오른쪽 레이더 + 범례, 아래 요약 문장·요소 목록(그대로) |
| 모바일(767px 이하) | 매력 점수 → 시장·섹터 점수 → 레이더 순서로 세로. 390px에서 가로 스크롤 없음 |
| `market_condition`이 없을 때 | (응답 실패·옛 서버) 둘째 게이지 행을 그리지 않아요. 콘솔 에러 없음 |

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

섹터 미반영이면 둘째 줄이 `시장 심리 28 · 섹터 미반영`, 섹터 중앙값 줄은 빼고, 마지막 줄은 `시장 심리 100%(섹터 미반영), 투자 권유 아님`. 지수 이름은 `index_code`가 `KOSPI`면 `KOSPI`, `SPX`면 `S&P 500`.

`pages.css`는 `[S7-A]` 구역에 추가해요. 기존 `.score-panel` 규칙은 이 구역에서 덮어써요(공통 CSS 파일은 건드리지 않음).

### 5-10. 테스트

#### `backend/tests/test_market_condition.py` (C, 새)

| 테스트 이름 | 확인하는 것 |
| --- | --- |
| `test_sector_flow_score_bounds` | −0.20 → 0.00, −0.10 → 0.00, −0.034 → 33.00, 0 → 50.00, 0.02 → 60.00, 0.10 → 100.00, None → None |
| `test_compute_condition_weights_and_half_up` | (28, −0.024) → 31·"낮음"·38.00 / (Decimal("50.50"), None) → 51·"보통" / (Decimal("49.50"), None) → 50·"보통" |
| `test_band_label_boundaries` | None·0·19·20·39·40·59·60·79·80·100 → 데이터 부족·매우 낮음·매우 낮음·낮음·낮음·보통·보통·높음·높음·매우 높음·매우 높음 |
| `test_compute_condition_without_sentiment` | (None, 0.0) → score None·"데이터 부족"·sector_flow 50.00 |
| `test_sector_flow_sql_median_sample_and_exclusions` | 아래 픽스처 → `sector_r5 == 0.005`, `n == 6`, `ref_date == 기준일` |
| `test_sector_flow_sql_falls_back_to_previous_day` | 기준일 일봉이 있는 표본이 4개뿐 → `ref_date`가 전 거래일 |
| `test_get_condition_without_sector_uses_market_only` | sector None → score = 시장 심리 반올림, sector 필드들 null·0 |
| `test_get_condition_small_sector_uses_market_only` | 표본 3개 → `sector_name` 있음, `sector_flow` null, `sector_sample` 3 |
| `test_get_condition_stale_sentiment_is_insufficient` | 심리 거래일이 기준일보다 10거래일 전 → score None, `sentiment` 값은 있음 |
| `test_get_condition_never_raises` | `read_sector_flow`를 예외로 바꿔도(monkeypatch) `empty_condition` 모양 반환 |

픽스처(`test_sector_flow_sql_median_sample_and_exclusions`): KR(market_id 1) 종목 101~106 `sector='반도체·전자'`, `coverage` 101~103 `featured`·104~106 `benchmark`, 각각 기준일까지 6거래일 일봉. 5일 수익률 −0.05, −0.02, 0.00, 0.01, 0.03, 0.04 → 중앙값 (0.00 + 0.01) / 2 = 0.005. 제외 확인용: 107 `listed`(같은 섹터, 수익률 +0.50), 108 `featured`인데 기준일 일봉 없음, 미국 종목 109 같은 섹터 이름. 기준일은 `last_closed_session`을 쓰지 않고 `read_sector_flow(conn, "KR", "반도체·전자", 기준일)`로 직접 넘겨요. 각 테스트 시작에 `clear_cache()`.

#### `backend/tests/test_stocks_api.py` (B)

`test_stock_detail_includes_market_condition` — `GET /api/v1/stocks/KOSPI/005930` 응답에 `market_condition`이 있고 키 집합이 정확히 `{"score","label","sentiment","sector_name","sector_flow","sector_sample","sector_as_of","index_code","stock_r5","sector_r5","index_r5","as_of"}`, `index_code == "KOSPI"`. 픽스처에 시장 심리 행이 없으니 `score is None`, `label == "데이터 부족"`. 그다음 `market_sentiment_daily`에 (KR, 픽스처 기준일 D, 62.00, '탐욕', formula_version 1) 1행을 넣고 다시 부르면 `score == 62`, `label == "높음"`(종목 1은 sector NULL → 시장만).

### 5-11. 완료 기준

1. `pytest -q` 전부 통과
2. 개발 DB에서 같은 섹터 종목 여러 개를 열어 `sector_flow`·`sector_sample`이 같은지, `sentiment`가 홈 시장 심리 카드 값과 같은지
3. 금융 종목(sector NULL)에서 섹터 문장이 `섹터 분류가 없어 시장 심리만 반영했습니다`
4. 화면 배치가 시안과 같은 방향, 390px에서 세로로 쌓이고 가로 스크롤 없음, 콘솔 에러 0
5. 상세 응답 시간이 이 필드 추가 전과 비교해 눈에 띄게 늘지 않음(캐시 적중 시 쿼리 3개: 심리 1·종목 r5 1·지수 r5 1)
6. `docs/06`(2절 표, 3-2 상세 예시, 4절 화면 연결), `docs/09`(시장·섹터 점수 절 — 매력도와 별개라는 점, 계산식, 미반영 조건) 갱신

---

## 6. 파트 8-1 — 한국 재무 일괄 첫 적재 + 공시 기준점 증분 (계획 4-1)

### 6-1-1. DB [D 선행] — `backend/db/migrations/008_ingest_cursor.sql`

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

같은 블록을 `schema.sql`에 넣고, `tests/conftest.py`의 `TABLES` 맨 앞에 `"ingest_cursor"`를 추가해요. `ingestion_logs.job_type` CHECK는 **바꾸지 않아요**(아래 작업은 기존 `FINANCIALS`·`DISCLOSURES`로 기록).

### 6-1-2. `backend/app/services/freshness.py` [D 선행]

```python
def expire_financials(conn: Connection, stock_ids: list[int], now: datetime | None = None) -> int:
    """새 사업보고서가 확인된 종목의 재무 유효기간을 지금 끝낸다(다음 재무 작업 대상이 됨).
    기록이 없거나 이미 지난 종목은 그대로. 반환: 바꾼 행 수."""
```

```sql
UPDATE data_freshness SET valid_until = fetched_at
WHERE kind = 'financials' AND stock_id = ANY(:ids) AND valid_until > :now
```

### 6-1-3. `backend/app/providers/dart.py` (B)

```python
@dataclass(frozen=True)
class FiledReport:
    rcept_no: str                   # 접수번호 14자리 (YYYYMMDD + 일련번호) — 문자열 크기 비교가 시간 순서
    rcept_dt: date
    corp_code: str
    stock_code: str | None          # 비상장이면 None (응답의 빈 문자열 → None)
    report_nm: str                  # 공백을 한 칸으로 정리한 제목. 정정은 "[기재정정]사업보고서 (2025.12)" 형태


class DartClient:
    def list_annual_reports(self, start: date, end: date, page_no: int = 1) -> tuple[list[FiledReport], int]:
        """회사 지정 없이 사업보고서(A001) 목록 한 페이지, 최신순 100건. 정정 공시 포함. 반환: (목록, total_page).
        status 013(데이터 없음)이면 ([], 0). start~end는 90일 이하로 부른다(초과는 호출 측이 나눔)."""
```

요청 파라미터 약속: `list.json`, `bgn_de=start(YYYYMMDD)`, `end_de=end`, `pblntf_ty="A"`, `pblntf_detail_ty="A001"`, `sort="date"`, `sort_mth="desc"`, `page_no`, `page_count=100`. `corp_code`·`last_reprt_at`은 보내지 않아요. `_get`을 거치므로 `_limiter`·`_throttle`이 그대로 걸려요.

`backend/app/providers/factory.py` `[S8-B]`: `Providers`에 `kr_feed: DartClient | None = None` 필드 추가, `default_providers()`에서 DART 키가 있으면 재무용과 **같은** `DartClient` 인스턴스를 넣어요.

`backend/tests/fakes.py` `[S8-B]`:

```python
class FakeDartFeed(CallLog):
    """list_annual_reports만 흉내. pages: 호출 순서대로 돌려줄 (목록, total_page). fail_on: 이 번째 호출에서 ProviderError."""
    source = "DART"
    def __init__(self, pages: list[tuple[list[FiledReport], int]], fail_on: int | None = None): ...
    def list_annual_reports(self, start: date, end: date, page_no: int = 1) -> tuple[list[FiledReport], int]: ...
```

`make_providers(..., kr_feed=None)` 키워드 추가.

### 6-1-4. `backend/app/ingest/jobs.py` — 공시 증분 (B)

```python
FEED_SOURCE = "DART_A001"      # ingest_cursor.source
FEED_OVERLAP_DAYS = 2          # 기준점 날짜보다 이만큼 앞부터 다시 받는다(늦게 반영되는 공시)
FEED_WINDOW_DAYS = 90          # 회사 지정 없는 list.json 조회 기간 상한
FEED_FIRST_DAYS = 7            # 기준점이 없을 때 처음 받는 기간


def load_dart_feed(engine: Engine, providers: Providers, *, today: date | None = None) -> dict:
    """새 사업보고서(정정 포함)를 낸 DB 종목의 재무 유효기간을 끝내고 공시 행을 넣는다. 기준점은 모두 성공한 뒤에만 옮긴다.
    반환: {"status": "SUCCESS"|"FAILED"|"SKIPPED", "pages": int, "filings": int, "matched": int, "expired": int,
           "cursor": str | None}"""
```

동작 (순서 그대로):

1. `providers.kr_feed`가 None이면 `{"status": "SKIPPED", ...0, "cursor": None}` 반환(로그 없음).
2. `today = today or 서울 날짜`. 기준점 읽기: 행이 있으면 `last_no, start = 행.last_rcept_no, 행.last_rcept_dt − FEED_OVERLAP_DAYS`. 없으면 `last_no = "00000000000000"`, `start = today − FEED_FIRST_DAYS`.
3. `job_log(engine, source="DART", job_type="DISCLOSURES", label="feed A001")` 안에서 4~8을 해요(예외는 FAILED 기록 후 삼킴 → 반환 `status: "FAILED"`, 기준점 그대로).
4. `[start, today]`를 앞에서부터 `FEED_WINDOW_DAYS`일씩 나눈 구간을 **오래된 구간부터** 차례로. 구간마다 `page = 1`부터: `LockSession`의 `hold(DART_LOCK_KEY)` 안에서 `list_annual_reports(구간 시작, 구간 끝, page)` → `new = [x for x in items if x.rcept_no > last_no]` 모으기(키 `rcept_no`로 중복 제거) → `len(new) < len(items)`(기준점에 닿음) 또는 `page >= total_page`면 그 구간 끝, 아니면 `page += 1`.
5. 모은 것 중 `"사업보고서" in report_nm`만 남겨요.
6. `SELECT stock_id, corp_code FROM stocks WHERE corp_code = ANY(:codes) AND is_active` 로 DB 종목만 골라요.
7. 한 트랜잭션에서: 고른 공시를 `disclosures`에 upsert(`stock_id, rcept_no, title=report_nm, report_type="정기공시", filed_at=rcept_dt 00:00 서울, url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}", data_source="DART"`, 충돌 키 `["rcept_no"]`) → `expired = freshness.expire_financials(conn, 고른 stock_id 목록)` → 기준점 upsert: 모은 것이 있으면 가장 큰 `rcept_no`와 그 `rcept_dt`, 없고 행도 없으면 `(f"{start:%Y%m%d}000000", start)`, 없고 행이 있으면 그대로.
8. `res.rows = 고른 공시 수`, 비고 `pages=… filings=… matched=… expired=…`.

#### `_fetch_financials` 빈 응답 규칙 (8-1에서 추가)

`get_annual_financials`가 빈 목록이면 `raise ProviderError("재무 빈 응답")` — 잠금 블록 바로 다음 줄. 공시 직후 재무 API가 아직 비어 있을 때 최신으로 기록하지 않고 FAILED(1일 뒤 재시도)로 두려는 거예요. 이 규칙 때문에 빈 응답을 SUCCESS로 기대하던 테스트가 있으면 함께 고쳐요.

### 6-1-5. `backend/app/ingest/benchmark.py` — `run_benchmark` (D)

상장 종목 목록 동기화 블록 바로 다음, 선정 전에:

```python
            try:                              # 새 사업보고서를 낸 종목의 재무를 먼저 만료시킨다 → 아래 재무 갱신 대상
                out["feed"] = jobs.load_dart_feed(engine, providers, today=today)
            except Exception as e:  # noqa: BLE001 — 실패 사유는 load_dart_feed의 ingestion_logs 행에 남는다
                res.notes.append(f"공시 증분 실패: {e}")
```

### 6-1-6. `backend/app/ingest/dart_bulk.py` (B, 새) — 첫 적재(로컬, API 호출 없음)

```python
"""OpenDART 재무정보 일괄다운로드(사업보고서) txt → financial_statements. 개발 PC에서 한 번 돌리는 첫 적재 (D10).

계정 규칙은 DART API 적재와 같다: ACCOUNT_MAP(account_id 후보 → account_nm 후보), 연결 우선 → 별도.
"""
ENCODING = "cp949"
REQUIRED_COLUMNS: tuple[str, ...] = (...)   # 확인 뒤 채움(아래 '먼저 확인할 것')


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
    """헤더 이름으로 열을 찾는다(위치로 찾지 않음). REQUIRED_COLUMNS 중 없는 열이 있으면 ValueError(없는 열 이름 목록)."""


def to_financials(rows: list[BulkRow]) -> dict[str, list[Financial]]:
    """종목코드 → FY 재무 목록(결산일 오름차순). 회사·결산일마다 연결 행이 있으면 연결만, 없으면 별도만.
    Financial은 data_source="DART", accounting_std="K-IFRS", period_type="FY", 별도면 notes=["fs_div=OFS"]."""


def load_bulk(engine: Engine, paths: list[Path], *, as_of: date, years: int = 4) -> dict:
    """파일들을 읽어 DB 종목(stocks.ticker, 국내 시장)에 맞는 회사만 최근 years개 FY를 upsert.
    회사마다 freshness.mark(financials, SUCCESS) — BatchWriter 사용(flush_every 기본값).
    기준점: ingest_cursor(DART_A001)가 없거나 last_rcept_dt < as_of이면 (f"{as_of:%Y%m%d}000000", as_of)로 둔다.
    로그: ingestion_logs 1행(source="DART_BULK", job_type="FINANCIALS", stock_id NULL, label=f"bulk {as_of}").
    반환: {"files": n, "companies": 맞춘 회사 수, "rows": upsert 행 수, "skipped": DB에 없는 회사 수}"""
```

`source="DART_BULK"`인 이유: 8-2의 하루 예산은 `source='DART'` 행만 세서, 일괄 적재가 그날 예산을 먹지 않게 해요.

CLI (`__main__.py` `[S8-B]`):

```
python -m app.ingest dart-feed
python -m app.ingest dart-bulk --as-of 2026-10-15 --years 4 FILE [FILE ...]
```

**먼저 확인할 것 (B, 코드 전에 — 결과를 이 절에 표로 채워요)**

1. 일괄다운로드 파일의 실제 헤더 이름·인코딩·종목코드 형식(`[005930]`?)·금액 형식 → `REQUIRED_COLUMNS`와 `BulkRow` 매핑 표
2. 재무제표 종류 값 → `statement`(BS·IS·CIS)·`consolidated` 판정 규칙 표
3. 표본 3종목(삼성전자 005930, 현대차 005380, NAVER 035420)의 같은 연도 값이 API(`fnlttSinglAcntAll`) 적재 값과 같은지. 다르면 항목코드 대응표를 `dart_bulk.py` 상수로 추가
4. 적재 뒤 `SELECT pg_size_pretty(pg_database_size(current_database()))` — 무료 500MB에 여유가 적으면 `--years`를 줄여요(D10)

### 6-1-7. 테스트 (B)

| 파일 | 테스트 이름 | 확인하는 것 |
| --- | --- | --- |
| `test_dart_feed.py` | `test_feed_expires_only_db_stocks_and_moves_cursor` | 목록 3건(DB 종목 1·DB에 없는 회사 1·사업보고서 아닌 제목 1) → 공시 1행, 재무 만료 1, 기준점 = 가장 큰 rcept_no |
| | `test_feed_stops_at_cursor` | 2페이지째에 기준점 이하 번호 → 3페이지를 부르지 않음(`FakeDartFeed.count`) |
| | `test_feed_failure_keeps_cursor` | 2번째 호출 실패 → `status: "FAILED"`, 기준점 그대로, 공시 0행 |
| | `test_feed_splits_long_gap_into_90_day_windows` | 기준점 200일 전 → 구간 3개(오래된 순 호출 인자 확인) |
| | `test_feed_first_run_starts_7_days_back` | 기준점 없음 → `start = today − 7` |
| | `test_empty_financials_are_failed` | 빈 재무 → FAILED, freshness FAILED |
| `test_dart_bulk.py` | `test_parse_requires_columns` | 열 하나 빠진 파일 → ValueError에 열 이름 |
| | `test_consolidated_preferred_over_separate` | 같은 회사·연도 연결·별도 → 연결 값 |
| | `test_load_bulk_is_idempotent_and_seeds_cursor` | 두 번 적재해도 행 수 그대로, 기준점 `as_of` |

테스트용 txt는 `backend/tests/data/dart_bulk_sample_*.txt`(B, cp949, 확인한 헤더 그대로 5~10행).

---

## 7. 파트 8-2 — 우선순위 백그라운드 적재와 하루 예산 (계획 4-3)

### 7-1. 설정 — `universe.yaml` (D)

```yaml
# 백그라운드 재무 적재(상장 목록 종목을 우선순위대로 미리 받기). 단위: ingestion_logs 행 수(회사 1건 = 1행 ≈ 호출 2~5번)
background:
  dart_calls_per_day: 2000   # 오늘(서울 0시부터) source='DART' 재무·공시 행이 이 수에 닿으면 멈춤 — 키 1개 하루 약 2만 번의 절반 이하 (권하는 시작값)
  sec_calls_per_day: 1000    # source='SEC' 같은 기준 (권하는 시작값)
  run_at_kst: "08:00"        # 07:00 비교군 갱신 뒤
```

값은 계획에 없던 **권하는 시작값**이에요(11절 D12). 키 이름은 계획대로 `*_calls_per_day`이고, 단위가 "로그 행 수"라는 것을 주석으로 못 박아요.

### 7-2. `backend/app/ingest/background.py` (D, 새)

```python
def used_today(conn: Connection, source: str, now: datetime | None = None) -> int:
    """오늘(서울 0시 이후) ingestion_logs에서 source가 같고 job_type IN ('FINANCIALS','DISCLOSURES')인 행 수."""


def priority_queue(conn: Connection, country: str, limit: int) -> list[int]:
    """재무 기록(data_freshness kind='financials')이 아예 없는 활성 listed 종목을 우선순위 순으로 limit개.
    순위: (D11 결정에 따름) — 아래 표."""


def run_background(engine: Engine, providers: Providers, *, now: datetime | None = None) -> dict:
    """국가마다 남은 예산 = calls_per_day − used_today. 남은 예산 > 0이면 priority_queue(…, 남은 예산)를
    jobs.load_financials(stock_ids=…, years=benchmark.config()["fin_years"])로 받는다.
    상세 요청은 이 큐와 상관없이 바로 받는다(회사 단위 잠금이라 기다리지 않음).
    반환: {"KR": {"budget": int, "used": int, "queued": int, "statuses": {...}}, "US": {...}}"""
```

로그: `job_log(source="INTERNAL", job_type="BENCHMARK", label="background")` 1행(요약). 스케줄러 연결: `scheduler.py`에 `run_at_kst` 이후 하루 1회 — 비교군과 같은 방식(D).

| 우선순위 | 국내 (KR) | 미국 (US) |
| --- | --- | --- |
| 1 | 거래대금(종가 × 거래량) — `providers.kr_bulk.get_bars_by_date(last_closed_day("KR"))` 1회 호출로 전 종목 | **D11 결정 필요** (11절) |
| 2 (같은 값) | 시가총액 | — |

큐는 테이블 없이 매번 쿼리로 만들어요(상태 저장 없음). 받은 종목은 freshness 기록이 생겨 다음 큐에서 빠지고, 이후에는 8-1 공시 증분으로만 갱신돼요.

### 7-3. 테스트 (D — `test_background.py`)

| 테스트 이름 | 확인하는 것 |
| --- | --- |
| `test_used_today_counts_only_today_and_source` | 어제 행·다른 source 행은 세지 않음 |
| `test_queue_skips_stocks_with_freshness` | 기록 있는 listed·비활성·featured는 큐에 없음 |
| `test_budget_stops_background` | 예산 5, 오늘 사용 3 → 2개만 받음 |
| `test_kr_queue_orders_by_trading_value_then_cap` | 거래대금 같으면 시가총액 순 |

---

## 8. 파트 8-3 — 미국 재무 일괄 수집 (계획 4-2) — D8 결정 뒤 착수

지금 확정하는 것은 인터페이스뿐이에요. 방식(companyfacts.zip 스트리밍 / frames API)은 smoke 결과로 D가 정하고, 정한 날 이 절을 채워요.

```python
# backend/app/providers/sec_bulk.py (C, 새) — 방식과 상관없이 이 시그니처를 지킨다
def get_annual_financials_bulk(ciks: set[str], years: int) -> dict[str, list[Financial]]:
    """CIK → FY 재무 목록(결산일 오름차순). sec.py get_annual_financials와 같은 태그 대체 규칙·같은 Financial 모양.
    data_source="SEC". 받지 못한 CIK는 결과에 없음."""
```

- `jobs.merge_supplement`(yfinance 보완) 규칙은 그대로 써요.
- smoke 비교 기준(D8): 받는 크기, 최대 메모리(Cloud Run 1~2GiB), 지금 태그 대체 규칙(매출 태그 여러 개 등)을 그대로 옮길 수 있는지, 호출 수. 결과는 `docs/smoke_test_result.md`.
- 적재는 `BatchWriter`(4-2절)로, 잠금은 `SEC_LOCK_KEY`를 파일 내려받는 동안 1회.

---

## 9. 파트 8-4 — 노출 종목 확장 (계획 4-4) — D5 결정 뒤 착수

노출 수 N(D5)은 4-1 적재 뒤 다시 잰 적재 시간·DB 크기로 정해요. 그 전까지 25개를 유지해요. 화면 구성(D6)은 확정이라 API 계약만 먼저 정해 둬요.

### 9-1. `GET /stocks` — `sector` 필터 (B)

| 파라미터 | 타입 | 규칙 |
| --- | --- | --- |
| `sector` | string, 선택, 1~32자 | `stocks.sector`와 정확히 일치. `universe.yaml sectors[].name` 밖의 값이면 422 `VALIDATION_ERROR` |

- 기존 `country`·`group`·`q`·`sort`·`order`·`limit`·`offset`·`preset`과 함께 써요(AND). `total`은 필터 뒤 개수.
- `StockRow`에 `sector: str | None` 추가(마지막 필드).
- `stock_list.sql`: `AND (CAST(:sector AS text) IS NULL OR s.sector = :sector)`.

### 9-2. 화면 (A — `stocks.js`)

- 페이지 나누기: 한 페이지 `limit=25`, `offset`으로 이동, `total`로 페이지 수. URL 쿼리 `?page=`로 새로고침해도 유지.
- 필터: 국가 탭(기존) + 섹터 선택(`universe.yaml` 섹터 9개 + "전체"). 섹터 목록은 화면 상수(백엔드 호출 없음) — 이름은 `universe.yaml sectors[].name`과 같아야 해요.

### 9-3. 노출 규칙 (D)

D5 수치가 나오면 `universe.yaml stocks` 확장 또는 "노출 = 시가총액 상위 N" 규칙 중 하나를 D가 정하고 이 절에 적어요. 영향: `peer_groups`(테마) 관리, 첫 적재 시간, DB 용량(무료 500MB).

---

## 10. D 선행 계약·껍데기 체크리스트

단계 시작 전에 D가 `stage{N}`에 넣고 `pytest -q`·`python team/tools/check_contract.py {N}` 통과를 확인해요. 팀원은 아래 이름을 ✅ 있음으로 써요.

### 10-1. Stage 7

| # | 무엇 | 파일 | 종류 |
| --- | --- | --- | --- |
| 1 | `SEC_LOCK_KEY`·`LOCK_WAIT_NOTE_SECONDS`·`provider_lock_key`·`error_text`·`default_flush_every`·`LockSession`·`Unit`·`write_logs`·`BatchWriter` + `test_store_batch.py` | `ingest/store.py` | 완성본 |
| 2 | `due(..., limit=)` | `services/freshness.py` | 완성본 |
| 3 | `sessions_between` | `services/market_calendar.py` | 완성본 |
| 4 | `benchmark.fin_daily_budget`, `ingest.flush_every` | `config/universe.yaml` | 완성본 |
| 5 | `MarketConditionOut`, `StockDetailOut.market_condition` | `schemas/api.py` `[S7-D]` | 완성본 |
| 6 | `stock_detail`의 `get_condition` 연결 | `api/stocks.py` | 완성본 |
| 7 | `get_condition` → 5-6 첫 예시 dict | `services/market_condition.py` | [껍데기] C |
| 8 | `FinBasisOut`, `ScoreOut.fin_basis`, `_attractiveness`의 예시 값 | `api/analysis.py` | 필드 완성 + [껍데기] B |
| 9 | `fiscal_year_mix` 예시 값 | `services/data_quality.py` | [껍데기] C |

`team/contracts/stage7.toml`의 `[[planned]]`:

```toml
[[planned]]
owner = "C"
names = ["app.services.market_condition", "query:sector_flow", "query:fin_basis", "app.services.sentiment:latest_stored"]

[[planned]]
owner = "B"
names = ["app.ingest.jobs:_fetch_financials", "app.ingest.jobs:_fetch_disclosures"]
```

### 10-2. Stage 8

| # | 무엇 | 파일 | 종류 |
| --- | --- | --- | --- |
| 1 | `008_ingest_cursor.sql` + schema + conftest `TABLES` | DB | 완성본 |
| 2 | `expire_financials` | `services/freshness.py` | 완성본 |
| 3 | `Providers.kr_feed`(None 기본) | `providers/factory.py` | 필드만 — B가 `[S8-B]`에서 채움 |
| 4 | `load_dart_feed` → `{"status": "SKIPPED", "pages": 0, "filings": 0, "matched": 0, "expired": 0, "cursor": None}` | `ingest/jobs.py` | [껍데기] B |
| 5 | `run_benchmark`의 `load_dart_feed` 호출 | `ingest/benchmark.py` | 완성본 |

---

## 11. 결정이 더 필요한 것

| # | 질문 | 권하는 답 | 왜 |
| --- | --- | --- | --- |
| D11 | 미국 listed 우선순위(거래대금)를 어디서 구할지 | `us_rank_pool`(1,500) 안에서만, `classify_us`가 매달 구하는 시가총액 순. 시가총액을 `stocks`에 저장할 열 1개(`market_cap_rank_krw` 등) 추가가 필요해 D가 마이그레이션 | 미국은 전 종목 일괄 시세 무료 소스가 없어 거래대금을 매일 구하려면 호출이 커요 |
| D12 | 백그라운드 하루 예산 값 | DART 2,000행 · SEC 1,000행으로 시작, 첫 주 `ingestion_logs`로 조정 | DART 키 1개 하루 약 2만 번 중 절반 이하(행당 2~5번) |
| D5 | 노출 종목 수 | 계획대로 4-1 뒤 측정 | — |
| D8 | 미국 일괄 방식 | 계획대로 smoke 뒤 | — |

---

## 12. 계획 문서와 비교해 이 정의서가 새로 정하거나 다르게 정한 것

계획의 결정(D1~D10)은 그대로예요. 아래는 계획에 없던 세부를 구현 가능하게 정한 것이에요. 다르게 하고 싶으면 이 표에서 고쳐 주세요.

| # | 항목 | 정한 것 | 이유 |
| --- | --- | --- | --- |
| 1 | `market_condition` 필드 | 계획 9개 + `sector_sample`·`sector_as_of`·`index_code` | 화면 문장(표본 부족 안내)·툴팁(지수 이름, 섹터 날짜)에 필요 |
| 2 | 섹터 기준일 | 마지막 마감 거래일이 아니라 "표본 5개 이상이 일봉을 가진 가장 최근 날짜(ref_date)" | 비교군 일봉은 07:00에만 들어와서, 마감 거래일을 고정하면 매일 저녁~아침에 섹터가 빠져요 |
| 3 | 캐시 | "하루 캐시" → **1시간** + 표본 5개 이상일 때만 저장 | 07:00 일봉이 들어와도 같은 기준일 키로 하루 내내 옛 값이 남는 문제 |
| 4 | 시장 심리 오래됨 판정 | 거래소 달력 거래일 수(`sessions_between`), 달력을 못 쓰면 달력일 7일 | 계획의 "5거래일"을 휴장일까지 정확히 세려고 |
| 5 | 표본 부족 문구 | `섹터 표본이 적어 시장 심리만 반영했습니다` | 계획은 섹터 없음 문구(D9)만 있었어요 |
| 6 | 툴팁의 섹터 미반영 마지막 줄 | `시장 심리 100%(섹터 미반영), 투자 권유 아님` | 비중이 실제와 다르게 보이지 않게 |
| 7 | 점수 반올림 | HALF_UP 정수 | 파이썬 `round`는 짝수 반올림이라 50.5 → 50이 돼요 |
| 8 | FY 기준 표기 위치 | `attractiveness.fin_basis` + '계산 근거' 안 한 줄 | 계획은 "data_quality에 넣을 수 있다"까지였어요. 저장된 `stock_scores.data_quality`에 넣으면 지난 점수까지 다시 계산해야 해서 응답 계산으로 |
| 9 | 백그라운드 예산 단위 | 키 이름은 계획대로, 단위는 "ingestion_logs 행 수" | 계획이 "DART 행 수로 계산"이라고 해서 |
| 10 | 일괄 적재 로그 source | `DART_BULK` | 예산 계산에서 빼려고 |
| 11 | 공시 증분 로그 | 새 job_type 없이 `DISCLOSURES`/`label="feed A001"` | `ingestion_logs` CHECK 변경(마이그레이션)을 피하려고 |
| 12 | 재무 freshness 실패 사유 | 고정 문구 → 실제 사유 | 묶음 저장 실패와 수집 실패를 구분하려고 |
| 13 | `_load_valuation_base` | 삭제(내용은 `fundamental_bases` 행 + `on_flush`로 이동) | 묶음 저장과 "재무 저장 뒤 파생" 순서를 지키려고 |
| 14 | 첫 실행 공시 증분 범위 | 기준점 없으면 7일 전부터, 일괄 적재가 기준점을 `as_of`로 심음 | 일괄 적재와 증분 사이 빈틈이 없게 |
