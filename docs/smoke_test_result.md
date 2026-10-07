# Smoke Test 결과

- 실행 시각: 2026-10-07T10:35:12+09:00
- PRICE_SOURCE_KR=pykrx, KRX 로그인 설정=예
- pykrx 1.2.9, yfinance 1.7.0

## pykrx

| 항목 | 결과 | 상세 |
|---|---|---|
| 일봉 get_market_ohlcv(adjusted=True) | OK | 005930 수정주가 20행, 컬럼=['시가', '고가', '저가', '종가', '거래량', '등락률'] |
| 시가총액 get_market_cap | OK | 005930 20행, 컬럼=['시가총액', '거래량', '거래대금', '상장주식수'] |
| 펀더멘털 get_market_fundamental | OK | 005930 20행, 컬럼=['BPS', 'PER', 'PBR', 'EPS', 'DIV', 'DPS'] |
| 지수 KOSPI(1001) | OK | 1001 20행, 컬럼=['시가', '고가', '저가', '종가', '거래량', '거래대금', '상장시가총액'] |
| 지수 KOSDAQ(2001) | OK | 2001 20행, 컬럼=['시가', '고가', '저가', '종가', '거래량', '거래대금', '상장시가총액'] |

### 국내 티커 검증 (pykrx 종목명)

| 티커 | 설정 이름 | pykrx 이름 | 일치 |
|---|---|---|---|
| 005930 | 삼성전자 | 삼성전자 | O |
| 000660 | SK하이닉스 | SK하이닉스 | O |
| 005380 | 현대차 | 현대차 | O |
| 000270 | 기아 | 기아 | O |
| 035420 | NAVER | NAVER | O |
| 035720 | 카카오 | 카카오 | O |
| 373220 | LG에너지솔루션 | LG에너지솔루션 | O |
| 006400 | 삼성SDI | 삼성SDI | O |
| 247540 | 에코프로비엠 | 에코프로비엠 | O |
| 207940 | 삼성바이오로직스 | 삼성바이오로직스 | O |
| 068270 | 셀트리온 | 셀트리온 | O |
| 005490 | POSCO홀딩스 | POSCO홀딩스 | O |
| 004020 | 현대제철 | 현대제철 | O |
| 012450 | 한화에어로스페이스 | 한화에어로스페이스 | O |
| 047810 | 한국항공우주 | 한국항공우주 | O |
| 064350 | 현대로템 | 현대로템 | O |

## yfinance

### 종목 일봉(2년, auto_adjust=True) 및 거래소 검증

| 시장 | 티커 | 심볼 | 행 수 | 첫 날짜 | 마지막 날짜 | 통화 | 거래소 | 결과 |
|---|---|---|---|---|---|---|---|---|
| KOSPI | 005930 | 005930.KS | 486 | 2024-10-07 | 2026-10-07 | KRW | KSC | OK |
| KOSPI | 000660 | 000660.KS | 486 | 2024-10-07 | 2026-10-07 | KRW | KSC | OK |
| KOSPI | 005380 | 005380.KS | 486 | 2024-10-07 | 2026-10-07 | KRW | KSC | OK |
| KOSPI | 000270 | 000270.KS | 486 | 2024-10-07 | 2026-10-07 | KRW | KSC | OK |
| KOSPI | 035420 | 035420.KS | 486 | 2024-10-07 | 2026-10-07 | KRW | KSC | OK |
| KOSPI | 035720 | 035720.KS | 486 | 2024-10-07 | 2026-10-07 | KRW | KSC | OK |
| KOSPI | 373220 | 373220.KS | 486 | 2024-10-07 | 2026-10-07 | KRW | KSC | OK |
| KOSPI | 006400 | 006400.KS | 486 | 2024-10-07 | 2026-10-07 | KRW | KSC | OK |
| KOSDAQ | 247540 | 247540.KQ | 486 | 2024-10-07 | 2026-10-07 | KRW | KOE | OK |
| KOSPI | 207940 | 207940.KS | 486 | 2024-10-07 | 2026-10-07 | KRW | KSC | OK |
| KOSPI | 068270 | 068270.KS | 486 | 2024-10-07 | 2026-10-07 | KRW | KSC | OK |
| KOSPI | 005490 | 005490.KS | 486 | 2024-10-07 | 2026-10-07 | KRW | KSC | OK |
| KOSPI | 004020 | 004020.KS | 486 | 2024-10-07 | 2026-10-07 | KRW | KSC | OK |
| KOSPI | 012450 | 012450.KS | 486 | 2024-10-07 | 2026-10-07 | KRW | KSC | OK |
| KOSPI | 047810 | 047810.KS | 486 | 2024-10-07 | 2026-10-07 | KRW | KSC | OK |
| KOSPI | 064350 | 064350.KS | 486 | 2024-10-07 | 2026-10-07 | KRW | KSC | OK |
| NASDAQ | AAPL | AAPL | 501 | 2024-10-07 | 2026-10-06 | USD | NMS | OK |
| NASDAQ | MSFT | MSFT | 501 | 2024-10-07 | 2026-10-06 | USD | NMS | OK |
| NASDAQ | GOOGL | GOOGL | 501 | 2024-10-07 | 2026-10-06 | USD | NMS | OK |
| NASDAQ | AMZN | AMZN | 501 | 2024-10-07 | 2026-10-06 | USD | NMS | OK |
| NASDAQ | NVDA | NVDA | 501 | 2024-10-07 | 2026-10-06 | USD | NMS | OK |
| NASDAQ | META | META | 501 | 2024-10-07 | 2026-10-06 | USD | NMS | OK |
| NASDAQ | TSLA | TSLA | 501 | 2024-10-07 | 2026-10-06 | USD | NMS | OK |
| NASDAQ | AVGO | AVGO | 501 | 2024-10-07 | 2026-10-06 | USD | NMS | OK |
| NASDAQ | AMD | AMD | 501 | 2024-10-07 | 2026-10-06 | USD | NMS | OK |

### 지수·환율 (2년)

| 코드 | 심볼 | 행 수 | 마지막 날짜 | 마지막 종가 | 인덱스 tz |
|---|---|---|---|---|---|
| KOSPI | ^KS11 | 487 | 2026-10-07 | 6915.8901 | Asia/Seoul |
| KOSDAQ | ^KQ11 | 487 | 2026-10-07 | 911.7100 | Asia/Seoul |
| SPX | ^GSPC | 501 | 2026-10-06 | 7818.9302 | America/New_York |
| IXIC | ^IXIC | 501 | 2026-10-06 | 27599.8867 | America/New_York |
| DJI | ^DJI | 501 | 2026-10-06 | 51521.2812 | America/New_York |
| USD/KRW | KRW=X | 518 | 2026-10-07 | 1338.4800 | Europe/London |

### 밸류에이션 필드 (Ticker.info)

| 심볼 | marketCap | trailingPE | priceToBook | trailingEps | bookValue | sharesOutstanding | currency |
|---|---|---|---|---|---|---|---|
| 005930.KS | 1799238304399360 | None | None | None | None | 5764191903 | KRW |
| 247540.KQ | 12423723483136 | None | None | None | None | 97824591 | KRW |
| AAPL | 4869056364544 | 38.17277 | 45.330162 | 8.74 | 7.36 | 14594180000 | USD |
| NVDA | 5776928145408 | 30.207071 | 25.228304 | 7.92 | 9.483 | 24147000000 | USD |

### 재무제표 (연간, 보완용)

| 심볼 | income_stmt 기간 수 | 기간 | 주요 행 존재 |
|---|---|---|---|
| AAPL | 4 | ['2025-09-30', '2024-09-30', '2023-09-30', '2022-09-30'] | Total Revenue=O, Operating Income=O, Net Income=O, Total Assets=O, Stockholders Equity=O, Total Debt=O |
| 005930.KS | 4 | ['2025-12-31', '2024-12-31', '2023-12-31', '2022-12-31'] | Total Revenue=O, Operating Income=O, Net Income=O, Total Assets=O, Stockholders Equity=O, Total Debt=O |

## OpenDART

| 항목 | 결과 | 상세 |
|---|---|---|
| corpCode.xml 티커→corp_code | OK | 전체 119558개 법인, 매핑 16/16, 누락=[] |
| 공시검색 list.json (삼성전자 1년) | OK | status=000, total=2898, 필드=['corp_code', 'corp_name', 'stock_code', 'corp_cls', 'report_nm', 'rcept_no', 'flr_nm', 'rcept_dt', 'rm'] |
| 단일회사 전체재무제표 2025 사업보고서 CFS(연결) | OK | status=000, 229행, Revenue=O, OperatingIncomeLoss=O, ProfitLoss=O, Assets=O, Equity=O, Liabilities=O |
| 단일회사 전체재무제표 2021 사업보고서 CFS(연결) | OK | status=000, 186행, Revenue=O, OperatingIncomeLoss=O, ProfitLoss=O, Assets=O, Equity=O, Liabilities=O |

## SEC EDGAR

| 항목 | 결과 | 상세 |
|---|---|---|
| company_tickers.json 티커→CIK | OK | 매핑 9/9: {'NVDA': '0001045810', 'AAPL': '0000320193', 'GOOGL': '0001652044', 'MSFT': '0000789019', 'AMZN': '0001018724', 'META': '0001326801', 'AVGO': '0001730168', 'TSLA': '0001318605', 'AMD': '0000002488'} |
| submissions (AAPL) | OK | recent 필드=['accessionNumber', 'filingDate', 'reportDate', 'acceptanceDateTime', 'act', 'form', 'fileNumber', 'filmNumber']..., 건수=1000 |
| companyfacts (AAPL) | OK | Revenues=O, RevenueFromContractWithCustomerExcludingAssessedTax=O, OperatingIncomeLoss=O, NetIncomeLoss=O, Assets=O, StockholdersEquity=O, LongTermDebt=O; NetIncomeLoss 10-K FY end 최근=['2020-09-26', '2021-09-25', '2022-09-24', '2023-09-30', '2024-09-28', '2025-09-27'] |
