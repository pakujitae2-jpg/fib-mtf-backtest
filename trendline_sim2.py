# -*- coding: utf-8 -*-
# 확장 실험: 1) 익절x손절 그리드(엣지 지도)  2) 투입 비중/배율  3) 추세 필터  4) 부트스트랩
import sys, random
import trendline_core as c
from trendline_core import day, lo, hi, cl, gen_signals, simulate, line_val

sys.stdout.reconfigure(encoding='utf-8')

SETS = [  # (N, k, zone, valid, stop)  대표 신호셋 2개
    (60, 3, 0.01, 'low', 'fixed'),
    (60, 2, 0.02, 'close', 'trail'),
]


def run(sigs, stop, sbuf, lev, tp=None, pos=None):
    otp, opos = c.TP, c.POS
    if tp is not None:
        c.TP = tp
    if pos is not None:
        c.POS = pos
    r = simulate(sigs, stop, sbuf, lev)
    c.TP, c.POS = otp, opos
    return r


# ---------------------------------------------------------------- 1) 익절 x 손절 그리드
TPS = [0.03, 0.05, 0.07, 0.10, 0.15, 0.20]
SBS = [0.005, 0.01, 0.02, 0.03]
for N, k, zone, vm, sm in SETS:
    sigs = gen_signals(N, k, zone, vm)
    print('=' * 100)
    print('익절 x 손절버퍼 그리드  |  N=%d k=%d zone=%.0f%% valid=%s stop=%s  |  10x, 투입 30%%  |  신호 %d건' % (
        N, k, zone * 100, vm, sm, len(sigs)))
    print('=' * 100)
    print('각 칸: 거래수 / 승률% / 거래당 마진손익% / 최종자산$   (손익분기 승률 = 손절폭/(익절+손절폭))')
    print('%-8s' % '익절\\버퍼' + ''.join('%22s' % ('버퍼 %.1f%%' % (s * 100)) for s in SBS))
    print('-' * 100)
    for tp in TPS:
        row = '%-8s' % ('+%.0f%%' % (tp * 100))
        for sb in SBS:
            r = run(sigs, sm, sb, 10, tp=tp)
            row += '%22s' % ('%3d/%4.1f/%+6.1f/%6.0f' % (r['n'], r['wr'], r['pnl_m'], r['eq']))
        print(row)
    print()

# ---------------------------------------------------------------- 2) 투입 비중 x 배율
N, k, zone, vm, sm = SETS[0]
sigs = gen_signals(N, k, zone, vm)
print('=' * 100)
print('투입 비중 x 배율  |  N=%d k=%d zone=%.0f%% valid=%s stop=%s  |  익절 +10%% 손절버퍼 1%%' % (N, k, zone * 100, vm, sm))
print('=' * 100)
print('%-6s %4s | %4s %6s %8s | %10s %8s %6s %4s | %s' % (
    '투입', 'lev', '거래', '승률%', '마진손익%', '최종자산$', '수익률%', 'MDD%', '연패', '실효배율(계좌기준)'))
print('-' * 100)
for pos in (0.05, 0.10, 0.15, 0.20, 0.30, 0.50):
    for lev in (5, 10, 20):
        r = run(sigs, sm, 0.01, lev, pos=pos)
        print('%5.0f%% %3dx | %4d %6.1f %8.1f | %10.0f %8.1f %6.1f %4d | %.1fx' % (
            pos * 100, lev, r['n'], r['wr'], r['pnl_m'], r['eq'], r['ret'], r['mdd'], r['worst'], pos * lev))
    print('-' * 100)

# ---------------------------------------------------------------- 3) 필터
def sma(n):
    out = [None] * len(cl)
    s = 0.0
    for i in range(len(cl)):
        s += cl[i]
        if i >= n:
            s -= cl[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


MA50, MA200 = sma(50), sma(200)


def touches(i, tl, tol=0.01):
    """p1~i 구간에서 추세선 1% 이내로 내려온 봉 묶음(연속봉은 1회) 수"""
    p1 = tl[0]
    n, prev = 0, False
    for t in range(p1, i + 1):
        hit = lo[t] <= line_val(tl, t) * (1 + tol)
        if hit and not prev:
            n += 1
        prev = hit
    return n


def body_up(i):
    return cl[i] > c.D[i]['o']


FILTERS = [
    ('필터 없음', lambda i, tl: True),
    ('종가>MA50', lambda i, tl: MA50[i] is not None and cl[i] > MA50[i]),
    ('종가>MA200', lambda i, tl: MA200[i] is not None and cl[i] > MA200[i]),
    ('MA50>MA200', lambda i, tl: MA200[i] is not None and MA50[i] > MA200[i]),
    ('터치 3회+', lambda i, tl: touches(i, tl) >= 3),
    ('신호봉 양봉', lambda i, tl: body_up(i)),
    ('양봉+MA200', lambda i, tl: body_up(i) and MA200[i] is not None and cl[i] > MA200[i]),
    ('터치3+MA200', lambda i, tl: touches(i, tl) >= 3 and MA200[i] is not None and cl[i] > MA200[i]),
]
for N, k, zone, vm, sm in SETS:
    sigs = gen_signals(N, k, zone, vm)
    print('\n' + '=' * 100)
    print('추가 필터 효과  |  N=%d k=%d zone=%.0f%% valid=%s stop=%s  |  10x 투입 30%% 익절 +10%% 버퍼 1%%' % (
        N, k, zone * 100, vm, sm))
    print('=' * 100)
    print('%-12s %5s %4s | %3s %3s %3s %3s | %6s %6s %8s %5s | %10s %8s %6s %4s' % (
        '필터', '신호', '거래', 'TP', '익손', '손절', '청산', '승률%', '손절폭', '마진손익%', '보유', '최종자산$', '수익률%', 'MDD%', '연패'))
    print('-' * 100)
    for name, fn in FILTERS:
        fs = [(i, tl) for i, tl in sigs if fn(i, tl)]
        r = run(fs, sm, 0.01, 10)
        print('%-12s %5d %4d | %3d %3d %3d %3d | %6.1f %6.2f %8.1f %5.1f | %10.0f %8.1f %6.1f %4d' % (
            name, len(fs), r['n'], r['tp'], r['sp'], r['sl'], r['liq'], r['wr'], r['risk'], r['pnl_m'],
            r['hold'], r['eq'], r['ret'], r['mdd'], r['worst']))

# ---------------------------------------------------------------- 4) 부트스트랩
N, k, zone, vm, sm = SETS[0]
r = run(gen_signals(N, k, zone, vm), sm, 0.01, 10)
pnls = [t[6] for t in r['trades'] if t[2] != 'open']
random.seed(7)
print('\n' + '=' * 100)
print('부트스트랩 (거래 순서 무작위 리샘플 5000회)  |  N=%d k=%d zone=%.0f%% valid=%s stop=%s 10x 투입 30%%  |  거래 %d건' % (
    N, k, zone * 100, vm, sm, len(pnls)))
print('=' * 100)
for pos in (0.10, 0.20, 0.30):
    finals, mdds = [], []
    for _ in range(5000):
        eq, peak, mdd = 1.0, 1.0, 0.0
        for pm in random.choices(pnls, k=len(pnls)):
            eq *= 1 + pos * pm / 100
            peak = max(peak, eq)
            mdd = max(mdd, 1 - eq / peak)
        finals.append(eq)
        mdds.append(mdd)
    finals.sort()
    mdds.sort()
    q = lambda xs, p: xs[int(len(xs) * p)]
    print('투입 %3.0f%%: 최종배수 5%%분위 %.2fx / 중앙값 %.2fx / 95%%분위 %.2fx  |  손실확률 %.0f%%  |  MDD 중앙값 %.0f%% / 95%%분위 %.0f%%' % (
        pos * 100, q(finals, 0.05), q(finals, 0.5), q(finals, 0.95),
        sum(1 for f in finals if f < 1) / len(finals) * 100, q(mdds, 0.5) * 100, q(mdds, 0.95) * 100))
wins = sum(1 for p in pnls if p > 0)
print('표본 승률 %.1f%% (%d/%d) -> 95%% 신뢰구간 약 %.0f%% ~ %.0f%% (이항 근사)' % (
    wins / len(pnls) * 100, wins, len(pnls),
    max(0, (wins / len(pnls) - 1.96 * (wins / len(pnls) * (1 - wins / len(pnls)) / len(pnls)) ** 0.5) * 100),
    (wins / len(pnls) + 1.96 * (wins / len(pnls) * (1 - wins / len(pnls)) / len(pnls)) ** 0.5) * 100))
