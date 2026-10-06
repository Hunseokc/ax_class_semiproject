# 인덱스 전후 EXPLAIN 비교 (실제 실행 결과)

- 실행 시각: 2026-10-06T21:51:44+09:00
- 명령: `python -m app.ingest explain` / 각 쿼리 7회 실행, 실행 시간은 중앙값
- '인덱스 전'은 트랜잭션 안에서 해당 인덱스를 DROP 후 측정하고 ROLLBACK

## 요약

| 쿼리 | 인덱스 | 행 수 | 인덱스 전 계획 | 전(ms) | 인덱스 후 계획 | 후(ms) |
|---|---|---|---|---|---|---|
| 종목별 최근 공시 5건 (종목 상세 '최근 공시') | `ix_disclosures_stock_filed` | 1,349 | Seq Scan | 0.040 | Index Scan (ix_disclosures_stock_filed) | 0.005 |
| 특정 거래일의 전 종목 시세 (거래량 순위·날짜 단위 조회) | `ix_daily_prices_trade_date` | 12,276 | Seq Scan | 0.233 | Bitmap Heap Scan, Bitmap Index Scan | 0.012 |
| 종목별 최신 FY 재무 5건 (재무 추이) | `ix_fin_stock_type_end` | 125 | Seq Scan | 0.007 | Seq Scan | 0.007 |
| 종목별 최신 밸류에이션 1행 — 삭제한 인덱스가 PK(stock_id, as_of)와 기능이 겹치는지 확인 (A-34) | `ix_valuation_stock_asof` | 3,881 | Index Scan Backward (valuation_snapshots_pkey) | 0.005 | Index Scan (ix_valuation_stock_asof) | 0.005 |

## 종목별 최근 공시 5건 (종목 상세 '최근 공시')

- 인덱스: `ix_disclosures_stock_filed` / 테이블 `disclosures` 약 1,349행
- 쿼리 (파라미터 {'sid': '14'}):
```sql
SELECT rcept_no, title, filed_at FROM disclosures WHERE stock_id = :sid ORDER BY filed_at DESC LIMIT 5
```
### 인덱스 전 (중앙값 0.040 ms)
```
Limit  (cost=53.59..53.60 rows=5 width=64) (actual time=0.039..0.040 rows=5 loops=1)
  Buffers: shared hit=35
  ->  Sort  (cost=53.59..53.85 rows=104 width=64) (actual time=0.039..0.039 rows=5 loops=1)
        Sort Key: filed_at DESC
        Sort Method: top-N heapsort  Memory: 26kB
        Buffers: shared hit=35
        ->  Seq Scan on disclosures  (cost=0.00..51.86 rows=104 width=64) (actual time=0.021..0.034 rows=104 loops=1)
              Filter: (stock_id = '14'::smallint)
              Rows Removed by Filter: 1245
              Buffers: shared hit=35
Planning Time: 0.007 ms
Execution Time: 0.041 ms
```
### 인덱스 후 (중앙값 0.005 ms)
```
Limit  (cost=0.28..5.80 rows=5 width=64) (actual time=0.002..0.003 rows=5 loops=1)
  Buffers: shared hit=3
  ->  Index Scan using ix_disclosures_stock_filed on disclosures  (cost=0.28..115.17 rows=104 width=64) (actual time=0.002..0.003 rows=5 loops=1)
        Index Cond: (stock_id = '14'::smallint)
        Buffers: shared hit=3
Planning Time: 0.011 ms
Execution Time: 0.005 ms
```

## 특정 거래일의 전 종목 시세 (거래량 순위·날짜 단위 조회)

- 인덱스: `ix_daily_prices_trade_date` / 테이블 `daily_prices` 약 12,276행
- 쿼리 (파라미터 {'d': '2026-10-06'}):
```sql
SELECT stock_id, close, volume FROM daily_prices WHERE trade_date = :d ORDER BY volume DESC
```
### 인덱스 전 (중앙값 0.233 ms)
```
Sort  (cost=278.00..278.06 rows=24 width=18) (actual time=0.218..0.218 rows=16 loops=1)
  Sort Key: volume DESC
  Sort Method: quicksort  Memory: 25kB
  Buffers: shared hit=124
  ->  Seq Scan on daily_prices  (cost=0.00..277.45 rows=24 width=18) (actual time=0.014..0.217 rows=16 loops=1)
        Filter: (trade_date = '2026-10-06'::date)
        Rows Removed by Filter: 12260
        Buffers: shared hit=124
Planning Time: 0.006 ms
Execution Time: 0.220 ms
```
### 인덱스 후 (중앙값 0.012 ms)
```
Sort  (cost=65.52..65.58 rows=24 width=18) (actual time=0.008..0.008 rows=16 loops=1)
  Sort Key: volume DESC
  Sort Method: quicksort  Memory: 25kB
  Buffers: shared hit=19
  ->  Bitmap Heap Scan on daily_prices  (cost=4.47..64.97 rows=24 width=18) (actual time=0.002..0.006 rows=16 loops=1)
        Recheck Cond: (trade_date = '2026-10-06'::date)
        Heap Blocks: exact=17
        Buffers: shared hit=19
        ->  Bitmap Index Scan on ix_daily_prices_trade_date  (cost=0.00..4.46 rows=24 width=0) (actual time=0.001..0.001 rows=17 loops=1)
              Index Cond: (trade_date = '2026-10-06'::date)
              Buffers: shared hit=2
Planning Time: 0.008 ms
Execution Time: 0.011 ms
```

## 종목별 최신 FY 재무 5건 (재무 추이)

- 인덱스: `ix_fin_stock_type_end` / 테이블 `financial_statements` 약 125행
- 쿼리 (파라미터 {'sid': '1'}):
```sql
SELECT period_end, revenue FROM financial_statements WHERE stock_id = :sid AND period_type = 'FY' ORDER BY period_end DESC LIMIT 5
```
### 인덱스 전 (중앙값 0.007 ms)
```
Limit  (cost=3.93..3.95 rows=5 width=13) (actual time=0.006..0.007 rows=5 loops=1)
  Buffers: shared hit=2
  ->  Sort  (cost=3.93..3.95 rows=5 width=13) (actual time=0.006..0.006 rows=5 loops=1)
        Sort Key: period_end DESC
        Sort Method: quicksort  Memory: 25kB
        Buffers: shared hit=2
        ->  Seq Scan on financial_statements  (cost=0.00..3.88 rows=5 width=13) (actual time=0.005..0.005 rows=5 loops=1)
              Filter: ((stock_id = '1'::smallint) AND ((period_type)::text = 'FY'::text))
              Rows Removed by Filter: 120
              Buffers: shared hit=2
Planning Time: 0.018 ms
Execution Time: 0.010 ms
```
### 인덱스 후 (중앙값 0.007 ms)
```
Limit  (cost=3.93..3.95 rows=5 width=13) (actual time=0.006..0.006 rows=5 loops=1)
  Buffers: shared hit=2
  ->  Sort  (cost=3.93..3.95 rows=5 width=13) (actual time=0.006..0.006 rows=5 loops=1)
        Sort Key: period_end DESC
        Sort Method: quicksort  Memory: 25kB
        Buffers: shared hit=2
        ->  Seq Scan on financial_statements  (cost=0.00..3.88 rows=5 width=13) (actual time=0.004..0.005 rows=5 loops=1)
              Filter: ((stock_id = '1'::smallint) AND ((period_type)::text = 'FY'::text))
              Rows Removed by Filter: 120
              Buffers: shared hit=2
Planning Time: 0.011 ms
Execution Time: 0.007 ms
```

## 종목별 최신 밸류에이션 1행 — 삭제한 인덱스가 PK(stock_id, as_of)와 기능이 겹치는지 확인 (A-34)

- 인덱스: `ix_valuation_stock_asof` / 테이블 `valuation_snapshots` 약 3,881행
- 쿼리 (파라미터 {'sid': '1'}):
```sql
SELECT per, pbr, market_cap FROM valuation_snapshots WHERE stock_id = :sid ORDER BY as_of DESC LIMIT 1
```
### 인덱스 전 (중앙값 0.005 ms)
```
Limit  (cost=0.28..0.65 rows=1 width=26) (actual time=0.003..0.003 rows=1 loops=1)
  Buffers: shared hit=3
  ->  Index Scan Backward using valuation_snapshots_pkey on valuation_snapshots  (cost=0.28..88.89 rows=242 width=26) (actual time=0.003..0.003 rows=1 loops=1)
        Index Cond: (stock_id = '1'::smallint)
        Buffers: shared hit=3
Planning Time: 0.010 ms
Execution Time: 0.005 ms
```
### 인덱스 후 (중앙값 0.005 ms)
```
Limit  (cost=0.28..0.65 rows=1 width=26) (actual time=0.003..0.003 rows=1 loops=1)
  Buffers: shared hit=3
  ->  Index Scan using ix_valuation_stock_asof on valuation_snapshots  (cost=0.28..88.89 rows=242 width=26) (actual time=0.003..0.003 rows=1 loops=1)
        Index Cond: (stock_id = '1'::smallint)
        Buffers: shared hit=3
Planning Time: 0.015 ms
Execution Time: 0.005 ms
```

