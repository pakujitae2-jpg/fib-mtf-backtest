# -*- coding: utf-8 -*-
# Variant C: the tradeable version of the retest.
# Instead of assuming a fill at the day's low (which is only knowable after the
# fact), a resting limit order sits at the TOP of the zone, L*1.015.
#   fill   = L * 1.015   (order is hit the moment price enters the zone)
#   stop   = any later low < L          -> risk is fixed at 1.478% of fill
#   target = fill * 1.05
# Everything is resolved on 1h candles. Cases that cut straight through L are
# losses here, not skipped, because the resting order was already filled.
import csv, sys, random
from bisect import bisect_left

sys.stdout.reconfigure(encoding='utf-8')

ZONE = 0.015
TARGET_PCT = 0.05
NS = [10, 20, 30]
START = '2023-01-01'
DAY_MS = 86400000
EPS = 1e-9


def load(p):
    with open(p, encoding='utf-8') as f:
        return [{'ot': int(r['open_time']), 'dt': r['dt'], 'day': r['dt'][:10],
                 'h': float(r['high']), 'l': float(r['low']),
                 'c': float(r['close'])} for r in csv.DictReader(f)]


D = load('btcusdt_1d.csv')
H = load('btcusdt_1h.csv')
H_OT = [b['ot'] for b in H]
lo = [d['l'] for d in D]
day = [d['day'] for d in D]
d_ot = [d['ot'] for d in D]

STATE = {'same_hour': 0}


def walk_limit(j, L, fill):
    target = fill * (1 + TARGET_PCT)
    start = bisect_left(H_OT, d_ot[j])
    k, end = start, d_ot[j] + DAY_MS
    fi = None
    while k < len(H) and H[k]['ot'] < end:
        if H[k]['l'] <= fill + EPS:
            fi = k
            break
        k += 1
    if fi is None:
        return None, ''
    if H[fi]['l'] < L - EPS:
        STATE['same_hour'] += 1
        return 'loss', H[fi]['dt']          # filled and stopped inside one hour
    for m in range(fi + 1, len(H)):
        if H[m]['l'] < L - EPS:
            return 'loss', H[m]['dt']
        if H[m]['h'] >= target - EPS:
            return 'win', H[m]['dt']
    return 'open', ''


def run(n, mode):
    out = {'base': 0, 'nofill': 0, 'win': 0, 'loss': 0, 'open': 0, 'rows': []}
    for i in range(len(D)):
        if day[i] < START or i + n >= len(D):
            continue
        out['base'] += 1
        L = lo[i]
        fill = L * (1 + ZONE)
        rng = range(i + n, i + n + 1) if mode == 'A' else range(i + 1, i + n + 1)
        j = next((x for x in rng if lo[x] <= fill + EPS), None)
        if j is None:
            out['nofill'] += 1
            continue
        res, when = walk_limit(j, L, fill)
        if res is None:
            out['nofill'] += 1
            continue
        out[res] += 1
        out['rows'].append({'ref': day[i], 'n': n, 'L': L, 'fill': fill,
                            'entry_day': day[j], 'res': res, 'when': when})
    return out


RISK = ZONE / (1 + ZONE) * 100          # 1.478% of the fill price
RR = TARGET_PCT * 100 / RISK
print('=' * 92)
print('C) 실전형: 존 상단 L*1.015 지정가 대기 -> 손절 L / 목표 +5%   [선행편향 없음]')
print('=' * 92)
print('고정 손절폭 %.3f%%  |  손익비 %.2f : 1  |  손익분기 승률 %.2f%%\n' % (
    RISK, RR, 100 / (1 + RR)))
print('%-5s %-6s %8s %8s %8s %8s %8s %9s %10s' % (
    'mode', 'N', '기준봉', '미체결', '체결', '성공', '실패', '승률%', '기대값%'))
print('-' * 92)
KEEP = {}
for mode, tag in (('B', 'B'), ('A', 'A')):
    for n in NS:
        r = run(n, mode)
        KEEP[(mode, n)] = r
        s = r['win'] + r['loss']
        wr = (r['win'] / s * 100) if s else 0.0
        exp = (wr / 100) * TARGET_PCT * 100 - (1 - wr / 100) * RISK
        print('%-5s %-6d %8d %8d %8d %8d %8d %9.2f %10.3f' % (
            tag, n, r['base'], r['nofill'], s + r['open'], r['win'], r['loss'], wr, exp))
    print('-' * 92)
print('체결과 손절이 같은 1시간봉 안에서 일어나 실패 처리한 건: %d' % STATE['same_hour'])

# ---- how much does N actually change anything in mode B? ----
print('\n' + '=' * 92)
print('N이 실제로 결과를 바꾸는가 - 존 첫 진입까지 걸린 일수 분포 (B안, N=30)')
print('=' * 92)
buckets = {'1일': 0, '2-3일': 0, '4-7일': 0, '8-14일': 0, '15-30일': 0}
with open('retest_trades.csv', encoding='utf-8-sig') as f:
    for r in csv.DictReader(f):
        if r['mode'] == 'B_window' and r['N'] == '30':
            w = int(r['days_to_approach'])
            k = ('1일' if w == 1 else '2-3일' if w <= 3 else '4-7일'
                 if w <= 7 else '8-14일' if w <= 14 else '15-30일')
            buckets[k] += 1
tot = sum(buckets.values())
for k, v in buckets.items():
    print('  %-8s %5d건  %5.1f%%  %s' % (k, v, v / tot * 100, '#' * int(v / tot * 60)))
print('\n=> 접근의 %.1f%%가 기준봉 다음날 바로 발생. 그래서 10/20/30일 결과가 거의 같음.'
      % (buckets['1일'] / tot * 100))

# ---- independent replay of random trades, 1h data only ----
print('\n' + '=' * 92)
print('검증: 무작위 8건을 1시간봉 원본으로 독립 재생')
print('=' * 92)
pool = [x for x in KEEP[('B', 20)]['rows'] if x['res'] in ('win', 'loss')]
random.seed(11)
print('%-12s %-12s %11s %11s %11s %-6s %-6s %s' % (
    '기준봉', '체결일', '기준저점L', '체결가', '목표가', '기록', '재검증', '판정'))
print('-' * 92)
ok = 0
for x in random.sample(pool, 8):
    L, fill = x['L'], x['fill']
    target = fill * 1.05
    v, seen_fill = 'open', False
    for b in H:
        if b['day'] < x['entry_day']:
            continue
        if not seen_fill:
            if b['l'] <= fill + EPS:
                seen_fill = True
                if b['l'] < L - EPS:
                    v = 'loss'
                    break
            continue
        if b['l'] < L - EPS:
            v = 'loss'
            break
        if b['h'] >= target - EPS:
            v = 'win'
            break
    ok += v == x['res']
    print('%-12s %-12s %11.2f %11.2f %11.2f %-6s %-6s %s' % (
        x['ref'], x['entry_day'], L, fill, target, x['res'], v,
        'OK' if v == x['res'] else 'MISMATCH'))
print('-' * 92)
print('일치 %d / 8' % ok)
