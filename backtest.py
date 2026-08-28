# -*- coding: utf-8 -*-
# BTCUSDT spot backtest:
#   entry  = daily close of day D
#   stop   = LOW of the single daily candle at D-N   (N = 10, 20, 30)
#   target = entry * 1.05
#   stop is hit when a later daily LOW touches it (wick counts, low <= stop)
#   unlimited holding; same-day conflicts resolved with 1h candles
import csv, sys, time
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

NOW_MS = int(time.time() * 1000)
START = '2023-01-01'
TARGET_PCT = 0.05
NS = [10, 20, 30]


def load(path):
    rows = []
    with open(path, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            rows.append({
                'ot': int(r['open_time']), 'dt': r['dt'], 'day': r['dt'][:10],
                'o': float(r['open']), 'h': float(r['high']),
                'l': float(r['low']), 'c': float(r['close']),
                'ct': int(r['close_time']),
            })
    return rows


D = load('btcusdt_1d.csv')
H = load('btcusdt_1h.csv')

hour_by_day = defaultdict(list)
for b in H:
    hour_by_day[b['day']].append(b)

last_closed = max(i for i, d in enumerate(D) if d['ct'] <= NOW_MS)

lo = [d['l'] for d in D]
hi = [d['h'] for d in D]
cl = [d['c'] for d in D]
day = [d['day'] for d in D]

STATE = {'ties': 0}


def resolve_day(j, stop, target):
    """Both levels touched on day j -> use 1h bars to find which came first."""
    bars = hour_by_day.get(day[j], [])
    if not bars:
        return 'loss'
    for b in bars:
        s = b['l'] <= stop
        t = b['h'] >= target
        if s and t:
            STATE['ties'] += 1
            return 'loss'
        if s:
            return 'loss'
        if t:
            return 'win'
    return None


def run(stop_of):
    trades = []
    for i in range(len(D)):
        if day[i] < START or i > last_closed:
            continue
        stop = stop_of(i)
        if stop is None:
            continue
        entry = cl[i]
        if stop >= entry:
            trades.append({'day': day[i], 'res': 'invalid', 'entry': entry,
                           'stop': stop, 'risk': None, 'bars': 0})
            continue
        target = entry * (1 + TARGET_PCT)
        res, bars = 'open', 0
        for j in range(i + 1, len(D)):
            bars = j - i
            s = lo[j] <= stop
            t = hi[j] >= target
            if s and t:
                r = resolve_day(j, stop, target)
                if r:
                    res = r
                    break
            elif s:
                res = 'loss'
                break
            elif t:
                res = 'win'
                break
        trades.append({'day': day[i], 'res': res, 'entry': entry, 'stop': stop,
                       'risk': (entry - stop) / entry * 100, 'bars': bars})
    return trades


def summarize(trades):
    valid = [t for t in trades if t['res'] in ('win', 'loss', 'open')]
    win = [t for t in valid if t['res'] == 'win']
    loss = [t for t in valid if t['res'] == 'loss']
    op = [t for t in valid if t['res'] == 'open']
    inv = [t for t in trades if t['res'] == 'invalid']
    dec = len(win) + len(loss)

    def avg(xs):
        return (sum(xs) / len(xs)) if xs else 0.0

    risk = avg([t['risk'] for t in valid])
    wr = (len(win) / dec * 100) if dec else 0.0
    exp_pct = (wr / 100) * TARGET_PCT * 100 - (1 - wr / 100) * risk
    return {
        'total': len(trades), 'invalid': len(inv), 'valid': len(valid),
        'win': len(win), 'loss': len(loss), 'open': len(op), 'dec': dec,
        'wr': wr, 'risk': risk,
        'rr': (TARGET_PCT * 100 / risk) if risk else 0.0,
        'exp': exp_pct,
        'win_days': avg([t['bars'] for t in win]),
        'loss_days': avg([t['bars'] for t in loss]),
        'max_risk': max([t['risk'] for t in valid]) if valid else 0.0,
        'min_risk': min([t['risk'] for t in valid]) if valid else 0.0,
        'trades': trades,
    }


def hdr(t):
    print('\n' + '=' * 84)
    print(t)
    print('=' * 84)


def table(res_by_n, label):
    hdr(label)
    print('%-7s %6s %6s %6s %6s %6s %8s %10s %8s %9s' % (
        'N일전', '표본', '성공', '실패', '미결', '무효',
        '승률%', '평균손절%', '손익비', '기대값%'))
    print('-' * 84)
    for n in NS:
        s = res_by_n[n]
        print('%-7d %6d %6d %6d %6d %6d %8.2f %10.2f %8.2f %9.3f' % (
            n, s['total'], s['win'], s['loss'], s['open'], s['invalid'],
            s['wr'], s['risk'], s['rr'], s['exp']))
    print('-' * 84)
    for n in NS:
        s = res_by_n[n]
        print('  N=%-2d  손절폭 범위 %.2f%% ~ %.2f%%   평균 소요일: 성공 %.1f일 / 실패 %.1f일' % (
            n, s['min_risk'], s['max_risk'], s['win_days'], s['loss_days']))


A = {}
for n in NS:
    A[n] = summarize(run(lambda i, n=n: lo[i - n] if i - n >= 0 else None))
table(A, 'A) 기준 = N일 전 "그 일봉 하나"의 저가   [요청하신 조건 그대로]')

B = {}
for n in NS:
    B[n] = summarize(run(lambda i, n=n: min(lo[i - n + 1:i + 1]) if i - n + 1 >= 0 else None))
table(B, 'B) 참고 = 최근 N일 최저가(롤링 최저) 기준')

hdr('A안 연도별 결과')
print('%-6s %-4s %6s %6s %6s %6s %9s' % ('연도', 'N', '표본', '성공', '실패', '미결', '승률%'))
print('-' * 84)
for y in ['2023', '2024', '2025', '2026']:
    for n in NS:
        ts = [t for t in A[n]['trades'] if t['day'][:4] == y and t['res'] != 'invalid']
        w = sum(1 for t in ts if t['res'] == 'win')
        l = sum(1 for t in ts if t['res'] == 'loss')
        o = sum(1 for t in ts if t['res'] == 'open')
        print('%-6s %-4d %6d %6d %6d %6d %9s' % (
            y, n, len(ts), w, l, o,
            ('%.2f' % (w / (w + l) * 100)) if (w + l) else '-'))
    print('-' * 84)

print('\n1시간봉으로도 순서를 못 가린 케이스(같은 1h 안 동시 터치 -> 실패 처리): %d건' % STATE['ties'])
print('데이터: Binance SPOT BTCUSDT / 일봉 %s ~ %s / 진입일 %s ~ %s' % (
    day[0], day[-1], START, day[last_closed]))

with open('trades_detail.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    w.writerow(['variant', 'N', 'entry_day', 'entry', 'stop', 'risk_pct',
                'result', 'bars_to_result'])
    for name, RES in (('A_single', A), ('B_rolling', B)):
        for n in NS:
            for t in RES[n]['trades']:
                w.writerow([name, n, t['day'], '%.2f' % t['entry'], '%.2f' % t['stop'],
                            ('%.3f' % t['risk']) if t['risk'] is not None else '',
                            t['res'], t['bars']])
print('\n상세 내역 저장: trades_detail.csv')
