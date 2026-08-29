# H0 — 기존 회귀점수 감사 (상대 분석)

감사 대상: `risk_signal_validation.py` (①, +2R 확률 로지스틱, script sha256 47872d3a23f3...) 와 `exit_aware_signal_validation.py` (②, 실제 청산 R 회귀). 산출물 `ab3/risk_signal_summary.json`, `ab3/exit_aware_summary.json`, `ab3/actual_trades_exit_aware_scores.csv` (열 `risk_tier`).

| 확인 항목 | ① +2R 확률 모델 | ② exit-aware 회귀 (지시서의 "회귀점수 A급") |
|---|---|---|
| 피팅 표본 | V2 shadow 후보 101건 (`ab/testB_candidates.csv` + `ab2/b5_outcomes.csv` S1), DEV 66건 | 실제 A1 거래 중 shadow 매핑 81건 (DEV 56건), 목표 = 실제 청산 R 을 [−1.25, +5] 로 절단 |
| 피팅 구간 | **2019~2022 만** (연도 블록 CV 로 λ·상위비율 선택, 15 trial) | **2019~2022 만** (동일 방식, 18 trial), λ=10 상위 35% | 
| 조건 원값 | 15개 원값(손절폭 log, D/R 구조, R/ATR, ARM·확정 경과, 일봉 7/30/90일 수익, 200일 이격, 일봉 20일 변동성, 4H 6/42봉 수익·변동성, 3일 펀딩). 상위 시간대 상승추세=d_ret_30/90·d_ma200_gap, 단기 비과열=d_ret_7·h_ret_6, 낮은 변동성=d_rv20·h_rv42, 짧은 손절=log_stop_pct | 동일 15개 |
| 정규화 | DEV 학습표본의 평균·표준편차로 표준화 (전 기간 백분위 아님) | 동일 |
| 점수→등급 경계 | DEV 학습점수의 상위 25% 분위값 0.4059 (DEV 에서 결정) | DEV 학습점수의 상위 35% 분위값 -0.0142 (DEV 에서 결정) |
| 결과 (상대 분석 보고) | DEV A급 17건 +0.69R → TEST A급 4건 −0.33R: 필터로 **채택하지 않음** (자체 판정) | DEV A급 20건 +1.33R → TEST A급 7건 +5.32R (PF 10.1); 최대 1건(+36.5R) 제외 시 +0.73R |
| look-ahead | 일봉·4H 는 decision 이전 종료 봉만 (`feature_bars_close_before_decision: true`) | 동일 |

**감사 결과: 형식 통과 (피팅 2019~22, 정규화 DEV 기준, 경계 DEV 결정).** 단, 다음 두 가지를 결과 해석에 반드시 붙인다.
1. ② 는 ① 의 TEST(2023~26) 결과를 관측한 뒤 설계된 2차 모델이다 (`exit_aware_signal_validation.py` 독스트링 및 상대 분석 §5 자인). 같은 TEST 블록을 두 번 본 것이므로 ② 의 "TEST A급 7건 +5.32R" 은 순수 검증값이 아니라 **참고(sequential, in-sample-adjacent)** 로 표기한다.
2. 목표변수가 본 지시서(RIDE7 / R_REAL) 와 다르고(① +2R 도달, ② 절단 R), 변수 15개 중 다수가 서로 상관이 높다. 따라서 §5 등급(6조건 3분위 개수 합) 과 나란히 보고하되 두 등급을 합치지 않는다.

본 지시서 §2 의 분기: 피팅 구간 2019~22 + 과거 기준 정규화 → **감사 통과** → §5 등급과 `risk_tier` 를 `h3_grades.csv` 에 병기한다. 4조건(상위 추세·단기 비과열·낮은 변동성·짧은 손절) 은 §3 의 RET100/MA200 · RET14 · VOL30 · STOPPCT 가 대응한다.
