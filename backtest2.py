# -*- coding: utf-8 -*-
# BTCUSDT spot - support RETEST backtest.
#
#   reference candle T  ->  L = low(T)
#   zone = [L, L*1.015]                       ("전 저점 부근 0~1.5%")
#   scan T+1 .. T+N for the FIRST day whose low enters the zone
#       low < L        -> broke straight through, no trade  ("즉시 이탈")
#       L <= low <= hi -> entry; base = that day's low       ("접근 때 찍은 저가")
#   target = base * 1.05 ,  stop = any later low < L
#   forward walk runs on 1h candles, unlimited holding
import csv, sys
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


def walk(j, base, L):
    """From the bounce low on day j, does price hit base*1.05 before losing L?"""
    target = base * (1 + TARGET_PCT)
    start = bisect_left(H_OT, d_ot[j])
    end_of_day = d_ot[j] + DAY_MS
    # locate the 1h bar that printed the day's low, then continue after it
    m = None
    k = start
    while k < len(H) and H[k]['ot'] < end_of_day:
        if H[k]['l'] <= base + EPS:
            m = k
            break
        k += 1
    if m is None:
        m = start - 1
    for b in H[m + 1:]:
        if b['l'] < L - EPS:
            return 'loss', b['dt']
        if b['h'] >= target - EPS:
            return 'win', b['dt']
    return 'open', ''


def run(n, mode):
    """mode 'B' = zone entry anywhere in T+1..T+N ; 'A' = only on day T+N."""
    out = {'base': 0, 'noapproach': 0, 'through': 0,
           'win': 0, 'loss': 0, 'open': 0, 'rows': []}
    for i in range(len(D)):
        if day[i] < START or i + n >= len(D):
            continue
        out['base'] += 1
        L = lo[i]
        hi_z = L * (1 + ZONE)
        rng = range(i + n, i + n + 1) if mode == 'A' else range(i + 1, i + n + 1)
        j = next((x for x in rng if lo[x] <= hi_z + EPS), None)
        if j is None:
            out['noapproach'] += 1
            continue
        if lo[j] < L - EPS:
            out['through'] += 1
            continue
        base = lo[j]
        res, when = walk(j, base, L)
        out[res] += 1
        out['rows'].append({
            'ref': day[i], 'n': n, 'L': L, 'entry_day': day[j], 'base': base,
            'gap': (base - L) / base * 100, 'res': res, 'when': when,
            'wait': j - i,
        })
    return out


def report(mode, title):
    print('\n' + '=' * 92)
    print(title)
    print('=' * 92)
    print('%-5s %7s %9s %9s %8s %7s %7s %7s %8s %7s %8s' % (
        'N', '기준봉', '미접근', '즉시이탈', '표본', '성공', '실패', '미결',
        '승률%', '손익비', '기대값%'))
    print('-' * 92)
    keep = {}
    for n in NS:
        r = run(n, mode)
        keep[n] = r
        s = r['win'] + r['loss']
        wr = (r['win'] / s * 100) if s else 0.0
        gaps = [x['gap'] for x in r['rows']]
        risk = sum(gaps) / len(gaps) if gaps else 0.0
        rr = (TARGET_PCT * 100 / risk) if risk else 0.0
        exp = (wr / 100) * 5 - (1 - wr / 100) * risk
        print('%-5d %7d %9d %9d %8d %7d %7d %7d %8.2f %7.2f %8.3f' % (
            n, r['base'], r['noapproach'], r['through'],
            r['win'] + r['loss'] + r['open'], r['win'], r['loss'], r['open'],
            wr, rr, exp))
    print('-' * 92)
    for n in NS:
        r = keep[n]
        gaps = [x['gap'] for x in r['rows']]
        if not gaps:
            continue
        risk = sum(gaps) / len(gaps)
        waits = [x['wait'] for x in r['rows']]
        print('  N=%-2d 평균 손절폭 %.3f%% (진입가-L)  |  손익비 %.1f : 1  |  '
              '손익분기 승률 %.1f%%  |  평균 접근 소요 %.1f일' % (
                  n, risk, TARGET_PCT * 100 / risk,
                  100 / (1 + TARGET_PCT * 100 / risk), sum(waits) / len(waits)))
    return keep


B = report('B', 'B) 접근 시점 = T+1 ~ T+N 사이 아무 때나   [선택하신 조건]')
A = report('A', 'A) 참고: 접근 시점 = T+N 그날 봉에서만')

print('\n' + '=' * 92)
print('B안 연도별 (기준봉 연도 기준)')
print('=' * 92)
print('%-6s %-4s %7s %7s %7s %7s %9s' % ('연도', 'N', '표본', '성공', '실패', '미결', '승률%'))
print('-' * 92)
for y in ['2023', '2024', '2025', '2026']:
    for n in NS:
        rs = [x for x in B[n]['rows'] if x['ref'][:4] == y]
        w = sum(1 for x in rs if x['res'] == 'win')
        l = sum(1 for x in rs if x['res'] == 'loss')
        o = sum(1 for x in rs if x['res'] == 'open')
        print('%-6s %-4d %7d %7d %7d %7d %9s' % (
            y, n, len(rs), w, l, o,
            ('%.1f' % (w / (w + l) * 100)) if (w + l) else '-'))
    print('-' * 92)

with open('retest_trades.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    w.writerow(['mode', 'N', 'ref_day', 'ref_low_L', 'entry_day', 'entry_low',
                'gap_pct', 'target', 'result', 'resolved_at', 'days_to_approach'])
    for name, RES in (('B_window', B), ('A_exact', A)):
        for n in NS:
            for x in RES[n]['rows']:
                w.writerow([name, n, x['ref'], '%.2f' % x['L'], x['entry_day'],
                            '%.2f' % x['base'], '%.3f' % x['gap'],
                            '%.2f' % (x['base'] * 1.05), x['res'], x['when'], x['wait']])
print('\n상세 내역 저장: retest_trades.csv')
print('데이터: Binance SPOT BTCUSDT / 기준봉 %s ~ / 1h 추적 %s ~ %s' % (
    START, H[0]['dt'], H[-1]['dt']))
