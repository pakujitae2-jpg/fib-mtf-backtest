# -*- coding: utf-8 -*-
# 청산 대안(tpR3 / halfR2spec)의 BTC Walk-forward + 4종목 연도별 PF
import sys, time
import fib_mtf as F

sys.stdout.reconfigure(encoding='utf-8')
POS, LEV, SEED = 0.30, 10, 10000.0
YEARS = [str(y) for y in range(2019, 2027)]
V2 = dict(DCONF=0.382, DMIN=0.08, R4=0.236, R_ENTRY_FIB=0.236, R_RATIO=0.1, ATR_MULT=1.0, TOL=0.003, BUF=0.003,
          EXIT='spec', RATCHET=0.0, MFILT='off', STRUCT='HH_HL', SIDES='both')
SYMS = ['btcusdt', 'ethusdt', 'bnbusdt', 'solusdt']
DATA = {s: F.load_data('2019-03-01', s) for s in SYMS}


def yearly(data, trades):
    out = {}
    for y in YEARS:
        pms = [F.pm_of(t, LEV) for t in trades if F.ts(data.h_ot[t['t0']])[:4] == y and t['result'] != 'open']
        out[y] = {'n': len(pms), 'pf': F._pf(pms), 'pms': pms}
    return out


def yline(yr):
    return ' '.join('%4.1f' % min(yr[y]['pf'], 9.9) if yr[y]['n'] >= 3 else '   -' for y in YEARS)


def pooled(yr, ys):
    pms = [p for y in ys for p in yr[y]['pms']]
    pos = sum(1 for y in ys if yr[y]['n'] >= 3 and yr[y]['pf'] > 1)
    cnt = sum(1 for y in ys if yr[y]['n'] >= 3)
    ret = 1.0
    for p in pms:
        ret *= max(0.0, 1 + POS * p / 100)
    return {'n': len(pms), 'pf': F._pf(pms), 'pos': pos, 'cnt': cnt, 'ret': (ret - 1) * 100,
            'min': min((sum(yr[y]['pms']) for y in ys if yr[y]['n'] >= 3), default=-999)}


for EXIT, RC in (('spec', 0.0), ('tpR3', 0.0), ('halfR2spec', 0.0), ('halfR2spec', 0.10)):
    print('=' * 150)
    print('EXIT=%s 래칫 %.0f%%' % (EXIT, RC * 100))
    print('=' * 150)
    data = DATA['btcusdt']
    t0 = time.time()
    RES = []
    for DMIN in (0.06, 0.08, 0.10, 0.12):
        for R4 in (0.236, 0.382):
            for RR in (0.1, 0.2):
                for AM in (1.0, 1.5):
                    for TOL in (0.003, 0.005):
                        P = dict(V2, DMIN=DMIN, R4=R4, R_RATIO=RR, ATR_MULT=AM, TOL=TOL, EXIT=EXIT, RATCHET=RC)
                        tr, _, _ = F.run(data, P)
                        RES.append((P, yearly(data, tr)))
    oos = []
    print('BTC Walk-forward (expanding, 일관성 선택):')
    for ty in range(2022, 2027):
        train = [str(y) for y in range(2019, ty)]
        cands = [(P, yr, pooled(yr, train)) for P, yr in RES if pooled(yr, train)['n'] >= 15]
        P, yr, pl = max(cands, key=lambda c: (c[2]['pos'], c[2]['min'], c[2]['pf']))
        te = yr[str(ty)]
        oos += te['pms']
        print('  %d <- %s~%s  DMIN %.2f R4 %.3f Rr %.1f ATR %.1f TOL %.3f | 학습 PF %.2f (%d/%d) | 검증 n %2d PF %.2f' % (
            ty, train[0], train[-1], P['DMIN'], P['R4'], P['R_RATIO'], P['ATR_MULT'], P['TOL'], pl['pf'], pl['pos'], pl['cnt'], te['n'], te['pf']))
    eq, peak, mdd = 1.0, 1.0, 0.0
    for p in oos:
        eq *= max(0.0, 1 + POS * p / 100)
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak)
    print('  WF 검증구간 합산: 거래 %d 승률 %.1f%% PF %.2f 기대값 %+.1f%% 누적 %+.0f%% MDD %.0f%%  (%.0fs)' % (
        len(oos), sum(1 for p in oos if p > 0) / len(oos) * 100, F._pf(oos), sum(oos) / len(oos), (eq - 1) * 100, mdd * 100, time.time() - t0))
    print('4종목 연도별 PF (V2 진입 고정):')
    for s in SYMS:
        d = DATA[s]
        tr, _, _ = F.run(d, dict(V2, EXIT=EXIT, RATCHET=RC))
        yrs = (d.h_ot[d.LAST] - d.h_ot[d.start4]) / F.D_MS / 365.25
        e = F.evaluate(tr, POS, LEV, SEED, yrs)
        yr = yearly(d, tr)
        pos = sum(1 for y in YEARS if yr[y]['n'] >= 3 and yr[y]['pf'] > 1)
        cnt = sum(1 for y in YEARS if yr[y]['n'] >= 3)
        print('  %-4s n %3d 승률 %4.1f PF %.2f 기대값 %+5.1f MDD %2.0f 연패 %2d | %s (%d/%d) | 10%%x10x 수익률 %+.0f%%' % (
            s.upper().replace('USDT', ''), e['n'], e['wr'], e['pf'], e['exp'], e['mdd'], e['worst'], yline(yr), pos, cnt,
            F.evaluate(tr, 0.10, 10, SEED, yrs)['ret']))
    print()
