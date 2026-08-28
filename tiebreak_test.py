# -*- coding: utf-8 -*-
# Daily candles only, but run twice with OPPOSITE tie-break rules.
# If the two answers disagree wildly, the daily bar is not carrying enough
# information to decide the question and neither number means anything.
import csv, sys

sys.stdout.reconfigure(encoding='utf-8')

ZONE, TP, EPS = 0.003, 0.010, 1e-9
LEV, SEED = 10, 100.0
FEE_MAKER, FEE_TAKER, FUNDING = 0.0002, 0.0005, 0.0001
SLIP = 0.0003
START = '2023-01-01'

with open('btcusdt_1d.csv', encoding='utf-8') as f:
    D = [(r['dt'][:10], float(r['high']), float(r['low']), float(r['close']))
         for r in csv.DictReader(f)]
day = [x[0] for x in D]
hi = [x[1] for x in D]
lo = [x[2] for x in D]
cl = [x[3] for x in D]


def build(n, rule):
    """rule: 'stop' = stop wins a tie, 'target' = target wins a tie."""
    out = []
    for i in range(len(D)):
        if day[i] < START or i + n >= len(D):
            continue
        L = lo[i]
        px = L * (1 + ZONE)
        taker = False
        if cl[i] <= px + EPS:
            px, taker, j = cl[i], True, i + 1
            if j >= len(D):
                continue
        else:
            j = next((x for x in range(i + 1, i + n + 1) if lo[x] <= px + EPS), None)
            if j is None:
                continue
        tgt = px * (1 + TP)
        res, k = None, None
        for m in range(j, len(D)):
            b = lo[m] < L - EPS
            t = hi[m] >= tgt - EPS
            if b and t:
                res, k = ('loss' if rule == 'stop' else 'win'), m
                break
            if b:
                res, k = 'loss', m
                break
            if t:
                res, k = 'win', m
                break
        out.append((j, k if k is not None else len(D) - 1, px, L, taker,
                    res or 'open'))
    out.sort()
    return out


def sim(sigs, lev=LEV):
    eq, peak, mdd, busy = SEED, SEED, 0.0, -1
    w = l = 0
    streak = worst = 0
    for j, k, fill, L, taker, res in sigs:
        if j <= busy:
            continue
        busy = k
        if res == 'open':
            continue
        notional = eq * lev
        qty = notional / fill
        fe = notional * (FEE_TAKER if taker else FEE_MAKER)
        if res == 'win':
            ex = fill * (1 + TP)
            fx = qty * ex * FEE_MAKER
            w += 1
            streak = 0
        else:
            ex = L * (1 - SLIP)
            fx = qty * ex * FEE_TAKER
            l += 1
            streak += 1
            worst = max(worst, streak)
        fd = qty * fill * FUNDING * max(k - j, 0) * 3
        eq += qty * (ex - fill) - fe - fx - fd
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak * 100)
        if eq < 1e-12:
            break
    t = w + l
    return {'eq': eq, 'w': w, 'l': l, 'n': t, 'mdd': mdd, 'worst': worst,
            'wr': (w / t * 100) if t else 0.0}


# how large is a daily candle compared to the levels we are trying to resolve?
rng = [(hi[i] - lo[i]) / lo[i] * 100 for i in range(len(D)) if day[i] >= START]
rng.sort()
print('=' * 92)
print('일봉 한 개의 크기 vs 우리가 재려는 폭')
print('=' * 92)
print('  BTC 일봉 고가-저가 평균 변동폭   : %.2f%%' % (sum(rng) / len(rng)))
print('  중앙값 %.2f%%   하위10%% %.2f%%   상위10%% %.2f%%'
      % (rng[len(rng) // 2], rng[len(rng) // 10], rng[len(rng) * 9 // 10]))
print('  우리가 재려는 손절폭             : 0.30%%')
print('  우리가 재려는 익절폭             : 1.00%%')
print('  => 손절선과 익절선이 둘 다 일봉 하나 안에 들어감. 일봉은 순서를 기록하지 않음.')
small = sum(1 for x in rng if x < 1.3)
print('  일봉 변동폭이 1.3%%(=0.3+1.0)보다 작은 날: %d / %d (%.1f%%)'
      % (small, len(rng), small / len(rng) * 100))

print('\n' + '=' * 92)
print('같은 데이터, 동점 처리 규칙만 반대로 -> 답이 얼마나 달라지는가')
print('=' * 92)
print('%-6s %-14s %8s %8s %8s %9s %9s %13s' % (
    'N', '동점 규칙', '거래수', '성공', '실패', '승률%', 'MDD%', '최종자산$'))
print('-' * 92)
for n in (10, 20, 30):
    res = {}
    for rule, label in (('stop', '손절 우선(보수)'), ('target', '익절 우선(낙관)')):
        r = sim(build(n, rule))
        res[rule] = r
        print('%-6d %-14s %8d %8d %8d %9.2f %9.1f %13.4f' % (
            n, label, r['n'], r['w'], r['l'], r['wr'], r['mdd'], r['eq']))
    a, b = res['stop'], res['target']
    print('       -> 승률 %.2f%% vs %.2f%% (%.1f%%p 차이) | 최종자산 $%.2f vs $%.2f'
          % (a['wr'], b['wr'], b['wr'] - a['wr'], a['eq'], b['eq']))
    print('-' * 92)

print('\n두 규칙 모두 "일봉 데이터에서 도출"된 값입니다.')
print('답이 이만큼 갈린다는 것은, 일봉이 이 질문에 대한 답을 담고 있지 않다는 뜻입니다.')
