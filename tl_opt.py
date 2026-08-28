# -*- coding: utf-8 -*-
# 추세선 전략 최적화 - 일봉 vs 4시간봉, 5가지 청산 모드
#   IS  (최적화) : 2023-02-01 ~ 2024-12-31
#   OOS (검증)   : 2025-01-01 ~ 현재
import csv, sys, time, random
from tl_engine import build

sys.stdout.reconfigure(encoding='utf-8')

START = '2023-02-01'
OOS = '2025-01-01'
POS, LEV = 0.30, 10
SEED = 10000.0

CFG = {
    '1d': {'N': [30, 60, 90], 'k': [2, 3]},
    '4h': {'N': [90, 180, 360], 'k': [3, 5]},     # 15일 / 30일 / 60일
}
ZONES = [0.01, 0.02, 0.03]
VMODES = ['low', 'close']
SBUFS = [0.01, 0.02]
EXITS = ['tp10f', 'tp10t', 'tp20t', 'trail', 'half']

t0 = time.time()
ENG = {tf: build(tf, START) for tf in CFG}
for tf, e in ENG.items():
    print('%s: 봉 %d개  %s ~ %s  (신호 시작 %s)' % (tf, e.n, e.label[0], e.label[e.LAST], e.label[e.START_I]))
print('5분봉 %d개 로드, %.1fs' % (len(ENG['1d'].f_ot), time.time() - t0))

rows = []
t0 = time.time()
for tf, cfg in CFG.items():
    e = ENG[tf]
    oos_i = next(i for i in range(e.n) if e.label[i][:10] >= OOS)
    for N in cfg['N']:
        for k in cfg['k']:
            for vm in VMODES:
                for z in ZONES:
                    sigs = e.signals(N, k, z, vm)
                    for sb in SBUFS:
                        for ex in EXITS:
                            a = e.simulate(sigs, ex, sb, POS, LEV, SEED, hi_i=oos_i - 1)
                            b = e.simulate(sigs, ex, sb, POS, LEV, SEED, lo_i=oos_i)
                            f = e.simulate(sigs, ex, sb, POS, LEV, SEED)
                            rows.append({'tf': tf, 'N': N, 'k': k, 'valid': vm, 'zone': z, 'sbuf': sb,
                                         'exit': ex, 'sig': len(sigs), 'is': a, 'oos': b, 'full': f})
print('조합 %d개 계산 완료 (%.1fs)' % (len(rows), time.time() - t0))

with open('tl_opt_sweep.csv', 'w', newline='', encoding='utf-8-sig') as fh:
    w = csv.writer(fh)
    keys = ['n', 'wr', 'pnl_m', 'pf', 'ret', 'mdd', 'worst', 'hold', 'liq']
    w.writerow(['tf', 'N', 'k', 'valid', 'zone', 'sbuf', 'exit', 'sig'] +
               ['is_' + x for x in keys] + ['oos_' + x for x in keys] + ['full_' + x for x in keys])
    for r in rows:
        w.writerow([r['tf'], r['N'], r['k'], r['valid'], r['zone'], r['sbuf'], r['exit'], r['sig']] +
                   ['%.3f' % r[p][x] for p in ('is', 'oos', 'full') for x in keys])


def hdr():
    print('%-2s %3s %1s %-5s %2s %2s %-5s %4s | %-30s | %-30s | %-30s' % (
        'tf', 'N', 'k', 'valid', 'zn', 'sb', 'exit', '신호',
        'IS  거래/승률/PF/수익률/MDD', 'OOS 거래/승률/PF/수익률/MDD', '전체 거래/승률/PF/수익률/MDD'))
    print('-' * 140)


def cell(r):
    return '%3d %5.1f %4.2f %+7.1f %5.1f' % (r['n'], r['wr'], min(r['pf'], 9.99), r['ret'], r['mdd'])


def line(r):
    print('%-2s %3d %1d %-5s %2.0f %2.0f %-5s %4d | %-30s | %-30s | %-30s' % (
        r['tf'], r['N'], r['k'], r['valid'], r['zone'] * 100, r['sbuf'] * 100, r['exit'], r['sig'],
        cell(r['is']), cell(r['oos']), cell(r['full'])))


def median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0.0


print('\n' + '=' * 140)
print('청산 모드별 / 타임프레임별 요약 (IS 거래 15건 이상 조합, 30%% 투입 %dx)' % LEV)
print('=' * 140)
print('%-4s %-6s %4s | %8s %8s %8s | %8s %8s %8s | %8s' % (
    'tf', 'exit', '조합', 'IS수익중앙', 'IS승률', 'IS PF', 'OOS수익중앙', 'OOS승률', 'OOS PF', 'OOS양수비율'))
print('-' * 140)
for tf in CFG:
    for ex in EXITS:
        rs = [r for r in rows if r['tf'] == tf and r['exit'] == ex and r['is']['n'] >= 15]
        if not rs:
            continue
        print('%-4s %-6s %4d | %+8.1f %8.1f %8.2f | %+8.1f %8.1f %8.2f | %7.0f%%' % (
            tf, ex, len(rs), median([r['is']['ret'] for r in rs]),
            sum(r['is']['wr'] for r in rs) / len(rs), median([r['is']['pf'] for r in rs]),
            median([r['oos']['ret'] for r in rs]), sum(r['oos']['wr'] for r in rs) / len(rs),
            median([r['oos']['pf'] for r in rs]),
            sum(1 for r in rs if r['oos']['ret'] > 0) / len(rs) * 100))
    print('-' * 140)

ok = [r for r in rows if r['is']['n'] >= 15]
print('\n' + '=' * 140)
print('IS 수익률 상위 15개 -> OOS 성적 (과최적화 점검)')
print('=' * 140)
hdr()
for r in sorted(ok, key=lambda r: -r['is']['ret'])[:15]:
    line(r)

both = [r for r in ok if r['oos']['n'] >= 8 and r['is']['pf'] > 1 and r['oos']['pf'] > 1]
print('\n' + '=' * 140)
print('IS/OOS 모두 PF>1 인 조합: %d개 / %d개   (min(IS,OOS) 수익률 순 상위 15)' % (len(both), len(ok)))
print('=' * 140)
hdr()
both.sort(key=lambda r: -min(r['is']['ret'], r['oos']['ret']))
for r in both[:15]:
    line(r)

# ---------------------------------------------------------------- 추천 조합 상세
if both:
    best = both[0]
else:
    best = max(ok, key=lambda r: r['full']['ret'])
    print('\n(IS/OOS 모두 양수인 조합 없음 -> 전체 기간 최고 조합을 표시)')
e = ENG[best['tf']]
sigs = e.signals(best['N'], best['k'], best['zone'], best['valid'])
full = best['full']
print('\n' + '=' * 140)
print('추천 조합: %s  N=%d k=%d valid=%s zone=%.0f%% sbuf=%.0f%% exit=%s  |  30%% 투입 %dx' % (
    best['tf'], best['N'], best['k'], best['valid'], best['zone'] * 100, best['sbuf'] * 100, best['exit'], LEV))
print('=' * 140)
print('전체: 거래 %d  승 %d (TP %d / 익손 %d)  패 %d (손절 %d / 청산 %d)  미결 %d' % (
    full['n'], full['tp'] + full['sp'], full['tp'], full['sp'], full['sl'] + full['liq'], full['sl'], full['liq'], full['open']))
print('      승률 %.1f%%  평균승 %+.1f%%  평균패 %+.1f%%  (마진 기준)  PF %.2f  거래당 %+.1f%%  손절폭 %.2f%%  보유 %.1f일' % (
    full['wr'], full['avg_win'], full['avg_loss'], full['pf'], full['pnl_m'], full['risk'], full['hold']))
print('      최종자산 $%.0f (%+.1f%%)  MDD %.1f%%  최대연패 %d' % (full['eq'], full['ret'], full['mdd'], full['worst']))

print('\n연도별:')
for y in ('2023', '2024', '2025', '2026'):
    ts = [t for t in full['trades'] if e.label[t['i']][:4] == y and t['res'] != 'open']
    if ts:
        w = sum(1 for t in ts if t['pm'] > 0)
        print('  %s: 거래 %3d  승 %3d  패 %3d  승률 %5.1f%%  마진손익 합계 %+.0f%%  최대 %+.0f%% / 최소 %+.0f%%' % (
            y, len(ts), w, len(ts) - w, w / len(ts) * 100, sum(t['pm'] for t in ts),
            max(t['pm'] for t in ts), min(t['pm'] for t in ts)))

print('\n거래 내역 (%s):' % ('전체' if full['n'] <= 60 else '최근 40건'))
print('%-16s %-16s %-4s %9s %9s %9s %7s %8s %6s  %s' % (
    '진입', '청산', '결과', '진입가', '초기손절', '청산가', '손절폭%', '마진손익%', '보유일', '체결'))
print('-' * 140)
for t in full['trades'][-40:] if full['n'] > 60 else full['trades']:
    fl = ' '.join('%s@%.0f' % (k, px) for _, px, _, k in t['fills'])
    print('%-16s %-16s %-4s %9.0f %9.0f %9.0f %7.2f %+8.1f %6.1f  %s' % (
        e.label[t['i']], e.label[t['j']], t['res'], t['entry'], t['stop'], t['exit'], t['risk'], t['pm'],
        (t['j'] - t['i']) * e.hours / 24, fl))

with open('tl_opt_trades.csv', 'w', newline='', encoding='utf-8-sig') as fh:
    w = csv.writer(fh)
    w.writerow(['entry', 'exit_time', 'result', 'entry_px', 'init_stop', 'exit_px', 'risk_pct',
                'margin_pnl_pct', 'hold_days', 'p1', 'p2', 'fills'])
    for t in full['trades']:
        w.writerow([e.label[t['i']], e.label[t['j']], t['res'], '%.2f' % t['entry'], '%.2f' % t['stop'],
                    '%.2f' % t['exit'], '%.3f' % t['risk'], '%.2f' % t['pm'],
                    '%.2f' % ((t['j'] - t['i']) * e.hours / 24), e.label[t['tl'][0]], e.label[t['tl'][1]],
                    ' '.join('%s@%.0f' % (k, px) for _, px, _, k in t['fills'])])

# ---------------------------------------------------------------- 사이징
print('\n' + '=' * 140)
print('투입 비중 x 배율 (추천 조합, 전체 기간)')
print('=' * 140)
print('%-6s %4s | %4s %6s %8s | %10s %8s %6s %4s %4s | %s' % (
    '투입', 'lev', '거래', '승률%', '마진손익%', '최종자산$', '수익률%', 'MDD%', '연패', '청산', '실효배율'))
print('-' * 140)
for pos in (0.05, 0.10, 0.15, 0.20, 0.30):
    for lev in (5, 10, 20):
        r = e.simulate(sigs, best['exit'], best['sbuf'], pos, lev, SEED)
        print('%5.0f%% %3dx | %4d %6.1f %8.1f | %10.0f %8.1f %6.1f %4d %4d | %.1fx' % (
            pos * 100, lev, r['n'], r['wr'], r['pnl_m'], r['eq'], r['ret'], r['mdd'], r['worst'], r['liq'], pos * lev))
    print('-' * 140)

# ---------------------------------------------------------------- 부트스트랩
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

print('\n저장: tl_opt_sweep.csv (전체 조합) / tl_opt_trades.csv (추천 조합 거래내역)')
