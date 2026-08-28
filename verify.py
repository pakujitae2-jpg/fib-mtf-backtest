# -*- coding: utf-8 -*-
# Independent re-check of a few trades using raw 1h candles only (no daily shortcut).
import csv, sys, random
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')


def load(p):
    with open(p, encoding='utf-8') as f:
        return [{'day': r['dt'][:10], 'dt': r['dt'], 'o': float(r['open']),
                 'h': float(r['high']), 'l': float(r['low']),
                 'c': float(r['close'])} for r in csv.DictReader(f)]


D = load('btcusdt_1d.csv')
H = load('btcusdt_1h.csv')
dmap = {d['day']: i for i, d in enumerate(D)}

rows = []
with open('trades_detail.csv', encoding='utf-8-sig') as f:
    for r in csv.DictReader(f):
        if r['variant'] == 'A_single' and r['result'] in ('win', 'loss'):
            rows.append(r)

random.seed(7)
sample = random.sample(rows, 8)

print('%-4s %-12s %11s %11s %11s %-6s %-6s %s' % (
    'N', '진입일', '진입가', '손절선', '목표가', '기록', '재검증', '판정시각(1h)'))
print('-' * 100)
ok = 0
for r in sample:
    n = int(r['N'])
    i = dmap[r['entry_day']]
    entry, stop = float(r['entry']), float(r['stop'])
    target = entry * 1.05
    # confirm the stop level really is the low of the candle N days earlier
    assert abs(D[i - n]['l'] - stop) < 1e-6, (r['entry_day'], n, D[i - n]['l'], stop)
    # replay hour by hour from the day AFTER entry
    verdict, when = 'open', ''
    for b in H:
        if b['day'] <= r['entry_day']:
            continue
        if b['l'] <= stop:
            verdict, when = 'loss', b['dt']
            break
        if b['h'] >= target:
            verdict, when = 'win', b['dt']
            break
    match = 'OK' if verdict == r['result'] else 'MISMATCH'
    ok += verdict == r['result']
    print('%-4d %-12s %11.2f %11.2f %11.2f %-6s %-6s %-17s %s' % (
        n, r['entry_day'], entry, stop, target, r['result'], verdict, when, match))

print('-' * 100)
print('일치: %d / %d   (손절선 = N일 전 일봉 저가 확인도 전건 통과)' % (ok, len(sample)))

# how many entries were skipped as invalid, and why
d_lo = [d['l'] for d in D]
d_cl = [d['c'] for d in D]
print()
for n in (10, 20, 30):
    inv = sum(1 for i in range(len(D))
              if D[i]['day'] >= '2023-01-01' and i - n >= 0 and d_lo[i - n] >= d_cl[i])
    print('N=%-2d 무효(그날 종가가 이미 N일전 저가 이하) : %d건' % (n, inv))
