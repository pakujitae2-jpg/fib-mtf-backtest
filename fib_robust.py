# -*- coding: utf-8 -*-
# 과최적화 점검: (1) 2019~2022 로 파라미터 선택 -> 2023~2026 검증  (2) 비용 상향 민감도  (3) 부트스트랩  (4) 이웃 파라미터
import csv, sys, random
import fib_mtf as F

sys.stdout.reconfigure(encoding='utf-8')
IS_Y, OOS_Y = ['2019', '2020', '2021', '2022'], ['2023', '2024', '2025', '2026']
KEYS = ['DMIN', 'R4', 'R_RATIO', 'ATR_MULT', 'TOL', 'BUF', 'EXIT', 'RATCHET', 'MFILT', 'STRUCT']

rows = []
seen = set()
with open('fib_sweep.csv', encoding='utf-8-sig') as f:
    for r in csv.DictReader(f):
        key = tuple(r[k] for k in KEYS)
        if key in seen:
            continue
        seen.add(key)
        def agg(ys):
            ret = 1.0
            n = 0
            pos = 0
            cnt = 0
            for y in ys:
                ny = int(r[y + '_n'])
                ret *= 1 + float(r[y + '_ret']) / 100
                n += ny
                if ny >= 3:
                    cnt += 1
                    pos += float(r[y + '_pf']) > 1
            return {'ret': (ret - 1) * 100, 'n': n, 'pos': pos, 'cnt': cnt,
                    'min': min((float(r[y + '_ret']) for y in ys if int(r[y + '_n']) >= 3), default=-999)}
        r['is'], r['oos'] = agg(IS_Y), agg(OOS_Y)
        rows.append(r)
print('조합 %d개 (중복 제거)' % len(rows))


def show(rs, title):
    print('\n' + '=' * 150)
    print(title)
    print('=' * 150)
    print('%4s %5s %4s %4s %5s %5s %-5s %4s %-3s %-5s | %-32s | %-32s' % (
        'DMIN', 'R4', 'Rrat', 'ATRx', 'TOL', 'BUF', 'EXIT', '래칫', 'M', 'STR', 'IS 2019-22: 거래/양수연도/수익률/최악', 'OOS 2023-26: 거래/양수연도/수익률/최악'))
    print('-' * 150)
    for r in rs:
        a, b = r['is'], r['oos']
        print('%4s %5s %4s %4s %5s %5s %-5s %4s %-3s %-5s | %4d  %d/%d  %+8.0f%%  %+6.0f%%      | %4d  %d/%d  %+8.0f%%  %+6.0f%%' % (
            r['DMIN'], r['R4'], r['R_RATIO'], r['ATR_MULT'], r['TOL'], r['BUF'], r['EXIT'], r['RATCHET'], r['MFILT'], r['STRUCT'],
            a['n'], a['pos'], a['cnt'], a['ret'], a['min'], b['n'], b['pos'], b['cnt'], b['ret'], b['min']))


ok = [r for r in rows if r['is']['n'] >= 20 and r['oos']['n'] >= 10]
by_cons = sorted(ok, key=lambda r: (-r['is']['pos'], -r['is']['min']))
show(by_cons[:12], '(1) IS(2019~22) 연도별 일관성 기준 상위 12 -> OOS(2023~26) 성적')
by_ret = sorted(ok, key=lambda r: -r['is']['ret'])
show(by_ret[:8], '    IS 수익률 기준 상위 8 -> OOS')
is_pos = [r for r in ok if r['is']['ret'] > 0]
print('\nIS 양수 조합 %d개 중 OOS 도 양수: %d개 (%.0f%%)   |   IS 음수 조합 %d개 중 OOS 양수: %d개' % (
    len(is_pos), sum(1 for r in is_pos if r['oos']['ret'] > 0), sum(1 for r in is_pos if r['oos']['ret'] > 0) / max(1, len(is_pos)) * 100,
    len(ok) - len(is_pos), sum(1 for r in ok if r['is']['ret'] <= 0 and r['oos']['ret'] > 0)))
top10 = by_cons[:10]
print('IS 일관성 상위 10개의 OOS: 양수 %d개 / 수익률 중앙값 %+.0f%% / 양수연도 평균 %.1f/4' % (
    sum(1 for r in top10 if r['oos']['ret'] > 0), sorted(r['oos']['ret'] for r in top10)[5], sum(r['oos']['pos'] for r in top10) / 10))

# ---------------------------------------------------------------- 이웃 파라미터 (최종 후보 주변)
BEST = dict(DMIN=0.08, R4=0.236, R_RATIO=0.1, ATR_MULT=1.0, TOL=0.003, BUF=0.003, EXIT='spec', RATCHET=0.0, MFILT='off', STRUCT='HH_HL')
print('\n' + '=' * 150)
print('(4) 최종 후보의 이웃: 한 파라미터만 바꿨을 때 (전체 기간 PF / 양수연도)')
print('=' * 150)
idx = {tuple(r[k] for k in KEYS): r for r in rows}
for k in KEYS:
    vals = sorted(set(r[k] for r in rows), key=str)
    out = []
    for v in vals:
        P = dict(BEST)
        P[k] = v
        key = tuple(str(P[kk]) for kk in KEYS)
        r = idx.get(key)
        if r:
            out.append('%s=%s: PF %.2f, %s/%s yrs, %+.0f%%' % (k, v, float(r['pf']), r['pos_years'], r['n_years'], float(r['ret'])))
    if len(out) > 1:
        print('  ' + ' | '.join(out))

# ---------------------------------------------------------------- 비용 민감도 + 부트스트랩
data = F.load_data('2019-03-01')
P = dict(BEST, DCONF=0.382, SIDES='both')
YRS = (data.h_ot[data.LAST] - data.h_ot[data.start4]) / F.D_MS / 365.25
print('\n' + '=' * 150)
print('(2) 비용 민감도 (최종 후보, 30% 투입 10x)')
print('=' * 150)
print('%-44s | %4s %6s %6s %8s %10s %6s %4s' % ('비용 가정', '거래', '승률', 'PF', '기대값%', '최종자산$', 'MDD', '연패'))
print('-' * 150)
base = (F.FEE_MAKER, F.FEE_TAKER, F.SLIP, F.FUNDING)
for name, mk, tk, sl, fd in (
        ('기본: maker .02% taker .05% slip .05% fund .01%', 0.0002, 0.0005, 0.0005, 0.0001),
        ('슬리피지 2배 (.10%)', 0.0002, 0.0005, 0.0010, 0.0001),
        ('전부 taker (.05%) + slip .10%', 0.0005, 0.0005, 0.0010, 0.0001),
        ('taker .07% + slip .15% + 펀딩 .03%', 0.0002, 0.0007, 0.0015, 0.0003),
        ('극단: taker .10% + slip .20%', 0.0002, 0.0010, 0.0020, 0.0001)):
    F.FEE_MAKER, F.FEE_TAKER, F.SLIP, F.FUNDING = mk, tk, sl, fd
    trades, _, _ = F.run(data, P)
    e = F.evaluate(trades, 0.30, 10, 10000.0, YRS)
    print('%-44s | %4d %6.1f %6.2f %+8.1f %10.0f %6.1f %4d' % (name, e['n'], e['wr'], e['pf'], e['exp'], e['eq'], e['mdd'], e['worst']))
F.FEE_MAKER, F.FEE_TAKER, F.SLIP, F.FUNDING = base

trades, _, _ = F.run(data, P)
closed = [t for t in trades if t['result'] != 'open']
pnls10 = [F.pm_of(t, 10) for t in closed]
random.seed(11)
print('\n' + '=' * 150)
print('(3) 부트스트랩 5000회 (거래 %d건 순서 리샘플, 10x)' % len(pnls10))
print('=' * 150)
for pos in (0.05, 0.10, 0.15, 0.20, 0.30):
    finals, mdds = [], []
    for _ in range(5000):
        eq, peak, mdd = 1.0, 1.0, 0.0
        for pm in random.choices(pnls10, k=len(pnls10)):
            eq *= max(0.0, 1 + pos * pm / 100)
            peak = max(peak, eq)
            mdd = max(mdd, 1 - eq / peak)
        finals.append(eq)
        mdds.append(mdd)
    finals.sort()
    mdds.sort()
    q = lambda xs, p: xs[int(len(xs) * p)]
    print('  투입 %3.0f%%: 최종배수 5%%분위 %5.2fx / 중앙값 %5.2fx / 95%%분위 %6.2fx | 손실확률 %4.1f%% | MDD 중앙값 %2.0f%% / 95%%분위 %2.0f%%' % (
        pos * 100, q(finals, 0.05), q(finals, 0.5), q(finals, 0.95), sum(1 for x in finals if x < 1) / 50, q(mdds, 0.5) * 100, q(mdds, 0.95) * 100))

# 상위 3개 거래 제외 시
srt = sorted(pnls10)
rest = srt[:-3]
print('\n상위 3개 거래 제외 시: PF %.2f -> %.2f, 기대값 %+.1f%% -> %+.1f%%' % (
    F._pf(pnls10), F._pf(rest), sum(pnls10) / len(pnls10), sum(rest) / len(rest)))
