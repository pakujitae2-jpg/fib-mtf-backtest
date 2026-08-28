# -*- coding: utf-8 -*-
# v2 후보 교차검증: ETH / BNB / SOL 에 BTC 파라미터를 그대로 적용 + 이웃 그리드 + 무작위 대비 가설검정
import os, sys, time, random
import fib_mtf as F

sys.stdout.reconfigure(encoding='utf-8')
POS, LEV, SEED = 0.30, 10, 10000.0
YEARS = [str(y) for y in range(2019, 2027)]
V2 = dict(DCONF=0.382, DMIN=0.08, R4=0.236, R_ENTRY_FIB=0.236, R_RATIO=0.1, ATR_MULT=1.0, TOL=0.003, BUF=0.003,
          EXIT='spec', RATCHET=0.0, MFILT='off', STRUCT='HH_HL', SIDES='both')
SYMS = [s for s in sys.argv[1:]] or ['btcusdt', 'ethusdt', 'bnbusdt', 'solusdt']


def yearly(data, trades):
    out = {}
    for y in YEARS:
        pms = [F.pm_of(t, LEV) for t in trades if F.ts(data.h_ot[t['t0']])[:4] == y and t['result'] != 'open']
        out[y] = {'n': len(pms), 'pf': F._pf(pms)}
    return out


def yline(yr):
    return ' '.join('%4.1f' % min(yr[y]['pf'], 9.9) if yr[y]['n'] >= 3 else '   -' for y in YEARS)


def forward(sd, t, entry, stop, mults, last, maxbars=360):
    hit = {m: False for m in mults}
    risk = entry - stop
    for j in range(t + 1, min(t + maxbars, last) + 1):
        for m in mults:
            if not hit[m] and sd.h_hi[j] >= entry + m * risk - F.EPS:
                hit[m] = True
        if sd.h_lo[j] <= stop + F.EPS:
            break
    return hit


MULTS = [1, 2, 3, 5]
summary = []
for sym in SYMS:
    if sym != 'btcusdt' and not os.path.exists('%s_5m.csv' % sym):
        print('%s: 데이터 없음, 건너뜀' % sym)
        continue
    t0 = time.time()
    data = F.load_data('2019-03-01', sym)
    yrs = (data.h_ot[data.LAST] - data.h_ot[data.start4]) / F.D_MS / 365.25
    trades, events, sides = F.run(data, V2)
    e = F.evaluate(trades, POS, LEV, SEED, yrs)
    yr = yearly(data, trades)
    pos = sum(1 for y in YEARS if yr[y]['n'] >= 3 and yr[y]['pf'] > 1)
    cnt = sum(1 for y in YEARS if yr[y]['n'] >= 3)
    print('\n' + '=' * 150)
    print('%s  |  %s ~ %s (%.1f년)  |  V2 파라미터 그대로  (로드+실행 %.1fs)' % (sym.upper(), F.ts(data.h_ot[data.start4]), F.ts(data.h_ot[data.LAST]), yrs, time.time() - t0))
    print('=' * 150)
    print('거래 %d (롱 %d / 숏 %d)  승률 %.1f%%  평균승 %+.0f%% 평균패 %+.0f%%  PF %.2f (롱 %.2f / 숏 %.2f)  기대값 %+.1f%%  수익률 %+.0f%%  MDD %.0f%%  연패 %d  청산 %d' % (
        e['n'], e['long_n'], e['short_n'], e['wr'], e['avg_win'], e['avg_loss'], e['pf'], min(e['long_pf'], 9.99), min(e['short_pf'], 9.99),
        e['exp'], e['ret'], e['mdd'], e['worst'], e['liq']))
    print('연도별 PF 19~26: %s  (%d/%d 양수)' % (yline(yr), pos, cnt))
    # 가설검정
    closed = [t for t in trades if t['result'] != 'open']
    pat = [forward(t['side'], t['t0'], t['entry'], t['stop0'], MULTS, data.LAST) for t in closed]
    random.seed(5)
    smap = {s.s: s for s in sides}
    rnd = []
    for _ in range(2000):
        t = random.randint(data.start4, data.LAST - 400)
        tr = random.choice(closed)
        sd = smap[tr['side'].s]
        entry = sd.h_cl[t]
        risk = (tr['entry'] - tr['stop0']) / abs(tr['entry'])
        rnd.append(forward(sd, t, entry, entry - risk * abs(entry), MULTS, data.LAST))
    ps = ['%5.1f%%' % (sum(1 for h in pat if h[m]) / len(pat) * 100) for m in MULTS]
    rs = ['%5.1f%%' % (sum(1 for h in rnd if h[m]) / len(rnd) * 100) for m in MULTS]
    print('가설검정 +1R/+2R/+3R/+5R 도달:  전략 %s  |  무작위 %s' % (' '.join(ps), ' '.join(rs)))
    # 이웃 그리드
    print('\n이웃 그리드 (DMIN x R4, 나머지 V2):')
    print('%6s | %s' % ('DMIN', ' | '.join('R4=%.3f: 거래/PF/양수연도' % r4 for r4 in (0.236, 0.382))))
    for dm in (0.06, 0.08, 0.10, 0.12):
        cells = []
        for r4 in (0.236, 0.382):
            tr_, _, _ = F.run(data, dict(V2, DMIN=dm, R4=r4))
            e2 = F.evaluate(tr_, POS, LEV, SEED, yrs)
            yr2 = yearly(data, tr_)
            p2 = sum(1 for y in YEARS if yr2[y]['n'] >= 3 and yr2[y]['pf'] > 1)
            c2 = sum(1 for y in YEARS if yr2[y]['n'] >= 3)
            cells.append('%3d / %4.2f / %d/%d' % (e2['n'], min(e2['pf'], 9.99), p2, c2))
        print('%5.0f%% | %s' % (dm * 100, ' | '.join('%-26s' % c for c in cells)))
    summary.append((sym, e, pos, cnt, ps[0], rs[0], ps[1], rs[1]))

print('\n' + '=' * 150)
print('요약 (V2 파라미터 고정)')
print('=' * 150)
print('%-8s %4s %5s %5s %7s %8s %6s %4s | %8s | %-18s %-18s' % ('종목', '거래', '승률', 'PF', '기대값', '수익률', 'MDD', '연패', '양수연도', '+1R 전략/무작위', '+2R 전략/무작위'))
print('-' * 150)
for sym, e, pos, cnt, p1, r1, p2, r2 in summary:
    print('%-8s %4d %5.1f %5.2f %+7.1f %+8.0f %6.0f %4d | %5d/%d  | %s / %s     %s / %s' % (
        sym.upper().replace('USDT', ''), e['n'], e['wr'], e['pf'], e['exp'], e['ret'], e['mdd'], e['worst'], pos, cnt, p1.strip(), r1.strip(), p2.strip(), r2.strip()))
