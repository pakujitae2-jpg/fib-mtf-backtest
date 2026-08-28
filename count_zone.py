# -*- coding: utf-8 -*-
# How many samples survive the "approached within 0~1.5% of the reference low
# without breaking it" filter, under two readings of when the approach happens.
import csv, sys

sys.stdout.reconfigure(encoding='utf-8')

with open('btcusdt_1d.csv', encoding='utf-8') as f:
    D = [{'day': r['dt'][:10], 'l': float(r['low']), 'h': float(r['high']),
          'c': float(r['close'])} for r in csv.DictReader(f)]

lo = [d['l'] for d in D]
day = [d['day'] for d in D]
ZONE = 0.015
NS = [10, 20, 30]

print('기준봉 2023-01-01 이후, 관찰일이 데이터 안에 있는 경우만\n')
print('%-6s %10s %14s %14s' % ('N', '기준봉 수', 'A) T+N 그날만', 'B) T+1~T+N 중'))
print('-' * 50)
for n in NS:
    base = a = b = 0
    for i in range(len(D)):
        if day[i] < '2023-01-01' or i + n >= len(D):
            continue
        base += 1
        L = lo[i]
        hi_z = L * (1 + ZONE)
        # A: the candle exactly N days later dips into the zone, no break
        if L <= lo[i + n] <= hi_z:
            a += 1
        # B: somewhere in T+1..T+N price enters the zone and never breaks L
        wmin = min(lo[i + 1:i + n + 1])
        if L <= wmin <= hi_z:
            b += 1
    print('%-6d %10d %14d %14d' % (n, base, a, b))
