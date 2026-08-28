# -*- coding: utf-8 -*-
# Resting limit buy at L*1.015, stop at L, take profit at +1.0%.
# 10x leverage, $100 seed, Binance USDS-M futures fees, slippage and funding.
# Resolved on 5m candles because TP (+1.0%) and SL (-1.478%) sit close together.
import csv, sys
from bisect import bisect_left

sys.stdout.reconfigure(encoding='utf-8')

ZONE = 0.015          # limit price sits 1.5% above the reference low
TP = 0.010            # take profit +1.0% from fill
NS = [10, 20, 30]
START = '2023-01-01'
DAY_MS = 86400000
EPS = 1e-9

LEV = 10
SEED = 100.0
FEE_MAKER = 0.0002    # 0.02%  resting limit order
FEE_TAKER = 0.0005    # 0.05%  stop-market / immediate fill
FUNDING = 0.0001      # 0.01% per 8h funding stamp, long pays (flat assumption)


def load_daily(p):
    with open(p, encoding='utf-8') as f:
        return [(int(r['open_time']), r['dt'][:10], float(r['low']), float(r['close']))
                for r in csv.DictReader(f)]


def load_fine(p):
    ot, hi, lo = [], [], []
    with open(p, encoding='utf-8') as f:
        rd = csv.reader(f)
        next(rd)
        for r in rd:
            ot.append(int(r[0]))
            hi.append(float(r[3]))
            lo.append(float(r[4]))
    return ot, hi, lo


D = load_daily('btcusdt_1d.csv')
d_ot = [x[0] for x in D]
d_day = [x[1] for x in D]
d_lo = [x[2] for x in D]
d_cl = [x[3] for x in D]
F_OT, F_HI, F_LO = load_fine('btcusdt_5m.csv')
print('5m bars: %d  (%s ~ %s)' % (len(F_OT), d_day[0], d_day[-1]))

STATE = {'amb': 0}


def signals(n):
    """Every resting order and the exact 5m bar where it would have filled."""
    out = []
    for i in range(len(D)):
        if d_day[i] < START or i + n >= len(D):
            continue
        L = d_lo[i]
        px = L * (1 + ZONE)
        if d_cl[i] <= px + EPS:
            # already inside the zone when the order is placed -> immediate taker fill
            k = bisect_left(F_OT, d_ot[i] + DAY_MS)
            if k < len(F_OT):
                out.append((k, d_cl[i], L, d_day[i], FEE_TAKER))
            continue
        for j in range(i + 1, i + n + 1):
            if d_lo[j] > px + EPS:
                continue
            s = bisect_left(F_OT, d_ot[j])
            e = bisect_left(F_OT, d_ot[j] + DAY_MS)
            k = next((m for m in range(s, e) if F_LO[m] <= px + EPS), None)
            if k is not None:
                out.append((k, px, L, d_day[i], FEE_MAKER))
            break
    out.sort()
    return out


def resolve(k, fill, L):
    """From the fill bar forward: does +TP land before price loses L?"""
    target = fill * (1 + TP)
    if F_LO[k] < L - EPS:
        STATE['amb'] += 1
        return 'loss', k                       # filled and stopped in the same 5m bar
    for m in range(k + 1, len(F_OT)):
        s = F_LO[m] < L - EPS
        t = F_HI[m] >= target - EPS
        if s and t:
            STATE['amb'] += 1
            return 'loss', m                   # both inside one 5m bar -> conservative
        if s:
            return 'loss', m
        if t:
            return 'win', m
    return 'open', len(F_OT) - 1


def fundings(t0, t1):
    """Number of 00/08/16 UTC funding stamps crossed while holding."""
    return max(0, int(t1 // (8 * 3600000)) - int(t0 // (8 * 3600000)))


def simulate(sigs, slip, verbose=False):
    eq = SEED
    peak, mdd = SEED, 0.0
    busy = -1
    w = l = op = 0
    fees = fund = slipcost = 0.0
    streak = worst = 0
    hold = []
    curve = []
    for k, fill, L, ref, entry_fee in sigs:
        if k <= busy:
            continue
        res, m = resolve(k, fill, L)
        busy = m
        if res == 'open':
            op += 1
            continue
        notional = eq * LEV
        qty = notional / fill
        fe = notional * entry_fee
        if res == 'win':
            exit_px = fill * (1 + TP)
            fx = qty * exit_px * FEE_MAKER
            sl = 0.0
            w += 1
            streak = 0
        else:
            exit_px = L * (1 - slip)
            fx = qty * exit_px * FEE_TAKER
            sl = qty * L * slip
            l += 1
            streak += 1
            worst = max(worst, streak)
        fd = qty * fill * FUNDING * fundings(F_OT[k], F_OT[m])
        pnl = qty * (exit_px - fill) - fe - fx - fd
        eq += pnl
        fees += fe + fx
        fund += fd
        slipcost += sl
        hold.append((F_OT[m] - F_OT[k]) / 3600000.0)
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak * 100)
        curve.append(eq)
        if eq < 1e-6:
            break
    tot = w + l
    return {'eq': eq, 'w': w, 'l': l, 'open': op, 'n': tot,
            'wr': (w / tot * 100) if tot else 0.0, 'mdd': mdd, 'worst': worst,
            'fees': fees, 'fund': fund, 'slip': slipcost,
            'hold': (sum(hold) / len(hold)) if hold else 0.0, 'curve': curve}


risk = ZONE / (1 + ZONE) * 100
print('\n' + '=' * 94)
print('설정: 지정가 매수 L*1.015 / 손절 L / 익절 +1.0% / 10배 / 시드 $100')
print('=' * 94)
print('손절폭 %.3f%%  익절폭 1.000%%  ->  손익비 %.2f : 1  ->  손익분기 승률 %.2f%% (수수료 전)'
      % (risk, TP * 100 / risk, risk / (TP * 100 + risk) * 100))
print('10배 적용 시 1회당  승리 +%.1f%% / 패배 -%.1f%% (자기자본 대비, 비용 전)'
      % (TP * 100 * LEV, risk * LEV))

SIG = {n: signals(n) for n in NS}
print('\n%-5s %9s %11s %9s %10s %9s %9s %8s %10s' % (
    'N', '주문건수', '순차진입', '성공', '실패', '승률%', '평균보유h', 'MDD%', '최종자산$'))
print('-' * 94)
BASE = {}
for n in NS:
    r = simulate(SIG[n], 0.0003)
    BASE[n] = r
    print('%-5d %9d %11d %9d %10d %9.2f %9.1f %8.1f %10.2f' % (
        n, len(SIG[n]), r['n'], r['w'], r['l'], r['wr'], r['hold'], r['mdd'], r['eq']))
print('-' * 94)
for n in NS:
    r = BASE[n]
    print('  N=%-2d 최대 연속손실 %d회 | 누적 수수료 $%.2f | 펀딩 $%.2f | 슬리피지 $%.2f'
          % (n, r['worst'], r['fees'], r['fund'], r['slip']))
print('\n5분봉 안에서도 손절/익절 선후를 못 가려 실패 처리한 건: %d' % STATE['amb'])

print('\n' + '=' * 94)
print('슬리피지 민감도 (N=20)')
print('=' * 94)
print('%-14s %9s %9s %10s %12s' % ('손절 슬리피지', '승률%', 'MDD%', '최종자산$', '총수익률%'))
print('-' * 94)
for s in (0.0, 0.0002, 0.0003, 0.0005, 0.0010):
    r = simulate(SIG[20], s)
    print('%-14s %9.2f %9.1f %10.2f %12.1f' % (
        '%.2f%%' % (s * 100), r['wr'], r['mdd'], r['eq'], (r['eq'] / SEED - 1) * 100))

print('\n' + '=' * 94)
print('익절폭을 바꾸면? (N=20, 슬리피지 0.03%, 손절은 L 고정)')
print('=' * 94)
print('%-8s %9s %9s %9s %10s %10s %11s' % (
    '익절%', '손익비', '분기승률%', '실제승률%', 'MDD%', '거래수', '최종자산$'))
print('-' * 94)
for tp in (0.005, 0.010, 0.015, 0.020, 0.030, 0.050):
    TP = tp
    r = simulate(signals(20), 0.0003)
    print('%-8s %9.2f %9.2f %9.2f %10.1f %10d %11.2f' % (
        '%.1f%%' % (tp * 100), tp * 100 / risk, risk / (tp * 100 + risk) * 100,
        r['wr'], r['mdd'], r['n'], r['eq']))
TP = 0.010

print('\n' + '=' * 94)
print('레버리지 민감도 (N=20, 익절 1%, 슬리피지 0.03%)')
print('=' * 94)
print('%-8s %12s %10s %12s' % ('배율', '최종자산$', 'MDD%', '총수익률%'))
print('-' * 94)
for lv in (1, 2, 3, 5, 10, 20):
    LEV = lv
    r = simulate(SIG[20], 0.0003)
    print('%-8s %12.2f %10.1f %12.1f' % ('%dx' % lv, r['eq'], r['mdd'],
                                         (r['eq'] / SEED - 1) * 100))
LEV = 10
