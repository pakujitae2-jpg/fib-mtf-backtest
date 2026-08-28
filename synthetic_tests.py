# -*- coding: utf-8 -*-
"""Synthetic tests (작업지시서 §20) + 회귀 assert (§19).
작은 합성 4H/5분봉 데이터에 상태를 주입해 교정 엔진의 이벤트 순서를 검증한다.
python synthetic_tests.py  -> 전부 PASS 여야 한다. 실패 시 AssertionError.
"""
import sys, time, calendar
from collections import Counter
import fib_mtf as F
import fib_engine_c as E

sys.stdout.reconfigure(encoding='utf-8')
H = F.H_MS
FIVE = 5 * 60000
T0 = calendar.timegm((2024, 1, 1, 0, 0, 0)) * 1000        # 2024-01-01 00:00 UTC (월요일)
BASE = dict(DCONF=0.382, DMIN=0.08, R4=0.236, R_ENTRY_FIB=0.236, R_RATIO=0.0, ATR_MULT=0.0, TOL=0.0, BUF=0.003,
            EXIT='tpR2', RATCHET=0.0, MFILT='off', STRUCT='HH_HL', SIDES='both', FILL='A', PEN=0.0, TGT_POLICY='retro')
results = []


def flat(px, n):
    return [(px, px, px, px)] * n


def bar5(o, h, l, c):
    return (o, h, l, c)


def make_env(bars4h, funding=None):
    """bars4h: 4H 봉마다 48개 (o,h,l,c) 5분봉 리스트. 일봉/4H 는 집계로 만든다.
    앞에 워밍업 4H 봉 1개(T0-4H, 첫 봉 시가로 flat) 를 붙여 R 확정 시각(봉 0 종료) 이 실제 시각이 되게 한다. start4 = 1."""
    fine, h4, daily = [], [], {}
    p0 = bars4h[0][0][0]
    bars4h = [flat(p0, 48)] + list(bars4h)
    for i, bars in enumerate(bars4h):
        ot = T0 - 4 * H + i * 4 * H
        assert len(bars) == 48
        for j, (o, h, l, c) in enumerate(bars):
            fine.append((ot + j * FIVE, o, h, l, c, ot + j * FIVE + FIVE - 1))
        o, h, l, c = bars[0][0], max(b[1] for b in bars), min(b[2] for b in bars), bars[-1][3]
        h4.append((ot, o, h, l, c, ot + 4 * H - 1))
        day = ot - ot % F.D_MS
        if day not in daily:
            daily[day] = [o, h, l, c]
        else:
            daily[day][1] = max(daily[day][1], h)
            daily[day][2] = min(daily[day][2], l)
            daily[day][3] = c
    d_rows = [(k, v[0], v[1], v[2], v[3], k + F.D_MS - 1) for k, v in sorted(daily.items())]
    return E.Data(d_rows, h4, fine, F.ts(T0, 24), funding=funding)


def inject(side_sign, armed=True, P0=None, R=None, dsize=100.0, R_t=None, hzz=None):
    def init(sides):
        for sd in sides:
            s = 1 if sd.s > 0 else -1
            if s == side_sign:
                sd.armed, sd.P0, sd.H1, sd.dsize, sd.arm_day, sd.lastL = armed, P0, (P0 + dsize if P0 is not None else None), dsize, 0, None
                sd.R = R
                sd.R_broken = False
                sd.hzz = hzz if hzz is not None else ['DOWN', 0, 1e12, 0, 0.0, -1]     # 새 R 이 생기지 않는 상태
                sd._leg_anchor = None
            else:
                sd.armed, sd.R = False, None
                sd.hzz = ['DOWN', 0, 1e12, 0, 0.0, -1]
                sd._leg_anchor = None
    return init


def check(name, cond, detail=''):
    results.append((name, bool(cond), detail))
    print('  [%s] %s %s' % ('PASS' if cond else 'FAIL', name, detail))


R_T = 0             # R 확정봉 = start4-1 = 워밍업 봉 (start4=1)
S = 1               # start4


def mi(env, t, j):
    """케이스 기준 4H 봉 t 의 j 번째 5분봉 절대 index."""
    return env.fine_range(env.start4 + t)[0] + j
LONG_R = (100.0, 120.0, 20.0, R_T)             # entry = 100 + 0.236*20 = 104.72 (TOL 0), stop = 99.7
LV, STOP = 104.72, 99.7
TP2 = LV + 2 * (LV - STOP)                     # 114.76

print('=' * 100)
print('Synthetic tests — 교정 엔진 fib_engine_c.run (5M chronology)')
print('=' * 100)

# ---------------------------------------------------------------- Case 1: Entry -> Stop  (1 loss)
print('\nCase 1  Entry -> Stop')
b = flat(110, 48)
b[10] = bar5(110, 110, 104.5, 105)      # 진입 터치
b[20] = bar5(105, 105, 99.0, 100)       # 손절
env = make_env([b, flat(100, 48)])
tr, ev, _, dg = E.run(env, BASE, init=inject(+1, P0=95.0, R=LONG_R))
check('1 loss trade', len(tr) == 1 and tr[0]['result'] == 'stop' and tr[0]['r_net'] < 0, '%s' % [(t['result'], round(t['r_net'], 4)) for t in tr])
check('entry_time < stop_time, fill_m=10 exit_m=20', tr and tr[0]['fill_m'] == mi(env, 0, 10) and tr[0]['exit_m'] == mi(env, 0, 20) and tr[0]['entry_time'] < tr[0]['exit_time'])
check('R_INVALID 는 포지션 보유 중엔 신호 아님 (order 없음)', Counter(x[2] for x in ev)['R_INVALID'] == 0)
E.assert_invariants(tr, ev, env)

# ---------------------------------------------------------------- Case 2: R invalidated -> Entry touch (0 trade)
print('\nCase 2  R.low break -> Entry level touch')
b = flat(110, 48)
b[10] = bar5(110, 110, 99.0, 108)       # R.low(100) 이탈 (진입 레벨 104.72 도 동시에 터치되지만 5분봉 하나라 진입->손절 순서가 되어야 함? -> 아래 2b)
b[20] = bar5(108, 108, 104.5, 105)
env = make_env([b, flat(100, 48)])
tr, ev, _, dg = E.run(env, BASE, init=inject(+1, P0=95.0, R=LONG_R))
# 봉 10 은 low 99 < stop 99.7 이므로 동일봉 "진입 -> 손절" (불리한 순서) 로 1 손실 거래가 맞다. 순수 Case 2 는 봉 10 low 가 레벨 위인 경우:
check('2a 동일 5분봉 (레벨 터치 + R 이탈 + 손절가) -> 진입 후 손절 1건 (불리한 순서)', len(tr) == 1 and tr[0]['result'] == 'stop' and tr[0]['fill_m'] == mi(env, 0, 10) and tr[0]['exit_m'] == mi(env, 0, 10))
b = flat(110, 48)
b[10] = bar5(110, 110, 99.0, 108)
b[20] = bar5(108, 108, 104.5, 105)
env = make_env([b, flat(100, 48)])
R2 = (100.0, 130.0, 30.0, R_T)          # entry = 107.08 > 108? no: 100+0.236*30 = 107.08 ; 봉10 low 99 터치. 대신 R.low 만 깨는 봉을 따로:
b = flat(110, 48)
b[8] = bar5(110, 110, 105.5, 106)       # 레벨(104.72) 미터치
b[10] = bar5(106, 106, 99.9, 100.5)     # R.low 100 이탈 but stop 99.7 미도달, 레벨은 터치 -> 진입 후 R 이탈 (포지션 유지)
env = make_env([b, flat(100, 48)])
tr, ev, _, dg = E.run(env, BASE, init=inject(+1, P0=95.0, R=LONG_R))
check('2b 동일 5분봉 (레벨 터치 + R.low 이탈, 손절 미도달) -> 진입 유지 (open)', len(tr) == 1 and tr[0]['result'] == 'open' and tr[0]['fill_m'] == mi(env, 0, 10))
# 순수 Case 2: R.low 이탈이 먼저(봉 5), 레벨 터치가 나중(봉 20). 봉 5 는 레벨도 지나가므로 진입 조건과 겹친다 -> 이탈만 일어나게 하려면 레벨 미터치가 불가능(레벨 > R.low).
# 따라서 "이탈 먼저" 는 다른 5분봉에서 레벨 위로 갭 없이 내려올 수 없음 -> 현실적 케이스: 주문이 아직 없을 때(R 확정 직후 봉 t 이전) 이탈. R[3] = 0 (봉 0 종료에 확정) 으로 두고 봉 0 에서 이탈:
b0 = flat(110, 48); b0[30] = bar5(110, 110, 99.0, 108)          # 봉 0: 주문 없음(R 확정 전) 에 R.low 이탈
b1 = flat(108, 48); b1[10] = bar5(108, 108, 104.5, 105)         # 봉 1: 레벨 터치
env = make_env([b0, b1, flat(100, 48)])
tr, ev, _, dg = E.run(env, BASE, init=inject(+1, P0=95.0, R=(100.0, 120.0, 20.0, S)))
check('2c R 이탈(봉0, 주문 전) -> 레벨 터치(봉1) : 0 trade', len(tr) == 0, str(Counter(x[2] for x in ev)))
# 그리고 5분봉 단위 순서: 봉 안에서 이탈 봉(m=5, low 99 <stop) 이 터치 봉이기도 하므로 진입->손절. 이탈이 레벨 터치보다 '먼저' 인 유일한 방법은 위 2c.
# 4H 선행판정(레거시) 이라면 봉 10 터치 + 봉 30 이탈 순서에서도 거래가 사라진다:
b = flat(110, 48); b[10] = bar5(110, 110, 104.5, 105); b[30] = bar5(105, 105, 99.0, 100)
env = make_env([b, flat(100, 48)])
trC, evC, _, _ = E.run(env, BASE, init=inject(+1, P0=95.0, R=LONG_R))
trL, evL, _, _ = E.run(env, BASE, legacy=E.LEGACY_ALL, init=inject(+1, P0=95.0, R=LONG_R))
check('2d 터치(m10) -> R 이탈(m30): 교정 = 1 stop 거래, 레거시 = 0 거래 (R_INVALID 선행)', len(trC) == 1 and trC[0]['result'] == 'stop' and len(trL) == 0,
      'legacy events %s' % dict(Counter(x[2] for x in evL)))

# ---------------------------------------------------------------- Case 3: Entry -> TP
print('\nCase 3  Entry -> TP')
b = flat(110, 48); b[10] = bar5(110, 110, 104.5, 105); b[25] = bar5(105, 116, 105, 115)
env = make_env([b, flat(115, 48)])
tr, ev, _, dg = E.run(env, BASE, init=inject(+1, P0=95.0, R=LONG_R))
check('1 winning trade (tp @ +2R)', len(tr) == 1 and tr[0]['result'] == 'tp' and tr[0]['r_net'] > 0 and abs(tr[0]['fills'][0][1] - TP2) < 1e-6)
check('MFE = TP 가격 기준, MAE = 진입 후 최저가(104.5)', abs(tr[0]['mfe'] - (TP2 - LV) / LV) < 1e-9 and abs(tr[0]['mae'] - (104.5 - LV) / LV) < 1e-9, 'mae %.5f mfe %.5f' % (tr[0]['mae'], tr[0]['mfe']))
E.assert_invariants(tr, ev, env)

# ---------------------------------------------------------------- Case 4: P0 break after Entry -> V exit (stop 보다 P0 가 위)
print('\nCase 4  Entry -> P0 break (P0 99.9 > stop 99.7)')
b = flat(110, 48); b[10] = bar5(110, 110, 104.5, 105); b[20] = bar5(105, 105, 99.8, 101); b[21] = bar5(101.5, 102, 101, 102)
env = make_env([b, flat(102, 48)])
tr, ev, _, dg = E.run(env, BASE, init=inject(+1, P0=99.9, R=LONG_R))
check('Entry recorded -> V exit at next 5m open (101.5)', len(tr) == 1 and tr[0]['result'] == 'v' and tr[0]['exit_m'] == mi(env, 0, 21) and abs(tr[0]['fills'][0][1] - 101.5) < 1e-9,
      '%s' % [(t['result'], t['exit_m'], t['fills']) for t in tr])
check('V_POS 이벤트 기록', Counter(x[2] for x in ev)['V_POS'] == 1)
trL, evL, _, _ = E.run(env, BASE, legacy=E.LEGACY_ALL, init=inject(+1, P0=99.9, R=LONG_R))
check('레거시: 4H 선행 V -> armed 해제 -> 거래 자체가 없음', len(trL) == 0, str(dict(Counter(x[2] for x in evL))))

# ---------------------------------------------------------------- Case 5: P0 break before Entry -> no trade
print('\nCase 5  P0 break -> Entry touch')
# P0 = 106 (레벨 104.72 보다 위): 봉 8 에서 105.5 까지 하락 -> P0 훼손 (레벨 미터치) -> 봉 10 레벨 터치 -> 거래 없음
b = flat(110, 48); b[8] = bar5(110, 110, 105.5, 106.5); b[10] = bar5(106.5, 107, 104.5, 105)
env = make_env([b, flat(105, 48)])
tr, ev, _, dg = E.run(env, BASE, init=inject(+1, P0=106.0, R=LONG_R))
check('No trade, V(5M) + ORDER_CANCEL', len(tr) == 0 and Counter(x[2] for x in ev)['V'] == 1 and any(x[2] == 'ORDER_CANCEL' and x[5]['reason'] == 'V' for x in ev), str(dict(Counter(x[2] for x in ev))))
# 반대: 같은 데이터에서 P0 = 95 면 정상 진입
tr, ev, _, dg = E.run(env, BASE, init=inject(+1, P0=95.0, R=LONG_R))
check('(대조) P0=95 면 진입', len(tr) == 1)

# ---------------------------------------------------------------- Case 6: Market entry at 5M close, same candle low below stop, next candle rises
print('\nCase 6  FILL=C: same-candle low < stop, next candle rises')
b = flat(110, 48); b[10] = bar5(110, 110, 99.0, 104.6); b[11] = bar5(104.6, 106, 104.0, 105.5)
env = make_env([b, flat(105.5, 48)])
PC = dict(BASE, FILL='C')
tr, ev, _, dg = E.run(env, PC, init=inject(+1, P0=95.0, R=LONG_R))
check('same candle stop = false (포지션 유지)', len(tr) == 1 and tr[0]['result'] != 'stop' and tr[0]['fill_at_close'] and tr[0]['fill_m'] == mi(env, 0, 10), '%s diag %s' % ([(t['result'], t['fill_m']) for t in tr], dict(dg)))
check('진입가 = 5분 종가 + slip, entry_time = 봉 종료', abs(tr[0]['entry'] - (104.6 + F.SLIP * 104.72)) < 1e-9 and tr[0]['entry_time'] == env.f_ot[mi(env, 0, 10)] + FIVE - 1)
check('MAE 창에 진입 봉 low(99) 미포함', tr[0]['mae'] >= (104.0 - tr[0]['entry']) / tr[0]['entry'] - 1e-9, 'mae %.5f' % tr[0]['mae'])
trL, _, _, dgL = E.run(env, PC, legacy=frozenset(['SAMEBAR_C']), init=inject(+1, P0=95.0, R=LONG_R))
check('(대조) SAMEBAR_C 레거시 플래그면 동일봉 손절', len(trL) == 1 and trL[0]['result'] == 'stop' and trL[0]['exit_m'] == mi(env, 0, 10))
E.assert_invariants(tr, ev, env)

# ---------------------------------------------------------------- Case 7: old R waiting -> new R confirmed -> cancel old, place new, R_REPLACED
print('\nCase 7  Old R waiting -> new R')
# 봉 0: hzz UP 상태 anchor 100 / ext 120 주입, 봉 0 low 가 115 이하로 내려가면 (120 - 0.236*20 = 115.28) 봉 0 종료 시 H 피벗 확정 -> 새 R=(100,120,20,t=0)
old_R = (90.0, 110.0, 20.0, R_T)                         # old level = 94.72, 새 level = 104.72
b0 = flat(118, 48); b0[40] = bar5(118, 118, 115.0, 116)  # 새 R 확정 (old level 94.72 는 미터치)
b1 = flat(116, 48); b1[10] = bar5(116, 116, 104.5, 105)  # 새 level 터치
env = make_env([b0, b1, flat(105, 48)])
hz = ['UP', -5, 100.0, -3, 120.0, -1]
tr, ev, _, dg = E.run(env, BASE, init=inject(+1, P0=85.0, R=old_R, hzz=hz))
kinds = [(x[2], x[5]) for x in ev if x[2] in ('ORDER_CREATE', 'ORDER_CANCEL', 'R_REPLACED', 'R_CONFIRM', 'FILL')]
check('R_REPLACED 기록 + old order cancel(reason R_REPLACED) + new order', any(k == 'R_REPLACED' for k, _ in kinds)
      and any(k == 'ORDER_CANCEL' and d.get('reason') == 'R_REPLACED' for k, d in kinds)
      and sum(1 for k, _ in kinds if k == 'ORDER_CREATE') == 2, str(kinds))
check('체결은 새 R 기준 (entry 104.72, ENTRY_R_LOW 100)', len(tr) == 1 and abs(tr[0]['entry'] - 104.72) < 1e-6 and tr[0]['entry_R']['ENTRY_R_LOW'] == 100.0 and tr[0]['entry_R']['ENTRY_R_T'] == S)
check('r_confirm_time < order_create_time < entry_time', tr[0]['r_confirm_time'] < tr[0]['order_create_time'] < tr[0]['entry_time'])

# ---------------------------------------------------------------- Case 8: Position filled -> new R -> entry R / stop / 2R unchanged
print('\nCase 8  Position filled -> new R confirmed')
# 봉 0: old R(100,120) 로 진입(104.72). hzz 는 UP anchor 108 / ext 130 (봉 0 안에서 low 가 124.8 이하 -> 확정) -> 봉 0 종료 새 R=(108,130)
b0 = flat(126, 5) + [bar5(110, 110, 104.5, 105)] + flat(105, 42)     # m5 체결 후 TP(114.76) 미도달
b1 = flat(105, 48)
env = make_env([b0, b1, flat(105, 48)])
hz = ['UP', -5, 108.0, -3, 130.0, -1]           # 봉 0 low 104.5 <= 130-0.236*22 -> 봉 0 종료에 새 R=(108,130) 확정
tr, ev, _, dg = E.run(env, BASE, init=inject(+1, P0=95.0, R=LONG_R, hzz=hz))
frozen = [x for x in ev if x[2] == 'R_CONFIRM_POS_FROZEN']
check('새 R 확정 이벤트 + POS_FROZEN', any(x[2] == 'R_CONFIRM' for x in ev) and len(frozen) == 1, str(dict(Counter(x[2] for x in ev))))
check('Entry R / stop / 2R 불변', len(tr) == 1 and tr[0]['entry_R']['ENTRY_R_LOW'] == 100.0 and abs(tr[0]['stop0'] - STOP) < 1e-9 and abs(tr[0]['targets0'][0][0] - TP2) < 1e-9
      and abs(tr[0]['stop'] - STOP) < 1e-9, '%s' % (tr[0]['targets0'] if tr else None))
check('새 R 로 재진입 없음 (거래 1건)', len(tr) == 1)

# ---------------------------------------------------------------- Case 9: 5M cursor — 청산 이전 5분봉의 반대편 터치는 무시
print('\nCase 9  5M cursor: long stop at m20, short level touched only at m15 (<20) -> no short')
# short 미러: short R=(low=-110, high=-90) -> 미러 level = -110 + 0.236*20 = -105.28 -> 실제 가격 105.28 이상이면 터치. 손절 미러 -110*(1-0.003) -> 실제 110.33
b = flat(103, 48); b[5] = bar5(103, 103, 102.0, 102.5)     # (long 진입용 별도 R)  long R=(97,117): level 101.72
b[5] = bar5(103, 103, 101.5, 102)                          # long 터치 m5
b[15] = bar5(102, 106.0, 102, 103)                         # short 레벨(105.28) 터치 m15 — 롱 포지션 보유 중이라 불가
b[20] = bar5(103, 103, 96.0, 97)                           # long stop(97*0.997=96.709) m20
env = make_env([b, flat(97, 48)])


def init9(sides):
    for sd in sides:
        sd.hzz = ['DOWN', 0, 1e12, 0, 0.0, -1]
        sd._leg_anchor = None
        if sd.s > 0:
            sd.armed, sd.P0, sd.H1, sd.dsize, sd.arm_day, sd.R, sd.R_broken = True, 90.0, 190.0, 100.0, 0, (97.0, 117.0, 20.0, R_T), False
        else:
            sd.armed, sd.P0, sd.H1, sd.dsize, sd.arm_day, sd.R, sd.R_broken = True, -120.0, -20.0, 100.0, 0, (-110.0, -90.0, 20.0, R_T), False


tr, ev, _, dg = E.run(env, BASE, init=init9)
check('long stop 1건만, short 0건 (과거 5분봉 재진입 없음)', len(tr) == 1 and tr[0]['side'].s > 0 and tr[0]['result'] == 'stop', '%s diag %s' % ([(t['side'].s, t['result'], t['fill_m']) for t in tr], dict(dg)))
check('진단 카운터: 레거시였다면 과거 재진입 1건', dg.get('nocursor_past_reentry_possible', 0) == 1)

# ---------------------------------------------------------------- Case 10: ATR confirmed-only
print('\nCase 10 ATR confirmed-only: 현재 봉 포함 ATR 이면 R 무효, 직전 완성봉까지면 유효')
PA = dict(BASE, ATR_MULT=1.0)
# 이전 14봉 range 5 (atr[t-1] ≈ 5), 봉 t 는 range 300 -> atr[t] = (13*5+300)/14 ≈ 26 > R size 20
warm = []
for i in range(16):
    bb = flat(110, 48); bb[0] = bar5(110, 112.5, 107.5, 110)
    warm.append(bb)
bt = flat(110, 48); bt[10] = bar5(110, 110, 104.5, 105); bt[40] = bar5(105, 400, 105, 300)
env = make_env(warm + [bt, flat(300, 48)])
R_t16 = (100.0, 120.0, 20.0, S + 15)
trC, evC, _, _ = E.run(env, PA, init=inject(+1, P0=95.0, R=R_t16))
trL, evL, _, _ = E.run(env, PA, legacy=frozenset(['ATR_CUR']), init=inject(+1, P0=95.0, R=R_t16))
check('교정: atr[t-1] 로 유효 -> 진입 1건 / 레거시 ATR_CUR: atr[t] 로 무효 -> 0건', len(trC) == 1 and len(trL) == 0, 'C %d L %d atr[t-1]=%.2f atr[t]=%.2f' % (len(trC), len(trL), env.atr[S + 15], env.atr[S + 16]))
check('atr_end_time < decision_time', trC and trC[0]['atr_end_time'] < trC[0]['decision_time'])

# ---------------------------------------------------------------- Case 11: Funding 실제 시각 / 잔여수량
print('\nCase 11 Funding actual timestamps & remaining qty')
fund = [(T0 + k * 8 * H, 0.0001) for k in range(1, 6)]     # 08:00, 16:00, 00:00 ...
# 봉 0 (00:00~04:00) m10 진입, 봉 2 (08:00~12:00) m0 에서 절반 TP (halfR2), 봉 4 (16:00~20:00) m5 손절 -> 펀딩 08:00 (전량), 16:00 (절반)
PH = dict(BASE, EXIT='halfR2')
b0 = flat(110, 48); b0[10] = bar5(110, 110, 104.5, 105)
b1 = flat(105, 48)
b2 = flat(105, 48); b2[0] = bar5(105, 116, 105, 115)        # 08:00 봉에서 +2R 절반 (펀딩 08:00 은 진입 전량에 부과: fill_time(봉 끝) >= ft)
b3 = flat(115, 48)
b4 = flat(115, 48); b4[5] = bar5(115, 115, 99.0, 100)       # 16:00 봉 이후 손절 -> 16:00 펀딩은 잔여 0.5
env = make_env([b0, b1, b2, b3, b4, flat(100, 48)], funding=fund)
tr, ev, _, dg = E.run(env, PH, init=inject(+1, P0=95.0, R=LONG_R))
fe = tr[0]['funding_events'] if tr else []
check('펀딩 2회: 08:00 x1.0, 16:00 x0.5', len(fe) == 2 and abs(fe[0][1] - 0.0001) < 1e-12 and abs(fe[1][1] - 0.00005) < 1e-12, str([(F.ts(a), b) for a, b in fe]))
check('부호: 롱 = 지불(+)', all(a > 0 for _, a in fe))
trL, _, _, _ = E.run(env, PH, legacy=frozenset(['FUND_4H']), init=inject(+1, P0=95.0, R=LONG_R))
check('(대조) 레거시 4H 근사는 진입 4H 시가 이후 ~ 청산 4H 종료 전 스탬프: %d회' % len(trL[0]['funding_events']), True)
# 손절이 정확히 16:00 봉(m0) 이면 16:00 펀딩은 부과(exit_time = 봉 끝 >= ft)
b4b = flat(115, 48); b4b[0] = bar5(115, 115, 99.0, 100)
env = make_env([b0, b1, b2, b3, b4b, flat(100, 48)], funding=fund)
tr, ev, _, dg = E.run(env, PH, init=inject(+1, P0=95.0, R=LONG_R))
check('청산이 16:00 봉 안이면 16:00 펀딩 부과 (보수적)', len(tr[0]['funding_events']) == 2)
# 손절이 15:55 봉이면 16:00 펀딩 미부과
b3c = flat(115, 48); b3c[47] = bar5(115, 115, 99.0, 100)
env = make_env([b0, b1, b2, b3c, flat(100, 48), flat(100, 48)], funding=fund)
tr, ev, _, dg = E.run(env, PH, init=inject(+1, P0=95.0, R=LONG_R))
check('청산이 15:55 봉이면 16:00 펀딩 미부과', len(tr[0]['funding_events']) == 1)

# ---------------------------------------------------------------- Case 12: MTM MDD
print('\nCase 12 Mark-to-market MDD')
b0 = flat(110, 48); b0[10] = bar5(110, 110, 104.5, 105); b0[30] = bar5(105, 105, 100.0, 100.5)   # 보유 중 -4.5% 평가손 (청산가 아님)
b1 = flat(100.5, 48); b1[20] = bar5(100.5, 116, 100.5, 115)                                       # TP
env = make_env([b0, b1, flat(115, 48)])
tr, ev, _, dg = E.run(env, BASE, init=inject(+1, P0=95.0, R=LONG_R))
e = F.evaluate(tr, 0.3, 10, 10000.0)
m = E.evaluate_mtm(tr, env, 0.3, 10, 10000.0)
check('거래는 이익(TP) 이라 레거시 MDD 0, MTM MDD > 0 (보유 중 평가손)', e['mdd'] == 0.0 and m['mdd_close'] > 10 and m['mdd_low'] >= m['mdd_close'],
      'legacy %.1f mtm_close %.1f mtm_low %.1f' % (e['mdd'], m['mdd_close'], m['mdd_low']))
# peak = 봉 31~47 의 110 에서 평가이익 상태, 저점 = 100.5 종가 (수수료 0.02% 반영, 30% x 10x)
eq_peak = 10000 * (1 + 0.3 * 10 * ((110 - LV) / LV - F.FEE_MAKER))
eq_low = 10000 * (1 + 0.3 * 10 * ((100.5 - LV) / LV - F.FEE_MAKER))
exp_dd = (eq_peak - eq_low) / eq_peak * 100
check('MTM close 값 = (peak@110 - eq@100.5)/peak = %.2f%%' % exp_dd, abs(m['mdd_close'] - exp_dd) < 0.05, '%.3f' % m['mdd_close'])
eq_low2 = 10000 * (1 + 0.3 * 10 * ((100.0 - LV) / LV - F.FEE_MAKER))
check('MTM low 값 = 5분봉 저가(100.0) 기준 %.2f%%' % ((eq_peak - eq_low2) / eq_peak * 100), abs(m['mdd_low'] - (eq_peak - eq_low2) / eq_peak * 100) < 0.05, '%.3f' % m['mdd_low'])

# ---------------------------------------------------------------- Case 13: Short mirror (Entry -> Stop)
print('\nCase 13 Short mirror: entry -> stop')
b = flat(90, 48); b[10] = bar5(90, 95.5, 90, 95); b[20] = bar5(95, 101, 95, 100)   # short R=(-110,-90): level 미러 -105.28 -> 가격 105.28?  아니: 미러 low=-110(가격110), high=-90(가격90), size 20 -> level = -110+4.72 = -105.28 -> 가격 105.28 이상 터치
b = flat(100, 48); b[10] = bar5(100, 105.5, 100, 105); b[20] = bar5(105, 111, 105, 110)
env = make_env([b, flat(110, 48)])
tr, ev, _, dg = E.run(env, BASE, init=inject(-1, P0=-120.0, R=(-110.0, -90.0, 20.0, R_T)))
check('short 1 loss (stop)', len(tr) == 1 and tr[0]['side'].s < 0 and tr[0]['result'] == 'stop' and tr[0]['r_net'] < 0, str([(t['result'], round(t['r_net'], 4)) for t in tr]))

# ---------------------------------------------------------------- Case 14: 리뷰 #1/#2 — dexit 로 닫힌 포지션의 pending V 청산이 다음 포지션에 전이되지 않아야 한다
print('\nCase 14 stale pending V exit must not close the next (unrelated) position')
# 봉 0 (day 1, 00:00~04:00) m10 롱 진입(P0=101 > stop 99.7), 봉 5 (20:00~24:00) 마지막 5분봉에서 low 100.5 < P0 -> V_DETECT(pending)
# 일봉 종가 100.5 < P0 -> 다음날 00:00 dexit (EXIT='halfR2' 는 d_exit=True). 그 뒤 숏이 진입하면 'v' 로 닫히면 안 된다.
PH2 = dict(BASE, EXIT='halfR2', DMIN=0.5)      # 합성 일봉(9% 범위)이 일봉 ZigZag 를 건드리지 않도록 DMIN 을 크게
b0 = flat(110, 48); b0[10] = bar5(110, 110, 104.5, 105)
mid = [flat(105, 48) for _ in range(4)]
b5 = flat(105, 48); b5[47] = bar5(105, 105, 100.5, 100.5)
b6 = flat(100.5, 48); b6[10] = bar5(100.5, 126.0, 100.5, 125.0)      # day 2: 숏 레벨(125.28) 터치 (숏 R=(-130,-110) 라 day 1 의 110 에서는 미터치)
env = make_env([b0] + mid + [b5, b6, flat(105.5, 48)])


def init14(sides):
    for sd in sides:
        sd.hzz = ['DOWN', 0, 1e12, 0, 0.0, -1]
        sd._leg_anchor = None
        if sd.s > 0:
            sd.armed, sd.P0, sd.H1, sd.dsize, sd.arm_day, sd.R, sd.R_broken, sd.lastL = True, 101.0, 201.0, 100.0, 0, LONG_R, False, None
        else:
            sd.armed, sd.P0, sd.H1, sd.dsize, sd.arm_day, sd.R, sd.R_broken, sd.lastL = True, -140.0, -40.0, 100.0, 0, (-130.0, -110.0, 20.0, R_T), False, None


tr, ev, _, dg = E.run(env, PH2, init=init14)
kinds = [(t['side'].s, t['result'], [k for (_, k, _, _) in t['seq']]) for t in tr]
check('롱은 dexit, 숏은 v 로 닫히지 않음', len(tr) >= 2 and tr[0]['result'] == 'dexit' and tr[1]['side'].s < 0 and tr[1]['result'] != 'v'
      and not any(k == 'EXIT_V' for k in kinds[1][2]), '%s diag %s' % (kinds, dict(dg)))
check('pending 이 포지션 종료와 함께 소멸 (dropped 카운트 0, 롱 seq 에 V_DETECT 존재)', dg.get('pending_exit_dropped', 0) == 0 and 'V_DETECT' in kinds[0][2])
E.assert_invariants(tr, ev, env)

# ---------------------------------------------------------------- Case 15: 리뷰 #4 — 청산 봉과 같은 5분봉의 반대편 진입 금지 (§6)
print('\nCase 15 no opposite-side entry on the exit 5m bar')
b = flat(103, 48); b[5] = bar5(103, 103, 101.5, 102)                 # long 터치 (R=(97,117) level 101.72)
b[20] = bar5(103, 106.0, 96.0, 97)                                   # 같은 5분봉: long stop(96.709) + short 레벨(105.28) 터치
b[30] = bar5(97, 106.0, 97, 105.5)                                   # 이후 봉: short 레벨 재터치
env = make_env([b, flat(105.5, 48)])
tr, ev, _, dg = E.run(env, BASE, init=init9)
check('long stop @m20, short 진입은 m30 (m20 아님)', len(tr) == 2 and tr[0]['result'] == 'stop' and tr[1]['side'].s < 0 and tr[1]['fill_m'] == mi(env, 0, 30),
      '%s diag %s' % ([(t['side'].s, t['result'], t['fill_m'] - mi(env, 0, 0)) for t in tr], dict(dg)))
check('진단: 청산 봉 진입 스킵 1건, 거래 겹침 불변식 0', dg.get('entry_skipped_on_exit_bar', 0) == 1 and E.check_invariants(tr, ev, env)['trade_overlap'] == 0)
trL, _, _, dgL = E.run(env, BASE, legacy=frozenset(['NOCURSOR']), init=init9)
check('(대조) NOCURSOR 레거시 플래그면 같은 봉 진입', len(trL) == 2 and trL[1]['fill_m'] == mi(env, 0, 20))

# ---------------------------------------------------------------- Case 16: 리뷰 #3 — Limit 진입 5분봉의 TP 는 다음 봉부터 (§10)
print('\nCase 16 entry-bar TP deferred to the next 5m bar')
b = flat(110, 48); b[10] = bar5(116, 116, 104.5, 105)                # 진입 봉: high 116 >= TP 114.76 (시가부터 TP 위)
b[11] = bar5(105, 105, 104.8, 105)                                   # 다음 봉: TP 미도달
env = make_env([b, flat(105, 48)])
tr, ev, _, dg = E.run(env, BASE, init=inject(+1, P0=95.0, R=LONG_R))
check('교정: 진입봉 TP 미체결 -> open 유지 (entrybar_tp_deferred=1)', len(tr) == 1 and tr[0]['result'] == 'open' and dg.get('entrybar_tp_deferred', 0) == 1, '%s %s' % ([t['result'] for t in tr], dict(dg)))
trL, _, _, _ = E.run(env, BASE, legacy=frozenset(['ENTRYBAR_TP']), init=inject(+1, P0=95.0, R=LONG_R))
check('(대조) ENTRYBAR_TP 레거시 플래그면 진입봉 TP 체결', len(trL) == 1 and trL[0]['result'] == 'tp' and trL[0]['exit_m'] == mi(env, 0, 10))
# 진입봉 Entry->Stop 은 여전히 동일봉 (불리한 순서)
b = flat(110, 48); b[10] = bar5(116, 116, 99.0, 105)
env = make_env([b, flat(105, 48)])
tr, ev, _, dg = E.run(env, BASE, init=inject(+1, P0=95.0, R=LONG_R))
check('진입봉 Entry->Stop 은 동일봉 손절 유지', len(tr) == 1 and tr[0]['result'] == 'stop' and tr[0]['exit_m'] == mi(env, 0, 10))

# ---------------------------------------------------------------- Case 17: 펀딩 스탬프 ms 오차 정규화
print('\nCase 17 funding stamps with ms offsets are normalised')
fund_ms = [(T0 + k * 8 * H + (7 if k % 2 else 0), 0.0001) for k in range(1, 6)]     # 일부 스탬프가 +7ms
b0 = flat(110, 48); b0[10] = bar5(110, 110, 104.5, 105)
b2 = flat(105, 48); b2[0] = bar5(105, 105, 99.0, 100)                # 08:00 봉 시가에 손절 -> 08:00 펀딩(+7ms 스탬프) 은 부과 (exit_time = 봉 끝)
env = make_env([b0, flat(105, 48), b2, flat(100, 48)], funding=fund_ms)
tr, ev, _, dg = E.run(env, BASE, init=inject(+1, P0=95.0, R=LONG_R))
check('08:00(+7ms) 펀딩 1회 부과, 스탬프는 분 단위로 정규화', len(tr[0]['funding_events']) == 1 and tr[0]['funding_events'][0][0] == T0 + 8 * H, str([(F.ts(a), b) for a, b in tr[0]['funding_events']]))

# ---------------------------------------------------------------- 요약
print('\n' + '=' * 100)
n_fail = sum(1 for _, ok, _ in results if not ok)
print('Synthetic tests: %d PASS / %d FAIL' % (len(results) - n_fail, n_fail))
assert n_fail == 0, [r for r in results if not r[1]]
