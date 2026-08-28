# -*- coding: utf-8 -*-
# Revised spec:
#   resting limit buy at L * 1.003   (0.3% above the reference low)
#   stop  = any print below L        (칼손절)
#   target = fill * 1.01             (+1.0%)
#   10x leverage, $100 seed, Binance USDS-M fees + slippage + funding
#
# usage: python sim2.py [btcusdt_5m.csv | btcusdt_1m.csv]
import csv, sys
from bisect import bisect_left

sys.stdout.reconfigure(encoding='utf-8')

FINE = sys.argv[1] if len(sys.argv) > 1 else 'btcusdt_5m.csv'
ZONE = 0.003
TP = 0.010
NS = [10, 20, 30]
START = '2023-01-01'
DAY_MS = 86400000
EPS = 1e-9

LEV = 10
SEED = 100.0
FEE_MAKER = 0.0002
FEE_TAKER = 0.0005
FUNDING = 0.0001


def load_daily(p):
    with open(p, encoding='utf-8') as f:
        return [(int(r['open_time']), r['dt'][:10], float(r['low']), float(r['close']))
                for r in csv.DictReader(f)]


def load_fine(p):
    ot, hi, lo = [], [], []
    with open(p, encoding='utf-8') as f:
        rd = csv.reader(f)
        head = next(rd)
        ih, il = (3, 4) if len(head) > 3 else (1, 2)
        for r in rd:
            ot.append(int(r[0]))
            hi.append(float(r[ih]))
            lo.append(float(r[il]))
    return ot, hi, lo


D = load_daily('btcusdt_1d.csv')
d_ot = [x[0] for x in D]
d_day = [x[1] for x in D]
d_lo = [x[2] for x in D]
d_cl = [x[3] for x in D]
F_OT, F_HI, F_LO = load_fine(FINE)
print('정밀 데이터: %s  (%d bars)' % (FINE, len(F_OT)))

STATE = {'amb': 0, 'same': 0, 'taken': 0}


def signals(n, zone):
    out = []
    for i in range(len(D)):
        if d_day[i] < START or i + n >= len(D):
            continue
        L = d_lo[i]
        px = L * (1 + zone)
        if d_cl[i] <= px + EPS:
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


def resolve(k, fill, L, tp):
    target = fill * (1 + tp)
    STATE['taken'] += 1
    if F_LO[k] < L - EPS:
        STATE['same'] += 1
        return 'loss', k
    for m in range(k + 1, len(F_OT)):
        s = F_LO[m] < L - EPS
        t = F_HI[m] >= target - EPS
        if s and t:
            STATE['amb'] += 1
            return 'loss', m
        if s:
            return 'loss', m
        if t:
            return 'win', m
    return 'open', len(F_OT) - 1


def fundings(t0, t1):
    return max(0, int(t1 // (8 * 3600000)) - int(t0 // (8 * 3600000)))


def simulate(sigs, slip, lev=None, tp=None, seed=SEED):
    lev = lev or LEV
    tp = tp if tp is not None else TP
    eq, peak, mdd, busy = seed, seed, 0.0, -1
    w = l = op = 0
    fees = fund = slipc = 0.0
    streak = worst = 0
    hold, curve, ruin = [], [], None
    for k, fill, L, ref, efee in sigs:
        if k <= busy:
            continue
        res, m = resolve(k, fill, L, tp)
        busy = m
        if res == 'open':
            op += 1
            continue
        notional = eq * lev
        qty = notional / fill
        fe = notional * efee
        if res == 'win':
            ex = fill * (1 + tp)
            fx = qty * ex * FEE_MAKER
            sc = 0.0
            w += 1
            streak = 0
        else:
            ex = L * (1 - slip)
            fx = qty * ex * FEE_TAKER
            sc = qty * L * slip
            l += 1
            streak += 1
            worst = max(worst, streak)
        fd = qty * fill * FUNDING * fundings(F_OT[k], F_OT[m])
        eq += qty * (ex - fill) - fe - fx - fd
        fees += fe + fx
        fund += fd
        slipc += sc
        hold.append((F_OT[m] - F_OT[k]) / 3600000.0)
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak * 100)
        curve.append(eq)
        if ruin is None and eq < seed * 0.01:
            ruin = w + l
        if eq < 1e-9:
            break
    t = w + l
    return {'eq': eq, 'w': w, 'l': l, 'open': op, 'n': t,
            'wr': (w / t * 100) if t else 0.0, 'mdd': mdd, 'worst': worst,
            'fees': fees, 'fund': fund, 'slip': slipc, 'ruin': ruin,
            'hold': (sum(hold) / len(hold)) if hold else 0.0, 'curve': curve}


risk = ZONE / (1 + ZONE) * 100
print('\n' + '=' * 96)
print('설정: 지정가 매수 L*1.003 (전저점 +0.3%) / 손절 L 이탈 / 익절 +1.0% / 10배 / 시드 $100')
print('=' * 96)
print('손절폭 %.4f%%   익절폭 1.0000%%   ->   손익비 %.2f : 1   ->   손익분기 승률 %.2f%% (비용 전)'
      % (risk, TP * 100 / risk, risk / (TP * 100 + risk) * 100))
win_net = TP * 100 - 0.04
loss_net = risk + 0.07 + 0.03
print('비용 반영(진입 maker 0.02 + 청산 taker 0.05 + 슬리피지 0.03): '
      '실질 익절 %.3f%% / 실질 손절 %.3f%% -> 손익분기 승률 %.2f%%'
      % (win_net, loss_net, loss_net / (win_net + loss_net) * 100))
print('10배 적용 시 1회당  승리 +%.1f%% / 패배 -%.1f%% (자기자본 대비, 비용 전)'
      % (TP * 100 * LEV, risk * LEV))

SIG = {n: signals(n, ZONE) for n in NS}
print('\n%-5s %9s %10s %8s %9s %9s %10s %8s %11s %9s' % (
    'N', '주문건수', '순차진입', '성공', '실패', '승률%', '평균보유h', 'MDD%', '최종자산$', '파산시점'))
print('-' * 96)
R = {}
for n in NS:
    r = simulate(SIG[n], 0.0003)
    R[n] = r
    print('%-5d %9d %10d %8d %9d %9.2f %10.2f %8.1f %11.4f %9s' % (
        n, len(SIG[n]), r['n'], r['w'], r['l'], r['wr'], r['hold'], r['mdd'], r['eq'],
        ('%d번째' % r['ruin']) if r['ruin'] else '-'))
print('-' * 96)
for n in NS:
    r = R[n]
    print('  N=%-2d 최대 연속손실 %d회 | 수수료 $%.2f | 펀딩 $%.2f | 슬리피지 $%.2f'
          % (n, r['worst'], r['fees'], r['fund'], r['slip']))

tot = STATE['taken']
print('\n[판정 정밀도] 총 %d건 중' % tot)
print('  체결과 동시에 같은 봉에서 손절 (선후 불명, 실패 처리): %d건 (%.1f%%)'
      % (STATE['same'], STATE['same'] / tot * 100))
print('  이후 같은 봉에서 손절/익절 동시 (선후 불명, 실패 처리): %d건 (%.1f%%)'
      % (STATE['amb'], STATE['amb'] / tot * 100))
print('  => 합계 %.1f%% 가 보수적 가정에 의존. 이 비율이 높으면 결과 신뢰도가 낮음.'
      % ((STATE['same'] + STATE['amb']) / tot * 100))

print('\n' + '=' * 96)
print('레버리지 민감도 (N=20, 익절 1%, 슬리피지 0.03%)')
print('=' * 96)
print('%-8s %13s %10s %13s %10s' % ('배율', '최종자산$', 'MDD%', '총수익률%', '최대연속손실'))
print('-' * 96)
for lv in (1, 2, 3, 5, 10, 20):
    r = simulate(SIG[20], 0.0003, lev=lv)
    print('%-8s %13.4f %10.1f %13.1f %10d' % (
        '%dx' % lv, r['eq'], r['mdd'], (r['eq'] / SEED - 1) * 100, r['worst']))

print('\n' + '=' * 96)
print('진입 버퍼(전저점 대비 %)를 바꾸면? (N=20, 익절 1%, 10배, 슬리피지 0.03%)')
print('=' * 96)
print('%-9s %9s %10s %9s %9s %9s %11s' % (
    '버퍼', '손절폭%', '분기승률%', '거래수', '실제승률%', 'MDD%', '최종자산$'))
print('-' * 96)
for z in (0.001, 0.003, 0.005, 0.008, 0.010, 0.015, 0.020):
    sg = signals(20, z)
    rr = z / (1 + z) * 100
    r = simulate(sg, 0.0003)
    print('%-9s %9.4f %10.2f %9d %9.2f %9.1f %11.4f' % (
        '%.1f%%' % (z * 100), rr, rr / (TP * 100 + rr) * 100, r['n'], r['wr'],
        r['mdd'], r['eq']))

print('\n' + '=' * 96)
print('익절폭을 바꾸면? (N=20, 버퍼 0.3%, 10배, 슬리피지 0.03%)')
print('=' * 96)
print('%-9s %9s %10s %9s %9s %9s %11s' % (
    '익절%', '손익비', '분기승률%', '거래수', '실제승률%', 'MDD%', '최종자산$'))
print('-' * 96)
for tp in (0.003, 0.005, 0.010, 0.015, 0.020, 0.030):
    r = simulate(SIG[20], 0.0003, tp=tp)
    print('%-9s %9.2f %10.2f %9d %9.2f %9.1f %11.4f' % (
        '%.1f%%' % (tp * 100), tp * 100 / risk, risk / (tp * 100 + risk) * 100,
        r['n'], r['wr'], r['mdd'], r['eq']))
