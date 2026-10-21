# 인덱스 전후 EXPLAIN 비교 (실제 실행 결과)

- 실행 시각: 2026-10-15T17:41:50+09:00
- 명령: `python -m app.ingest explain` / 각 쿼리 7회 실행, 실행 시간은 중앙값
- '인덱스 전'은 트랜잭션 안에서 해당 인덱스를 DROP 후 측정하고 ROLLBACK

## 요약

| 쿼리 | 인덱스 | 행 수 | 인덱스 전 계획 | 전(ms) | 인덱스 후 계획 | 후(ms) |
|---|---|---|---|---|---|---|
| 종목별 최근 공시 5건 (종목 상세 '최근 공시') | `ix_disclosures_stock_filed` | 1,361 | Seq Scan | 0.072 | Index Scan (ix_disclosures_stock_filed) | 0.007 |
| 특정 거래일의 전 종목 시세 (거래량 순위·날짜 단위 조회) | `ix_daily_prices_trade_date` | 10,849 | Seq Scan | 0.253 | Bitmap Heap Scan, Bitmap Index Scan | 0.017 |
| 종목별 최신 FY 재무 5건 (재무 추이) | `ix_fin_stock_type_end` | 125 | Seq Scan | 0.013 | Seq Scan | 0.015 |
| 종목별 최신 밸류에이션 1행 — 삭제한 인덱스가 PK(stock_id, as_of)와 기능이 겹치는지 확인 (A-34) | `ix_valuation_stock_asof` | 3,681 | Index Scan Backward (valuation_snapshots_pkey) | 0.007 | Index Scan (ix_valuation_stock_asof) | 0.008 |

## 종목별 최근 공시 5건 (종목 상세 '최근 공시')

- 인덱스: `ix_disclosures_stock_filed` / 테이블 `disclosures` 약 1,361행
- 쿼리 (파라미터 {'sid': '14'}):
```sql
SELECT rcept_no, title, filed_at FROM disclosures WHERE stock_id = :sid ORDER BY filed_at DESC LIMIT 5
```
### 인덱스 전 (중앙값 0.072 ms)
```
Limit  (cost=51.77..51.79 rows=5 width=64) (actual time=0.058..0.059 rows=5 loops=1)
  Buffers: shared hit=33
  ->  Sort  (cost=51.77..52.04 rows=106 width=64) (actual time=0.058..0.058 rows=5 loops=1)
        Sort Key: filed_at DESC
        Sort Method: top-N heapsort  Memory: 26kB
        Buffers: shared hit=33
        ->  Seq Scan on disclosures  (cost=0.00..50.01 rows=106 width=64) (actual time=0.029..0.046 rows=106 loops=1)
              Filter: (stock_id = '14'::smallint)
              Rows Removed by Filter: 1255
              Buffers: shared hit=33
Planning Time: 0.023 ms
Execution Time: 0.064 ms
```
### 인덱스 후 (중앙값 0.007 ms)
```
Limit  (cost=0.28..3.44 rows=5 width=64) (actual time=0.002..0.003 rows=5 loops=1)
  Buffers: shared hit=3
  ->  Index Scan using ix_disclosures_stock_filed on disclosures  (cost=0.28..67.26 rows=106 width=64) (actual time=0.002..0.003 rows=5 loops=1)
        Index Cond: (stock_id = '14'::smallint)
        Buffers: shared hit=3
Planning Time: 0.011 ms
Execution Time: 0.005 ms
```

## 특정 거래일의 전 종목 시세 (거래량 순위·날짜 단위 조회)

- 인덱스: `ix_daily_prices_trade_date` / 테이블 `daily_prices` 약 10,849행
- 쿼리 (파라미터 {'d': '2026-10-15'}):
```sql
SELECT stock_id, close, volume FROM daily_prices WHERE trade_date = :d ORDER BY volume DESC
```
### 인덱스 전 (중앙값 0.253 ms)
```
Sort  (cost=238.04..238.09 rows=20 width=18) (actual time=0.236..0.236 rows=16 loops=1)
  Sort Key: volume DESC
  Sort Method: quicksort  Memory: 25kB
  Buffers: shared hit=102
  ->  Seq Scan on daily_prices  (cost=0.00..237.61 rows=20 width=18) (actual time=0.232..0.233 rows=16 loops=1)
        Filter: (trade_date = '2026-10-15'::date)
        Rows Removed by Filter: 10833
        Buffers: shared hit=102
Planning Time: 0.013 ms
Execution Time: 0.239 ms
```
### 인덱스 후 (중앙값 0.017 ms)
```
Sort  (cost=56.52..56.57 rows=20 width=18) (actual time=0.007..0.008 rows=16 loops=1)
  Sort Key: volume DESC
  Sort Method: quicksort  Memory: 25kB
  Buffers: shared hit=3
  ->  Bitmap Heap Scan on daily_prices  (cost=4.44..56.09 rows=20 width=18) (actual time=0.003..0.005 rows=16 loops=1)
        Recheck Cond: (trade_date = '2026-10-15'::date)
        Heap Blocks: exact=1
        Buffers: shared hit=3
        ->  Bitmap Index Scan on ix_daily_prices_trade_date  (cost=0.00..4.44 rows=20 width=0) (actual time=0.002..0.002 rows=16 loops=1)
              Index Cond: (trade_date = '2026-10-15'::date)
              Buffers: shared hit=2
Planning Time: 0.018 ms
Execution Time: 0.013 ms
```

## 종목별 최신 FY 재무 5건 (재무 추이)

- 인덱스: `ix_fin_stock_type_end` / 테이블 `financial_statements` 약 125행
- 쿼리 (파라미터 {'sid': '1'}):
```sql
SELECT period_end, revenue FROM financial_statements WHERE stock_id = :sid AND period_type = 'FY' ORDER BY period_end DESC LIMIT 5
```
### 인덱스 전 (중앙값 0.013 ms)
```
Limit  (cost=3.93..3.95 rows=5 width=13) (actual time=0.007..0.007 rows=5 loops=1)
  Buffers: shared hit=2
  ->  Sort  (cost=3.93..3.95 rows=5 width=13) (actual time=0.007..0.007 rows=5 loops=1)
        Sort Key: period_end DESC
        Sort Method: quicksort  Memory: 25kB
        Buffers: shared hit=2
        ->  Seq Scan on financial_statements  (cost=0.00..3.88 rows=5 width=13) (actual time=0.001..0.006 rows=5 loops=1)
              Filter: ((stock_id = '1'::smallint) AND ((period_type)::text = 'FY'::text))
              Rows Removed by Filter: 120
              Buffers: shared hit=2
Planning Time: 0.014 ms
Execution Time: 0.010 ms
```
### 인덱스 후 (중앙값 0.015 ms)
```
Limit  (cost=3.93..3.95 rows=5 width=13) (actual time=0.009..0.010 rows=5 loops=1)
  Buffers: shared hit=2
  ->  Sort  (cost=3.93..3.95 rows=5 width=13) (actual time=0.009..0.009 rows=5 loops=1)
        Sort Key: period_end DESC
        Sort Method: quicksort  Memory: 25kB
        Buffers: shared hit=2
        ->  Seq Scan on financial_statements  (cost=0.00..3.88 rows=5 width=13) (actual time=0.003..0.007 rows=5 loops=1)
              Filter: ((stock_id = '1'::smallint) AND ((period_type)::text = 'FY'::text))
              Rows Removed by Filter: 120
              Buffers: shared hit=2
Planning Time: 0.031 ms
Execution Time: 0.015 ms
```

## 종목별 최신 밸류에이션 1행 — 삭제한 인덱스가 PK(stock_id, as_of)와 기능이 겹치는지 확인 (A-34)

- 인덱스: `ix_valuation_stock_asof` / 테이블 `valuation_snapshots` 약 3,681행
- 쿼리 (파라미터 {'sid': '1'}):
```sql
SELECT per, pbr, market_cap FROM valuation_snapshots WHERE stock_id = :sid ORDER BY as_of DESC LIMIT 1
```
### 인덱스 전 (중앙값 0.007 ms)
```
Limit  (cost=0.28..0.96 rows=1 width=26) (actual time=0.003..0.004 rows=1 loops=1)
  Buffers: shared hit=3
  ->  Index Scan Backward using valuation_snapshots_pkey on valuation_snapshots  (cost=0.28..86.13 rows=127 width=26) (actual time=0.003..0.003 rows=1 loops=1)
        Index Cond: (stock_id = '1'::smallint)
        Buffers: shared hit=3
Planning Time: 0.016 ms
Execution Time: 0.007 ms
```
### 인덱스 후 (중앙값 0.008 ms)
```
Limit  (cost=0.28..0.96 rows=1 width=26) (actual time=0.004..0.004 rows=1 loops=1)
  Buffers: shared hit=3
  ->  Index Scan using ix_valuation_stock_asof on valuation_snapshots  (cost=0.28..86.13 rows=127 width=26) (actual time=0.003..0.004 rows=1 loops=1)
        Index Cond: (stock_id = '1'::smallint)
        Buffers: shared hit=3
Planning Time: 0.018 ms
Execution Time: 0.007 ms
```

