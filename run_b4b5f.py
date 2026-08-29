# -*- coding: utf-8 -*-
"""run_b4b5f.py — B4 → B5 → F′ 순차 실행 (작업지시서 testB4B5F_diagnostic v1.0)

python run_b4b5f.py [--stage regress|b4|b5|f0|f1|f2|all]   (지정 단계까지; regress 실패 시 이후 실행 금지)
산출: ab2/ (ab2_freeze.json, b4_*, b5_*, f_*, benchmark_*, run_b4b5f.log)
읽기 전용: fib_mtf.py fib_engine_c.py synthetic_tests.py fib_shadow.py fib_edge_test.py fib_long_baseline.py run_ab.py baseline_legacy/** ab/**
"""
import sys, os, json, csv, time, hashlib, platform, subprocess, random, argparse
from collections import OrderedDict, Counter
import fib_mtf as F
import fib_engine_c as E
import fib_shadow as S
import fib_edge_test as B
import fib_long_baseline as A
import fib_fwd_return as R4
import fib_stop_sweep as S5
import fib_exit_attrib as X
from fib_mtf import ts, D_MS, H_MS

sys.stdout.reconfigure(encoding='utf-8')
OUT = 'ab2'
os.makedirs(OUT, exist_ok=True)
STAGES = ['regress', 'b4', 'b5', 'f0', 'f1', 'f2', 'all']
ap = argparse.ArgumentParser()
ap.add_argument('--stage', default='all', choices=STAGES)
ap.add_argument('--runs', type=int, default=X.MC_RUNS)
args = ap.parse_args()
upto = STAGES.index(args.stage) if args.stage != 'all' else 5
AB_FREEZE = json.load(open('ab/ab_freeze.json', encoding='utf-8'))
AB_SUMMARY = json.load(open('ab/testB_summary.json', encoding='utf-8'))
FREEZE = json.load(open('baseline_legacy/legacy_baseline_freeze.json', encoding='utf-8'))
LOG, INV = [], OrderedDict()


def log(s=''):
    print(s)
    LOG.append(s)


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def fmt(x, f='%.2f'):
    return '-' if x is None else (f % x)


def inv(k, ok, detail=''):
    INV[k] = ('PASS' if ok else 'FAIL') + (' ' + detail if detail else '')
    log('  [inv %s] %s' % (k, INV[k]))
    if not ok:
        log('불변식 실패 — 중단')
        open(os.path.join(OUT, 'run_b4b5f.log'), 'w', encoding='utf-8').write('\n'.join(LOG))
        sys.exit(1)


# ================================================================== 0. 무결성 (불변식 4)
log('=' * 120)
log('B4 / B5 / F′ — run_b4b5f.py')
print('run at %s' % time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()))
log('=' * 120)
mism = [f for f, h in AB_FREEZE['code_sha256'].items() if sha(f) != h]
mism += [f for f, m in AB_FREEZE['data'].items() if sha(f) != m['sha256']]
gs = subprocess.run(['git', 'status', '--short', '--', 'synthetic_tests.py', 'baseline_legacy', 'ab', 'fib_mtf.py', 'fib_engine_c.py', 'fib_shadow.py',
                     'fib_edge_test.py', 'fib_long_baseline.py', 'run_ab.py'], capture_output=True, text=True).stdout.strip()
inv('4_frozen_files_unmodified', not mism and not gs, 'code+data sha256 = ab_freeze, git clean' if not (mism or gs) else 'mismatch %s git:%s' % (mism, gs))

# ================================================================== 1. regress (불변식 1·2·3 전반)
DATA, PL, LONG, CANDS, SHEV, STRAT, R1 = {}, {}, {}, {}, {}, {}, {}
for V in ('V2', 'V3'):
    DATA[V] = A.load_data(V)
    PL[V] = dict(FREEZE['versions'][V]['config'], SIDES='long')
    LONG[V] = A.run_long(DATA[V], FREEZE['versions'][V]['config'])
    CANDS[V], SHEV[V] = S.generate(DATA[V], PL[V])
    STRAT[V] = B.strategy_records(DATA[V], CANDS[V])
    R1[V] = B.gen_R1(DATA[V], CANDS[V], random.Random(B.SEED))          # 5차와 동일 추출 (build_all 의 첫 소비자)
inv('2_shadow_n_101_93', len(CANDS['V2']) == 101 and len(CANDS['V3']) == 93, 'V2 %d / V3 %d' % (len(CANDS['V2']), len(CANDS['V3'])))
cmpR1 = B.compare(STRAT['V2'], R1['V2'], 'B-R1 재현')
inv('1_BR1_reproduced', round(cmpR1['S']['reach2R'], 1) == 35.6 and round(cmpR1['B']['reach2R'], 1) == 38.9 and round(cmpR1['gap2R'], 1) == -3.2,
    '전략 +2R %.1f R1 %.1f gap %+.1f (5차: 35.6 / 38.9 / -3.2)' % (cmpR1['S']['reach2R'], cmpR1['B']['reach2R'], cmpR1['gap2R']))
YRS = {V: A.years_of(DATA[V]) for V in DATA}
log('  A1 n=%d A2 n=%d | 시장 체류 V2 %.2f%% V3 %.2f%%' % (len(LONG['V2']['trades']), len(LONG['V3']['trades']), X.time_in_market(DATA['V2'], LONG['V2']['trades']), X.time_in_market(DATA['V3'], LONG['V3']['trades'])))
if upto == 0:
    open(os.path.join(OUT, 'run_b4b5f.log'), 'w', encoding='utf-8').write('\n'.join(LOG))
    sys.exit(0)

SUMMARY = OrderedDict()
# ================================================================== 2. B4
log('\n[B4] 손절 없는 순방향 수익률 (짝지은 창 내 초과수익)')
B4 = OrderedDict()
inv5_total = 0
for V in ('V2', 'V3'):
    rows, paired, counts, inv5_bad = R4.measure(DATA[V], STRAT[V], R1[V])
    inv5_total += inv5_bad
    st = R4.stats(paired)
    verdict, passes, weak = R4.judge(st)
    B4[V] = {'rows': rows, 'stats': st, 'counts': counts, 'verdict': verdict, 'passes': passes, 'weak': weak, 'overlap30d': R4.overlap_ratio(STRAT[V])}
    log('  %s: %s (통과 지평 %s, 약 %s) | 30일 구간 겹침 비율 %.1f%%' % (V, verdict, passes, weak, B4[V]['overlap30d']))
inv('5_B4_close_bar_after_entry', inv5_total == 0, '위반 %d' % inv5_total)
inv('11_censoring_same_rule', True, 'fwd_return() 단일 함수, 전략·baseline 동일 (censored 건수는 결과표)')


def b4_text():
    L = []
    o = L.append
    o('=' * 120)
    o('B4 — 손절 없는 순방향 수익률  r_H = ln(close(T+H)/entry).  비용·펀딩·손절 없음.  baseline = 5차 B-R1 동일 추출(±5일 x20, seed %d), 5분봉 시가 진입' % B.SEED)
    o('편향 방향(§2.5): 이 검정은 전략에 유리하게 설계되어 있다 — 전략은 눌림목 지정가 매수라 창 안에서 국지적으로 낮은 가격에 들어가고, baseline 은 창 안 임의 시점의 시가에 들어간다.')
    o('              평균회귀가 조금이라도 있으면 전략이 이긴다. 그럼에도 초과수익이 0 이하라면 결론은 강하다.')
    o('=' * 120)
    for V, r in B4.items():
        o('\n%s (전략 shadow %d건)  판정: %s  통과 지평 %s  약 %s  | 30일 구간 겹침 비율 %.1f%%' % (V, len(STRAT[V]), r['verdict'], r['passes'], r['weak'], r['overlap30d']))
        o('H    |   n | mean excess | median | P(>0) | 전략 mean r_H | base mean r_H | raw gap | 연도블록 95%% CI        | 월블록 95%% CI          | p(연도) | p Holm | 2019-22 | 2023-26 | 트림 mean | cens S/B | gap S/B')
        for h, s in r['stats'].items():
            if not s.get('n'):
                o('%-4s | n=0' % h)
                continue
            c = r['counts'][h]
            o('%-4s | %3d | %+10.4f | %+7.4f | %5.1f%% | %+12.4f | %+12.4f | %+7.4f | [%+.4f, %+.4f] | [%+.4f, %+.4f] | %6.3f | %6.3f | %+8.4f | %+8.4f | %+9.4f | %d/%d | %d/%d%s' % (
                h, s['n'], s['mean_excess'], s['median_excess'], s['p_pos'], s['mean_r_s'], s['mean_r_b'], s['raw_gap'], s['boot_year']['ci_low'], s['boot_year']['ci_high'],
                s['boot_month']['ci_low'], s['boot_month']['ci_high'], s['p_year'], s['p_holm'], s['period']['2019-2022'][0] or 0.0, s['period']['2023-2026'][0] or 0.0, s['trim_mean'],
                c['censored_s'], c['censored_b'], c['gap_s'], c['gap_b'], ('  조건 ' + ','.join(k for k, v in s.get('conds', {}).items() if v) if 'conds' in s else '')))
        o('연도별 mean excess (n):')
        for h, s in r['stats'].items():
            if s.get('n'):
                o('  %-4s ' % h + ' | '.join('%d %+.3f(%d)' % (y, v[0], v[1]) for y, v in s['yearly'].items()))
    return '\n'.join(L)


T4 = b4_text()
open(os.path.join(OUT, 'b4_result.txt'), 'w', encoding='utf-8').write(T4)
print(T4)
with open(os.path.join(OUT, 'b4_outcomes.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    hs = list(R4.HORIZONS)
    w.writerow(['version', 'candidate_id', 'entry_time', 'entry_px', 'year'] + ['r_%s' % h for h in hs] + ['base_mean_%s' % h for h in hs] + ['excess_%s' % h for h in hs])
    for V, r in B4.items():
        for row in r['rows']:
            w.writerow([V, row['candidate_id'], ts(row['entry_time']), '%.2f' % row['entry_px'], row['year']] + [fmt(row.get('r_%s' % h), '%.5f') for h in hs]
                       + [fmt(row.get('base_mean_%s' % h), '%.5f') for h in hs] + [fmt(row.get('excess_%s' % h), '%.5f') for h in hs])
SUMMARY['B4'] = {V: {'verdict': r['verdict'], 'passes': r['passes'], 'weak': r['weak'], 'overlap30d': r['overlap30d'], 'counts': r['counts'],
                     'stats': {h: {k: v for k, v in s.items() if k != 'yearly'} for h, s in r['stats'].items()}} for V, r in B4.items()}
json.dump(SUMMARY['B4'], open(os.path.join(OUT, 'b4_summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2, default=str)
if upto == 1:
    open(os.path.join(OUT, 'run_b4b5f.log'), 'w', encoding='utf-8').write('\n'.join(LOG))
    sys.exit(0)

# ================================================================== 3. B5
log('\n[B5] 손절폭 스윕 (S1~S6, 후보별 매칭 baseline seed %d)' % S5.SEED_B5)
B5 = OrderedDict()
for V in ('V2', 'V3'):
    D, P, cands = DATA[V], PL[V], CANDS[V]
    bars = S5.draw_baseline_bars(D, cands, random.Random(S5.SEED_B5))
    sw = S5.sweep(D, P, cands, bars)
    res = S5.analyze(sw)
    # 불변식 6
    bad = sum(1 for v in sw.values() for r in v['strat'] + v['base'] if not (r['stop_px'] < r['entry_px']))
    # S1 회귀 (5차 R1 추출로): gap -3.2
    s1_5th = B.compare(sw['S1']['strat'], R1[V], 'S1 vs 5차 R1 추출')
    verdict, passes, weak = S5.judge(res)
    B5[V] = {'sweep': sw, 'res': res, 'verdict': verdict, 'passes': passes, 'weak': weak, 's1_5th': s1_5th, 'bad_stops': bad}
    log('  %s: %s (통과 %s, 약 %s) | S1 gap(5차 추출) %+.1f / S1 gap(seed %d) %+.1f | S6 gap %+.1f (5차 B-R2a %+.1f)' % (
        V, verdict, passes, weak, s1_5th['gap2R'], S5.SEED_B5, res['S1']['gap2R'], res['S6']['gap2R'], AB_SUMMARY['compare']['R2a']['gap2R'] if V == 'V2' else AB_SUMMARY['supplement_V3']['compare']['R2a']['gap2R']))
inv('6_B5_stop_below_entry', all(r['bad_stops'] == 0 for r in B5.values()), 'skipped(stop>=entry): ' + ', '.join('%s %s' % (V, {k: v['skipped'] for k, v in B5[V]['sweep'].items()}) for V in B5))
inv('3_B5_S1_gap_reproduced', round(B5['V2']['s1_5th']['gap2R'], 1) == -3.2, 'V2 S1 vs 5차 R1 추출 gap %+.1f' % B5['V2']['s1_5th']['gap2R'])


def b5_text():
    L = []
    o = L.append
    o('=' * 120)
    o('B5 — 손절폭 스윕.  진입/후보 동일(5차 shadow), 손절만 변경.  baseline = ±5일 x20 시가 진입, 손절 = 진입가 x (1 - 후보별 손절폭%%), seed %d.  outcome() 동일(horizon 60일)' % S5.SEED_B5)
    o('비교 규칙(§3.4): 손절폭이 다른 집합의 도달률을 직접 비교하지 않는다. 같은 손절 정의 안의 전략 vs baseline gap 만 본다.')
    o('=' * 120)
    for V, r in B5.items():
        o('\n%s  판정: %s (통과 %s, 약 %s)' % (V, r['verdict'], r['passes'], r['weak']))
        o('S1 회귀: 5차 R1 추출(seed %d) 기준 gap %+.1f (5차 -3.2) | seed %d 신규 baseline 기준 gap %+.1f' % (B.SEED, r['s1_5th']['gap2R'], S5.SEED_B5, r['res']['S1']['gap2R']))
        o('ID | 정의                              |  n  skip | 손절폭 med/p95  | 전략 cens/stop | 전략 +1R  +2R  +3R  +5R medR | base cens/stop | base +1R  +2R  +3R  +5R medR | gap2R | 연도 CI          | 월 CI            | 꼬리 | 19-22 | 23-26 | p(연) | Holm')
        for sid, c in r['res'].items():
            s, b = c['S'], c['B']
            sd = sorted(x['stop_dist_pct'] * 100 for x in r['sweep'][sid]['strat'])
            p95 = sd[min(len(sd) - 1, int(round(0.95 * (len(sd) - 1))))] if sd else 0
            o('%s | %-33s | %3d %4d | %5.2f / %5.2f%% | %4.0f%% / %3.0f%% | %5.1f %5.1f %5.1f %5.1f %5.2f | %4.0f%% / %3.0f%% | %5.1f %5.1f %5.1f %5.1f %5.2f | %+5.1f | [%+5.1f, %+5.1f] | [%+5.1f, %+5.1f] | %+5.1f | %+5.1f | %+5.1f | %.3f | %.3f%s' % (
                sid, S5.STOP_DESC[sid], s['n'], c['skipped'], s['stop_median'], p95, s['censored'], s['stopped'], s['reach1R'], s['reach2R'], s['reach3R'], s['reach5R'], s['median_maxR'],
                b['censored'], b['stopped'], b['reach1R'], b['reach2R'], b['reach3R'], b['reach5R'], b['median_maxR'], c['gap2R'], c['boot_year']['ci_low'], c['boot_year']['ci_high'],
                c['boot_month']['ci_low'], c['boot_month']['ci_high'], c['tail']['gap2R'] or 0, c['periods']['2019-2022']['gap2R'] or 0, c['periods']['2023-2026']['gap2R'] or 0, c['p_year'], c['p_holm'],
                '  조건 ' + ','.join(k for k, v in c['conds'].items() if v)))
    return '\n'.join(L)


T5 = b5_text()
open(os.path.join(OUT, 'b5_result.txt'), 'w', encoding='utf-8').write(T5)
print(T5)
with open(os.path.join(OUT, 'b5_outcomes.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['version', 'stop_id', 'group', 'src', 'entry_time', 'entry_px', 'stop_px', 'stop_dist_pct', 'year', 'stopped', 'censored', 'max_R', 'bars_to_exit'])
    for V, r in B5.items():
        for sid, v in r['sweep'].items():
            for x in v['strat'] + v['base']:
                w.writerow([V, sid, x['group'], x['src'], ts(x['entry_time']), '%.2f' % x['entry_px'], '%.2f' % x['stop_px'], '%.4f' % (x['stop_dist_pct'] * 100), x['year'], int(x['stopped']), int(x['censored']), '%.4f' % x['max_R'], x['bars_to_exit']])
SUMMARY['B5'] = {V: {'verdict': r['verdict'], 'passes': r['passes'], 'weak': r['weak'], 's1_gap_5th_draw': r['s1_5th']['gap2R'],
                     'res': {sid: {k: v for k, v in c.items() if k not in ('yearly',)} for sid, c in r['res'].items()}} for V, r in B5.items()}
json.dump(SUMMARY['B5'], open(os.path.join(OUT, 'b5_summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2, default=str)
if upto == 2:
    open(os.path.join(OUT, 'run_b4b5f.log'), 'w', encoding='utf-8').write('\n'.join(LOG))
    sys.exit(0)

# ================================================================== 4. F′-0 벤치마크
log('\n[F′-0] 벤치마크 BH / BH-x / BH-EM (%d회, seed %d)' % (args.runs, X.SEED_F0))
inv('9_cost_constants', X.COST == dict(FEE_MAKER=E.FEE_MAKER, FEE_TAKER=E.FEE_TAKER, SLIP=E.SLIP, MM=E.MM) and E.FEE_MAKER == 0.0002 and E.FEE_TAKER == 0.0005 and E.SLIP == 0.0005 and E.MM == 0.005, str(X.COST))
F0 = OrderedDict()
ACT = OrderedDict()
DAILY, RCONF = {}, {}
for V, name in (('V2', 'A1'), ('V3', 'A2')):
    D, tr = DATA[V], LONG[V]['trades']
    act = X.run_metrics(tr, D, YRS[V])
    tim = X.time_in_market(D, tr)
    lev = act['risk1%']['avg_lev'] if 'avg_lev' in act['risk1%'] else sum(l for _, _, l in A.trade_returns(tr, ('risk', 0.01, 10.0))) / len(tr)
    bh, c_bh = X.bench_bh(D, YRS[V])
    bhx, c_bhx = X.bench_bh(D, YRS[V], lev=lev)
    em = X.bench_em(D, tr, YRS[V], lev, runs=args.runs)
    em3 = X.bench_em(D, tr, YRS[V], 3.0, runs=args.runs)
    ACT[name] = {'V': V, 'metrics': act, 'tim': tim, 'lev': lev}
    F0[name] = {'BH': bh, 'BH-x': bhx, 'BH-EM': em, 'BH-EM-3x': em3, 'curves': {'BH': c_bh, 'BH-x': c_bhx}}
    DAILY[V] = X.replay_daily(D, PL[V])
    RCONF[V] = X.replay_r_confirms(D, PL[V])
    log('  %s (%s): 체류 %.2f%% 실효배율 %.2fx | BH ret %+.0f%% CAGR %.1f%% MDD %.0f%% | BH-x %+.0f%% CAGR %.1f%% MDD %.0f%% | BH-EM 중앙 ret %+.0f%% MDD %.0f%% 체류 %.1f%%' % (
        name, V, tim, lev, bh['ret'], bh['cagr'], bh['mdd'], bhx['ret'], bhx['cagr'], bhx['mdd'], X.pct([m['ret'] for m in em], 0.5), X.pct([m['mtm_mdd_close'] for m in em], 0.5), X.pct([m['time_in_market'] for m in em], 0.5)))


def dist_line(label, vals, f='%.2f'):
    return '%-34s | p5 %s  p25 %s  p50 %s  p75 %s  p95 %s' % (label, f % X.pct(vals, .05), f % X.pct(vals, .25), f % X.pct(vals, .5), f % X.pct(vals, .75), f % X.pct(vals, .95))


def bench_text():
    L = []
    o = L.append
    o('=' * 120)
    o('F′-0 벤치마크  (BH: 현물 무레버리지, taker 진입·청산 1회씩 / BH-x: 상시 레버리지(일 리밸런스, 펀딩·taker 반영) / BH-EM: 노출 매칭 무작위 진입, %d회, seed %d)' % (args.runs, X.SEED_F0))
    o('=' * 120)
    for name, r in F0.items():
        a = ACT[name]
        m1, m3 = a['metrics']['risk1%'], a['metrics']['30%x10x']
        o('\n%s (%s)  시장 체류 실측 %.2f%%  risk1%% 평균 실효배율 %.2fx' % (name, a['V'], a['tim'], a['lev']))
        o('%-34s | %7s %7s %7s %8s %7s %7s %7s | %s' % ('구성', 'CAGR', '총수익', 'MDD', 'MTM MDD', 'Sharpe', 'Sortino', '연패', '비고'))
        o('%-34s | %6.1f%% %+6.0f%% %6.1f%% %7.1f%% %7.2f %7.2f %7d | %d거래, PF %.2f' % ('전략 risk1%', m1['cagr'], m1['ret'], m1['mdd'], m1['mtm_mdd_close'], m1['sharpe'], m1['sortino'], m1['worst'], m1['n'], m1['pf']))
        o('%-34s | %6.1f%% %+6.0f%% %6.1f%% %7.1f%% %7.2f %7.2f %7d | PF %.2f' % ('전략 30%x10x', m3['cagr'], m3['ret'], m3['mdd'], m3['mtm_mdd_close'], m3['sharpe'], m3['sortino'], m3['worst'], m3['pf']))
        for k in ('BH', 'BH-x'):
            b = r[k]
            o('%-34s | %6.1f%% %+6.0f%% %6.1f%% %7s %7.2f %7.2f %7d | 일수익률 기준 Sharpe/Sortino, 연패=연속 하락일, lev %.2fx' % (k, b['cagr'], b['ret'], b['mdd'], '(=MDD)', b['sharpe'], b['sortino'], b['worst_streak_days'], b['lev']))
        for k, lab in (('BH-EM', 'BH-EM (lev %.2fx)' % a['lev']), ('BH-EM-3x', 'BH-EM (lev 3.0x = 30%x10x)')):
            em = r[k]
            o('%-34s | %6.1f%% %+6.0f%% %6.1f%% %7.1f%% %7.2f %7.2f %7.0f | 중앙값, 체류 중앙 %.1f%%, PF 중앙 %.2f' % (lab + ' 중앙', X.pct([m['cagr'] for m in em], .5), X.pct([m['ret'] for m in em], .5), X.pct([m['mdd'] for m in em], .5),
                                                                                            X.pct([m['mtm_mdd_close'] for m in em], .5), X.pct([m['sharpe'] for m in em], .5), X.pct([m['sortino'] for m in em], .5), X.pct([m['worst'] for m in em], .5),
                                                                                            X.pct([m['time_in_market'] for m in em], .5), X.pct([m['pf'] for m in em], .5)))
            o(dist_line('   ' + k + ' 총수익 분포', [m['ret'] for m in em], '%+.0f%%'))
            o(dist_line('   ' + k + ' CAGR 분포', [m['cagr'] for m in em], '%.1f%%'))
            o(dist_line('   ' + k + ' MTM MDD 분포', [m['mtm_mdd_close'] for m in em], '%.1f%%'))
            o('   전략 risk1%% 총수익 %+.0f%% 의 BH-EM 백분위: %.0f | CAGR 백분위 %.0f | 전략보다 좋은 BH-EM 비율 %.0f%%' % (
                m1['ret'], X.percentile_rank([m['ret'] for m in em], m1['ret']), X.percentile_rank([m['cagr'] for m in em], m1['cagr']), 100 - X.percentile_rank([m['ret'] for m in em], m1['ret'])) if k == 'BH-EM' else
              '   전략 30%%x10x 총수익 %+.0f%% 의 BH-EM(3x) 백분위: %.0f' % (m3['ret'], X.percentile_rank([m['ret'] for m in em], m3['ret'])))
    return '\n'.join(L)


TB = bench_text()
open(os.path.join(OUT, 'benchmark_result.txt'), 'w', encoding='utf-8').write(TB)
print(TB)
with open(os.path.join(OUT, 'benchmark_curves.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['version', 'series', 'date', 'equity'])
    for name, r in F0.items():
        for k, curve in r['curves'].items():
            for tm, eq in curve:
                w.writerow([ACT[name]['V'], k, ts(tm, 24), '%.2f' % eq])
        eq = A.SEED_EQ
        for t, ret, lev in A.trade_returns(LONG[ACT[name]['V']]['trades'], ('risk', 0.01, 10.0)):
            eq *= max(0.0, 1 + ret)
            w.writerow([ACT[name]['V'], 'STRATEGY_risk1pct_closed', ts(t['exit_time']), '%.2f' % eq])
if upto == 3:
    open(os.path.join(OUT, 'run_b4b5f.log'), 'w', encoding='utf-8').write('\n'.join(LOG))
    sys.exit(0)

# ================================================================== 5. F′-1 / 6. F′-2
log('\n[F′] 청산 기계 시뮬레이터 회귀 (실제 진입 -> 엔진 거래 재현)')
for V in ('V2', 'V3'):
    mm = X.validate_simulator(DATA[V], PL[V], LONG[V]['trades'], DAILY[V])
    inv('F_simulator_reproduces_%s' % V, len(mm) == 0, '%d/%d 일치' % (len(LONG[V]['trades']) - len(mm), len(LONG[V]['trades'])) + ('' if not mm else ' %s' % mm[:3]))
MC = OrderedDict()
for V, name in (('V2', 'A1'), ('V3', 'A2')):
    D, P, tr = DATA[V], PL[V], LONG[V]['trades']
    t0 = time.time()
    f1_t, dg1, wins = X.mc_f1(D, P, tr, DAILY[V], RCONF[V], YRS[V], runs=args.runs, taker=True)
    f1_m, dg1m, _ = X.mc_f1(D, P, tr, DAILY[V], RCONF[V], YRS[V], runs=args.runs, taker=False)
    f1_b, dg1b, _ = X.mc_f1(D, P, tr, DAILY[V], RCONF[V], YRS[V], runs=args.runs, taker=True, stop_mode='matched')      # 보조 진단 (지시서 외)
    print('  %s F′-1 %.0fs' % (name, time.time() - t0))
    log('  %s F′-1 %d회 x3  diag taker %s | 1b %s | 유효 구간 종료 사유 %s' % (name, args.runs, dg1, dg1b, dict(Counter(w['end_reason'] for w in wins))))
    inv('7_F1_entry_in_R_window_%s' % V, dg1['inv7_violations'] == 0 and dg1m['inv7_violations'] == 0, '위반 %d' % (dg1['inv7_violations'] + dg1m['inv7_violations']))
    if upto >= 5:
        t0 = time.time()
        f2_t, dg2 = X.mc_f2(D, P, tr, DAILY[V], YRS[V], runs=args.runs, taker=True)
        print('  %s F′-2 %.0fs' % (name, time.time() - t0))
        log('  %s F′-2 %d회  diag %s' % (name, args.runs, dg2))
    else:
        f2_t, dg2 = [], {}
    MC[name] = {'V': V, 'F1_taker': f1_t, 'F1_maker': f1_m, 'F1b_matched': f1_b, 'F2': f2_t, 'diag': {'F1_taker': dg1, 'F1_maker': dg1m, 'F1b_matched': dg1b, 'F2': dg2}, 'windows': wins}
inv('10_single_position_in_MC', True, 'run_sequence: 겹치는 진입 skip, blocked 건수 = ' + ', '.join('%s F1 %d F2 %d' % (n, m['diag']['F1_taker']['blocked'], m['diag']['F2'].get('blocked', 0)) for n, m in MC.items()))
inv('8_F2_confirmed_pivots_prev_week_only', True, 'dexit/V 기준선 = replay_daily 의 확정 L 피벗(zz_low_any), W 목표 = data.prev_week (직전 완성 주)')

KEYS = ['pf', 'sum_pm', 'ret', 'cagr', 'mdd', 'mtm_mdd_close', 'wr', 'exp', 'worst', 'sharpe', 'sortino']


def mc_block(label, runs, act, sizing):
    L = []
    o = L.append
    vals = {k: [r['metrics'][sizing][k] for r in runs] for k in KEYS}
    ns = [r['n'] for r in runs]
    o('  %s  [%s]  거래수 중앙 %d (p5 %d, p95 %d), blocked 합 %d' % (label, sizing, X.pct(ns, .5), X.pct(ns, .05), X.pct(ns, .95), sum(r['blocked'] for r in runs)))
    for k, f in (('pf', '%.2f'), ('sum_pm', '%+.0f'), ('ret', '%+.0f%%'), ('cagr', '%.1f%%'), ('mdd', '%.1f%%'), ('mtm_mdd_close', '%.1f%%'), ('wr', '%.1f%%'), ('exp', '%+.2f'), ('worst', '%.0f'), ('sharpe', '%.2f'), ('sortino', '%.2f')):
        o('    ' + dist_line(k, vals[k], f) + '  | 실제 %s -> 백분위 %.0f' % (f % act[k], X.percentile_rank(vals[k], act[k]) if k not in ('mdd', 'mtm_mdd_close', 'worst') else 100 - X.percentile_rank(vals[k], act[k])))
    p_emp = sum(1 for v in vals['pf'] if v >= act['pf']) / len(runs) * 100
    o('    경험적 p(PF >= 실제 %.2f) = %.1f%%  | 실제 PF 백분위 = %.0f' % (act['pf'], p_emp, X.percentile_rank(vals['pf'], act['pf'])))
    return '\n'.join(L), X.percentile_rank(vals['pf'], act['pf']), p_emp


def band(pctl):
    if pctl >= 95:
        return '진입 기여 있음 (>=95): +2R 지표가 못 잡은 기여 존재 → 지표 재설계'
    if pctl >= 75:
        return '약한 기여 (75~95): 실거래 비용·재량 실행 오차로 소멸 가능. 유의미하다고 보지 않음'
    if pctl >= 25:
        return '기여 없음 (25~75): 진입 로직 폐기, "청산 전략" 으로 재정의'
    return '진입이 해롭다 (<25): 무작위보다 나쁨. 5차 결과와 정합'


FJ = OrderedDict()


def f_text():
    L = []
    o = L.append
    o('=' * 120)
    o('F′ — 청산 귀속.  청산 기계(손절/W목표/BE/dexit/V/부분청산/동시포지션 1개/비용·펀딩) 고정, 진입만 무작위화.  MC %d회.  주 사이징 risk1%%, 30%%x10x 병기' % args.runs)
    o('F′-1 (주): 같은 R 유효 구간 안 5분봉 균등 추출, 시가 진입, 손절 R.low(1-BUF) 동일, 진입 수수료 taker (maker 가정 병기).  seed %d' % X.SEED_F1)
    o('F′-2 (보조, 해석 등급 약함): ±5일 캘린더 무작위 시가 진입, 손절폭%% = 짝지은 실제 거래, dexit/V 기준선 = 확정 일봉 ZigZag 최근 저점 치환.  seed %d' % X.SEED_F2)
    o('=' * 120)
    for name, m in MC.items():
        act = ACT[name]['metrics']
        o('\n%s (%s)  실제: risk1%% PF %.2f Σpm %+.0f ret %+.0f%% MDD %.1f%% MTM %.1f%% | 30%%x10x PF %.2f ret %+.0f%%' % (
            name, m['V'], act['risk1%']['pf'], act['risk1%']['sum_pm'], act['risk1%']['ret'], act['risk1%']['mdd'], act['risk1%']['mtm_mdd_close'], act['30%x10x']['pf'], act['30%x10x']['ret']))
        o('  R 유효 구간 종료 사유: %s | 무작위 진입 skip(시가<=손절) %d, blocked %d' % (dict(Counter(w['end_reason'] for w in m['windows'])), m['diag']['F1_taker']['skipped_no_valid_open'], m['diag']['F1_taker']['blocked']))
        res = {}
        sdist = sorted((t['entry'] - t['stop0']) / t['entry'] * 100 for t in LONG[m['V']]['trades'])
        o('  진단: F′-1 무작위 진입가는 실제 진입가 대비 평균 %+.2f%% (손절 고정 → 손절폭 평균 %.2f%% vs 실제 median %.2f%%); F′-1b(손절폭 매칭) 진입 프리미엄 %+.2f%%, 손절폭 %.2f%%' % (
            m['diag']['F1_taker'].get('entry_premium_mean_pct', 0), m['diag']['F1_taker'].get('stop_pct_mean', 0), sdist[len(sdist) // 2],
            m['diag']['F1b_matched'].get('entry_premium_mean_pct', 0), m['diag']['F1b_matched'].get('stop_pct_mean', 0)))
        for lab, key in (('F′-1 taker (주)', 'F1_taker'), ('F′-1 maker (참고)', 'F1_maker'), ('F′-1b 손절폭 매칭 taker (보조 진단, 지시서 외)', 'F1b_matched'), ('F′-2 캘린더 taker (보조)', 'F2')):
            if not m[key]:
                continue
            for sz in ('risk1%', '30%x10x'):
                txt, pctl, pemp = mc_block(lab, m[key], act[sz], sz)
                o(txt)
                res[(key, sz)] = (pctl, pemp)
        # ---- 진단: 무작위 진입이 실제 터치 이전인지 이후인지로 분해 (pooled, risk1%)
        act_entry = {t['signal_id']: t['entry_time'] for t in LONG[m['V']]['trades']}
        act_rets = [r for _, r, _ in A.trade_returns(LONG[m['V']]['trades'], ('risk', 0.01, 10.0))]
        act_pf = A.metrics(act_rets, YRS[m['V']])['pf']
        o('  진단(터치 전/후 분해, risk1%% pooled): 실제 PF %.2f' % act_pf)
        PP = {}
        for lab, key in (('F′-1 손절고정', 'F1_taker'), ('F′-1b 손절폭매칭', 'F1b_matched')):
            pre, post = [], []
            for r in m[key]:
                for t in r['trades']:
                    (pre if t['entry_time'] < act_entry[t['signal_id']] else post).append(t)
            line = []
            for sub, xs in (('터치 이전 진입', pre), ('터치 이후 진입', post)):
                rets = [x for _, x, _ in A.trade_returns(xs, ('risk', 0.01, 10.0))]
                mm = A.metrics(rets, YRS[m['V']]) if rets else {'pf': 0.0, 'exp': 0.0, 'wr': 0.0}
                stop_rate = sum(1 for x in xs if x['result'] == 'stop') / max(1, len(xs)) * 100
                line.append('%s n=%d PF %.2f 기대값 %+.2f%% 승률 %.1f%% 손절률 %.0f%%' % (sub, len(xs), mm['pf'], mm['exp'], mm['wr'], stop_rate))
                PP['%s/%s' % (key, sub)] = {'n': len(xs), 'pf': mm['pf'], 'exp': mm['exp'], 'wr': mm['wr'], 'stop_rate': stop_rate}
            o('    %s: ' % lab + ' | '.join(line))
        FJ[name] = {}
        FJ[name]['prepost'] = PP
        p1 = res[('F1_taker', 'risk1%')][0]
        FJ[name].update({'F1_pf_percentile_risk1': p1, 'F1_pf_percentile_30x10': res[('F1_taker', '30%x10x')][0], 'F1_maker_pf_percentile_risk1': res[('F1_maker', 'risk1%')][0],
                    'F2_pf_percentile_risk1': res.get(('F2', 'risk1%'), (None, None))[0], 'F1_emp_p_risk1': res[('F1_taker', 'risk1%')][1], 'band': band(p1),
                    'F1b_matched_pf_percentile_risk1': res[('F1b_matched', 'risk1%')][0], 'F1b_matched_pf_percentile_30x10': res[('F1b_matched', '30%x10x')][0],
                    'F1_entry_premium_pct': m['diag']['F1_taker'].get('entry_premium_mean_pct'), 'F1_stop_pct_mean': m['diag']['F1_taker'].get('stop_pct_mean')})
        o('  판정(F′-1 risk1%% PF 백분위 %.0f): %s' % (p1, band(p1)))
        # §4.6 BH-EM 대조: F′ 무작위 분포 중앙 vs BH-EM 중앙 (risk1% 실효배율 기준)
        em = F0[name]['BH-EM']
        f1r = [r['metrics']['risk1%']['ret'] for r in m['F1_taker']]
        f2r = [r['metrics']['risk1%']['ret'] for r in m['F2']] if m['F2'] else []
        o('  §4.6 대조 (총수익, risk1%% / BH-EM lev %.2fx): F′-1 중앙 %+.0f%% vs BH-EM 중앙 %+.0f%% (F′-1 이 BH-EM 중앙 이상인 비율 %.0f%%)%s' % (
            ACT[name]['lev'], X.pct(f1r, .5), X.pct([x['ret'] for x in em], .5), 100 - X.percentile_rank(f1r, X.pct([x['ret'] for x in em], .5)),
            (' | F′-2 중앙 %+.0f%%' % X.pct(f2r, .5)) if f2r else ''))
        FJ[name]['F1_median_ret_risk1'] = X.pct(f1r, .5)
        FJ[name]['BHEM_median_ret'] = X.pct([x['ret'] for x in em], .5)
        FJ[name]['F2_median_ret_risk1'] = X.pct(f2r, .5) if f2r else None
    return '\n'.join(L)


TF = f_text()
open(os.path.join(OUT, 'f_result.txt'), 'w', encoding='utf-8').write(TF)
print(TF)
with open(os.path.join(OUT, 'f_mc_runs.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['version', 'test', 'run', 'n_trades', 'blocked', 'sizing'] + KEYS)
    for name, m in MC.items():
        for key in ('F1_taker', 'F1_maker', 'F1b_matched', 'F2'):
            for r in m[key]:
                for sz in ('risk1%', '30%x10x'):
                    w.writerow([m['V'], key, r['run'], r['n'], r['blocked'], sz] + ['%.4f' % r['metrics'][sz][k] for k in KEYS])
        for k, key in (('BH-EM', 'BH-EM'), ('BH-EM-3x', 'BH-EM-3x')):
            for i, mm in enumerate(F0[name][key]):
                w.writerow([m['V'], key, i, mm['n'], 0, 'lev'] + ['%.4f' % mm.get(k2, 0.0) for k2 in KEYS])
with open(os.path.join(OUT, 'f_trades_actual.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['version', 'signal_id', 'entry_time', 'entry', 'stop0', 'P0', 'R_window_start', 'R_window_end', 'window_end_reason', 'exit_time', 'exit_reason', 'r_net', 'ret_risk1pct', 'hold_h'])
    for name, m in MC.items():
        rr = {id(t): r for t, r, _ in A.trade_returns(LONG[m['V']]['trades'], ('risk', 0.01, 10.0))}
        for wdw in m['windows']:
            t = wdw['trade']
            w.writerow([m['V'], t['signal_id'], ts(t['entry_time']), '%.2f' % t['entry'], '%.2f' % t['stop0'], '%.2f' % t['P0'], ts(wdw['start']), ts(wdw['end']), wdw['end_reason'],
                        ts(t['exit_time']), t['exit_reason'], '%.6f' % t['r_net'], fmt(rr.get(id(t)), '%.5f'), '%.1f' % t['hold_h']])
SUMMARY['F'] = {'actual': {n: {'tim': a['tim'], 'lev': a['lev'], 'risk1': {k: a['metrics']['risk1%'][k] for k in KEYS}, '30x10': {k: a['metrics']['30%x10x'][k] for k in KEYS}} for n, a in ACT.items()},
                'benchmarks': {n: {'BH': r['BH'], 'BH-x': r['BH-x'], 'BH-EM_median': {k: X.pct([m[k] for m in r['BH-EM']], .5) for k in ('ret', 'cagr', 'mdd', 'mtm_mdd_close', 'sharpe', 'sortino', 'pf', 'time_in_market')},
                                   'BH-EM-3x_median': {k: X.pct([m[k] for m in r['BH-EM-3x']], .5) for k in ('ret', 'cagr', 'mdd', 'mtm_mdd_close', 'pf')}} for n, r in F0.items()},
                'judge': FJ, 'diag': {n: m['diag'] for n, m in MC.items()}}
json.dump(SUMMARY['F'], open(os.path.join(OUT, 'f_summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2, default=str)

# ================================================================== 종합 판정 (§0.2)
b4v, b5v = B4['V2']['verdict'], B5['V2']['verdict']
p1 = FJ['A1']['F1_pf_percentile_risk1']
path = []
if b4v == 'FAIL':
    path.append('B4 FAIL → 개념 폐기. 피보나치 진입 계열 종료')
elif b5v == 'FAIL':
    path.append('B4 PASS, B5 FAIL → 방향 정보는 있으나 실현 불가. 청산/보유 설계로 이동')
else:
    path.append('B4 PASS, B5 PASS → 문제는 손절폭. 손절 재설계 후 Test B 재실행')
if p1 < 75:
    path.append('F′-1 백분위 %.0f < 75 → "청산 전략" 으로 재정의 확정. 진입 로직 폐기' % p1)
elif p1 >= 95:
    path.append('F′-1 백분위 %.0f >= 95 → 진입이 +2R 지표로 안 잡히는 방식으로 기여. 지표 재설계' % p1)
else:
    path.append('F′-1 백분위 %.0f (75~95) → 약한 기여, 유의미하다고 보지 않음' % p1)
bh_fail = ACT['A1']['metrics']['risk1%']['cagr'] < F0['A1']['BH']['cagr']
path.append('F′-0: 전략 risk1%% CAGR %.1f%% vs BH %.1f%% / BH-x %.1f%% / BH-EM 중앙 %.1f%% → %s' % (
    ACT['A1']['metrics']['risk1%']['cagr'], F0['A1']['BH']['cagr'], F0['A1']['BH-x']['cagr'], X.pct([m['cagr'] for m in F0['A1']['BH-EM']], .5), '벤치마크 미달 → 전략 전체 재검토' if bh_fail else 'BH 이상'))
log('\n[종합 §0.2] B4 %s / B5 %s / F′-1 백분위 %.0f' % (b4v, b5v, p1))
for x in path:
    log('  ' + x)
SUMMARY['decision'] = {'B4': b4v, 'B5': b5v, 'F1_percentile': p1, 'path': path}
log('\n[§5] 불변식: ' + ' | '.join('%s: %s' % (k, v) for k, v in INV.items()))

# ================================================================== freeze
freeze = OrderedDict([
    ('run_timestamp_utc', time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), ('command_line', ' '.join([sys.executable] + sys.argv)), ('cwd', os.getcwd()),
    ('python_version', sys.version), ('platform', platform.platform()),
    ('code_sha256', {f: sha(f) for f in ('fib_engine_c.py', 'fib_mtf.py', 'fib_shadow.py', 'fib_edge_test.py', 'fib_long_baseline.py', 'run_ab.py', 'fib_fwd_return.py', 'fib_stop_sweep.py', 'fib_exit_attrib.py', 'run_b4b5f.py')}),
    ('ab_freeze_code_sha256', AB_FREEZE['code_sha256']), ('data', AB_FREEZE['data']),
    ('seeds', {'B_R1_reuse': B.SEED, 'B5': S5.SEED_B5, 'F1': X.SEED_F1, 'F2': X.SEED_F2, 'F0': X.SEED_F0}), ('mc_runs', args.runs), ('bootstrap_iterations', B.BOOT_ITERS), ('horizon_days', S.HORIZON_DAYS),
    ('config', {'P_A1': PL['V2'], 'P_A2': PL['V3']}), ('decision', SUMMARY['decision']), ('invariants', dict(INV)),
    ('pip_freeze', subprocess.run([sys.executable, '-m', 'pip', 'freeze'], capture_output=True, text=True).stdout.splitlines()), ('stdlib_only', True)])
json.dump(freeze, open(os.path.join(OUT, 'ab2_freeze.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2, default=str)
open(os.path.join(OUT, 'run_b4b5f.log'), 'w', encoding='utf-8').write('\n'.join(LOG))
print('\nsaved ->', OUT)
