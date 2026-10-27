## sanity 결과 — 점수 계산일 2026-10-27 · 모델 v2-2026-10-27

> 수정 1(검토_장부 D-011 PR 2~6, D-014·D-017 반영) 뒤 `python -m app.ingest sanity`로 돌린 결과다. 데이터는 **개발 DB**(일봉·밸류에이션 2026-10-26)이고,
> DART FY2024 누락 5종목과 SEC 태그 보완 7종목(XOM·CLX·EMN·EXP·GTX·OSK·AEIS)은 개발 DB에서 다시 받은 뒤 계산했다.
> 배포 DB는 PR 1(재배포)과 같은 재수집을 마친 뒤 다시 돌려야 같은 결과가 나온다.

required(known_fail 포함) 통과 **32/32**

| id | status | 결과 | 실제 값 |
|---|---|---|---|
| SIRI-growth | required | 통과 | SIRI: 균형 142/277 가치 135/277 성장 182/277 |
| RIVN-growth | required | 통과 | RIVN: 균형 267/277 가치 271/277 성장 232/277 |
| INTC-growth | required | 통과 | INTC: 균형 261/277 가치 266/277 성장 257/277 |
| LOTTE-HOLDINGS-growth | required | 통과 | 004990: 점수 없음 |
| ASIANA-growth | required | 통과 | 020560: 균형 287/298 가치 289/298 성장 289/298 |
| SARAMIN-balanced | required | 통과 | 143240: 균형 73/298 가치 48/298 성장 168/298 |
| KCC-oneoff-cut | required | 통과 | 순이익/영업이익 3.6배 → e = 0.78 × 영업이익, 지표 0.0903 (기대 0.0903) |
| MICHANG-oneoff-cut | required | 통과 | 순이익/영업이익 2.0배 → e = 0.78 × 영업이익, 지표 0.1339 (기대 0.1339) |
| KCC-MICHANG-badge | required | 통과 | 002380 있음 · 003650 있음 |
| WDC-value | required | 통과 | WDC: 균형 24/277 가치 96/277 성장 11/277 |
| HANIL-HOLDINGS-value | required | 통과 | 003300: 균형 47/298 가치 18/298 성장 145/298 |
| HANIL-HOLDINGS-value-strict | known_fail | 실패(감수 D-001) | 003300: 균형 47/298 가치 18/298 성장 145/298 |
| HOME-family-mix | required | 통과 | family 섞임 없음 |
| SCREEN-no-phi-number | required | 통과 | 화면 코드 확인 |
| SCREEN-theme-position | required | 통과 | 화면 코드 확인 |
| GLD-IAU-not-scored | required | 통과 | GLD: 점수 없음 · IAU: 점수 없음 |
| DAOU-family | required | 통과 | 023590: 균형 5/31 가치 2/31 성장 11/31 |
| SKSQUARE-not-scored | required | 통과 | 402340: 점수 없음 |
| SEC-tags-scored | required | 통과 | XOM: 균형 92/277 가치 81/277 성장 150/277 · CLX: 균형 200/277 가치 166/277 성장 180/277 · EMN: 균형 57/277 가치 13/277 성장 149/277 · EXP: 균형 130/277 가치 60/277 성장 192/277 · GTX: 균형 220/277 가치 248/277 성장 140/277 · OSK: 균형 20/277 가치 3/277 성장 66/277 · AEIS: 균형 238/277 가치 227/277 성장 227/277 |
| DAEHAN-SHIPBUILDING-value | required | 통과 | 439260: 균형 46/298 가치 33/298 성장 89/298 |
| CJ-LOGISTICS-history | required | 통과 | 이어지는 FY [2025, 2024, 2023] |
| MU-value | required | 통과 | MU: 균형 2/277 가치 16/277 성장 1/277 |
| SIRI-value | required | 통과 | SIRI: 균형 142/277 가치 135/277 성장 182/277 |
| KGSTEEL-value | target | 실패 | 016380: 균형 41/298 가치 7/298 성장 148/298 |
| T-value | known_fail | 실패(감수 D-001) | T: 균형 17/277 가치 1/277 성장 79/277 |
| MSI-balanced | target | 실패 | MSI: 균형 217/277 가치 171/277 성장 238/277 |
| ADP-balanced | target | 실패 | ADP: 균형 181/277 가치 119/277 성장 211/277 |
| BUYBACK-vs-DISTRESSED | required | 통과 | MCK -0.1638 · PM -0.1896 vs 잠식+적자 중앙값 -2.7692 (n=1) |
| R1-oneoff-top10 | required | 통과 | 잘리지 않은 일회성 0개 [] |
| R2-turnaround-growth | required | 통과 | US 0 [] / KR 0 [] |
| R3-value-trap | required | 통과 | US 0 [] / KR 2 ['016380', '003300'] |
| R4-cycle-value | target | 실패 | US 1 ['NEU'] / KR 4 ['007340', '003650', '017940', '016380'] |
| R5-fiscal-gap-badge | required | 통과 | 대상 9종목 · 배지 없음 0 [] |
| R6-score-honesty | required | 통과 | 식 불일치 0 · 종합 순서 뒤집힘 0 · 구간 라벨 불일치 0 |
| R7-badge-inflation | target | 통과 | US 5.9% / KR 17.0% (원자재 배지 제외) |
| R8-top10-stability | target | 실패 | US위험 7 US성장 8 US균형 5 US가치 6 KR위험 7 KR성장 7 KR균형 5 KR가치 6 |
| R9-no-score-loss | required | 통과 | 이전 2026-10-26: 재무 칸 누락으로 잃음 0 [] · 재무 없음(표기 안 함, D-014) 13 ['NGG', 'MUFG', 'ENB', 'CP', 'DEO', 'HLN', 'RYAAY', 'BNTX', 'TM', 'SMFG', 'DRD', 'MESO', 'IPX'] · 점수 없음 테마 12 |
| R10-independent-benchmark | required | 통과 | 이상 종목 14(≤14) · 우량 거짓 음성 26(≤27) · {'US위험': 2, 'US성장': 1, 'US균형': 0, 'US가치': 0, 'KR위험': 3, 'KR성장': 4, 'KR균형': 3, 'KR가치': 1} |
[sanity] 완료 0.3s
