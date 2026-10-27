# sanity 결과 — 수정 3 (검토_장부 D-024~D-030, `매력도_v3_계획.md` 3절의 PR A~D)

> **데이터**: 이 PC에 새로 적재한 개발 DB `stockdb_fix3`(2026-10-27 실데이터 — `init-db` → `master` → `listing` → `benchmark --reselect` → 비교군 재무 3년). 비교 표본 649종목(국내 일반 299·미국 일반 272 + 금융·점수 없음), 일봉·밸류에이션 2026-10-27. 라운드 1~3이 쓴 개발 DB(다른 PC)와 비교군 구성·재무 수집 시점이 달라 **v2.2 기준선부터 결과가 다르다** — 수정 3의 효과는 아래 기준선과의 차이로 읽는다.
> PR마다 `python -m app.ingest scores` → `python -m app.ingest sanity`. 기준선은 점수 계산일 2026-10-27, 각 PR은 2026-10-28(R9가 직전 모델과 비교).
> **4칸**(D-030): 통과 / 감수한 실패(known_fail·결정 번호) / target 실패 / 미검증(데이터 없음·실행 불가). required 실패는 따로 적는다(종료를 막음).

## 기준선 — 모델 v2.2 (수정 3 전, 같은 DB)

**통과 35 · 감수한 실패 1 · target 실패 5 · 미검증 0** · required 실패 3 (required·known_fail 36개 중 통과 + 감수 33)

- required 실패 3개는 수정 3 전부터 이 DB에서 실패한다: DAEHAN-SHIPBUILDING-value(대한조선 가치 13위 ≤ 20), R10-independent-benchmark(이상 18 > 16), CLIP-order(미국 매출 CAGR 0.49 < 0.5). 라운드 3 DB에서는 36/36이었다 — 비교군을 오늘 시가총액으로 다시 골랐고(649종목) 재무를 새로 받았기 때문이다(대한조선 FY2025 반영 등). 합격선은 이 데이터로 바꾸지 않는다(D-030).

<details><summary>기준선 전체 표</summary>

required(known_fail 포함) 통과 **33/36** — 실패: DAEHAN-SHIPBUILDING-value, R10-independent-benchmark, CLIP-order

| id | status | 결과 | 실제 값 |
|---|---|---|---|
| SIRI-growth | required | 통과 | SIRI: 균형 151/272 가치 155/272 성장 185/272 |
| RIVN-growth | required | 통과 | RIVN: 균형 255/272 가치 264/272 성장 196/272 |
| INTC-growth | required | 통과 | INTC: 균형 254/272 가치 257/272 성장 249/272 |
| LOTTE-HOLDINGS-growth | required | 통과 | 004990: 표본에 없음 |
| ASIANA-growth | required | 통과 | 020560: 균형 282/299 가치 284/299 성장 285/299 |
| SARAMIN-balanced | required | 통과 | 143240: 균형 72/299 가치 64/299 성장 178/299 |
| KCC-oneoff-cut | required | 통과 | 순이익/영업이익 3.6배 → e = 0.78 × 영업이익, 지표 0.0882 (기대 0.0882) |
| MICHANG-oneoff-cut | required | 통과 | 순이익/영업이익 2.0배 → e = 0.78 × 영업이익, 지표 0.1326 (기대 0.1326) |
| KCC-MICHANG-badge | required | 통과 | 002380 있음 · 003650 있음 |
| WDC-value | required | 통과 | WDC: 균형 48/272 가치 132/272 성장 13/272 |
| HANIL-HOLDINGS-value | required | 통과 | 003300: 균형 67/299 가치 43/299 성장 166/299 |
| HANIL-HOLDINGS-value-strict | required | 통과 | 003300: 균형 67/299 가치 43/299 성장 166/299 |
| HOME-family-mix | required | 통과 | family 섞임 없음 |
| SCREEN-no-phi-number | required | 통과 | 화면 코드 확인 |
| SCREEN-theme-position | required | 통과 | 화면 코드 확인 |
| SCREEN-theme-position-momentum | required | 통과 | 화면 코드 확인 |
| GLD-IAU-not-scored | required | 통과 | GLD: 표본에 없음 · IAU: 표본에 없음 |
| DAOU-family | required | 통과 | 023590: 균형 6/30 가치 3/30 성장 13/30 |
| SKSQUARE-not-scored | required | 통과 | 402340: 표본에 없음 |
| SEC-tags-scored | required | 통과 | XOM: 균형 73/272 가치 55/272 성장 140/272 · CLX: 균형 220/272 가치 199/272 성장 209/272 · EMN: 균형 134/272 가치 74/272 성장 187/272 · EXP: 균형 147/272 가치 75/272 성장 203/272 · GTX: 균형 234/272 가치 251/272 성장 212/272 · OSK: 균형 80/272 가치 21/272 성장 121/272 · AEIS: 균형 217/272 가치 213/272 성장 200/272 |
| DAEHAN-SHIPBUILDING-value | required | 실패 | 439260: 균형 53/299 가치 13/299 성장 118/299 |
| CJ-LOGISTICS-history | required | 통과 | 이어지는 FY [2025, 2024, 2023] |
| MU-value | required | 통과 | MU: 균형 1/272 가치 11/272 성장 1/272 |
| SIRI-value | required | 통과 | SIRI: 균형 151/272 가치 155/272 성장 185/272 |
| KGSTEEL-value | target | 실패 | 016380: 균형 55/299 가치 9/299 성장 162/299 |
| T-value | known_fail | 실패(감수 D-001) | T: 균형 15/272 가치 1/272 성장 87/272 |
| DNAUTO-weak-theme-first | target | 실패 | 007340: 균형 2/299 가치 4/299 성장 5/299 |
| MSI-balanced | target | 실패 | MSI: 균형 210/272 가치 181/272 성장 218/272 |
| ADP-balanced | target | 실패 | ADP: 균형 152/272 가치 118/272 성장 172/272 |
| BUYBACK-vs-DISTRESSED | required | 통과 | MCK -0.3733 · PM -0.255 vs 잠식+적자 중앙값 -2.2317 (n=1) |
| R1-oneoff-top10 | required | 통과 | 잘리지 않은 일회성 0개 [] |
| R2-turnaround-growth | required | 통과 | US 0 [] / KR 0 [] |
| R3-value-trap | required | 통과 | US 0 [] / KR 1 ['016380'] |
| R4-cycle-value | target | 통과 | US 1 ['MLI'] / KR 2 ['007340', '016380'] |
| R5-fiscal-gap-badge | required | 통과 | 대상 10종목 · 배지 없음 0 [] |
| R6-score-honesty | required | 통과 | 식 불일치 0 · 종합 순서 뒤집힘 0 · 구간 라벨 불일치 0 |
| R7-badge-inflation | target | 통과 | US 6.4% / KR 14.3% (원자재 배지 제외) |
| R8-top10-stability | target | 실패 | US위험 6 US성장 8 US균형 7 US가치 7 KR위험 5 KR성장 8 KR균형 6 KR가치 6 |
| R9-no-score-loss | required | 통과 | 이전 모델 점수 없음 — 비교 대상 없음 |
| R10-independent-benchmark | required | 실패 | 이상 종목 18(≤16) · 우량 거짓 음성 27(≤27) · {'US위험': 2, 'US성장': 2, 'US균형': 2, 'US가치': 0, 'KR위험': 4, 'KR성장': 4, 'KR균형': 2, 'KR가치': 2} |
| TRAP-penalty-only | required | 통과 | 564종목 중 양수 0 |
| WEAK-theme-first | target | 통과 | 23개 (기록만) · US위험 3['IRDM', 'LTH', 'BE'] US성장 2['IRDM', 'CRS'] US균형 4['IPAR', 'VZ', 'NEU', 'ROST'] US가치 4['T', 'FSLR', 'DIS', 'EXEL'] KR위험 3['007340', '024840', '457190'] KR성장 3['007340', '112610', '457190'] KR균형 2['007340', '068270'] KR가치 2['007340', '145020'] |
| THEME-position-raw | required | 통과 | 테마·팩터 345칸 중 차이 0 [] |
| CLIP-order | required | 실패 | 18개 지표 최저 0.49 · 0.5 미만 ['US revenue_cagr2 0.49'] |



</details>

## PR A — 분류 (D-024·D-025·R3-1), 모델 v2.3

**통과 41 · 감수한 실패 2 · target 실패 5 · 미검증 1** · required 실패 2 (required·known_fail 41개 중 통과 + 감수 39)

- 감수한 실패: T-value(D-001), SPEAR-business-combination-growth(D-005 — 스피어 성장 2위).
- 미검증: THEME-main-business-unjudged — 보류 33종목 중 판정하지 못한 6종목(현대바이오·HON·CTAS·FISV·CPAY·PYPL, 업종 코드 그대로).
- required 실패: DAEHAN-SHIPBUILDING-value(기준선과 같음, 가치 14위), **R10 이상 18 → 24**(거짓 음성 27 그대로).
  - 빠진 이상: 한국앤컴퍼니(국내 균형·가치 — I1, D-025로 점수 없음).
  - 들어온 이상(모두 테마를 옮긴 종목이 아니라 **같은 테마에 남은 동료**): 미국 위험 WDC·Lumentum, 성장 WDC(SNDK가 하드웨어 → 반도체로 빠져 하드웨어 테마 평균이 내려감 — WDC 균형 48 → 17위), 국내 위험 티에스이·피에스케이홀딩스(반도체 장비·소재에 원익QnC·원익홀딩스·리노공업·이엔에프·레이크·기가비스 6종목이 들어옴), 국내 균형 씨어스. 모두 3년 안 영업적자 이력(I3) 또는 이름의 '홀딩스'(I1)다.
  - D-002 다시 열 조건(이상 > 16)에 걸린다 — 기준선(18)부터 걸려 있었다. 합격선은 같은 데이터로 바꾸지 않고(D-030) 라운드 4에 넘긴다(장부 U-9).
- 통과로 바뀐 것: CLIP-order 0.49 → 0.58(미국 매출 CAGR 상위 순서 — 테마 평균이 바뀌어 중립화 뒤 순서가 원값에 가까워짐).
- 분류 결과: THEME-main-business-KR 35종목·US 30종목 모두 판정대로(다름 0). 지주·금융 연결 3종목(한국앤컴퍼니·한화·다우기술) 점수 없음.
- **변경안과 다른 점**: THEME-main-business-KR의 삼성물산(028260)은 건설·엔지니어링이 아니라 **유통·커머스**(2025 사업보고서 상사 14.64조 35.9% > 건설 14.15조 34.7% — 2024년은 건설 44.3%), SK오션플랜트(100090)는 재생에너지가 아니라 **조선**(보고부문 조선/해양사업부 97%, 그 안에서 특수선 59.0% > 해상풍력 33.7%). 라운드 3은 2024 자료였다. 판정 못한 종목을 세는 `THEME-main-business-unjudged`(target)를 더했다.
- 순위 영향(기준선 → v2.3, general 묶음 × 프리셋 4): 테마를 옮긴 종목 240건 |Δ| 중앙값 **14계단**(평균 21.8, 20계단 이상 92건, 최대 168), 20% 구간이 바뀐 것 78건. 옮기지 않은 종목 2,260건 중앙값 3계단(최대 56). 라운드 3 측정(17계단)과 같은 방향이다.

<details><summary>PR A 전체 표</summary>

required(known_fail 포함) 통과 **39/41** — 실패: DAEHAN-SHIPBUILDING-value, R10-independent-benchmark

| id | status | 결과 | 실제 값 |
|---|---|---|---|
| SIRI-growth | required | 통과 | SIRI: 균형 149/272 가치 158/272 성장 180/272 |
| RIVN-growth | required | 통과 | RIVN: 균형 254/272 가치 264/272 성장 190/272 |
| INTC-growth | required | 통과 | INTC: 균형 258/272 가치 259/272 성장 253/272 |
| LOTTE-HOLDINGS-growth | required | 통과 | 004990: 표본에 없음 |
| ASIANA-growth | required | 통과 | 020560: 균형 282/297 가치 282/297 성장 283/297 |
| SARAMIN-balanced | required | 통과 | 143240: 균형 75/297 가치 64/297 성장 178/297 |
| KCC-oneoff-cut | required | 통과 | 순이익/영업이익 3.6배 → e = 0.78 × 영업이익, 지표 0.0882 (기대 0.0882) |
| MICHANG-oneoff-cut | required | 통과 | 순이익/영업이익 2.0배 → e = 0.78 × 영업이익, 지표 0.1326 (기대 0.1326) |
| KCC-MICHANG-badge | required | 통과 | 002380 있음 · 003650 있음 |
| WDC-value | required | 통과 | WDC: 균형 17/272 가치 110/272 성장 5/272 |
| HANIL-HOLDINGS-value | required | 통과 | 003300: 균형 67/297 가치 46/297 성장 167/297 |
| HANIL-HOLDINGS-value-strict | required | 통과 | 003300: 균형 67/297 가치 46/297 성장 167/297 |
| HOME-family-mix | required | 통과 | family 섞임 없음 |
| SCREEN-no-phi-number | required | 통과 | 화면 코드 확인 |
| SCREEN-theme-position | required | 통과 | 화면 코드 확인 |
| SCREEN-theme-position-momentum | required | 통과 | 화면 코드 확인 |
| GLD-IAU-not-scored | required | 통과 | GLD: 표본에 없음 · IAU: 표본에 없음 |
| DAOU-family | required | 통과 | 023590: 점수 없음 |
| HOLDING-equity-method | required | 통과 | 000240: 점수 없음 |
| FIN-consolidated-nonfinancial | required | 통과 | 000880: 점수 없음 · 023590: 점수 없음 |
| SKSQUARE-not-scored | required | 통과 | 402340: 표본에 없음 |
| SEC-tags-scored | required | 통과 | XOM: 균형 69/272 가치 55/272 성장 137/272 · CLX: 균형 217/272 가치 194/272 성장 208/272 · EMN: 균형 129/272 가치 75/272 성장 178/272 · EXP: 균형 155/272 가치 83/272 성장 211/272 · GTX: 균형 234/272 가치 252/272 성장 209/272 · OSK: 균형 132/272 가치 32/272 성장 182/272 · AEIS: 균형 214/272 가치 207/272 성장 196/272 |
| DAEHAN-SHIPBUILDING-value | required | 실패 | 439260: 균형 45/297 가치 14/297 성장 108/297 |
| CJ-LOGISTICS-history | required | 통과 | 이어지는 FY [2025, 2024, 2023] |
| MU-value | required | 통과 | MU: 균형 1/272 가치 14/272 성장 1/272 |
| SIRI-value | required | 통과 | SIRI: 균형 149/272 가치 158/272 성장 180/272 |
| KGSTEEL-value | target | 실패 | 016380: 균형 60/297 가치 10/297 성장 168/297 |
| T-value | known_fail | 실패(감수 D-001) | T: 균형 26/272 가치 1/272 성장 104/272 |
| DNAUTO-weak-theme-first | target | 실패 | 007340: 균형 14/297 가치 5/297 성장 32/297 |
| THEME-main-business-KR | required | 통과 | 35종목 중 다름 0 [] |
| THEME-main-business-US | required | 통과 | 30종목 중 다름 0 [] |
| THEME-main-business-unjudged | target | 확인 못함 | 판정 못함 048410 정밀화학 · HON 항공우주·방산 · CTAS 레저·의류·소비서비스 · FISV 인터넷 플랫폼 · CPAY 인터넷 플랫폼 · PYPL 인터넷 플랫폼 |
| SPEAR-business-combination-growth | known_fail | 실패(감수 D-005) | 347700: 균형 48/297 가치 188/297 성장 2/297 |
| MSI-balanced | target | 실패 | MSI: 균형 177/272 가치 164/272 성장 174/272 |
| ADP-balanced | target | 실패 | ADP: 균형 142/272 가치 112/272 성장 161/272 |
| BUYBACK-vs-DISTRESSED | required | 통과 | MCK -0.3733 · PM -0.255 vs 잠식+적자 중앙값 -2.2317 (n=1) |
| R1-oneoff-top10 | required | 통과 | 잘리지 않은 일회성 0개 [] |
| R2-turnaround-growth | required | 통과 | US 0 [] / KR 0 [] |
| R3-value-trap | required | 통과 | US 0 [] / KR 1 ['016380'] |
| R4-cycle-value | target | 통과 | US 1 ['MLI'] / KR 1 ['016380'] |
| R5-fiscal-gap-badge | required | 통과 | 대상 10종목 · 배지 없음 0 [] |
| R6-score-honesty | required | 통과 | 식 불일치 0 · 종합 순서 뒤집힘 0 · 구간 라벨 불일치 0 |
| R7-badge-inflation | target | 통과 | US 6.4% / KR 14.4% (원자재 배지 제외) |
| R8-top10-stability | target | 실패 | US위험 8 US성장 8 US균형 7 US가치 6 KR위험 6 KR성장 7 KR균형 6 KR가치 6 |
| R9-no-score-loss | required | 통과 | 이전 2026-10-27: 재무 칸 누락으로 잃음 0 [] · 재무 없음(표기 안 함, D-014) 0 [] · 점수 없음 테마 3 |
| R10-independent-benchmark | required | 실패 | 이상 종목 24(≤16) · 우량 거짓 음성 27(≤27) · {'US위험': 4, 'US성장': 3, 'US균형': 2, 'US가치': 0, 'KR위험': 6, 'KR성장': 4, 'KR균형': 3, 'KR가치': 2} |
| TRAP-penalty-only | required | 통과 | 562종목 중 양수 0 |
| WEAK-theme-first | target | 통과 | 22개 (기록만) · US위험 2['IRDM', 'BE'] US성장 1['IRDM'] US균형 3['IPAR', 'VZ', 'NEU'] US가치 4['T', 'FSLR', 'DIS', 'EXEL'] KR위험 3['462870', '024840', '457190'] KR성장 2['462870', '112610'] KR균형 3['236200', '458870', '007340'] KR가치 4['007340', '145020', '236200', '214150'] |
| THEME-position-raw | required | 통과 | 테마·팩터 345칸 중 차이 0 [] |
| CLIP-order | required | 통과 | 18개 지표 최저 0.58 |
| TOP20-theme-reviewed | target | 통과 | 고유 73종목 (기록만) · US위험 15['MU', 'FIX', 'STX', 'SN', 'WDC', 'LITE', 'SCCO', 'NEM', 'LLY', 'EXEL', 'IRDM', 'POWL', 'MRK', 'MNST', 'HALO'] US성장 15['MU', 'STX', 'WDC', 'NEM', 'FIX', 'SCCO', 'EXEL', 'LLY', 'SN', 'POWL', 'LITE', 'MNST', 'IRDM', 'PLTR', 'CDE'] US균형 17['MU', 'MNST', 'EXEL', 'MLI', 'NEM', 'JNJ', 'IPAR', 'MRK', 'SCCO', 'VZ', 'DUK', 'NEU', 'AEP', 'KO', 'WDC', 'D', 'CF'] US가치 19['T', 'VZ', 'PHM', 'MNST', 'GNTX', 'DUK', 'MLI', 'CBT', 'TOL', 'FISV', 'IPAR', 'DIS', 'MU', 'AEP', 'PFE', 'D', 'EXEL', 'JNJ', 'SO'] KR위험 15['458870', '278470', '462870', '131290', '031980', '161390', '042700', '062040', '024840', '080220', '041830', '236200', '009150', '440110', '319660'] KR성장 15['458870', '462870', '278470', '257720', '042700', '062040', '003230', '031980', '236200', '483650', '161390', '214150', '080220', '083650', '131290'] KR균형 16['462870', '236200', '271560', '161390', '458870', '259960', '214150', '033780', '145020', '093050', '278470', '257720', '041830', '002960', '071320', '062040'] KR가치 19['462870', '071320', '271560', '003480', '161390', '093050', '145020', '005880', '016380', '003650', '236200', '259960', '439260', '004690', '030200', '000120', '017940', '214150', '073240'] |

</details>

## PR B — 데이터 정확성 (D-026·D-027·D-029), 모델 v2.4

**통과 48 · 감수한 실패 2 · target 실패 4 · 미검증 1** · required 실패 2 (required·known_fail 47개 중 통과 + 감수 45)

- 새 required 6개 모두 통과: BOBCAT-currency(지표 0.0872 vs KRX EPS÷종가 0.0859, 비율 1.02), CURRENCY-krw(국내 594개 값 중 50배 넘게 어긋남 0), NEG-EQUITY-bp(BKNG·HCA·MCD·PM·YUM B/P 없음·사유), NEG-EQUITY-no-bp(자본 ≤ 0 18종목 중 B/P 있음 0), ONEOFF-badge-recurring(배지 49개 중 단정 문구 0), PREF-share-basis(대상 22종목 — 삼성전자 +13%, 현대차 +29% 등 — 기대값과 다름 0).
- required 실패 2개는 PR A와 같다: 대한조선(가치 14위), R10 — 이상 24 → **23**, 우량 거짓 음성 27 → **24**.
- target: KGSTEEL-value 통과로 바뀜(KG스틸 가치 10 → 11위), R4 미국 2(EPD·MLI)·국내 1.
- 두산밥캣 재수집: 2023~2025 USD 재무를 결산일 환율(1,277.84 · 1,467.39 · 1,437.91)로 환산, `currency = USD`·`fx_rate` 저장. 2025 순이익 4,068억 원.
- **HDB 원인 확인(D-026)**: yfinance `bookValue` 2.51달러·`priceToBook` 8.5(재무통화 INR, 상장주식수 51.4억) — 국내 상장 HDFC은행 P/B(2~3배)와 3~4배 차이라 **yfinance ADR 값의 단위(ADR 비율) 문제**로 보인다. DART 통화와는 무관하다. 이 DB에서 HDB는 SEC 재무가 비어(20-F) 점수가 없다(D-014) — 점수 영향 없음. 금융 비교(PR C)에서는 ROE가 없어 회귀선에 들어가지 않는다.
- 순위(PR A → PR B, 가치 프리셋): 두산밥캣 143 → 54 /297, BKNG 169 → 47, HCA 156 → 27, YUM 161 → 40, PM 150 → 43, MCD 73 → 19, TDG 179 → 86 /272. 음수 자본 동료의 B/P 부풀림이 빠짐 — CTAS 60 → 99, QSR 82 → 105, CMG 125 → 158. 우선주 보정: 현대차 85 → 99. 전체 2,500건 중앙값 0계단(20계단 이상 64건). 라운드 3 측정(BKNG 173 → 47, 두산밥캣 148 → 66, CTAS 57 → 103)과 같은 방향이다.

<details><summary>PR B 전체 표</summary>

required(known_fail 포함) 통과 **45/47** — 실패: DAEHAN-SHIPBUILDING-value, R10-independent-benchmark

| id | status | 결과 | 실제 값 |
|---|---|---|---|
| SIRI-growth | required | 통과 | SIRI: 균형 150/272 가치 150/272 성장 180/272 |
| RIVN-growth | required | 통과 | RIVN: 균형 253/272 가치 263/272 성장 190/272 |
| INTC-growth | required | 통과 | INTC: 균형 258/272 가치 258/272 성장 253/272 |
| LOTTE-HOLDINGS-growth | required | 통과 | 004990: 표본에 없음 |
| ASIANA-growth | required | 통과 | 020560: 균형 282/297 가치 282/297 성장 283/297 |
| SARAMIN-balanced | required | 통과 | 143240: 균형 76/297 가치 65/297 성장 179/297 |
| KCC-oneoff-cut | required | 통과 | 순이익/영업이익 3.6배 → e = 0.78 × 영업이익, 지표 0.0882 (기대 0.0882) |
| MICHANG-oneoff-cut | required | 통과 | 순이익/영업이익 2.0배 → e = 0.78 × 영업이익, 지표 0.1326 (기대 0.1326) |
| KCC-MICHANG-badge | required | 통과 | 002380 있음 · 003650 있음 |
| WDC-value | required | 통과 | WDC: 균형 19/272 가치 116/272 성장 5/272 |
| HANIL-HOLDINGS-value | required | 통과 | 003300: 균형 67/297 가치 46/297 성장 167/297 |
| HANIL-HOLDINGS-value-strict | required | 통과 | 003300: 균형 67/297 가치 46/297 성장 167/297 |
| HOME-family-mix | required | 통과 | family 섞임 없음 |
| SCREEN-no-phi-number | required | 통과 | 화면 코드 확인 |
| SCREEN-theme-position | required | 통과 | 화면 코드 확인 |
| SCREEN-theme-position-momentum | required | 통과 | 화면 코드 확인 |
| GLD-IAU-not-scored | required | 통과 | GLD: 표본에 없음 · IAU: 표본에 없음 |
| DAOU-family | required | 통과 | 023590: 점수 없음 |
| HOLDING-equity-method | required | 통과 | 000240: 점수 없음 |
| FIN-consolidated-nonfinancial | required | 통과 | 000880: 점수 없음 · 023590: 점수 없음 |
| SKSQUARE-not-scored | required | 통과 | 402340: 표본에 없음 |
| SEC-tags-scored | required | 통과 | XOM: 균형 73/272 가치 59/272 성장 138/272 · CLX: 균형 224/272 가치 210/272 성장 211/272 · EMN: 균형 137/272 가치 79/272 성장 181/272 · EXP: 균형 157/272 가치 84/272 성장 209/272 · GTX: 균형 192/272 가치 179/272 성장 168/272 · OSK: 균형 140/272 가치 34/272 성장 183/272 · AEIS: 균형 216/272 가치 206/272 성장 197/272 |
| DAEHAN-SHIPBUILDING-value | required | 실패 | 439260: 균형 45/297 가치 14/297 성장 108/297 |
| CJ-LOGISTICS-history | required | 통과 | 이어지는 FY [2025, 2024, 2023] |
| MU-value | required | 통과 | MU: 균형 1/272 가치 16/272 성장 1/272 |
| SIRI-value | required | 통과 | SIRI: 균형 150/272 가치 150/272 성장 180/272 |
| KGSTEEL-value | target | 통과 | 016380: 균형 60/297 가치 11/297 성장 168/297 |
| T-value | known_fail | 실패(감수 D-001) | T: 균형 31/272 가치 1/272 성장 111/272 |
| DNAUTO-weak-theme-first | target | 실패 | 007340: 균형 14/297 가치 5/297 성장 32/297 |
| THEME-main-business-KR | required | 통과 | 35종목 중 다름 0 [] |
| THEME-main-business-US | required | 통과 | 30종목 중 다름 0 [] |
| THEME-main-business-unjudged | target | 확인 못함 | 판정 못함 048410 정밀화학 · HON 항공우주·방산 · CTAS 레저·의류·소비서비스 · FISV 인터넷 플랫폼 · CPAY 인터넷 플랫폼 · PYPL 인터넷 플랫폼 |
| SPEAR-business-combination-growth | known_fail | 실패(감수 D-005) | 347700: 균형 48/297 가치 188/297 성장 2/297 |
| BOBCAT-currency | required | 통과 | 지표 0.0872 vs KRX EPS÷종가 0.0859 (비율 1.02) |
| NEG-EQUITY-bp | required | 통과 | BKNG: 자본 -5,578,000,000 · B/P 없음 · 자본 음수(자사주 매입 등) — 장부가 기준 저평가를 계산하지 않음 · HCA: 자본 -6,027,000,000 · B/P 없음 · 자본 음수(자사주 매입 등) — 장부가 기준 저평가를 계산하지 않음 · MCD: 자본 -1,791,000,000 · B/P 없음 · 자본 음수(자사주 매입 등) — 장부가 기준 저평가를 계산하지 않음 · PM: 자본 -9,994,000,000 · B/P 없음 · 자본 음수(자사주 매입 등) — 장부가 기준 저평가를 계산하지 않음 · YUM: 자본 -7,325,000,000 · B/P 없음 · 자본 음수(자사주 매입 등) — 장부가 기준 저평가를 계산하지 않음 |
| MSI-balanced | target | 실패 | MSI: 균형 184/272 가치 178/272 성장 179/272 |
| ADP-balanced | target | 실패 | ADP: 균형 149/272 가치 114/272 성장 161/272 |
| BUYBACK-vs-DISTRESSED | required | 통과 | MCK -0.3733 · PM -0.255 vs 잠식+적자 중앙값 -2.2317 (n=1) |
| R1-oneoff-top10 | required | 통과 | 잘리지 않은 일회성 0개 [] |
| R2-turnaround-growth | required | 통과 | US 0 [] / KR 0 [] |
| R3-value-trap | required | 통과 | US 0 [] / KR 1 ['016380'] |
| R4-cycle-value | target | 통과 | US 2 ['EPD', 'MLI'] / KR 1 ['003650'] |
| R5-fiscal-gap-badge | required | 통과 | 대상 10종목 · 배지 없음 0 [] |
| R6-score-honesty | required | 통과 | 식 불일치 0 · 종합 순서 뒤집힘 0 · 구간 라벨 불일치 0 |
| R7-badge-inflation | target | 통과 | US 6.4% / KR 14.4% (원자재 배지 제외) |
| R8-top10-stability | target | 실패 | US위험 8 US성장 8 US균형 7 US가치 6 KR위험 6 KR성장 7 KR균형 6 KR가치 6 |
| R9-no-score-loss | required | 통과 | 이전 2026-10-27: 재무 칸 누락으로 잃음 0 [] · 재무 없음(표기 안 함, D-014) 0 [] · 점수 없음 테마 3 |
| R10-independent-benchmark | required | 실패 | 이상 종목 23(≤16) · 우량 거짓 음성 24(≤27) · {'US위험': 4, 'US성장': 3, 'US균형': 2, 'US가치': 0, 'KR위험': 6, 'KR성장': 4, 'KR균형': 3, 'KR가치': 1} |
| TRAP-penalty-only | required | 통과 | 562종목 중 양수 0 |
| WEAK-theme-first | target | 통과 | 22개 (기록만) · US위험 2['IRDM', 'BE'] US성장 1['IRDM'] US균형 3['IPAR', 'NEU', 'VZ'] US가치 4['T', 'FSLR', 'DIS', 'EXEL'] KR위험 3['462870', '024840', '457190'] KR성장 2['462870', '112610'] KR균형 3['236200', '458870', '007340'] KR가치 4['007340', '145020', '236200', '214150'] |
| THEME-position-raw | required | 통과 | 테마·팩터 345칸 중 차이 0 [] |
| CLIP-order | required | 통과 | 18개 지표 최저 0.58 |
| CURRENCY-krw | required | 통과 | 594개 값 중 50배 넘게 어긋남 0 [] |
| NEG-EQUITY-no-bp | required | 통과 | 자본 ≤ 0 18종목 ['PM', 'DELL', 'ABBV', 'MCD', 'MO', 'BKNG', 'MCK', 'SBUX', 'LOW', 'MAR', 'HCA', 'HLT'] 중 B/P 있음 0 [] |
| ONEOFF-badge-recurring | required | 통과 | 배지 49개 중 단정 문구 0 [] |
| PREF-share-basis | required | 통과 | 대상 22종목 ['005930(+13%)', '005380(+29%)', '097950(+6%)', '000210(+8%)', '375500(+8%)', '051900(+12%)', '066570(+11%)', '051910(+11%)'] · 다름 0 [] |
| TOP20-theme-reviewed | target | 통과 | 고유 73종목 (기록만) · US위험 15['MU', 'FIX', 'STX', 'SN', 'WDC', 'LITE', 'SCCO', 'NEM', 'LLY', 'EXEL', 'IRDM', 'POWL', 'MRK', 'MNST', 'ROST'] US성장 15['MU', 'STX', 'WDC', 'NEM', 'FIX', 'SCCO', 'EXEL', 'LLY', 'POWL', 'SN', 'LITE', 'MNST', 'CDE', 'IRDM', 'PLTR'] US균형 18['MU', 'MNST', 'EXEL', 'NEM', 'MLI', 'IPAR', 'JNJ', 'MRK', 'EPD', 'SCCO', 'DUK', 'NEU', 'VZ', 'AEP', 'D', 'CF', 'WDC', 'AME'] US가치 19['T', 'PHM', 'DUK', 'EPD', 'MLI', 'MNST', 'VZ', 'CBT', 'TOL', 'GNTX', 'IPAR', 'DIS', 'FISV', 'PFE', 'MU', 'AEP', 'D', 'MCD', 'EXEL'] KR위험 15['458870', '278470', '462870', '131290', '031980', '161390', '042700', '062040', '024840', '080220', '041830', '236200', '009150', '440110', '003230'] KR성장 15['458870', '462870', '278470', '257720', '042700', '062040', '003230', '031980', '236200', '483650', '161390', '214150', '080220', '083650', '131290'] KR균형 16['462870', '236200', '271560', '161390', '458870', '259960', '214150', '033780', '145020', '093050', '278470', '257720', '002960', '041830', '071320', '062040'] KR가치 19['462870', '071320', '271560', '003480', '161390', '093050', '145020', '003650', '005880', '016380', '236200', '259960', '439260', '004690', '017940', '030200', '000120', '214150', '073240'] |

</details>
