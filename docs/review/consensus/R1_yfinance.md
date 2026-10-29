# R1 yfinance 표본 호출 — 결과 (2026-10-29)

> 진행 파일: `개발산출물/컨센서스/진행_컨센서스.md`. 입력: `R0_준비.md`(표본), 요청서 2장(해외 8종 목록).
> 다음 step(R3·R6·R7)은 이 파일만 읽으면 yfinance 쪽 사실을 모두 알 수 있게 적었다.

## 1. 호출 조건

| 항목 | 값 |
|---|---|
| 일시 | 2026-10-29 (KST 오후), 1회 |
| 라이브러리 | `yfinance==1.7.0` (`backend/requirements.txt`, 앱 이미지 `stockmind-api`) |
| 실행 | `docker compose run --rm -v C:/seokhunchoi_Ax_Fullstack/consensus_work:/work api python /work/scripts/r1_yfinance.py` |
| 표본 | AAPL · NVDA · FSLR · EDU(ADR) · `005930.KS` (R0 3절) |
| 호출 | 5종목 × 9속성(요청서 2장 8행, `eps_trend`·`eps_revisions`는 한 행에 두 속성) = 45회, 호출 사이 0.5초 |
| 소요 | 45회 합계 10.7초(가장 긴 것 `get_earnings_dates` 1.1초). 429·차단 없음 |
| 원본 | `consensus_work/raw/R1/<티커>__<속성>.csv`(DataFrame) / `.json`(dict), 요약 `raw/R1/_summary.json`. 요약 스크립트 `scripts/r1_inspect.py`(호출 없음) |

## 2. 커버리지 (8행 × 5종목 = 40칸)

상태 구분: **값** / None / 빈 DataFrame / 오류. 괄호는 행×열.

| 엔드포인트 | AAPL | NVDA | FSLR | EDU (ADR) | 005930.KS |
|---|---|---|---|---|---|
| `earnings_estimate` | 값 (4×7) | 값 (4×7) | 값 (4×7) | 값 (4×7) ※분기 애널리스트 1명 | 값 (4×7) |
| `revenue_estimate` | 값 (4×7) | 값 (4×7) | 값 (4×7) | 값 (4×7) ※분기 3명 | 값 (4×7) |
| `eps_trend` / `eps_revisions` | 값 (4×6) / 값 (4×5) | 값 / 값 | 값 / 값 | 값 / 값 | 값 / 값 ※revisions 모순(4-4절) |
| `growth_estimates` | 값 (5×2) ※LTG 종목값 NaN | 값 (같음) | 값 (같음) | 값 (같음) | 값 (같음) ※지수 비교값이 미국 지수 |
| `get_earnings_dates(limit=12)` | 값 (25×3) | 값 (25×3) | 값 (25×3) | 값 (25×3) | 값 (25×3) |
| `get_recommendations()` | 값 (4×6) | 값 (4×6) | 값 (4×6) | 값 (4×6) | 값 (4×6) |
| `analyst_price_targets` | 값 (dict 5키) | 값 | 값 | 값 | 값 |
| `upgrades_downgrades` | 값 (971×7) | 값 (984×7) | 값 (531×7) | 값 (23×7) | **빈 DataFrame** (열 없음) |

- 40칸 중 **39칸 값, 1칸 빈 DataFrame**(`005930.KS` `upgrades_downgrades`). None·예외는 없다.
- `005930.KS` `upgrades_downgrades` 오류 원문(yfinance가 예외를 던지지 않고 stderr에 찍은 뒤 빈 DataFrame 반환):
  `HTTP Error 404: {"quoteSummary":{"result":null,"error":{"code":"Not Found","description":"No fundamentals data found for symbol: 005930.KS"}}}`
- **국내 티커 판정**: `005930.KS`는 추정치·목표가·월별 의견 카운트는 나오지만 증권사별 이력은 없다. 국내 이력형 의견은 KIS `invest-opinion`(R2)이 유일한 후보다.

## 3. 필드 사전

공통: 행 인덱스 `period` = `0q`(이번 분기) · `+1q`(다음 분기) · `0y`(이번 회계연도) · `+1y`(다음 회계연도). `growth_estimates`만 `LTG`(장기 성장률) 행이 하나 더 있다.

**`0q`의 실제 뜻 = "아직 발표하지 않은 가장 가까운 분기"** (달력상 현재 분기가 아님). 근거: AAPL `0q` avg 1.97891 ≈ `get_earnings_dates`의 다음 발표(2026-11-02) EPS Estimate 1.98, `0q` yearAgoEps 1.85 = 2025-10-30 발표 실적 1.85. NVDA도 `0q` avg 2.47325 ≈ 2026-11-17 예상 2.47. EDU는 2026-10-28에 발표를 마쳐 `0q`가 다음 분기로 넘어갔고 애널리스트 수가 1명으로 줄었다. `0y`도 같은 규칙(AAPL `0y` = 9월 결산 FY2026, 결산은 끝났지만 미발표).

| 엔드포인트 | 필드 | 의미 | 단위 |
|---|---|---|---|
| `earnings_estimate` | `avg` `low` `high` | EPS 추정 평균·최저·최고 | 주당, `currency` 통화 (EDU는 ADS 1주당 USD) |
| | `yearAgoEps` | 1년 전 같은 기간 실적 EPS | 같음 |
| | `numberOfAnalysts` | 추정 애널리스트 수 | 명 |
| | `growth` | avg / yearAgoEps − 1 | **비율**(0.0697 = 6.97%) |
| | `currency` | 통화 | `USD` / `KRW` |
| `revenue_estimate` | `avg` `low` `high` `yearAgoRevenue` | 매출 추정·전년 실적 | **통화 원 단위**(USD 달러, KRW 원. 억·백만 아님) |
| | `numberOfAnalysts` `growth` `currency` | 위와 같음 | |
| `eps_trend` | `current` `7daysAgo` `30daysAgo` `60daysAgo` `90daysAgo` | 같은 기간 EPS 컨센서스 평균의 과거 시점 값 | 주당, 통화 |
| `eps_revisions` | `upLast7days` `upLast30days` `downLast7Days` `downLast30days` | 최근 7·30일 상향·하향한 애널리스트 수 | 명 (60·90일 없음. `downLast7Days`만 대문자 D) |
| `growth_estimates` | `stockTrend` | 종목 성장률 추정(`earnings_estimate.growth`와 비슷하지만 다름: AAPL 0q 0.0717 vs 0.0697, FSLR 0q 0.1018 vs 0.0934 — 계산 기준 미확인) | 비율 |
| | `indexTrend` | **지수**(S&P 500으로 보임) 성장률 추정 — 5종목 모두 같은 값(0q 0.2625, +1q 0.2737, 0y 0.3301, +1y 0.1653, LTG 0.122) | 비율 |
| | (없음) | 요청서가 기대한 **업종(industry)·섹터 대비 값은 yfinance 1.7 응답에 없다** | |
| `get_earnings_dates` | 인덱스 `Earnings Date` | 실적발표 일시, `America/New_York` 시간대(국내 종목도. 005930.KS 02:00−04:00 = 15:00 KST) | datetime(tz) |
| | `EPS Estimate` `Reported EPS` | 발표 직전 컨센서스·실제 EPS | 주당, 종목 통화 |
| | `Surprise(%)` | (실제/예상 − 1) × 100 | **퍼센트**(6.74 = 6.74%) — 다른 엔드포인트의 비율 표기와 다름 |
| `get_recommendations()` | `period` | `0m` `-1m` `-2m` `-3m` (이번 달·1~3개월 전) | 상대 월 라벨, **날짜 없음** |
| | `strongBuy` `buy` `hold` `sell` `strongSell` | 그 달 기준 의견별 애널리스트 수 | 명 |
| `analyst_price_targets` | `current` | **현재 주가**(목표가 아님) | 통화 |
| | `low` `high` `mean` `median` | 목표가 분포 | 통화 |
| | (없음) | 목표가를 낸 애널리스트 수 필드 없음 | |
| `upgrades_downgrades` | 인덱스 `GradeDate` | 의견 발표 일시(시간대 없음) | datetime |
| | `Firm` | 증권사 이름 문자열(코드 없음) | |
| | `ToGrade` `FromGrade` | 바뀐 뒤·앞 등급 원문 | 문자열 (init이면 `FromGrade` 빈칸) |
| | `Action` | `main`(유지) `reit`(재확인) `up` `down` `init`(신규) | 코드 |
| | `priceTargetAction` | `Raises` `Lowers` `Maintains` `Announces`(신규) `Adjusts` / 빈칸 | 코드 |
| | `currentPriceTarget` `priorPriceTarget` | 바뀐 뒤·앞 목표가 | 통화. **없으면 NaN이 아니라 0.0** |

## 4. 엔드포인트별 관찰

### 4-1. 기간 추정(`earnings_estimate`·`revenue_estimate`)

| 종목 | EPS 애널리스트 수 0q/+1q/0y/+1y | 매출 애널리스트 수 | 통화 |
|---|---|---|---|
| AAPL | 27 / 21 / 41 / 41 | 25 / 17 / 38 / 40 | USD |
| NVDA | 44 / 42 / 51 / 52 | 45 / 42 / 54 / 57 | USD |
| FSLR | 22 / 22 / 31 / 31 | 25 / 24 / 31 / 30 | USD |
| EDU | **1 / 1** / 10 / 12 | 3 / 3 / 22 / 21 | USD |
| 005930.KS | 8 / 7 / 33 / 33 | 10 / 14 / 17 / 36 | KRW |

- 중형·ADR도 연간(0y·+1y)은 10명 이상. 분기는 발표 직후 종목(EDU)에서 1명까지 떨어진다 → 표시 최소 건수 규칙 필요(R5 A-4).
- `005930.KS`도 KRW로 값이 나온다. 애널리스트 수 33명 → **시장 컨센서스 성격**(KIS 단일 추정 여부 판정 시 참고값, R2).
- 2026년 표본 값은 큰 변화가 많다(005930.KS 0q growth 6.6082 = +661%, NVDA 0y +95%). 값 자체 이상은 아니나 sanity 범위를 넓게 잡아야 한다(R5).

### 4-2. `eps_trend`·`eps_revisions`

- `eps_trend`는 7·30·60·90일 전 값을 한 번에 준다 → 스냅샷을 쌓지 않아도 최근 90일 리비전은 바로 계산된다. 90일보다 긴 이력은 우리가 스냅샷을 쌓아야 한다.
- `eps_revisions`는 7·30일 상향/하향 **사람 수**만 있다.
- **데이터 모순**: `005930.KS` 0q `upLast7days`=3 > `upLast30days`=1, +1q 2 > 1, 0y 9 > 6 (7일이 30일에 포함되므로 불가능). 미국 4종목에서는 모순 없음. → 국내 티커의 `eps_revisions`는 신뢰하지 않는다.
- 방침상 "리비전은 표시하지 않고 스냅샷만"(진행 파일 G 항목) 후보이므로, 축적 대상은 `eps_trend.current`(기간별)와 `numberOfAnalysts`로 충분하다.

### 4-3. `growth_estimates`

- 열이 `stockTrend`·`indexTrend` 2개뿐이고 `indexTrend`는 모든 종목이 같다(미국 지수). 업종 대비 상대 평가에는 **쓸 수 없다**. `005930.KS`에 미국 지수 값을 비교값으로 주므로 국내는 의미 없음.
- `LTG` 행의 `stockTrend`는 5종목 모두 NaN.
- 판정 초안: **제한적** — `stockTrend`는 `earnings_estimate.growth`와 거의 중복, 지수 비교만 남는다.

### 4-4. `get_earnings_dates(limit=12)`

- `limit=12`를 줬지만 **5종목 모두 25행**(약 6년, 2020-10 ~ 2026-11) 반환. 1.7.0에서 `limit`가 행 수를 제한하지 않는다(최소 25행을 받아 오는 것으로 보임) — R6 호출량 계산에서 "1회 = 25행"으로 본다.
- 첫 행이 다음 발표 예정일(Reported EPS NaN). AAPL 2026-11-02, NVDA 2026-11-17, FSLR 2026-10-29(오늘), 005930.KS 2026-10-28(어제 발표했지만 Reported 아직 NaN — **국내는 반영이 늦다**), EDU는 10-28 발표분까지 반영돼 미래 행 없음.
- 어닝 서프라이즈 이력: 미국 24~25분기 확보 가능. 005930.KS도 24분기(2026-07-29 −1.66%, 2026-04-29 +39.96%).
- R6 "변화 감지 신호": 발표일 + 서프라이즈 → 그 직후 추정치 갱신 트리거로 쓸 수 있다. 정확도(실제 공시일과의 차이)는 R6에서 DART·SEC 8-K와 대조.

### 4-5. `get_recommendations()` — 월별 기간 구조

| 종목 | 0m (sB/B/H/S/sS = 합) | −3m 합 | 3개월 변화 |
|---|---|---|---|
| AAPL | 6/18/13/3/3 = 43 | 46 | buy 22→18 |
| NVDA | 10/49/2/1/0 = 62 | 61 | 거의 불변 |
| FSLR | 10/17/8/0/1 = 36 | 36 | hold 12→8, buy 13→17 |
| EDU | 4/12/4/0/0 = 20 | 21 | 거의 불변 |
| 005930.KS | 11/24/1/0/0 = 36 | 37 | 거의 불변 |

- **4개월치(0m~−3m)만** 오고 날짜가 없다. 라벨 기준일은 호출일의 달로 해석해야 한다(2026-10 = `0m`). 4개월보다 긴 이력은 월 1회 스냅샷으로 쌓아야 한다.
- 이미 5단계 표준화된 카운트라 매핑이 필요 없다. 다만 증권사별 최신 의견이 아니라 Yahoo 내부 집계 규칙이 불투명하다.
- 국내 티커에서도 값이 나온다(36명).

### 4-6. `analyst_price_targets`

| 종목 | current(현재가) | low | median | mean | high | 괴리율(mean/current−1) |
|---|---|---|---|---|---|---|
| AAPL | 343.83 | 245 | 337.5 | 332.39 | 405 | −3.3% |
| NVDA | 215.38 | 180 | 315 | 328.95 | 515 | +52.7% |
| FSLR | 176.30 | 191 | 270 | 274.24 | 402 | +55.6% (현재가 < low) |
| EDU | 50.72 | 56.5 | 72.2 | 72.91 | 90 | +43.7% (현재가 < low) |
| 005930.KS | 230,750 | 290,000 | 450,000 | 478,905.62 | 725,000 | +107.5% (현재가 < low) |

- 괴리율 계산은 **가능**(같은 응답의 `current` 사용, 또는 우리 DB 종가). 애널리스트 수가 없어 "몇 명 기준" 표시는 `earnings_estimate`의 수나 `upgrades_downgrades` 직접 집계로 보완해야 한다.
- 3종목이 현재가 < 최저 목표가, 005930.KS는 +107%. 급락 후 목표가가 늦게 내려오는 경우로 보이며 **sanity 규칙 후보**(괴리율 상한·오래된 목표가 제외, R5 B).

### 4-7. `upgrades_downgrades` — 구분·목표가·날짜 범위

| 종목 | 행 | 날짜 범위 | 증권사 수(전체) | 최근 3/6/12개월 행 | 3/6/12개월 증권사 수 | 목표가 0.0 행 |
|---|---|---|---|---|---|---|
| AAPL | 971 | 2012-09-12 ~ 2026-10-20 | 60 | 31 / 60 / 111 | 19 / 27 / 29 | 22 |
| NVDA | 984 | 2017-08-11 ~ 2026-10-22 | 60 | 31 / 63 / 145 | 21 / 29 / 36 | 23 |
| FSLR | 531 | 2012-02-10 ~ 2026-10-27 | 65 | 21 / 35 / 63 | 16 / 21 / 27 | 66 |
| EDU | 23 | 2022-05-02 ~ 2026-07-30 | 7 | 1 / 2 / 3 | 1 / 2 / 3 | 2 |
| 005930.KS | 0 | — | — | — | — | — |

- 형태: **카운트형(이력형)이고 문장형이 아니다.** 텍스트·리포트 요약 필드는 없다(요청서 4장 C: "yfinance 범위에서 문장형 없음").
- 행 수가 크게 다르다. 연도별 행 수: AAPL 2019 103 · 2023 137 · 2025 144 · 2026 89(10월까지), 2012 1건만 따로 있다 → 2019년 이전은 듬성하다.
- **`Action` 값 분포**(5종목 합): `main` 1,786 · `reit` 320 · `up` 173 · `down` 137 · `init` 93. `main`·`reit`이 대부분 → 등급 변경(up/down)은 전체의 약 12%.
- **`priceTargetAction`**: `Raises` · `Lowers` · `Maintains` · `Announces`(=init과 함께) · `Adjusts` · 빈칸. 빈칸 행은 `currentPriceTarget`가 0.0(목표가 없이 등급만 발표).
- 목표가 필드: `currentPriceTarget`·`priorPriceTarget`, 없으면 **0.0**(NaN 아님) → 집계 시 0을 결측으로 바꿔야 한다. init 행은 `priorPriceTarget`=0.0.
- 같은 증권사의 연속 의견이 쌓여 있어 "증권사별 최신 1건" 규칙으로 줄여야 한다(R3). 12개월 증권사별 최신 등급(직접 집계):
  - AAPL: Buy 9 · Outperform 5 · Neutral 4 · Hold 4 · Overweight 3 · Underweight 2 · Strong Buy 1 · Underperform 1 (29곳)
  - NVDA: Buy 17 · Outperform 8 · Overweight 7 · Strong Buy 2 · Hold 1 · Positive 1 (36곳)
  - FSLR: Buy 12 · Overweight 5 · Outperform 3 · Hold 2 · Neutral 1 · Positive 1 · Underperform 1 · In-Line 1 · Sector Weight 1 (27곳)
  - EDU: Overweight 1 · Buy 1 · Neutral 1 (3곳)
- **월별 집계와 직접 집계의 차이**: `get_recommendations` 0m 합계 AAPL 43 · NVDA 62 · FSLR 36 · EDU 20 vs 12개월 증권사 수 29 · 36 · 27 · 3. Yahoo 월별 집계가 더 많은 애널리스트를 포함한다(특히 ADR EDU 20 vs 3 — 중국계 증권사가 이력에 없음으로 추정, **추측**). R3에서 비교군 전체로 대조한다.

### 4-8. 등급 표기 원문 (표본 5종목 `ToGrade`∪`FromGrade`, 22종)

`Accumulate` `Buy` `Conviction Buy` `Equal-Weight` `Hold` `In-Line` `Market Outperform` `Market Perform` `Market Underperform` `Neutral` `Outperform` `Overweight` `Peer Perform` `Perform` `Positive` `Reduce` `Sector Perform` `Sector Weight` `Sell` `Strong Buy` `Underperform` `Underweight`

- R3 매핑표 초안(확정은 R3, 비교군 전체 표기 수집 후):
  - 매수: Strong Buy, Conviction Buy, Buy, Outperform, Overweight, Market Outperform, Accumulate, Positive
  - 중립: Hold, Neutral, Equal-Weight, Market Perform, Sector Perform, Sector Weight, In-Line, Peer Perform, Perform
  - 매도: Sell, Underperform, Underweight, Market Underperform, Reduce
  - 애매(따로 표시): `Accumulate`(매수/약매수), `Positive`, `Peer Perform`(미평가 성격), `Sector Weight`

## 5. 요청서 2장 "확인이 필요한 점"에 대한 판정 초안

| 엔드포인트 | 확인이 필요한 점 | 판정 초안 | 근거 |
|---|---|---|---|
| `earnings_estimate` | 지표 목록 표시값으로 쓸 수 있나 | **사용 가능** | 5/5 값, 애널리스트 수 포함. 분기 1~3명인 경우 최소 건수 필요 |
| `revenue_estimate` | 위와 같음 | **사용 가능** | 5/5 값, 단위는 통화 원 단위 |
| `eps_trend`·`eps_revisions` | 스냅샷 축적 대상으로 적합한가 | trend **사용 가능**, revisions **제한적** | trend는 90일 과거값 내장. revisions는 국내 티커 모순·60/90일 없음 |
| `growth_estimates` | 업종 대비 상대 평가 | **제한적(업종 비교 불가)** | 업종·섹터 열 없음, 지수값 전 종목 동일, LTG 종목값 NaN |
| `get_earnings_dates` | 어닝 서프라이즈 이력 | **사용 가능** | 24~25분기, `limit` 무시. 국내 반영 지연 |
| `get_recommendations` | 카운트형 의견 | **사용 가능(4개월 한정)** | 5단계 카운트, 날짜 없음, 국내 티커도 값 |
| `analyst_price_targets` | 목표가 괴리율 | **사용 가능 + sanity 필요** | 5/5 값, 인원 수 없음, 현재가<low 3건 |
| `upgrades_downgrades` | 카운트형인지 문장형인지 | **카운트형(이력형), 미국만 사용 가능** | 텍스트 없음, 국내 404, 소형 ADR은 이력 적음 |

## 6. 다음 step에 넘길 것

- **R3**: 비교군 미국 321종목 × (`upgrades_downgrades`·`get_recommendations`·`analyst_price_targets`) = 963회. 1회 평균 약 0.24초(이번 45회 10.7초) + 간격 0.5초 → 약 12분 예상(차단 없을 때). 국내 티커(`.KS`)로 `upgrades_downgrades`를 받는 것은 404이므로 하지 않는다. 0.0 목표가 → 결측, `FromGrade` 빈칸 = init.
- **R4·R5**: `get_recommendations`는 4개월만 → 3·6·12개월 기간 비교는 `upgrades_downgrades` 직접 집계로만 가능(미국). 한 달 전 시점 재구성은 `GradeDate`로 가능.
- **R6**: `get_earnings_dates` 1회 25행, 다음 발표일이 첫 행. `eps_trend` 90일 내장이라 리비전 감지는 일 1회 스냅샷 없이도 가능.
- **R7 부록 발췌**: 위 3절·4절 표와 아래 7절.

## 7. 응답 발췌 (부록용, AAPL)

```
earnings_estimate
period,avg,low,high,yearAgoEps,numberOfAnalysts,growth,currency
0q,1.97891,1.93,2.06,1.85,27,0.069699995,USD
+1y,9.5758,8.5,10.67,8.83476,41,0.083900005,USD

eps_trend
period,current,7daysAgo,30daysAgo,60daysAgo,90daysAgo,currency
0q,1.97891,1.97817,1.97754,1.97656,2.01204,USD

eps_revisions
period,upLast7days,upLast30days,downLast30days,downLast7Days,currency
+1y,1,5,3,0,USD

growth_estimates
period,stockTrend,indexTrend
0q,0.0717,0.2625
LTG,,0.122

get_earnings_dates
Earnings Date,EPS Estimate,Reported EPS,Surprise(%)
2026-11-02 15:00:00-05:00,1.98,,
2026-07-30 16:00:00-04:00,1.89,2.02,6.74

get_recommendations
,period,strongBuy,buy,hold,sell,strongSell
0,0m,6,18,13,3,3
3,-3m,6,22,14,2,2

analyst_price_targets
{"current": 343.83, "high": 405.0, "low": 245.0, "mean": 332.3858, "median": 337.5}

upgrades_downgrades
GradeDate,Firm,ToGrade,FromGrade,Action,priceTargetAction,currentPriceTarget,priorPriceTarget
2026-10-20 18:00:28,MoffettNathanson,Neutral,Neutral,main,Lowers,283.0,304.0
2026-10-20 09:46:57,Loop Capital,Hold,Buy,down,Lowers,330.0,370.0
2025-10-01 12:20:24,Seaport Global,Buy,,init,Announces,310.0,0.0
```

```
005930.KS upgrades_downgrades (빈 DataFrame)
HTTP Error 404: {"quoteSummary":{"result":null,"error":{"code":"Not Found","description":"No fundamentals data found for symbol: 005930.KS"}}}
```
