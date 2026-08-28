# -*- coding: utf-8 -*-
# 저점 미훼손 리테스트(Higher-Low Retest) 패턴 최적화 - 일봉
#
#   기준 저점 L : 좌우 k봉보다 낮은 피벗 저가 (우측 k봉 확정 후에만 사용)
#   리테스트 j  : L 형성 후 GAP_MIN(5)일 이상 ~ gapmax일 이내,
#                 그 사이 L 이 한 번도 깨지지 않았고(모든 저가 >= L),
#                 j일 저가가 [L, L*(1+zone)] 안으로 눌리고, 종가는 L 위에서 마감
#                 (옵션) L 이후 j 이전에 L*(1+bounce) 이상 반등이 있었어야 함
#   진입        : close   = 리테스트 봉 종가
#                 confirm = 이후 3일 내 리테스트 봉 고가를 종가로 돌파한 날 종가
#   손절        : L*(1-buf)  (고정)
#   청산        : tp10f / tp15t / tp20t / trail(래칫) / half(절반익절+본절+래칫)
#   예시        : 2026-08-01 L=62,275 -> 2026-08-17 저가 62,751(+0.76%) -> 종가 64,532 진입
import csv, sys, time, random
from bisect import bisect_left, bisect_right
from tl_engine import build

sys.stdout.reconfigure(encoding='utf-8')

START = '2023-01-15'
GAP_MIN = 5
POS, LEV, SEED = 0.30, 10, 10000.0
YEARS = ['2023', '2024', '2025', '2026']

KS = [2, 3, 5]
GAPMAX = [30, 60]
ZONES = [0.005, 0.01, 0.02, 0.03]
BOUNCES = [0.0, 0.03]
ENTRIES = ['close', 'confirm']
BUFS = [0.005, 0.01]
EXITS = [('tp10f', None), ('tp20t', None), ('trail', 0.10), ('trail', 0.15), ('half', 0.10)]

e = build('1d', START)
lo, hi, cl, op, lab = e.lo, e.hi, e.cl, e.op, e.label
EPS = 1e-9


def setups(k, gapmax, zone, bounce):
    """리테스트 봉 j 와 기준 저점 L 목록. 같은 j 에 여러 L 이 있으면 가장 낮은 L."""
    P = e.pivots(k)
    out = []
    for j in range(e.START_I, e.LAST + 1):
        cand = P[bisect_left(P, j - gapmax):bisect_right(P, j - GAP_MIN)]
        best = None
        for T in cand:
            if T + k > j:
                continue
            L = lo[T]
            if lo[j] < L - EPS or lo[j] > L * (1 + zone) + EPS or cl[j] <= L:
                continue
            if min(lo[T + 1:j]) < L - EPS:
                continue
            if bounce and max(hi[T + 1:j]) < L * (1 + bounce) - EPS:
                continue
            if best is None or L < best[1]:
                best = (T, L)
        if best:
            out.append((j, best[0], best[1]))
    return out


def to_signals(sets, entry, buf):
    sigs = []
    for j, T, L in sets:
        stop = L * (1 - buf)
        if entry == 'close':
            sigs.append((j, stop, T, L))
            continue
        for m in range(j + 1, min(j + 4, e.LAST + 1)):
            if lo[m] < L - EPS:
                break
            if cl[m] > hi[j]:
                sigs.append((m, stop, T, L))
                break
    return sigs


def yearly(trades):
    out = {}
    for y in YEARS:
        ts = [t for t in trades if lab[t['i']][:4] == y and t['res'] != 'open']
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
for k in KS:
    for gm in GAPMAX:
        for z in ZONES:
            for b in BOUNCES:
                sets = setups(k, gm, z, b)
                for en in ENTRIES:
                    for buf in BUFS:
                        sigs = to_signals(sets, en, buf)
                        for ex, rc in EXITS:
                            f = e.simulate([(i, st) for i, st, T, L in sigs], ex, 0.0, POS, LEV, SEED, ratchet=rc)
                            yr = yearly(f['trades'])
                            ys = [yr[y] for y in YEARS if yr[y]['n'] >= 3]
                            rows.append({'k': k, 'gapmax': gm, 'zone': z, 'bounce': b, 'entry': en, 'buf': buf,
                                         'exit': ex, 'ratchet': rc or 0.0, 'setups': len(sets), 'sig': len(sigs),
                                         'sigs': sigs, 'full': f, 'yr': yr,
                                         'pos_years': sum(1 for y in ys if y['pf'] > 1), 'n_years': len(ys),
                                         'min_year': min((y['ret'] for y in ys), default=-999)})
print('조합 %d개 계산 (%.1fs)  |  데이터 %s ~ %s' % (len(rows), time.time() - t0, lab[e.START_I], lab[e.LAST]))

with open('hl_retest_sweep.csv', 'w', newline='', encoding='utf-8-sig') as fh:
    w = csv.writer(fh)
    w.writerow(['k', 'gapmax', 'zone', 'bounce', 'entry', 'buf', 'exit', 'ratchet', 'setups', 'sig', 'n', 'wr', 'pf',
                'pnl_m', 'avg_win', 'avg_loss', 'risk', 'ret', 'mdd', 'worst', 'hold', 'pos_years', 'n_years', 'min_year'] +
               ['%s_%s' % (y, x) for y in YEARS for x in ('n', 'pf', 'ret')])
    for r in rows:
        f = r['full']
        w.writerow([r['k'], r['gapmax'], r['zone'], r['bounce'], r['entry'], r['buf'], r['exit'], r['ratchet'],
                    r['setups'], r['sig'], f['n'], '%.1f' % f['wr'], '%.2f' % f['pf'], '%.1f' % f['pnl_m'],
                    '%.1f' % f['avg_win'], '%.1f' % f['avg_loss'], '%.2f' % f['risk'], '%.1f' % f['ret'],
                    '%.1f' % f['mdd'], f['worst'], '%.1f' % f['hold'], r['pos_years'], r['n_years'], '%.1f' % r['min_year']] +
                   [('%d' % r['yr'][y]['n'] if x == 'n' else '%.2f' % r['yr'][y][x]) for y in YEARS for x in ('n', 'pf', 'ret')])


def median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0.0


ok = [r for r in rows if r['full']['n'] >= 15]
print('\n' + '=' * 150)
print('요인별 요약 (거래 15건 이상 %d개 조합, 30%% 투입 %dx)   양수연도 = PF>1 연도 수(거래 3건 이상 연도 기준)' % (len(ok), LEV))
print('=' * 150)
print('%-18s %4s | %9s %7s %7s %7s %8s | %10s %10s' % ('요인', '조합', '수익중앙%', '승률', 'PF중앙', 'MDD중앙', '거래수중앙', '양수연도평균', '전연도양수'))
print('-' * 150)
for name, key in (('피벗 k', 'k'), ('최대간격', 'gapmax'), ('zone', 'zone'), ('반등조건', 'bounce'), ('진입', 'entry'),
                  ('손절버퍼', 'buf'), ('청산', 'exit'), ('래칫', 'ratchet')):
    for v in sorted(set(r[key] for r in ok), key=str):
        rs = [r for r in ok if r[key] == v]
        print('%-18s %4d | %+9.1f %7.1f %7.2f %7.1f %8d | %10.2f %9d개' % (
            '%s=%s' % (name, v), len(rs), median([r['full']['ret'] for r in rs]),
            sum(r['full']['wr'] for r in rs) / len(rs), median([r['full']['pf'] for r in rs]),
            median([r['full']['mdd'] for r in rs]), median([r['full']['n'] for r in rs]),
            sum(r['pos_years'] for r in rs) / len(rs),
            sum(1 for r in rs if r['n_years'] >= 3 and r['pos_years'] == r['n_years'])))
    print('-' * 150)


def hdr():
    print('%1s %3s %4s %4s %-7s %3s %-5s %4s %4s | %4s %5s %5s %6s %6s %7s %5s %4s | %s' % (
        'k', 'gap', 'zone', '반등', '진입', 'buf', 'exit', '래칫', '셋업',
        '거래', '승률', 'PF', '평균승', '평균패', '수익률%', 'MDD', '연패', '연도별 거래/PF/수익률  2023 | 2024 | 2025 | 2026'))
    print('-' * 150)


def line(r):
    f = r['full']
    ys = ' | '.join('%3d %4.2f %+5.0f' % (r['yr'][y]['n'], min(r['yr'][y]['pf'], 9.99), r['yr'][y]['ret']) for y in YEARS)
    print('%1d %3d %3.1f%% %3.0f%% %-7s %3.1f %-5s %4.0f %4d | %4d %5.1f %5.2f %+6.0f %+6.0f %+7.1f %5.1f %4d | %s' % (
        r['k'], r['gapmax'], r['zone'] * 100, r['bounce'] * 100, r['entry'], r['buf'] * 100, r['exit'],
        r['ratchet'] * 100, r['setups'], f['n'], f['wr'], min(f['pf'], 9.99), f['avg_win'], f['avg_loss'],
        f['ret'], f['mdd'], f['worst'], ys))


robust = [r for r in ok if r['n_years'] >= 3 and r['pos_years'] == r['n_years']]
print('\n' + '=' * 150)
print('모든 연도 PF>1 인 조합: %d개 / %d개   (최악 연도 수익률 순 상위 20)' % (len(robust), len(ok)))
print('=' * 150)
hdr()
for r in sorted(robust, key=lambda r: -r['min_year'])[:20]:
    line(r)

print('\n' + '=' * 150)
print('전체 PF 상위 15 (거래 15건 이상)')
print('=' * 150)
hdr()
for r in sorted(ok, key=lambda r: -r['full']['pf'])[:15]:
    line(r)

# ---------------------------------------------------------------- 추천 조합
pool = robust if robust else ok
best = max(pool, key=lambda r: (r['pos_years'], r['full']['pf'] * min(1.0, r['full']['n'] / 30)))
f = best['full']
print('\n' + '=' * 150)
print('추천 조합: k=%d 최대간격 %d일 zone %.1f%% 반등 %.0f%% 진입=%s 손절버퍼 %.1f%% 청산=%s 래칫 %.0f%%  |  30%% 투입 %dx' % (
    best['k'], best['gapmax'], best['zone'] * 100, best['bounce'] * 100, best['entry'], best['buf'] * 100,
    best['exit'], best['ratchet'] * 100, LEV))
print('=' * 150)
print('셋업 %d  거래 %d  승 %d (TP %d / 익손 %d)  패 %d  미결 %d' % (
    best['setups'], f['n'], f['tp'] + f['sp'], f['tp'], f['sp'], f['sl'] + f['liq'], f['open']))
print('승률 %.1f%%  평균승 %+.1f%%  평균패 %+.1f%% (마진)  PF %.2f  거래당 %+.1f%%  손절폭 %.2f%%  평균보유 %.1f일' % (
    f['wr'], f['avg_win'], f['avg_loss'], f['pf'], f['pnl_m'], f['risk'], f['hold']))
print('최종자산 $%.0f (%+.1f%%)  MDD %.1f%%  최대연패 %d' % (f['eq'], f['ret'], f['mdd'], f['worst']))
print('\n연도별:')
for y in YEARS:
    yr = best['yr'][y]
    print('  %s: 거래 %3d  승률 %5.1f%%  PF %.2f  계좌수익률 %+.1f%%' % (y, yr['n'], yr['wr'], yr['pf'], yr['ret']))

sigmap = {i: (T, L) for i, st, T, L in best['sigs']}
print('\n거래 내역:')
print('%-11s %-11s %-4s %8s %8s %8s %6s %7s %5s  %-11s %8s %6s  %s' % (
    '진입', '청산', '결과', '진입가', '손절', '청산가', '손절폭', '마진손익', '보유', '기준저점일', 'L', '눌림%', '체결'))
print('-' * 150)
for t in f['trades']:
    T, L = sigmap[t['i']]
    j = t['i'] if best['entry'] == 'close' else next(x for x in range(t['i'], T, -1) if lo[x] <= L * (1 + best['zone']) + EPS)
    fl = ' '.join('%s@%.0f' % (k_, px) for _, px, _, k_ in t['fills'])
    print('%-11s %-11s %-4s %8.0f %8.0f %8.0f %5.2f%% %+7.1f %5d  %-11s %8.0f %+5.2f  %s' % (
        lab[t['i']], lab[t['j']], t['res'], t['entry'], t['stop'], t['exit'], t['risk'], t['pm'], t['j'] - t['i'],
        lab[T], L, (lo[j] / L - 1) * 100, fl))
with open('hl_retest_trades.csv', 'w', newline='', encoding='utf-8-sig') as fh:
    w = csv.writer(fh)
    w.writerow(['entry', 'exit_time', 'result', 'entry_px', 'stop', 'exit_px', 'risk_pct', 'margin_pnl_pct',
                'hold_days', 'ref_low_day', 'L', 'fills'])
    for t in f['trades']:
        T, L = sigmap[t['i']]
        w.writerow([lab[t['i']], lab[t['j']], t['res'], '%.2f' % t['entry'], '%.2f' % t['stop'], '%.2f' % t['exit'],
                    '%.3f' % t['risk'], '%.2f' % t['pm'], t['j'] - t['i'], lab[T], '%.2f' % L,
                    ' '.join('%s@%.0f' % (k_, px) for _, px, _, k_ in t['fills'])])

print('\n' + '=' * 150)
print('투입 비중 x 배율 (추천 조합)')
print('=' * 150)
print('%-6s %4s | %4s %6s %8s | %10s %8s %6s %4s %4s | %s' % (
    '투입', 'lev', '거래', '승률%', '마진손익%', '최종자산$', '수익률%', 'MDD%', '연패', '청산', '실효배율'))
print('-' * 150)
S = [(i, st) for i, st, T, L in best['sigs']]
for pos in (0.05, 0.10, 0.15, 0.20, 0.30):
    for lev in (5, 10, 20):
        r = e.simulate(S, best['exit'], 0.0, pos, lev, SEED, ratchet=best['ratchet'] or None)
        print('%5.0f%% %3dx | %4d %6.1f %8.1f | %10.0f %8.1f %6.1f %4d %4d | %.1fx' % (
            pos * 100, lev, r['n'], r['wr'], r['pnl_m'], r['eq'], r['ret'], r['mdd'], r['worst'], r['liq'], pos * lev))
    print('-' * 150)

pnls = [t['pm'] for t in f['trades'] if t['res'] != 'open']
random.seed(11)
print('\n부트스트랩 5000회 (거래 %d건, %dx):' % (len(pnls), LEV))
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
        sum(1 for x in finals if x < 1) / len(finals) * 100, q(mdds, 0.5) * 100, q(mdds, 0.95) * 100))

# ---------------------------------------------------------------- 현재 감시 상태 (봇 출력 형태)
print('\n' + '=' * 150)
print('현재 감시 상태 (%s 종가 %.0f 기준, k=%d, 최대간격 %d일, zone %.1f%%)' % (
    lab[e.LAST], cl[e.LAST], best['k'], best['gapmax'], best['zone'] * 100))
print('=' * 150)
P = e.pivots(best['k'])
now = e.LAST
active = [T for T in P if now - best['gapmax'] <= T <= now - best['k'] and min(lo[T:now + 1]) >= lo[T] - EPS]
if not active:
    print('  살아있는 기준 저점 없음')
for T in active:
    L = lo[T]
    zone_hi = L * (1 + best['zone'])
    print('  기준저점 %s  L=%.0f  리테스트 존 %.0f ~ %.0f  (현재가 대비 %+.1f%% 아래)  손절 %.0f  경과 %d일%s' % (
        lab[T], L, L, zone_hi, (zone_hi / cl[now] - 1) * 100, L * (1 - best['buf']), now - T,
        '  <- 5일 미만, 아직 대기' if now - T < GAP_MIN else ''))
print('\n저장: hl_retest_sweep.csv / hl_retest_trades.csv')
