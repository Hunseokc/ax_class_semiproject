# 인덱스 전후 EXPLAIN 비교 (실제 실행 결과)

- 실행 시각: 2026-10-22T16:37:49+09:00
- 명령: `python -m app.ingest explain` / 각 쿼리 7회 실행, 실행 시간은 중앙값
- '인덱스 전'은 트랜잭션 안에서 해당 인덱스를 DROP 후 측정하고 ROLLBACK

## 요약

| 쿼리 | 인덱스 | 행 수 | 인덱스 전 계획 | 전(ms) | 인덱스 후 계획 | 후(ms) |
|---|---|---|---|---|---|---|
| 종목별 최근 공시 5건 (종목 상세 '최근 공시') | `ix_disclosures_stock_filed` | 1,361 | Seq Scan | 0.082 | Index Scan (ix_disclosures_stock_filed) | 0.013 |
| 특정 거래일의 전 종목 시세 (거래량 순위·날짜 단위 조회) | `ix_daily_prices_trade_date` | 45,126 | Seq Scan | 1.332 | Bitmap Heap Scan, Bitmap Index Scan | 0.032 |
| 종목별 최신 FY 재무 5건 (재무 추이) | `ix_fin_stock_type_end` | 20,896 | Index Scan Backward (financial_statements_stock_id_period_end_period_type_key) | 0.012 | Index Scan (ix_fin_stock_type_end) | 0.013 |
| 종목별 최신 밸류에이션 1행 — 삭제한 인덱스가 PK(stock_id, as_of)와 기능이 겹치는지 확인 (A-34) | `ix_valuation_stock_asof` | 4,580 | Index Scan Backward (valuation_snapshots_pkey) | 0.006 | Index Scan (ix_valuation_stock_asof) | 0.014 |

## 종목별 최근 공시 5건 (종목 상세 '최근 공시')

- 인덱스: `ix_disclosures_stock_filed` / 테이블 `disclosures` 약 1,361행
- 쿼리 (파라미터 {'sid': '14'}):
```sql
SELECT rcept_no, title, filed_at FROM disclosures WHERE stock_id = :sid ORDER BY filed_at DESC LIMIT 5
```
### 인덱스 전 (중앙값 0.082 ms)
```
Limit  (cost=78.77..78.79 rows=5 width=64) (actual time=0.068..0.069 rows=5 loops=1)
  Buffers: shared hit=60
  ->  Sort  (cost=78.77..79.04 rows=106 width=64) (actual time=0.067..0.068 rows=5 loops=1)
        Sort Key: filed_at DESC
        Sort Method: top-N heapsort  Memory: 26kB
        Buffers: shared hit=60
        ->  Seq Scan on disclosures  (cost=0.00..77.01 rows=106 width=64) (actual time=0.014..0.055 rows=106 loops=1)
              Filter: (stock_id = '14'::smallint)
              Rows Removed by Filter: 1255
              Buffers: shared hit=60
Planning Time: 0.023 ms
Execution Time: 0.074 ms
```
### 인덱스 후 (중앙값 0.013 ms)
```
Limit  (cost=0.28..9.67 rows=5 width=64) (actual time=0.008..0.009 rows=5 loops=1)
  Buffers: shared hit=3
  ->  Index Scan using ix_disclosures_stock_filed on disclosures  (cost=0.28..199.33 rows=106 width=64) (actual time=0.007..0.008 rows=5 loops=1)
        Index Cond: (stock_id = '14'::smallint)
        Buffers: shared hit=3
Planning Time: 0.030 ms
Execution Time: 0.017 ms
```

## 특정 거래일의 전 종목 시세 (거래량 순위·날짜 단위 조회)

- 인덱스: `ix_daily_prices_trade_date` / 테이블 `daily_prices` 약 45,126행
- 쿼리 (파라미터 {'d': '2026-10-22'}):
```sql
SELECT stock_id, close, volume FROM daily_prices WHERE trade_date = :d ORDER BY volume DESC
```
### 인덱스 전 (중앙값 1.332 ms)
```
Sort  (cost=1093.22..1093.40 rows=70 width=18) (actual time=1.282..1.283 rows=29 loops=1)
  Sort Key: volume DESC
  Sort Method: quicksort  Memory: 26kB
  Buffers: shared hit=527
  ->  Seq Scan on daily_prices  (cost=0.00..1091.08 rows=70 width=18) (actual time=0.877..1.276 rows=29 loops=1)
        Filter: (trade_date = '2026-10-22'::date)
        Rows Removed by Filter: 45097
        Buffers: shared hit=527
Planning Time: 0.024 ms
Execution Time: 1.290 ms
```
### 인덱스 후 (중앙값 0.032 ms)
```
Sort  (cost=201.78..201.96 rows=70 width=18) (actual time=0.013..0.014 rows=29 loops=1)
  Sort Key: volume DESC
  Sort Method: quicksort  Memory: 26kB
  Buffers: shared hit=16
  ->  Bitmap Heap Scan on daily_prices  (cost=4.83..199.64 rows=70 width=18) (actual time=0.005..0.010 rows=29 loops=1)
        Recheck Cond: (trade_date = '2026-10-22'::date)
        Heap Blocks: exact=14
        Buffers: shared hit=16
        ->  Bitmap Index Scan on ix_daily_prices_trade_date  (cost=0.00..4.82 rows=70 width=0) (actual time=0.002..0.002 rows=29 loops=1)
              Index Cond: (trade_date = '2026-10-22'::date)
              Buffers: shared hit=2
Planning Time: 0.018 ms
Execution Time: 0.019 ms
```

## 종목별 최신 FY 재무 5건 (재무 추이)

- 인덱스: `ix_fin_stock_type_end` / 테이블 `financial_statements` 약 20,896행
- 쿼리 (파라미터 {'sid': '1'}):
```sql
SELECT period_end, revenue FROM financial_statements WHERE stock_id = :sid AND period_type = 'FY' ORDER BY period_end DESC LIMIT 5
```
### 인덱스 전 (중앙값 0.012 ms)
```
Limit  (cost=0.29..21.81 rows=5 width=12) (actual time=0.003..0.004 rows=5 loops=1)
  Buffers: shared hit=4
  ->  Index Scan Backward using financial_statements_stock_id_period_end_period_type_key on financial_statements  (cost=0.29..21.81 rows=5 width=12) (actual time=0.002..0.003 rows=5 loops=1)
        Index Cond: ((stock_id = '1'::smallint) AND ((period_type)::text = 'FY'::text))
        Buffers: shared hit=4
Planning Time: 0.020 ms
Execution Time: 0.007 ms
```
### 인덱스 후 (중앙값 0.013 ms)
```
Limit  (cost=0.29..21.81 rows=5 width=12) (actual time=0.004..0.005 rows=5 loops=1)
  Buffers: shared hit=4
  ->  Index Scan using ix_fin_stock_type_end on financial_statements  (cost=0.29..21.81 rows=5 width=12) (actual time=0.003..0.004 rows=5 loops=1)
        Index Cond: ((stock_id = '1'::smallint) AND ((period_type)::text = 'FY'::text))
        Buffers: shared hit=4
Planning Time: 0.027 ms
Execution Time: 0.009 ms
```

## 종목별 최신 밸류에이션 1행 — 삭제한 인덱스가 PK(stock_id, as_of)와 기능이 겹치는지 확인 (A-34)

- 인덱스: `ix_valuation_stock_asof` / 테이블 `valuation_snapshots` 약 4,580행
- 쿼리 (파라미터 {'sid': '1'}):
```sql
SELECT per, pbr, market_cap FROM valuation_snapshots WHERE stock_id = :sid ORDER BY as_of DESC LIMIT 1
```
### 인덱스 전 (중앙값 0.006 ms)
```
Limit  (cost=0.28..1.72 rows=1 width=26) (actual time=0.002..0.002 rows=1 loops=1)
  Buffers: shared hit=3
  ->  Index Scan Backward using valuation_snapshots_pkey on valuation_snapshots  (cost=0.28..357.82 rows=249 width=26) (actual time=0.002..0.002 rows=1 loops=1)
        Index Cond: (stock_id = '1'::smallint)
        Buffers: shared hit=3
Planning Time: 0.011 ms
Execution Time: 0.005 ms
```
### 인덱스 후 (중앙값 0.014 ms)
```
Limit  (cost=0.28..1.70 rows=1 width=26) (actual time=0.007..0.008 rows=1 loops=1)
  Buffers: shared hit=3
  ->  Index Scan using ix_valuation_stock_asof on valuation_snapshots  (cost=0.28..353.82 rows=249 width=26) (actual time=0.007..0.007 rows=1 loops=1)
        Index Cond: (stock_id = '1'::smallint)
        Buffers: shared hit=3
Planning Time: 0.038 ms
Execution Time: 0.014 ms
```

