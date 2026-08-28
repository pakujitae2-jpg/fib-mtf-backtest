# -*- coding: utf-8 -*-
# 청산 방식 교차검증: 진입(V2)은 고정, 청산만 바꿔 BTC/ETH/BNB/SOL 에서 어떤 청산이 진입 우위를 가장 안정적으로 수익으로 바꾸는지
import sys, time
import fib_mtf as F

sys.stdout.reconfigure(encoding='utf-8')
POS, LEV, SEED = 0.30, 10, 10000.0
YEARS = [str(y) for y in range(2019, 2027)]
V2 = dict(DCONF=0.382, DMIN=0.08, R4=0.236, R_ENTRY_FIB=0.236, R_RATIO=0.1, ATR_MULT=1.0, TOL=0.003, BUF=0.003,
          EXIT='spec', RATCHET=0.0, MFILT='off', STRUCT='HH_HL', SIDES='both')
SYMS = ['btcusdt', 'ethusdt', 'bnbusdt', 'solusdt']
EXITS = ['spec', 'trail', 'tp10', 'tp20', 'half', 'tpR2', 'tpR3', 'halfR2', 'halfR2spec']
DESC = {'spec': 'W확장 25%x4 + 일봉전환', 'trail': '일봉전환만', 'tp10': '+10% 전량', 'tp20': '+20% 전량', 'half': '+10% 절반 + 본절 + 전환',
        'tpR2': '+2R 전량', 'tpR3': '+3R 전량', 'halfR2': '+2R 절반 + 본절 + 전환', 'halfR2spec': '+2R 절반 + W확장 12.5%x4 + 전환'}

DATA = {s: F.load_data('2019-03-01', s) for s in SYMS}
res = {}
t0 = time.time()
for ex in EXITS:
    for rc in (0.0, 0.10):
        for s in SYMS:
            data = DATA[s]
            yrs = (data.h_ot[data.LAST] - data.h_ot[data.start4]) / F.D_MS / 365.25
            trades, _, _ = F.run(data, dict(V2, EXIT=ex, RATCHET=rc))
            e = F.evaluate(trades, POS, LEV, SEED, yrs)
            pms_by_y = {}
            for t in trades:
                if t['result'] != 'open':
                    pms_by_y.setdefault(F.ts(data.h_ot[t['t0']])[:4], []).append(F.pm_of(t, LEV))
            ys = [(y, F._pf(p)) for y, p in pms_by_y.items() if len(p) >= 3]
            gp = sum(F.pm_of(t, LEV) for t in trades if t['result'] != 'open' and F.pm_of(t, LEV) > 0)
            gl = -sum(F.pm_of(t, LEV) for t in trades if t['result'] != 'open' and F.pm_of(t, LEV) <= 0)
            res[(ex, rc, s)] = {'e': e, 'pos': sum(1 for _, pf in ys if pf > 1), 'cnt': len(ys), 'gp': gp, 'gl': gl, 'hold': e['hold_d']}
print('계산 %d 런 (%.0fs)' % (len(res), time.time() - t0))

print('\n' + '=' * 160)
print('청산 방식 x 종목  (진입 V2 고정, 30%% 투입 %dx)   각 칸: 거래 / 승률 / PF / 기대값%% / MDD%% / 양수연도' % LEV)
print('=' * 160)
print('%-11s %4s | %-30s | %-30s | %-30s | %-30s | %-16s' % ('EXIT', '래칫', 'BTC', 'ETH', 'BNB', 'SOL', '4종목 합산 PF / 양수연도'))
print('-' * 160)
for ex in EXITS:
    for rc in (0.0, 0.10):
        cells = []
        GP = GL = 0.0
        P = C = 0
        for s in SYMS:
            r = res[(ex, rc, s)]
            e = r['e']
            cells.append('%3d %4.1f %4.2f %+5.1f %3.0f %d/%d' % (e['n'], e['wr'], min(e['pf'], 9.99), e['exp'], e['mdd'], r['pos'], r['cnt']))
            GP += r['gp']
            GL += r['gl']
            P += r['pos']
            C += r['cnt']
        print('%-11s %4.0f%% | %-30s | %-30s | %-30s | %-30s | %5.2f  %2d/%2d' % (ex, rc * 100, *cells, GP / GL if GL else 9.99, P, C))
    print('-' * 160)
print('\n청산 설명: ' + ' | '.join('%s=%s' % (k, v) for k, v in DESC.items()))

print('\n' + '=' * 160)
print('종목별 최적 청산 (PF 기준) vs spec')
print('=' * 160)
for s in SYMS:
    best = max(((ex, rc) for ex in EXITS for rc in (0.0, 0.10)), key=lambda k: res[(k[0], k[1], s)]['e']['pf'])
    b = res[(best[0], best[1], s)]
    sp = res[('spec', 0.0, s)]
    print('%-4s: 최적 %-10s 래칫 %2.0f%%  PF %.2f (%d/%d yrs, 보유 %.1f일)   |   spec PF %.2f (%d/%d yrs, 보유 %.1f일)' % (
        s.upper().replace('USDT', ''), best[0], best[1] * 100, b['e']['pf'], b['pos'], b['cnt'], b['hold'], sp['e']['pf'], sp['pos'], sp['cnt'], sp['hold']))

print('\n' + '=' * 160)
print('청산 방식별 4종목 평균 (동일 가중): PF 평균 / 양수연도 비율 / 기대값 평균 / MDD 평균 / 최저 PF 종목')
print('=' * 160)
rows = []
for ex in EXITS:
    for rc in (0.0, 0.10):
        rs = [res[(ex, rc, s)] for s in SYMS]
        rows.append((ex, rc, sum(r['e']['pf'] for r in rs) / 4, sum(r['pos'] for r in rs) / sum(r['cnt'] for r in rs) * 100,
                     sum(r['e']['exp'] for r in rs) / 4, sum(r['e']['mdd'] for r in rs) / 4, min(r['e']['pf'] for r in rs)))
for ex, rc, pf, py, exp, mdd, mn in sorted(rows, key=lambda r: -r[6]):
    print('%-11s 래칫 %2.0f%% | PF평균 %.2f | 양수연도 %3.0f%% | 기대값 %+5.1f%% | MDD %3.0f%% | 최저 PF %.2f' % (ex, rc * 100, pf, py, exp, mdd, mn))
