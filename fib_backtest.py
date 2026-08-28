# -*- coding: utf-8 -*-
# 다중 타임프레임 피보나치 전략 백테스트 - 2단계 스윕 + 연도별 일관성 + 가설검정 + 현재 상태
import csv, sys, time, random
from collections import Counter
import fib_mtf as F

sys.stdout.reconfigure(encoding='utf-8')
POS, LEV, SEED = 0.30, 10, 10000.0
YEARS = [str(y) for y in range(2019, 2027)]
data = F.load_data('2019-03-01')
YRS = (data.h_ot[data.LAST] - data.h_ot[data.start4]) / F.D_MS / 365.25
print('데이터: 일봉 %s~%s | 4H %s~%s (%d봉) | 5분봉 %d | 거래기간 %.1f년' % (
    F.ts(data.d_ot[0], 24), F.ts(data.d_ot[-1], 24), F.ts(data.h_ot[data.start4]), F.ts(data.h_ot[data.LAST]),
    data.n4, len(data.f_ot), YRS))

BASE = dict(DCONF=0.382, DMIN=0.08, R4=0.382, R_RATIO=0.2, ATR_MULT=1.5, TOL=0.003, BUF=0.003,
            EXIT='spec', RATCHET=0.0, MFILT='off', STRUCT='none', SIDES='both')


def yearly(trades, lev=LEV, pos=POS):
    out = {}
    for y in YEARS:
        ts_ = [t for t in trades if F.ts(data.h_ot[t['t0']])[:4] == y and t['result'] != 'open']
        pms = [F.pm_of(t, lev) for t in ts_]
        ret = 1.0
        for p in pms:
            ret *= max(0.0, 1 + pos * p / 100)
        out[y] = {'n': len(pms), 'pf': F._pf(pms), 'ret': (ret - 1) * 100,
                  'wr': sum(1 for p in pms if p > 0) / len(pms) * 100 if pms else 0.0}
    return out


def score(r):
    ys = [r['yr'][y] for y in YEARS if r['yr'][y]['n'] >= 3]
    r['pos_years'] = sum(1 for y in ys if y['pf'] > 1)
    r['n_years'] = len(ys)
    r['min_year'] = min((y['ret'] for y in ys), default=-999)


def do_run(P):
    trades, events, sides = F.run(data, P)
    ev = F.evaluate(trades, POS, LEV, SEED, YRS)
    r = {'P': dict(P), 'trades': trades, 'events': events, 'sides': sides, 'ev': ev, 'yr': yearly(trades)}
    score(r)
    return r


KEYS = ['DMIN', 'R4', 'R_RATIO', 'ATR_MULT', 'TOL', 'BUF', 'EXIT', 'RATCHET', 'MFILT', 'STRUCT']


def hdr():
    print('%4s %5s %4s %4s %5s %5s %-5s %4s %-3s %-5s | %4s %5s %5s %6s %6s %7s %5s %4s %5s %5s | %s' % (
        'DMIN', 'R4', 'Rrat', 'ATRx', 'TOL', 'BUF', 'EXIT', '래칫', 'M', 'STR',
        '거래', '승률', 'PF', '평균승', '평균패', '수익률%', 'MDD', '연패', 'L-PF', 'S-PF', '연도별 PF ' + ' '.join(y[2:] for y in YEARS)))
    print('-' * 160)


def line(r):
    P, e = r['P'], r['ev']
    ys = ' '.join('%4.1f' % min(r['yr'][y]['pf'], 9.9) if r['yr'][y]['n'] >= 3 else '   -' for y in YEARS)
    print('%4.2f %5.3f %4.2f %4.1f %5.3f %5.3f %-5s %4.2f %-3s %-5s | %4d %5.1f %5.2f %+6.0f %+6.0f %+7.0f %5.1f %4d %5.2f %5.2f | %s  (%d/%d yrs, min %+.0f%%)' % (
        P['DMIN'], P['R4'], P['R_RATIO'], P['ATR_MULT'], P['TOL'], P['BUF'], P['EXIT'], P['RATCHET'], P['MFILT'], P['STRUCT'],
        e['n'], e['wr'], min(e['pf'], 9.99), e['avg_win'], e['avg_loss'], e['ret'], e['mdd'], e['worst'],
        min(e['long_pf'], 9.99), min(e['short_pf'], 9.99), ys, r['pos_years'], r['n_years'], r['min_year']))


# ---------------------------------------------------------------- 1단계: 신호 파라미터
t0 = time.time()
rows = []
for DMIN in (0.04, 0.08, 0.12):
    for R4 in (0.382, 0.236):
        for RR in (0.1, 0.2, 0.35):
            for AM in (1.0, 2.0):
                for TOL in (0.003, 0.01):
                    for ST in ('none', 'HH_HL'):
                        for MF in ('off', 'zz'):
                            P = dict(BASE, DMIN=DMIN, R4=R4, R_RATIO=RR, ATR_MULT=AM, TOL=TOL, STRUCT=ST, MFILT=MF)
                            rows.append(do_run(P))
print('1단계 %d조합 (%.0fs)' % (len(rows), time.time() - t0))


def median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0.0


ok = [r for r in rows if r['ev']['n'] >= 30]
print('\n' + '=' * 160)
print('1단계 요인별 요약 (거래 30건 이상 %d개, EXIT=spec BUF=0.3%%, 30%% 투입 %dx)' % (len(ok), LEV))
print('=' * 160)
print('%-16s %4s | %8s %6s %6s %6s | %8s %8s | %6s %6s' % ('요인', '조합', '수익중앙', '승률', 'PF중앙', 'MDD중앙', '양수연도', '전연도양수', 'L-PF', 'S-PF'))
print('-' * 160)
for key in ('DMIN', 'R4', 'R_RATIO', 'ATR_MULT', 'TOL', 'STRUCT', 'MFILT'):
    for v in sorted(set(r['P'][key] for r in ok), key=str):
        rs = [r for r in ok if r['P'][key] == v]
        print('%-16s %4d | %+8.0f %6.1f %6.2f %6.1f | %8.2f %7d개 | %6.2f %6.2f' % (
            '%s=%s' % (key, v), len(rs), median([r['ev']['ret'] for r in rs]), sum(r['ev']['wr'] for r in rs) / len(rs),
            median([r['ev']['pf'] for r in rs]), median([r['ev']['mdd'] for r in rs]),
            sum(r['pos_years'] for r in rs) / len(rs), sum(1 for r in rs if r['n_years'] >= 5 and r['pos_years'] == r['n_years']),
            median([r['ev']['long_pf'] for r in rs]), median([r['ev']['short_pf'] for r in rs])))
    print('-' * 160)

ok.sort(key=lambda r: (-r['pos_years'], -r['min_year']))
print('\n' + '=' * 160)
print('1단계 연도별 일관성 상위 15')
print('=' * 160)
hdr()
for r in ok[:15]:
    line(r)

# ---------------------------------------------------------------- 2단계: 청산 파라미터
top = ok[:6]
rows2 = []
t0 = time.time()
for base in top:
    for EX in ('spec', 'trail', 'tp10', 'tp20', 'half'):
        for BUF in (0.003, 0.01):
            for RC in (0.0, 0.10):
                if RC and EX in ('tp10', 'tp20'):
                    continue
                P = dict(base['P'], EXIT=EX, BUF=BUF, RATCHET=RC)
                rows2.append(do_run(P))
print('\n2단계 %d조합 (%.0fs)' % (len(rows2), time.time() - t0))
ok2 = [r for r in rows2 if r['ev']['n'] >= 30]
print('\n' + '=' * 160)
print('2단계 청산 방식별 요약')
print('=' * 160)
print('%-16s %4s | %8s %6s %6s %6s | %8s %8s' % ('요인', '조합', '수익중앙', '승률', 'PF중앙', 'MDD중앙', '양수연도', '전연도양수'))
print('-' * 160)
for key in ('EXIT', 'BUF', 'RATCHET'):
    for v in sorted(set(r['P'][key] for r in ok2), key=str):
        rs = [r for r in ok2 if r['P'][key] == v]
        print('%-16s %4d | %+8.0f %6.1f %6.2f %6.1f | %8.2f %7d개' % (
            '%s=%s' % (key, v), len(rs), median([r['ev']['ret'] for r in rs]), sum(r['ev']['wr'] for r in rs) / len(rs),
            median([r['ev']['pf'] for r in rs]), median([r['ev']['mdd'] for r in rs]),
            sum(r['pos_years'] for r in rs) / len(rs), sum(1 for r in rs if r['n_years'] >= 5 and r['pos_years'] == r['n_years'])))
    print('-' * 160)
allr = ok + ok2
allr.sort(key=lambda r: (-r['pos_years'], -r['min_year']))
print('\n' + '=' * 160)
print('전체 연도별 일관성 상위 20 (1+2단계)')
print('=' * 160)
hdr()
for r in allr[:20]:
    line(r)

with open('fib_sweep.csv', 'w', newline='', encoding='utf-8-sig') as fh:
    w = csv.writer(fh)
    w.writerow(KEYS + ['n', 'wr', 'pf', 'exp', 'ret', 'mdd', 'worst', 'sharpe', 'hold_d', 'long_n', 'long_pf', 'short_n',
                       'short_pf', 'pos_years', 'n_years', 'min_year'] + ['%s_%s' % (y, x) for y in YEARS for x in ('n', 'pf', 'ret')])
    for r in rows + rows2:
        e = r['ev']
        w.writerow([r['P'][k] for k in KEYS] + [e['n'], '%.1f' % e['wr'], '%.2f' % e['pf'], '%.1f' % e['exp'], '%.1f' % e['ret'],
                    '%.1f' % e['mdd'], e['worst'], '%.2f' % e['sharpe'], '%.1f' % e['hold_d'], e['long_n'], '%.2f' % e['long_pf'],
                    e['short_n'], '%.2f' % e['short_pf'], r['pos_years'], r['n_years'], '%.1f' % r['min_year']] +
                   [('%d' % r['yr'][y]['n'] if x == 'n' else '%.2f' % r['yr'][y][x]) for y in YEARS for x in ('n', 'pf', 'ret')])

# ---------------------------------------------------------------- 최종 후보 상세
best = allr[0]
P, e, trades = best['P'], best['ev'], best['trades']
print('\n' + '=' * 160)
print('최종 후보: ' + ', '.join('%s=%s' % (k, P[k]) for k in KEYS) + '  |  30%% 투입 %dx' % LEV)
print('=' * 160)
print('거래 %d (롱 %d / 숏 %d)  승률 %.1f%%  평균승 %+.1f%% 평균패 %+.1f%% (마진)  PF %.2f (롱 %.2f / 숏 %.2f)  기대값 %+.1f%%/거래' % (
    e['n'], e['long_n'], e['short_n'], e['wr'], e['avg_win'], e['avg_loss'], e['pf'], e['long_pf'], e['short_pf'], e['exp']))
print('최종자산 $%.0f (%+.0f%%, 연환산 %+.1f%%)  MDD %.1f%%  최대연패 %d  샤프(거래기준) %.2f  평균보유 %.1f일  청산 %d' % (
    e['eq'], e['ret'], ((e['eq'] / SEED) ** (1 / YRS) - 1) * 100, e['mdd'], e['worst'], e['sharpe'], e['hold_d'], e['liq']))
print(Counter('%s-%s' % ('L' if t['side'].s > 0 else 'S', t['result']) for t in trades))
print('\n연도별:')
for y in YEARS:
    yr = best['yr'][y]
    print('  %s: 거래 %3d  승률 %5.1f%%  PF %.2f  계좌수익률 %+.1f%%' % (y, yr['n'], yr['wr'], yr['pf'], yr['ret']))

# 국면별 (월봉 방향)
print('\n월봉 국면별 (m_zz 기준):')
for side_s in (1, -1):
    for mdir in ('UP', 'DOWN'):
        pms = [F.pm_of(t, LEV) for t in trades if t['side'].s == side_s and data.m_zz[t['day']] == mdir and t['result'] != 'open']
        if pms:
            print('  %s / 월봉 %-4s: 거래 %3d  승률 %5.1f%%  PF %.2f  기대값 %+.1f%%' % (
                '롱' if side_s > 0 else '숏', mdir, len(pms), sum(1 for p in pms if p > 0) / len(pms) * 100, F._pf(pms), sum(pms) / len(pms)))

print('\n거래 내역 (최근 30건):')
print('%-2s %-16s %-16s %-5s %8s %8s %6s %7s %5s  %s' % ('방향', '진입', '청산', '결과', '진입가', '초기손절', '손절폭', '마진%', '보유일', '체결'))
print('-' * 160)
for t in trades[-30:]:
    sg = t['side'].s
    print('%-2s %-16s %-16s %-5s %8.0f %8.0f %5.2f%% %+7.1f %5.1f  %s' % (
        'L' if sg > 0 else 'S', F.ts(data.h_ot[t['t0']]), F.ts(data.h_ot[t['t1']]), t['result'], sg * t['entry'], sg * t['stop0'],
        (t['entry'] - t['stop0']) / abs(t['entry']) * 100, F.pm_of(t, LEV), t['hold_h'] / 24,
        ' '.join('%s@%.0f' % (k, sg * px) for _, px, fr, k in t['fills'])))
with open('fib_trades.csv', 'w', newline='', encoding='utf-8-sig') as fh:
    w = csv.writer(fh)
    w.writerow(['side', 'entry_time', 'exit_time', 'result', 'entry', 'stop0', 'risk_pct', 'r_net_pct', 'margin_pnl_10x', 'mae_pct',
                'hold_days', 'P0', 'H1', 'R_low', 'R_high', 'fills'])
    for t in trades:
        sg = t['side'].s
        w.writerow(['L' if sg > 0 else 'S', F.ts(data.h_ot[t['t0']]), F.ts(data.h_ot[t['t1']]), t['result'], '%.2f' % (sg * t['entry']),
                    '%.2f' % (sg * t['stop0']), '%.3f' % ((t['entry'] - t['stop0']) / abs(t['entry']) * 100), '%.3f' % (t['r_net'] * 100),
                    '%.2f' % F.pm_of(t, LEV), '%.2f' % (t['mae'] * 100), '%.2f' % (t['hold_h'] / 24), '%.2f' % (sg * t['P0']),
                    '%.2f' % (sg * t['H1']), '%.2f' % (sg * t['R'][0]), '%.2f' % (sg * t['R'][1]),
                    ' '.join('%s@%.0f' % (k, sg * px) for _, px, fr, k in t['fills'])])

# ---------------------------------------------------------------- 사이징
print('\n' + '=' * 160)
print('투입 비중 x 배율 (최종 후보)')
print('=' * 160)
print('%-6s %4s | %6s %8s | %10s %8s %6s %4s %4s | %s' % ('투입', 'lev', '승률%', '기대값%', '최종자산$', '수익률%', 'MDD%', '연패', '청산', '실효배율'))
print('-' * 160)
for pos in (0.05, 0.10, 0.15, 0.20, 0.30):
    for lev in (5, 10, 20):
        r = F.evaluate(trades, pos, lev, SEED, YRS)
        print('%5.0f%% %3dx | %6.1f %+8.1f | %10.0f %+8.0f %6.1f %4d %4d | %.1fx' % (
            pos * 100, lev, r['wr'], r['exp'], r['eq'], r['ret'], r['mdd'], r['worst'], r['liq'], pos * lev))
    print('-' * 160)

# ---------------------------------------------------------------- 가설검정: 23.6/76.4 진입 vs 무작위
def forward(sd, t, entry, stop, mults, maxbars=360):
    hit = {m: False for m in mults}
    risk = entry - stop
    for j in range(t + 1, min(t + maxbars, data.LAST) + 1):
        for m in mults:
            if not hit[m] and sd.h_hi[j] >= entry + m * risk - F.EPS:
                hit[m] = True
        if sd.h_lo[j] <= stop + F.EPS:
            break
    return hit


MULTS = [1, 2, 3, 5]
closed = [t for t in trades if t['result'] != 'open']
pat = [forward(t['side'], t['t0'], t['entry'], t['stop0'], MULTS) for t in closed]
random.seed(5)
sides_map = {s.s: s for s in best['sides']}
rnd = []
for _ in range(3000):
    t = random.randint(data.start4, data.LAST - 400)
    tr = random.choice(closed)
    sd = sides_map[tr['side'].s]
    entry = sd.h_cl[t]
    risk = (tr['entry'] - tr['stop0']) / abs(tr['entry'])
    rnd.append(forward(sd, t, entry, entry - risk * abs(entry), MULTS))
print('\n' + '=' * 160)
print('가설검정: 레드/블루라인 진입이 무작위 진입보다 나은가?  (손절 이탈 전 nR 도달 확률, R = 초기 손절폭, 최대 60일)')
print('=' * 160)
print('%-40s %6s | ' % ('', '표본') + ' '.join('%7s' % ('+%dR' % m) for m in MULTS))
for name, res in (('전략 진입 (23.6/76.4 레벨)', pat), ('무작위 진입 (같은 손절폭 분포)', rnd)):
    print('%-40s %6d | ' % (name, len(res)) + ' '.join('%6.1f%%' % (sum(1 for h in res if h[m]) / len(res) * 100) for m in MULTS))
for name, res in (('  롱만', [h for h, t in zip(pat, closed) if t['side'].s > 0]), ('  숏만', [h for h, t in zip(pat, closed) if t['side'].s < 0])):
    if res:
        print('%-40s %6d | ' % (name, len(res)) + ' '.join('%6.1f%%' % (sum(1 for h in res if h[m]) / len(res) * 100) for m in MULTS))

# ---------------------------------------------------------------- 현재 상태 (감지봇 출력)
print('\n' + '=' * 160)
print('현재 상태  %s 4H 종가 %.0f  (최종 후보 파라미터)' % (F.ts(data.h_ot[data.LAST]), data.h_cl[data.LAST]))
print('=' * 160)
dl = data.h_day[data.LAST]
print('월봉 방향: zz=%s  sma6=%s' % (data.m_zz[dl], data.m_sma[dl]))
pw = data.prev_week[dl]
print('전주 고가 %.0f 저가 %.0f  -> 상방 확장 #1-1 %.0f  #1-2 %.0f  #1-3 %.0f  #1-6 %.0f' % (
    pw[0], pw[1], *[pw[0] + (pw[0] - pw[1]) * f for f in F.FIB_EXT]))
for sd in best['sides']:
    sg = sd.s
    name = 'LONG ' if sg > 0 else 'SHORT'
    z = sd.dzz
    anc, ext = sg * z[2], sg * z[4]
    size = abs(z[4] - z[2])
    lvl = sg * (z[4] - 0.382 * (z[4] - z[2]))
    dirn = ('상승 leg 진행' if z[0] == 'UP' else '눌림 진행') if sg > 0 else ('하락 leg 진행' if z[0] == 'UP' else '반등 진행')
    print('\n[%s] 일봉 ZigZag: %s  시작 %.0f -> 극값 %.0f (폭 %.1f%%)  38.2%% 확정선 %.0f' % (name, dirn, anc, ext, size / abs(z[2]) * 100, lvl))
    print('        ARMED=%s  P0=%s  H1=%s  vFlag=%s  lastL=%s' % (
        sd.armed, '%.0f' % (sg * sd.P0) if sd.P0 else '-', '%.0f' % (sg * sd.H1) if sd.H1 else '-', sd.vflag,
        '%.0f' % (sg * sd.lastL) if sd.lastL else '-'))
    if sd.R:
        lo_r, hi_r = (sg * sd.R[0], sg * sd.R[1]) if sg > 0 else (sg * sd.R[1], sg * sd.R[0])
        lv = sg * sd.entry_level()
        st = sg * sd.stop_level()
        print('        4H R: %.0f ~ %.0f (폭 %.2f%%, 확정 %s)  유효=%s 훼손=%s  진입레벨 %.0f  손절 %.0f' % (
            lo_r, hi_r, sd.R[2] / abs(sd.R[0]) * 100, F.ts(data.h_ot[sd.R[3]]), sd.r_valid(data.LAST), sd.R_broken, lv, st))
    else:
        print('        4H R: 없음')
opn = [t for t in trades if t['result'] == 'open']
print('\n보유 포지션: ' + ('없음' if not opn else '%s 진입 %s @%.0f' % ('L' if opn[0]['side'].s > 0 else 'S', F.ts(data.h_ot[opn[0]['t0']]), opn[0]['side'].s * opn[0]['entry'])))
print('\n최근 이벤트:')
for t, sg, ev, d in best['events'][-12:]:
    print('  %s  %s  %s' % (F.ts(data.h_ot[t]), 'LONG ' if sg > 0 else 'SHORT', ev))
print('\n저장: fib_sweep.csv / fib_trades.csv')
