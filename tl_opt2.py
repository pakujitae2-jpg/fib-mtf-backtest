# -*- coding: utf-8 -*-
# 2차 최적화: 래칫 트레일 + MA200 국면 필터 추가, 연도별 일관성 기준으로 선정
import csv, sys, time, random
from tl_engine import build, load_csv

sys.stdout.reconfigure(encoding='utf-8')

START = '2023-02-01'
POS, LEV, SEED = 0.30, 10, 10000.0
YEARS = ['2023', '2024', '2025', '2026']

CFG = {'1d': {'N': [60, 90], 'k': [2, 3]}, '4h': {'N': [180, 360], 'k': [3, 5]}}
ZONES = [0.01, 0.02, 0.03]
VMODES = ['low', 'close']
SBUFS = [0.01, 0.02]
EXITS = ['tp20t', 'trail', 'half']
RATCHETS = [None, 0.10, 0.20]
FILTERS = ['none', 'ma200']

ENG = {tf: build(tf, START) for tf in CFG}

# 일봉 MA200 (해당 날짜의 "전날" 종가 기준 -> 장중 신호에도 선행편향 없음)
D = load_csv('btcusdt_1d.csv')
ma_by_day = {}
s = 0.0
for i, b in enumerate(D):
    s += b[4]
    if i >= 200:
        s -= D[i - 200][4]
    if i >= 199:
        ma_by_day[time.strftime('%Y-%m-%d', time.gmtime(b[0] / 1000 + 86400))] = (s / 200, b[4])
# ma_by_day[date] = (전날까지 MA200, 전날 종가)


def regime_ok(e, i):
    d = e.label[i][:10]
    if d not in ma_by_day:
        return False
    ma, c = ma_by_day[d]
    return c > ma


def yearly(e, trades):
    out = {}
    for y in YEARS:
        ts = [t for t in trades if e.label[t['i']][:4] == y and t['res'] != 'open']
        gp = sum(t['pm'] for t in ts if t['pm'] > 0)
        gl = -sum(t['pm'] for t in ts if t['pm'] <= 0)
        ret = 1.0
        for t in ts:
            ret *= 1 + POS * t['pm'] / 100
        out[y] = {'n': len(ts), 'pf': (gp / gl) if gl > 0 else (9.99 if gp > 0 else 0.0),
                  'ret': (ret - 1) * 100, 'wr': (sum(1 for t in ts if t['pm'] > 0) / len(ts) * 100) if ts else 0.0}
    return out


rows = []
t0 = time.time()
for tf, cfg in CFG.items():
    e = ENG[tf]
    for N in cfg['N']:
        for k in cfg['k']:
            for vm in VMODES:
                for z in ZONES:
                    sigs_all = e.signals(N, k, z, vm)
                    for flt in FILTERS:
                        sigs = sigs_all if flt == 'none' else [(i, tl) for i, tl in sigs_all if regime_ok(e, i)]
                        for sb in SBUFS:
                            for ex in EXITS:
                                for rc in RATCHETS:
                                    f = e.simulate(sigs, ex, sb, POS, LEV, SEED, ratchet=rc)
                                    yr = yearly(e, f['trades'])
                                    ys = [yr[y] for y in YEARS if yr[y]['n'] >= 3]
                                    rows.append({'tf': tf, 'N': N, 'k': k, 'valid': vm, 'zone': z, 'filter': flt,
                                                 'sbuf': sb, 'exit': ex, 'ratchet': rc or 0.0, 'sig': len(sigs),
                                                 'full': f, 'yr': yr,
                                                 'pos_years': sum(1 for y in ys if y['pf'] > 1),
                                                 'n_years': len(ys),
                                                 'min_year': min((y['ret'] for y in ys), default=-999)})
print('조합 %d개 계산 완료 (%.1fs)' % (len(rows), time.time() - t0))

with open('tl_opt2_sweep.csv', 'w', newline='', encoding='utf-8-sig') as fh:
    w = csv.writer(fh)
    w.writerow(['tf', 'N', 'k', 'valid', 'zone', 'filter', 'sbuf', 'exit', 'ratchet', 'sig', 'n', 'wr', 'pf',
                'pnl_m', 'ret', 'mdd', 'worst', 'hold', 'pos_years', 'n_years', 'min_year'] +
               ['%s_%s' % (y, x) for y in YEARS for x in ('n', 'pf', 'ret')])
    for r in rows:
        f = r['full']
        w.writerow([r['tf'], r['N'], r['k'], r['valid'], r['zone'], r['filter'], r['sbuf'], r['exit'], r['ratchet'],
                    r['sig'], f['n'], '%.1f' % f['wr'], '%.2f' % f['pf'], '%.1f' % f['pnl_m'], '%.1f' % f['ret'],
                    '%.1f' % f['mdd'], f['worst'], '%.1f' % f['hold'], r['pos_years'], r['n_years'],
                    '%.1f' % r['min_year']] +
                   [('%d' % r['yr'][y]['n'] if x == 'n' else '%.2f' % r['yr'][y][x]) for y in YEARS for x in ('n', 'pf', 'ret')])


def median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0.0


ok = [r for r in rows if r['full']['n'] >= 20]
print('\n' + '=' * 150)
print('요인별 요약 (전체 거래 20건 이상 %d개 조합, 30%% 투입 %dx)  |  "양수연도" = PF>1 인 연도 수 / 거래 3건 이상인 연도 수' % (len(ok), LEV))
print('=' * 150)
print('%-16s %4s | %9s %7s %7s %7s | %10s %10s' % ('요인', '조합', '수익중앙%', '승률', 'PF중앙', 'MDD중앙', '양수연도평균', '4년전부양수'))
print('-' * 150)
for name, key in (('타임프레임', 'tf'), ('청산', 'exit'), ('래칫', 'ratchet'), ('필터', 'filter'), ('유효', 'valid'), ('zone', 'zone'), ('sbuf', 'sbuf')):
    for v in sorted(set(r[key] for r in ok), key=str):
        rs = [r for r in ok if r[key] == v]
        print('%-16s %4d | %+9.1f %7.1f %7.2f %7.1f | %10.2f %9d개' % (
            '%s=%s' % (name, v), len(rs), median([r['full']['ret'] for r in rs]),
            sum(r['full']['wr'] for r in rs) / len(rs), median([r['full']['pf'] for r in rs]),
            median([r['full']['mdd'] for r in rs]), sum(r['pos_years'] for r in rs) / len(rs),
            sum(1 for r in rs if r['pos_years'] == r['n_years'] and r['n_years'] >= 3)))
    print('-' * 150)


def hdr():
    print('%-2s %3s %1s %-5s %2s %-5s %2s %-5s %4s %5s | %4s %5s %5s %7s %5s %4s | %s' % (
        'tf', 'N', 'k', 'valid', 'zn', 'filt', 'sb', 'exit', '래칫', '신호',
        '거래', '승률', 'PF', '수익률%', 'MDD', '연패', '연도별 거래/PF/수익률   2023 | 2024 | 2025 | 2026'))
    print('-' * 150)


def line(r):
    f = r['full']
    ys = ' | '.join('%3d %4.2f %+6.0f' % (r['yr'][y]['n'], min(r['yr'][y]['pf'], 9.99), r['yr'][y]['ret']) for y in YEARS)
    print('%-2s %3d %1d %-5s %2.0f %-5s %2.0f %-5s %4.0f %5d | %4d %5.1f %5.2f %+7.1f %5.1f %4d | %s' % (
        r['tf'], r['N'], r['k'], r['valid'], r['zone'] * 100, r['filter'], r['sbuf'] * 100, r['exit'],
        r['ratchet'] * 100, r['sig'], f['n'], f['wr'], min(f['pf'], 9.99), f['ret'], f['mdd'], f['worst'], ys))


robust = [r for r in ok if r['n_years'] >= 3 and r['pos_years'] == r['n_years']]
print('\n' + '=' * 150)
print('모든 연도 PF>1 인 조합: %d개 / %d개  (최악 연도 수익률 순)' % (len(robust), len(ok)))
print('=' * 150)
hdr()
for r in sorted(robust, key=lambda r: -r['min_year'])[:20]:
    line(r)

print('\n' + '=' * 150)
print('최악 연도 수익률 기준 상위 15 (전체)')
print('=' * 150)
hdr()
for r in sorted(ok, key=lambda r: (-r['pos_years'], -r['min_year']))[:15]:
    line(r)

print('\n' + '=' * 150)
print('전체 수익률 상위 10 (참고용 - 과최적화 가능성 높음)')
print('=' * 150)
hdr()
for r in sorted(ok, key=lambda r: -r['full']['ret'])[:10]:
    line(r)

# ---------------------------------------------------------------- 추천 조합
pool = robust if robust else ok
best = max(pool, key=lambda r: (r['pos_years'], r['min_year']))
e = ENG[best['tf']]
sigs = e.signals(best['N'], best['k'], best['zone'], best['valid'])
if best['filter'] == 'ma200':
    sigs = [(i, tl) for i, tl in sigs if regime_ok(e, i)]
rc = best['ratchet'] or None
full = best['full']
print('\n' + '=' * 150)
print('추천 조합: %s N=%d k=%d valid=%s zone=%.0f%% filter=%s sbuf=%.0f%% exit=%s ratchet=%.0f%%  |  30%% 투입 %dx' % (
    best['tf'], best['N'], best['k'], best['valid'], best['zone'] * 100, best['filter'], best['sbuf'] * 100,
    best['exit'], best['ratchet'] * 100, LEV))
print('=' * 150)
print('거래 %d  승 %d (TP %d / 익손 %d)  패 %d (손절 %d / 청산 %d)  미결 %d' % (
    full['n'], full['tp'] + full['sp'], full['tp'], full['sp'], full['sl'] + full['liq'], full['sl'], full['liq'], full['open']))
print('승률 %.1f%%  평균승 %+.1f%%  평균패 %+.1f%% (마진)  PF %.2f  거래당 %+.1f%%  손절폭 %.2f%%  평균보유 %.1f일' % (
    full['wr'], full['avg_win'], full['avg_loss'], full['pf'], full['pnl_m'], full['risk'], full['hold']))
print('최종자산 $%.0f (%+.1f%%)  MDD %.1f%%  최대연패 %d' % (full['eq'], full['ret'], full['mdd'], full['worst']))
print('\n연도별:')
for y in YEARS:
    yr = best['yr'][y]
    print('  %s: 거래 %3d  승률 %5.1f%%  PF %.2f  계좌수익률 %+.1f%%' % (y, yr['n'], yr['wr'], yr['pf'], yr['ret']))

print('\n거래 내역:')
print('%-16s %-16s %-4s %9s %9s %9s %7s %8s %6s  %s' % (
    '진입', '청산', '결과', '진입가', '초기손절', '청산가', '손절폭%', '마진손익%', '보유일', '체결'))
print('-' * 150)
for t in full['trades']:
    fl = ' '.join('%s@%.0f' % (k, px) for _, px, _, k in t['fills'])
    print('%-16s %-16s %-4s %9.0f %9.0f %9.0f %7.2f %+8.1f %6.1f  %s' % (
        e.label[t['i']], e.label[t['j']], t['res'], t['entry'], t['stop'], t['exit'], t['risk'], t['pm'],
        (t['j'] - t['i']) * e.hours / 24, fl))
with open('tl_opt2_trades.csv', 'w', newline='', encoding='utf-8-sig') as fh:
    w = csv.writer(fh)
    w.writerow(['entry', 'exit_time', 'result', 'entry_px', 'init_stop', 'exit_px', 'risk_pct',
                'margin_pnl_pct', 'hold_days', 'p1', 'p2', 'fills'])
    for t in full['trades']:
        w.writerow([e.label[t['i']], e.label[t['j']], t['res'], '%.2f' % t['entry'], '%.2f' % t['stop'],
                    '%.2f' % t['exit'], '%.3f' % t['risk'], '%.2f' % t['pm'],
                    '%.2f' % ((t['j'] - t['i']) * e.hours / 24), e.label[t['tl'][0]], e.label[t['tl'][1]],
                    ' '.join('%s@%.0f' % (k, px) for _, px, _, k in t['fills'])])

print('\n' + '=' * 150)
print('투입 비중 x 배율 (추천 조합)')
print('=' * 150)
print('%-6s %4s | %4s %6s %8s | %10s %8s %6s %4s %4s | %s' % (
    '투입', 'lev', '거래', '승률%', '마진손익%', '최종자산$', '수익률%', 'MDD%', '연패', '청산', '실효배율'))
print('-' * 150)
for pos in (0.05, 0.10, 0.15, 0.20, 0.30):
    for lev in (5, 10, 20):
        r = e.simulate(sigs, best['exit'], best['sbuf'], pos, lev, SEED, ratchet=rc)
        print('%5.0f%% %3dx | %4d %6.1f %8.1f | %10.0f %8.1f %6.1f %4d %4d | %.1fx' % (
            pos * 100, lev, r['n'], r['wr'], r['pnl_m'], r['eq'], r['ret'], r['mdd'], r['worst'], r['liq'], pos * lev))
    print('-' * 150)

pnls = [t['pm'] for t in full['trades'] if t['res'] != 'open']
random.seed(11)
print('\n부트스트랩 5000회 (거래 %d건 리샘플, %dx):' % (len(pnls), LEV))
for pos in (0.10, 0.20, 0.30):
    finals, mdds = [], []
    for _ in range(5000):
        eq, peak, mdd = 1.0, 1.0, 0.0
        for pm in random.choices(pnls, k=len(pnls)):
            eq *= max(0.0, 1 + pos * pm / 100)
            peak = max(peak, eq)
            mdd = max(mdd, 1 - eq / peak)
        finals.append(eq)
        mdds.append(mdd)
    finals.sort()
    mdds.sort()
    q = lambda xs, p: xs[int(len(xs) * p)]
    print('  투입 %3.0f%%: 최종배수 5%%분위 %.2fx / 중앙값 %.2fx / 95%%분위 %.2fx | 손실확률 %.0f%% | MDD 중앙값 %.0f%% / 95%%분위 %.0f%%' % (
        pos * 100, q(finals, 0.05), q(finals, 0.5), q(finals, 0.95),
        sum(1 for f in finals if f < 1) / len(finals) * 100, q(mdds, 0.5) * 100, q(mdds, 0.95) * 100))
print('\n저장: tl_opt2_sweep.csv / tl_opt2_trades.csv')
