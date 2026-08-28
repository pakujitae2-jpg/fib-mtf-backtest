# -*- coding: utf-8 -*-
"""V3 엔진 시간축 편향 진단 (교차검증 전용).

전략 파라미터는 건드리지 않는다. 기존 run() 을 그대로 복제한 뒤 계측만 추가해서
작업지시서가 주장하는 편향이 실제로 존재하는지, 크기가 얼마인지 센다.

측정 항목
  A) R_INVALID 선행 편향 : 같은 4H봉 안에서 (진입레벨 터치) 가 (R.low 이탈) 보다 먼저였는데
                           엔진이 4H 전체 low 로 R 을 먼저 죽여서 진입을 통째로 날린 건수
  A2) V(P0 훼손) 선행 편향 : 위와 동일하지만 armed 해제 쪽
  B) ATR look-ahead       : r_valid() 가 atr[t] 대신 atr[t-1] 을 썼을 때 판정이 뒤집히는 건수
  C) FILL=C 동일봉 SL/TP  : 5분봉 종가 시장가 진입 직후 '그 5분봉' 의 low/high 로 SL/TP 가 잡힌 건수
  D) 과거 5분봉 재진입     : 같은 4H봉 안에서 직전 포지션 청산 5분봉보다 '앞선' 5분봉에 신규 진입한 건수
"""
import sys, time
from collections import Counter
import fib_mtf as F
from fib_mtf import Side, EPS, H_MS, SLIP

sys.stdout.reconfigure(encoding='utf-8')


def run_diag(data, P):
    sides = []
    if P['SIDES'] in ('both', 'long'):
        sides.append(Side(+1, data, P))
    if P['SIDES'] in ('both', 'short'):
        sides.append(Side(-1, data, P))
    d0 = data.h_day[data.start4]
    for sd in sides:
        for d in range(0, d0):
            sd.daily_update(d)
    cur_day = d0
    for sd in sides:
        for t in range(max(0, data.start4 - 300), data.start4):
            sd.track_anchor()
            sd.h4_update(t)
    pos = None
    trades, events = [], []
    C = Counter()
    DET = {'A': [], 'A2': [], 'B': [], 'C': [], 'D': []}
    last_exit_m = [None]          # 이번 4H봉에서 마지막으로 청산이 일어난 5분봉 index

    def close_pos(t, px, frac, kind, fine_i=None):
        nonlocal pos
        pos['fills'].append((t, px, frac, kind))
        pos['frac'] -= frac
        if fine_i is not None:
            last_exit_m[0] = fine_i
        if pos['frac'] <= 1e-9:
            finish(t)

    def apply_policy(t, m):
        nonlocal pos
        policy = P.get('TGT_POLICY', 'retro')
        if policy == 'retro' or pos.get('policy_done'):
            return
        pos['policy_done'] = True
        sd = pos['side']
        passed = [x for x in pos['tgts'] if x[0] <= sd.f_hi[m] + EPS]
        pos['tgts'] = [x for x in pos['tgts'] if x[0] > sd.f_hi[m] + EPS]
        if policy == 'market':
            for px, fr in passed:
                if pos is None:
                    break
                close_pos(t, sd.f_cl[m] - SLIP * abs(sd.f_cl[m]), min(fr, pos['frac']), 'tpm', m)

    def finish(t):
        nonlocal pos
        sd = pos['side']
        e = pos['entry']
        r = 0.0
        fee = F.FEE_TAKER if pos.get('taker') else F.FEE_MAKER
        for (_, px, fr, kind) in pos['fills']:
            r += fr * (px - e) / abs(e)
            fee += fr * (F.FEE_MAKER if kind == 'tp' else F.FEE_TAKER)
            if kind == 'stop':
                r -= fr * SLIP
        hold_h = (data.h_ot[t] - data.h_ot[pos['t0']]) / H_MS + 4
        if data.fund_ts:
            from bisect import bisect_left
            a = bisect_left(data.fund_ts, data.h_ot[pos['t0']] + 1)
            b = bisect_left(data.fund_ts, data.h_ot[t] + 4 * H_MS)
            fund = 0.0
            for k in range(a, b):
                ft = data.fund_ts[k]
                rem = 1.0 - sum(fr for (j, _, fr, _) in pos['fills'] if data.h_ot[j] + 4 * H_MS <= ft)
                if rem <= 0:
                    break
                fund += data.fund_rate[k] * rem * (1 if sd.s > 0 else -1)
        else:
            fund = F.FUNDING * hold_h / 8
        pos['funding'] = fund
        pos['r_net'] = r - fee - fund
        pos['t1'] = t
        pos['hold_h'] = hold_h
        pos['result'] = pos['fills'][-1][3]
        trades.append(pos)
        pos = None

    for t in range(data.start4, data.LAST + 1):
        d = data.h_day[t]
        last_exit_m[0] = None
        if d != cur_day:
            for sd in sides:
                ev = sd.daily_update(d - 1)
                if ev:
                    events.append((t, sd.s, ev, d - 1))
                if pos and pos['side'] is sd and pos['frac'] > 0:
                    if pos['d_exit']:
                        ref = sd.lastL if sd.lastL is not None else pos['P0']
                        if sd.d_cl[d - 1] < ref - EPS:
                            close_pos(t, sd.h_op[t], pos['frac'], 'dexit')
            cur_day = d
        if pos:
            sd = pos['side']
            if P['RATCHET']:
                pos['stop'] = max(pos['stop'], pos['peak'] - P['RATCHET'] * abs(pos['peak']))
            a, b = data.fine_range(t)
            if a < b:
                for m in range(a, b):
                    if pos is None:
                        break
                    if sd.f_lo[m] <= pos['stop'] + EPS:
                        close_pos(t, pos['stop'], pos['frac'], 'stop', m)
                        break
                    while pos and pos['tgts'] and sd.f_hi[m] >= pos['tgts'][0][0] - EPS:
                        px, fr = pos['tgts'].pop(0)
                        close_pos(t, px, min(fr, pos['frac']), 'tp', m)
                        if pos and pos['be']:
                            pos['stop'] = max(pos['stop'], pos['entry'] + 0.002 * abs(pos['entry']))
                        if pos:
                            apply_policy(t, m)
            else:
                if sd.h_lo[t] <= pos['stop'] + EPS:
                    close_pos(t, pos['stop'], pos['frac'], 'stop')
                else:
                    while pos and pos['tgts'] and sd.h_hi[t] >= pos['tgts'][0][0] - EPS:
                        px, fr = pos['tgts'].pop(0)
                        close_pos(t, px, min(fr, pos['frac']), 'tp')
                        if pos and pos['be']:
                            pos['stop'] = max(pos['stop'], pos['entry'] + 0.002 * abs(pos['entry']))
            if pos:
                pos['peak'] = max(pos['peak'], sd.h_hi[t])
                pos['mae'] = min(pos['mae'], (sd.h_lo[t] - pos['entry']) / abs(pos['entry']))

        # ---------------- 계측 B: ATR look-ahead ----------------
        for sd in sides:
            if sd.R is None or sd.R_broken or sd.dsize is None:
                continue
            now = sd.R[2] >= max(sd.dsize * P['R_RATIO'], data.atr[t] * P['ATR_MULT'])
            prev = sd.R[2] >= max(sd.dsize * P['R_RATIO'], data.atr[t - 1] * P['ATR_MULT'])
            if now != prev:
                C['B_flip'] += 1
                if sd.armed and sd.R[3] < t:
                    C['B_flip_armed'] += 1
                    DET['B'].append((t, sd.s, 'now=%s prev=%s' % (now, prev)))

        # ---------------- V / R break (원본 로직 + 계측 A) ----------------
        for sd in sides:
            a, b = data.fine_range(t)
            # A2: armed 상태에서 P0 훼손
            if sd.armed and sd.h_lo[t] < sd.P0 - EPS:
                if (pos is None and sd.R and not sd.R_broken and sd.r_valid(t) and sd.R[3] < t
                        and sd.m_ok(d) and a < b):
                    lv = sd.entry_level()
                    if lv > sd.stop_level():
                        fm = next((m for m in range(a, b) if sd.f_lo[m] <= lv + EPS), None)
                        bm = next((m for m in range(a, b) if sd.f_lo[m] < sd.P0 - EPS), None)
                        if fm is not None and bm is not None and fm <= bm:
                            C['A2_missed'] += 1
                            DET['A2'].append((t, sd.s, fm - a, bm - a))
                sd.armed = False
                sd.vflag = True
                events.append((t, sd.s, 'V', d))
                if pos and pos['side'] is sd:
                    close_pos(t, sd.h_cl[t], pos['frac'], 'v')
            # A: R.low 이탈
            if sd.R and not sd.R_broken and sd.h_lo[t] < sd.R[0] - EPS:
                if sd.armed and sd.r_valid(t) and sd.sig_key == sd.R[3]:
                    events.append((t, sd.s, 'R_INVALID', d))
                if (pos is None and sd.armed and sd.r_valid(t) and sd.R[3] < t
                        and sd.m_ok(d) and a < b):
                    lv = sd.entry_level()
                    stop = sd.stop_level()
                    if lv > stop:
                        fm = next((m for m in range(a, b) if sd.f_lo[m] <= lv + EPS), None)
                        bm = next((m for m in range(a, b) if sd.f_lo[m] < sd.R[0] - EPS), None)
                        if fm is not None and bm is not None and fm <= bm:
                            C['A_missed'] += 1
                            # 이 거래는 (보수적으로) 손절로 끝난다: 진입 후 R.low 이탈 -> stop
                            C['A_missed_same5m' if fm == bm else 'A_missed_later'] += 1
                            DET['A'].append((t, sd.s, fm - a, bm - a, lv, stop))
                sd.R_broken = True

        for sd in sides:
            if sd.armed and sd.R and not sd.R_broken and sd.r_valid(t) and sd.R[3] < t and sd.sig_key != sd.R[3]:
                sd.sig_key = sd.R[3]
                events.append((t, sd.s, 'SIGNAL', d))

        fill_model = P.get('FILL', 'A')
        pen = P.get('PEN', 0.0)
        if pos is None:
            for sd in sides:
                if not sd.armed or not sd.r_valid(t) or sd.R[3] >= t:
                    continue
                if not sd.m_ok(d):
                    continue
                lv = sd.entry_level()
                need = lv - pen * abs(lv) if fill_model == 'B' else lv
                if sd.h_lo[t] > need + EPS:
                    continue
                stop = sd.stop_level()
                if lv <= stop:
                    continue
                other = [o for o in sides if o is not sd]
                if other and other[0].vflag:
                    other[0].vflag = False
                    events.append((t, sd.s, 'SKIP_V', d))
                    sd.R_broken = True
                    continue
                a, b = data.fine_range(t)
                fill_m = None
                if a < b:
                    fill_m = next((m for m in range(a, b) if sd.f_lo[m] <= need + EPS), None)
                    if fill_m is None:
                        continue
                # ---------------- 계측 D: 과거 5분봉 재진입 ----------------
                if fill_m is not None and last_exit_m[0] is not None and fill_m < last_exit_m[0]:
                    C['D_past_reentry'] += 1
                    DET['D'].append((t, sd.s, fill_m - a, last_exit_m[0] - a))
                expected = lv
                taker = False
                if fill_model == 'C':
                    lv = (sd.f_cl[fill_m] if fill_m is not None else sd.h_cl[t]) + SLIP * abs(lv)
                    taker = True
                    if lv <= stop:
                        continue
                ex = P['EXIT']
                tg, d_exit, be = [], False, False
                if ex == 'spec':
                    tg = [(x, 0.25) for x in sd.targets(d, lv)]
                    d_exit = True
                elif ex == 'trail':
                    d_exit = True
                elif ex in ('tpR2', 'tpR3'):
                    tg = [(lv + (2.0 if ex == 'tpR2' else 3.0) * (lv - stop), 1.0)]
                elif ex == 'halfR2':
                    tg = [(lv + 2.0 * (lv - stop), 0.5)]
                    d_exit, be = True, True
                elif ex == 'halfR2spec':
                    tg = [(lv + 2.0 * (lv - stop), 0.5)] + [(x, 0.125) for x in sd.targets(d, lv)]
                    d_exit, be = True, True
                pos = {'side': sd, 't0': t, 'entry': lv, 'stop': stop, 'stop0': stop, 'frac': 1.0,
                       'tgts': tg, 'd_exit': d_exit, 'be': be, 'fills': [], 'peak': lv, 'mae': 0.0,
                       'P0': sd.P0, 'H1': sd.H1, 'dsize': sd.dsize, 'R': sd.R, 'day': d,
                       'expected': expected, 'taker': taker, 'age': t - sd.R[3], 'key': (sd.s, sd.R[3]),
                       'fill_m': fill_m}
                sd.armed = False
                sd.R_broken = True
                if fill_m is not None:
                    for m in range(fill_m, b):
                        if pos is None:
                            break
                        if sd.f_lo[m] <= pos['stop'] + EPS:
                            # ---------------- 계측 C: 동일봉 SL ----------------
                            if m == fill_m:
                                C['C_same5m_stop_' + fill_model] += 1
                                DET['C'].append((t, sd.s, 'stop'))
                            close_pos(t, pos['stop'], pos['frac'], 'stop', m)
                            break
                        while pos and pos['tgts'] and sd.f_hi[m] >= pos['tgts'][0][0] - EPS:
                            if m == fill_m:
                                C['C_same5m_tp_' + fill_model] += 1
                                DET['C'].append((t, sd.s, 'tp'))
                            px, fr = pos['tgts'].pop(0)
                            close_pos(t, px, min(fr, pos['frac']), 'tp', m)
                            if pos and pos['be']:
                                pos['stop'] = max(pos['stop'], pos['entry'] + 0.002 * abs(pos['entry']))
                            if pos:
                                apply_policy(t, m)
                elif sd.h_lo[t] <= stop + EPS:
                    close_pos(t, stop, 1.0, 'stop')
                if pos:
                    pos['peak'] = max(pos['peak'], sd.h_hi[t])
                    pos['mae'] = min(pos['mae'], (sd.h_lo[t] - lv) / abs(lv))
                break
        for sd in sides:
            sd.track_anchor()
            sd.h4_update(t)
    if pos:
        pos['fills'].append((data.LAST, pos['side'].h_cl[data.LAST], pos['frac'], 'open'))
        pos['frac'] = 0.0
        finish(data.LAST)
    return trades, events, C, DET


V3 = dict(DCONF=0.382, DMIN=0.08, R4=0.236, R_ENTRY_FIB=0.236, R_RATIO=0.1, ATR_MULT=1.0, TOL=0.003, BUF=0.003,
          EXIT='halfR2spec', RATCHET=0.0, MFILT='off', STRUCT='HH_HL', SIDES='both', FILL='A', PEN=0.0,
          TGT_POLICY='retro')
START = '2019-12-15'

fund = F.load_funding('btcusdt_funding.csv')
d_spot = F.load_csv('btcusdt_1d_2017.csv')
h4_fut = F.load_csv('btcusdt_fut_4h.csv')
f_fut = F.load_csv('btcusdt_fut_5m.csv')
dC = F.Data(d_spot, h4_fut, f_fut, START, funding=fund)
yrs = (dC.h_ot[dC.LAST] - dC.h_ot[dC.start4]) / F.D_MS / 365.25

print('=' * 78)
print('구성 C (Spot D/W + Fut 4H/5m), halfR2spec, 실제 펀딩 — 3차 보고서 PF 1.70 재현 대상')
print('=' * 78)
for fm in ('A', 'C'):
    P = dict(V3, FILL=fm)
    tr, ev, C, DET = run_diag(dC, P)
    e = F.evaluate(tr, 0.30, 10, 10000.0, yrs)
    print('\n[FILL=%s] 거래 %d  PF %.2f  수익률 %+.0f%%  MDD %.0f%%' % (fm, e['n'], e['pf'], e['ret'], e['mdd']))
    print('  A  R.low 이탈보다 진입이 먼저였는데 통째로 날린 신호 : %d 건 '
          '(동일 5분봉 %d / 이후 5분봉 %d)' % (C['A_missed'], C['A_missed_same5m'], C['A_missed_later']))
    print('  A2 P0 훼손보다 진입이 먼저였던 신호                  : %d 건' % C['A2_missed'])
    print('  B  ATR[t] -> ATR[t-1] 로 r_valid 판정이 뒤집힘        : %d 건 (그중 armed+확정R %d 건)'
          % (C['B_flip'], C['B_flip_armed']))
    print('  C  진입 5분봉과 동일 5분봉에서 SL 체결                : %d 건' % C['C_same5m_stop_' + fm])
    print('     진입 5분봉과 동일 5분봉에서 TP 체결                : %d 건' % C['C_same5m_tp_' + fm])
    print('  D  직전 청산보다 앞선 5분봉에 재진입                  : %d 건' % C['D_past_reentry'])
    if DET['A'][:5]:
        print('  A 예시(4H봉 index, side, 진입 5분 offset, 이탈 5분 offset):')
        for x in DET['A'][:5]:
            print('     %s %s  fill@+%d  break@+%d' % (F.ts(dC.h_ot[x[0]]), '롱' if x[1] > 0 else '숏', x[2], x[3]))
    if DET['D'][:5]:
        print('  D 예시:')
        for x in DET['D'][:5]:
            print('     %s %s  진입@+%d  직전청산@+%d' % (F.ts(dC.h_ot[x[0]]), '롱' if x[1] > 0 else '숏', x[2], x[3]))
