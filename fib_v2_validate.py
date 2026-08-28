# -*- coding: utf-8 -*-
# v2 후보 검증 (BTC): (1) Walk-forward  (2) DMIN 5~14% 민감도  (3) R_ENTRY_FIB / TOL 민감도  (4) 시장 국면별 성과  (5) WF-OOS 몬테카를로
import csv, sys, time, random, math
import fib_mtf as F

sys.stdout.reconfigure(encoding='utf-8')
POS, LEV, SEED = 0.30, 10, 10000.0
YEARS = [str(y) for y in range(2019, 2027)]
V2 = dict(DCONF=0.382, DMIN=0.08, R4=0.236, R_ENTRY_FIB=0.236, R_RATIO=0.1, ATR_MULT=1.0, TOL=0.003, BUF=0.003,
          EXIT='spec', RATCHET=0.0, MFILT='off', STRUCT='HH_HL', SIDES='both')
data = F.load_data('2019-03-01')
YRS = (data.h_ot[data.LAST] - data.h_ot[data.start4]) / F.D_MS / 365.25


def year_of(t):
    return F.ts(data.h_ot[t['t0']])[:4]


def yearly(trades):
    out = {}
    for y in YEARS:
        pms = [F.pm_of(t, LEV) for t in trades if year_of(t) == y and t['result'] != 'open']
        ret = 1.0
        for p in pms:
            ret *= max(0.0, 1 + POS * p / 100)
        out[y] = {'n': len(pms), 'pf': F._pf(pms), 'ret': (ret - 1) * 100,
                  'wr': sum(1 for p in pms if p > 0) / len(pms) * 100 if pms else 0.0, 'pms': pms}
    return out


def run(P):
    trades, events, sides = F.run(data, P)
    return {'P': dict(P), 'trades': trades, 'ev': F.evaluate(trades, POS, LEV, SEED, YRS), 'yr': yearly(trades)}


def yline(yr):
    return ' '.join('%4.1f' % min(yr[y]['pf'], 9.9) if yr[y]['n'] >= 3 else '   -' for y in YEARS)


def pooled(yr, ys):
    pms = [p for y in ys for p in yr[y]['pms']]
    ret = 1.0
    for p in pms:
        ret *= max(0.0, 1 + POS * p / 100)
    pos = sum(1 for y in ys if yr[y]['n'] >= 3 and yr[y]['pf'] > 1)
    cnt = sum(1 for y in ys if yr[y]['n'] >= 3)
    return {'n': len(pms), 'pf': F._pf(pms), 'ret': (ret - 1) * 100, 'pos': pos, 'cnt': cnt,
            'min': min((yr[y]['ret'] for y in ys if yr[y]['n'] >= 3), default=-999)}


# ================================================================ (1) Walk-forward
print('=' * 150)
print('(1) Walk-forward  |  BTCUSDT %s ~ %s  |  30%% 투입 %dx' % (F.ts(data.h_ot[data.start4]), F.ts(data.h_ot[data.LAST]), LEV))
print('=' * 150)
GRID = []
for DMIN in (0.06, 0.08, 0.10, 0.12):
    for R4 in (0.236, 0.382):
        for RR in (0.1, 0.2):
            for AM in (1.0, 1.5):
                for TOL in (0.003, 0.005):
                    GRID.append(dict(V2, DMIN=DMIN, R4=R4, R_RATIO=RR, ATR_MULT=AM, TOL=TOL))
t0 = time.time()
RES = [run(P) for P in GRID]
print('그리드 %d조합 계산 (%.0fs): DMIN{6,8,10,12} x R4{.236,.382} x R_RATIO{.1,.2} x ATR{1,1.5} x TOL{.3,.5}' % (len(RES), time.time() - t0))


def pname(P):
    return 'DMIN %.2f R4 %.3f Rr %.1f ATR %.1f TOL %.3f' % (P['DMIN'], P['R4'], P['R_RATIO'], P['ATR_MULT'], P['TOL'])


def wf(mode, select):
    print('\n--- 창 방식: %s | 선택 기준: %s ---' % (mode, select))
    print('%-8s %-14s | %-40s | %-28s | %-28s' % ('검증연도', '학습연도', '선택 파라미터', '학습 거래/양수연도/PF/수익률', '검증 거래/PF/수익률/승률'))
    print('-' * 150)
    oos_pms, rows = [], []
    for ty in range(2022, 2027):
        train = [str(y) for y in (range(2019, ty) if mode == 'expanding' else range(ty - 3, ty))]
        cands = []
        for r in RES:
            pl = pooled(r['yr'], train)
            if pl['n'] < 15:
                continue
            cands.append((r, pl))
        if select == 'consistency':
            key = lambda c: (c[1]['pos'], c[1]['min'], c[1]['pf'])
        elif select == 'pf':
            key = lambda c: (c[1]['pf'],)
        else:
            key = lambda c: (c[1]['ret'],)
        r, pl = max(cands, key=key)
        te = r['yr'][str(ty)]
        oos_pms += te['pms']
        rows.append((ty, r['P']))
        print('%-8d %-14s | %-40s | %3d  %d/%d  %4.2f  %+7.0f%%       | %3d  %4.2f  %+7.0f%%  %4.0f%%' % (
            ty, '%s~%s' % (train[0], train[-1]), pname(r['P']), pl['n'], pl['pos'], pl['cnt'], pl['pf'], pl['ret'],
            te['n'], te['pf'], te['ret'], te['wr']))
    ret = 1.0
    peak, mdd, eq = 1.0, 0.0, 1.0
    for p in oos_pms:
        eq *= max(0.0, 1 + POS * p / 100)
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak)
    wins = sum(1 for p in oos_pms if p > 0)
    print('WF 검증구간(2022~2026) 합산: 거래 %d  승률 %.1f%%  PF %.2f  기대값 %+.1f%%  누적 %+.0f%%  MDD %.0f%%' % (
        len(oos_pms), wins / len(oos_pms) * 100, F._pf(oos_pms), sum(oos_pms) / len(oos_pms), (eq - 1) * 100, mdd * 100))
    return oos_pms


wf_res = {}
for mode in ('expanding', 'rolling3'):
    for select in ('consistency', 'pf'):
        wf_res[(mode, select)] = wf(mode, select)
v2r = run(V2)
v2_oos = [p for y in ('2022', '2023', '2024', '2025', '2026') for p in v2r['yr'][y]['pms']]
print('\n비교 - V2 고정 파라미터의 같은 구간(2022~2026): 거래 %d  PF %.2f  기대값 %+.1f%%' % (len(v2_oos), F._pf(v2_oos), sum(v2_oos) / len(v2_oos)))
print('       그리드 64개 중 2022~2026 PF 분포: 최소 %.2f / 중앙값 %.2f / 최대 %.2f, PF>1 비율 %.0f%%' % (
    min(pooled(r['yr'], YEARS[3:])['pf'] for r in RES), sorted(pooled(r['yr'], YEARS[3:])['pf'] for r in RES)[32],
    max(pooled(r['yr'], YEARS[3:])['pf'] for r in RES), sum(1 for r in RES if pooled(r['yr'], YEARS[3:])['pf'] > 1) / 64 * 100))

# ================================================================ (2) DMIN 민감도
print('\n' + '=' * 150)
print('(2) DMIN 민감도 (다른 파라미터 V2 고정)')
print('=' * 150)
print('%5s | %4s %5s %5s %7s %8s %6s %4s %5s %5s | %s' % ('DMIN', '거래', '승률', 'PF', '기대값', '수익률', 'MDD', '연패', 'L-PF', 'S-PF', '연도별 PF 19 20 21 22 23 24 25 26'))
print('-' * 150)
dmin_rows = []
for dm in (0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14):
    r = run(dict(V2, DMIN=dm))
    e = r['ev']
    pos = sum(1 for y in YEARS if r['yr'][y]['n'] >= 3 and r['yr'][y]['pf'] > 1)
    cnt = sum(1 for y in YEARS if r['yr'][y]['n'] >= 3)
    dmin_rows.append((dm, r))
    print('%4.0f%% | %4d %5.1f %5.2f %+7.1f %+8.0f %6.1f %4d %5.2f %5.2f | %s  (%d/%d)' % (
        dm * 100, e['n'], e['wr'], e['pf'], e['exp'], e['ret'], e['mdd'], e['worst'], min(e['long_pf'], 9.99), min(e['short_pf'], 9.99), yline(r['yr']), pos, cnt))

# ================================================================ (3) R_ENTRY_FIB / TOL / BUF
print('\n' + '=' * 150)
print('(3) R_ENTRY_FIB (진입 피보나치) / TOL / BUF 민감도')
print('=' * 150)
print('%-30s | %4s %5s %5s %7s %8s %6s %4s %6s | %s' % ('설정', '거래', '승률', 'PF', '기대값', '수익률', 'MDD', '연패', '손절폭', '연도별 PF'))
print('-' * 150)
for fib in (0.146, 0.236, 0.382, 0.5, 0.618):
    r = run(dict(V2, R_ENTRY_FIB=fib))
    e = r['ev']
    risk = sum((t['entry'] - t['stop0']) / abs(t['entry']) for t in r['trades']) / max(1, len(r['trades'])) * 100
    print('%-30s | %4d %5.1f %5.2f %+7.1f %+8.0f %6.1f %4d %5.2f%% | %s' % ('R_ENTRY_FIB=%.3f' % fib, e['n'], e['wr'], e['pf'], e['exp'], e['ret'], e['mdd'], e['worst'], risk, yline(r['yr'])))
print('-' * 150)
for tol in (0.001, 0.002, 0.003, 0.005, 0.007):
    r = run(dict(V2, TOL=tol))
    e = r['ev']
    print('%-30s | %4d %5.1f %5.2f %+7.1f %+8.0f %6.1f %4d %6s | %s' % ('TOL=%.1f%%' % (tol * 100), e['n'], e['wr'], e['pf'], e['exp'], e['ret'], e['mdd'], e['worst'], '', yline(r['yr'])))
print('-' * 150)
for buf in (0.001, 0.003, 0.005, 0.01):
    r = run(dict(V2, BUF=buf))
    e = r['ev']
    print('%-30s | %4d %5.1f %5.2f %+7.1f %+8.0f %6.1f %4d %6s | %s' % ('BUF=%.1f%%' % (buf * 100), e['n'], e['wr'], e['pf'], e['exp'], e['ret'], e['mdd'], e['worst'], '', yline(r['yr'])))

# ================================================================ (4) 시장 국면
print('\n' + '=' * 150)
print('(4) 시장 국면별 성과 (V2)  |  추세 = 진입 전일까지 100일 수익률 (>+15% 상승 / <-15% 하락 / 그 외 횡보)  |  변동성 = 30일 실현변동성 표본 중앙값 대비')
print('=' * 150)
cl = data.d_cl
logret = [0.0] + [math.log(cl[i] / cl[i - 1]) for i in range(1, len(cl))]


def vol30(d):
    xs = logret[max(1, d - 30):d]
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5 * (365 ** 0.5) * 100


trades = [t for t in v2r['trades'] if t['result'] != 'open']
vols = sorted(vol30(t['day']) for t in trades)
vmed = vols[len(vols) // 2]
print('변동성 중앙값 %.0f%% (연환산)' % vmed)


def trend(d):
    r = cl[d - 1] / cl[d - 101] - 1
    return '상승' if r > 0.15 else ('하락' if r < -0.15 else '횡보')


rows4 = []
for t in trades:
    rows4.append((trend(t['day']), '고변동' if vol30(t['day']) > vmed else '저변동', 'L' if t['side'].s > 0 else 'S', F.pm_of(t, LEV)))
print('%-14s | %4s %5s %5s %7s | %4s %5s %5s %7s | %4s %5s %5s %7s' % ('국면', '거래', '승률', 'PF', '기대값', '롱n', '롱승률', '롱PF', '롱기대', '숏n', '숏승률', '숏PF', '숏기대'))
print('-' * 150)


def stat(pms):
    return (len(pms), sum(1 for p in pms if p > 0) / len(pms) * 100 if pms else 0.0, min(F._pf(pms), 9.99) if pms else 0.0, sum(pms) / len(pms) if pms else 0.0)


for grp in (('상승',), ('횡보',), ('하락',), ('고변동',), ('저변동',), ('상승', '고변동'), ('상승', '저변동'), ('횡보', '고변동'), ('횡보', '저변동'), ('하락', '고변동'), ('하락', '저변동')):
    sel = [r for r in rows4 if all(g in r[:2] for g in grp)]
    a = stat([r[3] for r in sel])
    l = stat([r[3] for r in sel if r[2] == 'L'])
    s = stat([r[3] for r in sel if r[2] == 'S'])
    print('%-14s | %4d %5.1f %5.2f %+7.1f | %4d %5.1f %5.2f %+7.1f | %4d %5.1f %5.2f %+7.1f' % ('+'.join(grp), *a, *l, *s))

# 반기별
print('\n반기별 (V2):')
half = {}
for t in trades:
    k = F.ts(data.h_ot[t['t0']])[:4] + ('H1' if int(F.ts(data.h_ot[t['t0']])[5:7]) <= 6 else 'H2')
    half.setdefault(k, []).append(F.pm_of(t, LEV))
line = []
for k in sorted(half):
    pms = half[k]
    line.append('%s: n%d PF%.1f %+.0f%%' % (k, len(pms), min(F._pf(pms), 9.9), sum(pms)))
for i in range(0, len(line), 4):
    print('  ' + ' | '.join(line[i:i + 4]))

# ================================================================ (5) 몬테카를로 (WF-OOS 거래)
print('\n' + '=' * 150)
print('(5) 몬테카를로 5000회 - Walk-forward(expanding/consistency) 검증구간 거래 순서 리샘플, 10x')
print('=' * 150)
pms = wf_res[('expanding', 'consistency')]
random.seed(7)
for pos in (0.10, 0.15, 0.20, 0.30):
    finals, mdds = [], []
    for _ in range(5000):
        eq, peak, mdd = 1.0, 1.0, 0.0
        for pm in random.choices(pms, k=len(pms)):
            eq *= max(0.0, 1 + pos * pm / 100)
            peak = max(peak, eq)
            mdd = max(mdd, 1 - eq / peak)
        finals.append(eq)
        mdds.append(mdd)
    finals.sort()
    mdds.sort()
    q = lambda xs, p: xs[int(len(xs) * p)]
    print('  투입 %3.0f%%: 최종배수 5%% %5.2fx / 중앙 %5.2fx / 95%% %6.2fx | 손실확률 %4.1f%% | MDD 중앙 %2.0f%% / 95%% %2.0f%%' % (
        pos * 100, q(finals, 0.05), q(finals, 0.5), q(finals, 0.95), sum(1 for x in finals if x < 1) / 50, q(mdds, 0.5) * 100, q(mdds, 0.95) * 100))

with open('fib_v2_wf_grid.csv', 'w', newline='', encoding='utf-8-sig') as fh:
    w = csv.writer(fh)
    w.writerow(['DMIN', 'R4', 'R_RATIO', 'ATR_MULT', 'TOL', 'n', 'pf', 'ret', 'mdd'] + ['%s_%s' % (y, x) for y in YEARS for x in ('n', 'pf', 'ret')])
    for r in RES:
        P, e = r['P'], r['ev']
        w.writerow([P['DMIN'], P['R4'], P['R_RATIO'], P['ATR_MULT'], P['TOL'], e['n'], '%.2f' % e['pf'], '%.1f' % e['ret'], '%.1f' % e['mdd']] +
                   [('%d' % r['yr'][y]['n'] if x == 'n' else '%.2f' % r['yr'][y][x]) for y in YEARS for x in ('n', 'pf', 'ret')])
print('\n저장: fib_v2_wf_grid.csv')
