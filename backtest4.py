# -*- coding: utf-8 -*-
# Variant D: the honest tradeable form of the pattern the user described.
# Wait for the retest day to CLOSE. Only then do you know the low held.
#   first day j in T+1..T+N whose low enters [L, L*1.015]
#       low < L -> the low was broken, condition violated, no trade
#   entry  = close(j)          (knowable in real time)
#   stop   = any later low < L
#   target = close(j) * 1.05
import csv, sys
from bisect import bisect_left

sys.stdout.reconfigure(encoding='utf-8')

ZONE, TARGET_PCT, EPS = 0.015, 0.05, 1e-9
NS = [10, 20, 30]
START = '2023-01-01'


def load(p):
    with open(p, encoding='utf-8') as f:
        return [{'ot': int(r['open_time']), 'dt': r['dt'], 'day': r['dt'][:10],
                 'h': float(r['high']), 'l': float(r['low']),
                 'c': float(r['close'])} for r in csv.DictReader(f)]


D = load('btcusdt_1d.csv')
H = load('btcusdt_1h.csv')
H_OT = [b['ot'] for b in H]
lo = [d['l'] for d in D]
cl = [d['c'] for d in D]
day = [d['day'] for d in D]
d_ot = [d['ot'] for d in D]
DAY_MS = 86400000


def walk(j, L, entry):
    target = entry * (1 + TARGET_PCT)
    start = bisect_left(H_OT, d_ot[j] + DAY_MS)     # from the NEXT day onward
    for m in range(start, len(H)):
        if H[m]['l'] < L - EPS:
            return 'loss', H[m]['dt']
        if H[m]['h'] >= target - EPS:
            return 'win', H[m]['dt']
    return 'open', ''


print('=' * 96)
print('D) 실전형: 리테스트 봉 "종가" 진입 -> 손절 L / 목표 종가+5%   [선행편향 없음]')
print('=' * 96)
print('%-5s %-4s %7s %7s %8s %7s %7s %6s %8s %9s %8s %9s' % (
    'mode', 'N', '기준봉', '미접근', '즉시이탈', '표본', '성공', '실패', '미결',
    '승률%', '평균손절%', '기대값%'))
print('-' * 96)
ROWS = []
for mode in ('B', 'A'):
    for n in NS:
        base = noapp = through = w = l = op = 0
        risks = []
        for i in range(len(D)):
            if day[i] < START or i + n >= len(D):
                continue
            base += 1
            L = lo[i]
            hi_z = L * (1 + ZONE)
            rng = range(i + n, i + n + 1) if mode == 'A' else range(i + 1, i + n + 1)
            j = next((x for x in rng if lo[x] <= hi_z + EPS), None)
            if j is None:
                noapp += 1
                continue
            if lo[j] < L - EPS:
                through += 1
                continue
            entry = cl[j]
            if entry <= L:
                through += 1
                continue
            risks.append((entry - L) / entry * 100)
            res, when = walk(j, L, entry)
            w += res == 'win'
            l += res == 'loss'
            op += res == 'open'
            ROWS.append([mode, n, day[i], '%.2f' % L, day[j], '%.2f' % entry,
                         '%.3f' % ((entry - L) / entry * 100),
                         '%.2f' % (entry * 1.05), res, when])
        s = w + l
        wr = (w / s * 100) if s else 0.0
        risk = sum(risks) / len(risks) if risks else 0.0
        exp = (wr / 100) * 5 - (1 - wr / 100) * risk
        print('%-5s %-4d %7d %7d %8d %7d %7d %6d %8d %9.2f %8.2f %9.3f' % (
            mode, n, base, noapp, through, s + op, w, l, op, wr, risk, exp))
    print('-' * 96)

print('\n손익분기 승률 = 평균손절폭 / (5 + 평균손절폭)')
for r in (1.0, 1.5, 2.0):
    print('   손절 %.1f%% 일 때 손익분기 승률 %.1f%%' % (r, r / (5 + r) * 100))

with open('retest_close_entry.csv', 'w', newline='', encoding='utf-8-sig') as f:
    wr_ = csv.writer(f)
    wr_.writerow(['mode', 'N', 'ref_day', 'ref_low_L', 'entry_day', 'entry_close',
                  'risk_pct', 'target', 'result', 'resolved_at'])
    wr_.writerows(ROWS)
print('\n상세 내역 저장: retest_close_entry.csv')
