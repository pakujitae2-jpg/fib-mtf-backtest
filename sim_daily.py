# -*- coding: utf-8 -*-
# DAILY CANDLES ONLY. No intraday data anywhere.
#
#   reference candle T  ->  L = low(T)
#   resting limit buy at L * 1.003        (전저점 +0.3%)
#   filled on the first day in T+1..T+N whose daily LOW <= L*1.003
#   stop   = a daily LOW below L          (칼손절)
#   target = fill * 1.01                  (+1.0%)
#   10x leverage, $100 seed, fees + slippage + funding
#
# Within one daily candle the order of touches is unknowable, so the rule is
# stated explicitly and every ambiguous bar is counted and reported.
import csv, sys

sys.stdout.reconfigure(encoding='utf-8')

ZONE = 0.003
TP = 0.010
NS = [10, 20, 30]
START = '2023-01-01'
EPS = 1e-9

LEV = 10
SEED = 100.0
FEE_MAKER = 0.0002
FEE_TAKER = 0.0005
FUNDING = 0.0001          # per 8h stamp -> 3 per day held


def load(p):
    with open(p, encoding='utf-8') as f:
        return [(r['dt'][:10], float(r['open']), float(r['high']),
                 float(r['low']), float(r['close'])) for r in csv.DictReader(f)]


D = load('btcusdt_1d.csv')
day = [x[0] for x in D]
op = [x[1] for x in D]
hi = [x[2] for x in D]
lo = [x[3] for x in D]
cl = [x[4] for x in D]

S = {'fillday_amb': 0, 'later_amb': 0, 'n': 0}


def build(n, zone, tp):
    """Every signal, resolved on daily candles alone."""
    out = []
    for i in range(len(D)):
        if day[i] < START or i + n >= len(D):
            continue
        L = lo[i]
        px = L * (1 + zone)
        taker = False
        if cl[i] <= px + EPS:
            px = cl[i]                       # already in the zone at order time
            taker = True
            j = i + 1
            if j >= len(D):
                continue
        else:
            j = next((x for x in range(i + 1, i + n + 1) if lo[x] <= px + EPS), None)
            if j is None:
                continue
        target = px * (1 + tp)
        S['n'] += 1
        # --- the fill day itself ---
        broke = lo[j] < L - EPS
        hitt = hi[j] >= target - EPS
        if broke and hitt:
            S['fillday_amb'] += 1
        if broke:
            out.append((j, j, px, L, taker, 'loss'))
            continue
        if hitt:
            out.append((j, j, px, L, taker, 'win'))
            continue
        # --- subsequent days ---
        res, k = 'open', len(D) - 1
        for m in range(j + 1, len(D)):
            b = lo[m] < L - EPS
            t = hi[m] >= target - EPS
            if b and t:
                S['later_amb'] += 1
                res, k = 'loss', m
                break
            if b:
                res, k = 'loss', m
                break
            if t:
                res, k = 'win', m
                break
        out.append((j, k, px, L, taker, res))
    out.sort()
    return out


def simulate(sigs, slip, lev=LEV, tp=TP, seed=SEED):
    eq, peak, mdd, busy = seed, seed, 0.0, -1
    w = l = opn = 0
    fees = fund = slipc = 0.0
    streak = worst = 0
    held, ruin = [], None
    for j, k, fill, L, taker, res in sigs:
        if j <= busy:
            continue
        busy = k
        if res == 'open':
            opn += 1
            continue
        notional = eq * lev
        qty = notional / fill
        fe = notional * (FEE_TAKER if taker else FEE_MAKER)
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
        days = max(k - j, 0)
        fd = qty * fill * FUNDING * days * 3
        eq += qty * (ex - fill) - fe - fx - fd
        fees += fe + fx
        fund += fd
        slipc += sc
        held.append(days)
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak * 100)
        if ruin is None and eq < seed * 0.01:
            ruin = w + l
        if eq < 1e-12:
            break
    t = w + l
    return {'eq': eq, 'w': w, 'l': l, 'open': opn, 'n': t,
            'wr': (w / t * 100) if t else 0.0, 'mdd': mdd, 'worst': worst,
            'fees': fees, 'fund': fund, 'slip': slipc, 'ruin': ruin,
            'hold': (sum(held) / len(held)) if held else 0.0}


risk = ZONE / (1 + ZONE) * 100
print('=' * 96)
print('일봉 전용 시뮬레이션 - 지정가 L*1.003 / 손절 L 이탈 / 익절 +1.0% / 10배 / 시드 $100')
print('=' * 96)
print('데이터: btcusdt_1d.csv 만 사용. 분봉/시간봉 일절 미사용.')
print('손절폭 %.4f%%  익절 1.0000%%  ->  손익비 %.2f : 1  ->  손익분기 승률 %.2f%% (비용 전)'
      % (risk, TP * 100 / risk, risk / (TP * 100 + risk) * 100))
wn, ln = TP * 100 - 0.04, risk + 0.07 + 0.03
print('비용 반영 -> 실질 익절 %.3f%% / 실질 손절 %.3f%% -> 손익분기 승률 %.2f%%'
      % (wn, ln, ln / (wn + ln) * 100))
print('\n일봉 내 동시 터치 처리 규칙: 체결일에 저점 이탈이 같이 있으면 [손절 우선]')

print('\n%-5s %9s %10s %8s %8s %9s %9s %8s %11s %10s' % (
    'N', '신호수', '순차진입', '성공', '실패', '승률%', '평균보유일', 'MDD%', '최종자산$', '파산시점'))
print('-' * 96)
for n in NS:
    sg = build(n, ZONE, TP)
    r = simulate(sg, 0.0003)
    print('%-5d %9d %10d %8d %8d %9.2f %9.2f %8.1f %11.4f %10s' % (
        n, len(sg), r['n'], r['w'], r['l'], r['wr'], r['hold'], r['mdd'], r['eq'],
        ('%d번째' % r['ruin']) if r['ruin'] else '-'))
    print('        최대 연속손실 %d회 | 수수료 $%.2f | 펀딩 $%.2f | 슬리피지 $%.2f'
          % (r['worst'], r['fees'], r['fund'], r['slip']))
print('-' * 96)
print('[판정 정밀도] 전체 신호 %d건 중' % S['n'])
print('  체결일에 손절과 익절이 같은 일봉 안에 공존 (선후 불명): %d건 (%.1f%%)'
      % (S['fillday_amb'], S['fillday_amb'] / S['n'] * 100))
print('  이후 일봉에서 손절과 익절이 같은 봉에 공존 (선후 불명): %d건 (%.1f%%)'
      % (S['later_amb'], S['later_amb'] / S['n'] * 100))

print('\n' + '=' * 96)
print('레버리지 민감도 (N=20)')
print('=' * 96)
sg20 = build(20, ZONE, TP)
print('%-8s %13s %10s %13s %12s' % ('배율', '최종자산$', 'MDD%', '총수익률%', '최대연속손실'))
print('-' * 96)
for lv in (1, 2, 3, 5, 10, 20):
    r = simulate(sg20, 0.0003, lev=lv)
    print('%-8s %13.4f %10.1f %13.1f %12d' % (
        '%dx' % lv, r['eq'], r['mdd'], (r['eq'] / SEED - 1) * 100, r['worst']))

print('\n' + '=' * 96)
print('진입 버퍼를 바꾸면? (N=20, 익절 1%, 10배)')
print('=' * 96)
print('%-9s %9s %10s %8s %9s %9s %11s' % (
    '버퍼', '손절폭%', '분기승률%', '거래수', '실제승률%', 'MDD%', '최종자산$'))
print('-' * 96)
for z in (0.001, 0.003, 0.005, 0.010, 0.015, 0.020):
    r = simulate(build(20, z, TP), 0.0003)
    rr = z / (1 + z) * 100
    print('%-9s %9.4f %10.2f %8d %9.2f %9.1f %11.4f' % (
        '%.1f%%' % (z * 100), rr, rr / (TP * 100 + rr) * 100, r['n'], r['wr'],
        r['mdd'], r['eq']))

print('\n' + '=' * 96)
print('익절폭을 바꾸면? (N=20, 버퍼 0.3%, 10배)')
print('=' * 96)
print('%-9s %9s %10s %8s %9s %9s %11s' % (
    '익절%', '손익비', '분기승률%', '거래수', '실제승률%', 'MDD%', '최종자산$'))
print('-' * 96)
for tp in (0.003, 0.005, 0.010, 0.020, 0.030, 0.050):
    r = simulate(build(20, ZONE, tp), 0.0003, tp=tp)
    print('%-9s %9.2f %10.2f %8d %9.2f %9.1f %11.4f' % (
        '%.1f%%' % (tp * 100), tp * 100 / risk, risk / (tp * 100 + risk) * 100,
        r['n'], r['wr'], r['mdd'], r['eq']))
