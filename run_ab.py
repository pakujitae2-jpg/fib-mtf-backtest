# -*- coding: utf-8 -*-
"""run_ab.py — Test A → Test B 순차 실행 (작업지시서 testAB_long_only_entry_edge_work_order v1.0)

python run_ab.py [--stage A0|A|shadow|B|all]   (기본 all; 지정 단계까지 실행, 각 단계 실패 시 중단)
산출: ab/ (ab_freeze.json, testA_result.txt, testA_long_*_trades/events.csv, testB_result.txt, testB_candidates.csv,
       testB_outcomes.csv, testB_summary.json, 검증보고서_5차_롱전용_진입우위.md)
읽기 전용: fib_mtf.py, fib_engine_c.py, synthetic_tests.py, baseline_legacy/**
"""
import sys, os, json, csv, time, hashlib, platform, subprocess, random, argparse
from collections import OrderedDict, Counter
import fib_mtf as F
import fib_engine_c as E
import fib_shadow as S
import fib_edge_test as B
import fib_long_baseline as A
from fib_mtf import ts, D_MS

sys.stdout.reconfigure(encoding='utf-8')
OUT = 'ab'
os.makedirs(OUT, exist_ok=True)
STAGES = ['A0', 'A', 'shadow', 'B', 'all']
ap = argparse.ArgumentParser()
ap.add_argument('--stage', default='all', choices=STAGES)
args = ap.parse_args()
upto = STAGES.index(args.stage) if args.stage != 'all' else 3
FREEZE = json.load(open('baseline_legacy/legacy_baseline_freeze.json', encoding='utf-8'))
LOG = []
INV = OrderedDict()          # §4 불변식 결과


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


# ================================================================== §1.2 데이터 무결성
log('=' * 120)
log('Test A/B — run_ab.py  %s' % time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()))
log('=' * 120)
data_meta = OrderedDict()
mismatch = []
for V in ('V2', 'V3'):
    for f, meta in FREEZE['versions'][V]['data']['files'].items():
        if f in data_meta:
            continue
        h = sha(f)
        rows = sum(1 for _ in open(f, encoding='utf-8')) - 1
        data_meta[f] = {'sha256': h, 'bytes': os.path.getsize(f), 'rows': rows, 'match_freeze': h == meta['sha256']}
        if h != meta['sha256']:
            mismatch.append(f)
log('[§1.2] 데이터 sha256 대조: %s' % ('ALL MATCH (%d files)' % len(data_meta) if not mismatch else 'MISMATCH %s' % mismatch))
A0_MODE = 'exact' if not mismatch else 'explain-diff'

# ================================================================== Test A0
DATA, RES = {}, {}
log('\n[A0] 양방향 Corrected 회귀 확인 (판정 기준: %s)' % A0_MODE)
a0_ok = True
for V in ('V2', 'V3'):
    DATA[V] = A.load_data(V)
    r = A.run_A0(V, DATA[V], FREEZE['versions'][V]['config'])
    RES[('A0', V)] = r
    e = r['eval']
    log('  %s both: n=%d PF=%.2f ret=%+.0f%%  (기대 %d / %.2f / %+d) -> %s | assert_invariants PASS' % (
        V, e['n'], e['pf'], e['ret'], r['expected']['n'], r['expected']['pf'], r['expected']['ret'], 'OK' if r['ok'] else 'MISMATCH'))
    a0_ok &= r['ok']
INV['10_assert_invariants_A0'] = 'PASS'
if not a0_ok and A0_MODE == 'exact':
    log('A0 실패 — A1 이후 실행하지 않음')
    sys.exit(1)
if upto == 0:
    sys.exit(0)

# ================================================================== Test A
log('\n[A] 롱 전용 baseline (freeze config + SIDES=long)')
A_RES = {}
for V, name in (('V2', 'A1'), ('V3', 'A2')):
    D = DATA[V]
    r = A.run_long(D, FREEZE['versions'][V]['config'])
    an = A.analyze(r, D, r['events'])
    tag = A.tag_added(RES[('A0', V)]['trades'], RES[('A0', V)]['events'], r['trades'])
    A_RES[name] = {'V': V, 'run': r, 'an': an, 'tag': tag}
    E.assert_invariants(r['trades'], r['events'], D)
    p = an['perf']
    log('  %s (%s long): n=%d | 30%%x10x PF %.2f ret %+.0f%% MDD %.0f%% MTM %.0f/%.0f%% | risk1%% PF %.2f ret %+.0f%% MDD %.0f%% MTM %.0f/%.0f%% CAGR %.1f%%' % (
        name, V, p['30%x10x']['n'], p['30%x10x']['pf'], p['30%x10x']['ret'], p['30%x10x']['mdd'], p['30%x10x']['mtm_mdd_close'], p['30%x10x']['mtm_mdd_low'],
        p['risk1%']['pf'], p['risk1%']['ret'], p['risk1%']['mdd'], p['risk1%']['mtm_mdd_close'], p['risk1%']['mtm_mdd_low'], p['risk1%']['cagr']))
    log('      A0 롱 부분집합 대비: common %d, added %d %s, removed %d %s, changed %d %s | Σpm A0-long %+.1f -> A1 %+.1f' % (
        tag['common'], len(tag['added']), dict(Counter(x for _, x in tag['added'])), len(tag['removed']), dict(Counter(x for _, x in tag['removed'])),
        len(tag['changed']), dict(Counter(x for _, _, x in tag['changed'])), tag['sum_pm_a0_long'], tag['sum_pm_a1']))
INV['10_assert_invariants_A1_A2'] = 'PASS'


def write_trades(path, data, trades):
    cols = ['signal_id', 'side', 'D_arm_time', 'R_confirm_time', 'order_create_time', 'expected_entry', 'actual_entry', 'entry_time',
            'ENTRY_R_LOW', 'ENTRY_R_HIGH', 'ENTRY_R_SIZE', 'structural_stop', 'stop_dist_pct', 'exit_time', 'exit_reason', 'r_net', 'pm_30x10',
            'ret_risk1pct', 'lev_risk1pct', 'fee', 'funding', 'mae', 'mfe', 'mfe_R', 'hold_h', 'age_bars', 'atr_idx', 'atr_end_time', 'decision_time', 'fills']
    risk1 = {id(t): (r, l) for t, r, l in A.trade_returns(trades, ('risk', 0.01, 10.0))}
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(cols)
        for t in trades:
            s = t['side'].s
            dist = (t['entry'] - t['stop0']) / abs(t['entry'])
            rr = risk1.get(id(t), (None, None))
            w.writerow([t['signal_id'], 'LONG' if s > 0 else 'SHORT', ts(t['D_arm_time']) if t['D_arm_time'] else '', ts(t['r_confirm_time']), ts(t['order_create_time']),
                        '%.2f' % (s * t['expected']), '%.2f' % (s * t['entry']), ts(t['entry_time']),
                        '%.2f' % (s * t['entry_R']['ENTRY_R_LOW']), '%.2f' % (s * t['entry_R']['ENTRY_R_HIGH']), '%.2f' % t['entry_R']['ENTRY_R_SIZE'],
                        '%.2f' % (s * t['structural_stop']), '%.4f' % (dist * 100), ts(t['exit_time']), t['exit_reason'], '%.6f' % t['r_net'], '%.3f' % F.pm_of(t, 10),
                        fmt(rr[0], '%.5f'), fmt(rr[1], '%.3f'), '%.6f' % t['fee'], '%.6f' % t['funding'], '%.5f' % t['mae'], '%.5f' % t['mfe'],
                        '%.3f' % (t['mfe'] / dist if dist > 0 else 0), '%.2f' % t['hold_h'], t['age'], t['atr_idx'], ts(t['atr_end_time']), ts(t['decision_time']),
                        ';'.join('%s@%s:%.2f:%.3f' % (k, ts(tm), s * px, fr) for (m, tm, px, fr, k) in t['fill_detail'])])


def write_events(path, events):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['time', 'bar_t', 'event', 'detail'])
        for (t, s, kind, d, tm, det) in events:
            if kind == 'R_CONFIRM':
                continue
            w.writerow([ts(tm), t, kind, json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in det.items()}, ensure_ascii=False)])


for name, R in A_RES.items():
    write_trades(os.path.join(OUT, 'testA_long_%s_trades.csv' % R['V']), DATA[R['V']], R['run']['trades'])
    write_events(os.path.join(OUT, 'testA_long_%s_events.csv' % R['V']), R['run']['events'])


# ---- Test A 결과 텍스트
def testA_text():
    L = []
    o = L.append
    o('=' * 120)
    o('Test A — 롱 전용 교정 baseline (fib_engine_c, freeze config + SIDES=long)  판정 없음: 기준선 고정')
    o('=' * 120)
    o('[A0] ' + ' | '.join('%s both n=%d PF=%.2f ret=%+.0f%% -> %s' % (V, RES[('A0', V)]['eval']['n'], RES[('A0', V)]['eval']['pf'], RES[('A0', V)]['eval']['ret'], 'OK' if RES[('A0', V)]['ok'] else 'MISMATCH') for V in ('V2', 'V3')))
    for name, R in A_RES.items():
        an, tag, V = R['an'], R['tag'], R['V']
        o('\n' + '#' * 120)
        o('%s — %s long  (%s)  4H %s ~ %s, %.2f년' % (name, V, json.dumps(R['run']['P'], ensure_ascii=False), ts(DATA[V].h_ot[DATA[V].start4]), ts(DATA[V].h_ot[DATA[V].LAST]), A.years_of(DATA[V])))
        o('#' * 120)
        o('사이징           |   n  승률    PF   기대값  수익률   CAGR    MDD  MTMc  MTMl  평균승 평균패   RR  연패 Sharpe Sortino 평균배율')
        for sz, m in an['perf'].items():
            o('%-16s | %3d %5.1f %5.2f %+6.2f %+7.0f %6.1f %6.1f %5.1f %5.1f %+6.2f %+6.2f %5.2f %4d %6.2f %7.2f %6.2fx' % (
                sz, m['n'], m['wr'], m['pf'], m['exp'], m['ret'], m['cagr'], m['mdd'], m['mtm_mdd_close'], m['mtm_mdd_low'], m['avg_win'], m['avg_loss'], m['rr'], m['worst'], m['sharpe'], m['sortino'], m['avg_lev']))
        sd = an['stop_dist']
        o('손절폭(%%): median %.2f mean %.2f p95 %.2f max %.2f min %.2f | 청산 사유: %s' % (sd['median'], sd['mean'], sd['p95'], sd['max'], sd['min'], an['exit_reasons']))
        o('연도별 (30%%x10x pm): ' + ' | '.join('%s n%d PF %.2f Σpm %+.0f WR %.0f%%' % (y, r['n'], r['pf'], r['sum_pm'], r['wr']) for y, r in an['yearly'].items()))
        o('보유기간 기여 (Σpm 총 %+.1f): ' % an['holding_total_pm'] + ' | '.join('%s n%d 승%d Σpm %+.1f (%.0f%%)' % (k, v['n'], v['wins'], v['sum_pm'], v['contrib_pct']) for k, v in an['holding'].items()))
        o('꼬리 의존성 (상위 k건 제거 PF): ' + ' | '.join('k=%d PF %.2f Σpm %+.0f' % (k, v['pf'], v['sum_pm']) for k, v in an['tail'].items()))
        mf = an['mfe']
        o('MFE 도달률 (거래 내, R배수): ≥1R %.0f%%  ≥2R %.0f%%  ≥3R %.0f%%  ≥5R %.0f%%  ≥10R %.0f%%  median %.2fR  (n=%d)' % (mf[1], mf[2], mf[3], mf[5], mf[10], mf['median_R'], mf['n']))
        fn = an['funnel']
        o('신호 퍼널 (롱): D_ARM %d -> SIGNAL %d -> ORDER_CREATE %d -> FILL %d | D_DISARM %d, R_REPLACED %d | 주문 취소 사유 %s' % (
            fn['counts'].get('D_ARM', 0), fn['counts'].get('SIGNAL', 0), fn['counts'].get('ORDER_CREATE', 0), fn['counts'].get('FILL', 0),
            fn['counts'].get('D_DISARM', 0), fn['counts'].get('R_REPLACED', 0), fn['cancel_reasons']))
        o('§2.3 롱 전환 부작용 (A0 롱 부분집합 -> %s): common %d | added %d | removed %d | changed %d | Σpm %+.1f -> %+.1f' % (
            name, tag['common'], len(tag['added']), len(tag['removed']), len(tag['changed']), tag['sum_pm_a0_long'], tag['sum_pm_a1']))
        for t, why in tag['added']:
            o('    + %s %s entry %.2f %s pm %+.1f  [%s]' % (t['signal_id'], ts(t['entry_time']), t['entry'], t['result'], F.pm_of(t, 10), why))
        for t, why in tag['removed']:
            o('    - %s %s entry %.2f %s pm %+.1f  [%s]' % (t['signal_id'], ts(t['entry_time']), t['entry'], t['result'], F.pm_of(t, 10), why))
        for x, y, why in tag['changed']:
            o('    ~ %s %s->%s pm %+.1f -> %+.1f  [%s]' % (x['signal_id'], ts(x['entry_time']), ts(y['entry_time']), F.pm_of(x, 10), F.pm_of(y, 10), why))
    return '\n'.join(L)


TA = testA_text()
open(os.path.join(OUT, 'testA_result.txt'), 'w', encoding='utf-8').write(TA)
print(TA)
if upto == 1:
    sys.exit(0)

# ================================================================== shadow (§3.2) + 불변식 4
log('\n[shadow] 후보 생성 (V2 Spot, A1 config) + 하네스 검증')
assert S.self_test()
INV['5_6_7_outcome_rules_selftest'] = 'PASS'
P_B = A_RES['A1']['run']['P']
D2 = DATA['V2']
CANDS, SH_EV = S.generate(D2, P_B)
bad = [c for c in CANDS if not (c['atr_end_time'] < c['decision_time'])]
INV['1_atr_end_time<decision_time'] = 'PASS (%d cands)' % len(CANDS) if not bad else 'FAIL %d' % len(bad)
bad2 = [c for c in CANDS if not (c['R_confirm_time'] < c['entry_time'])]
INV['2_r_confirm_time<entry_time'] = 'PASS' if not bad2 else 'FAIL %d' % len(bad2)
bad3 = [c for c in CANDS if not (c['R_t'] < c['t'])]
INV['3_R_bar<entry_bar'] = 'PASS' if not bad3 else 'FAIL %d' % len(bad3)
assert not bad and not bad2 and not bad3
A1 = A_RES['A1']['run']['trades']
by_key = {c['R_t']: c for c in CANDS}
match, exc = 0, []
a1_iv = [(t['entry_time'], t['exit_time']) for t in A1]
cand_by_arm = {}
for c in CANDS:
    cand_by_arm.setdefault(c['D_arm_time'], []).append(c)
for t in A1:
    c = by_key.get(t['key'][1])
    if c is not None and c['entry_time'] == t['entry_time'] and abs(c['entry_level'] - t['entry']) < 1e-6:
        match += 1
    else:
        # 예외 메커니즘: 같은 ARM 의 shadow 후보가 A1 롱 포지션 보유 구간 안에서 체결(=슬롯 점유로 막힘) 되었는가
        same_arm = cand_by_arm.get(t['D_arm_time'], [])
        blocked = [x for x in same_arm if any(a <= x['entry_time'] <= b for a, b in a1_iv) and x['entry_time'] < t['entry_time']]
        exc.append({'signal_id': t['signal_id'], 'entry_time': ts(t['entry_time']), 'entry': t['entry'], 'R_t': t['key'][1],
                    'kind': 'KEY_MISSING' if c is None else 'TIME_DIFF', 'explained_by_slot': bool(blocked),
                    'shadow_same_arm': [(x['candidate_id'], ts(x['entry_time']), round(x['entry_level'], 2)) for x in same_arm]})
log('  shadow 후보 %d건 (ORDER_CREATE %d, FILL %d, R_INVALID %d, V %d, D_ARM %d) | 5분봉 결손 4H봉 후보 %d' % (
    len(CANDS), sum(1 for k, *_ in SH_EV if k == 'ORDER_CREATE'), sum(1 for k, *_ in SH_EV if k == 'FILL'), sum(1 for k, *_ in SH_EV if k == 'R_INVALID'),
    sum(1 for k, *_ in SH_EV if k == 'V'), sum(1 for k, *_ in SH_EV if k == 'D_ARM'), sum(1 for c in CANDS if c['partial_fine'])))
log('  불변식 4: A1 체결 %d건 중 shadow 일치 %d, 예외 %d' % (len(A1), match, len(exc)))
for x in exc:
    log('     예외 %s %s entry %.2f R_t %d [%s] 슬롯 점유로 설명됨=%s | 같은 ARM shadow 후보 %s' % (x['signal_id'], x['entry_time'], x['entry'], x['R_t'], x['kind'], x['explained_by_slot'], x['shadow_same_arm']))
all_explained = all(x['explained_by_slot'] for x in exc)
INV['4_A1_subset_of_shadow'] = ('PASS' if not exc else ('PASS-WITH-EXCEPTION (%d/%d 일치, 예외 %d건 전부 포지션 슬롯 점유로 설명)' % (match, len(A1), len(exc)) if all_explained else 'FAIL (%d 미설명)' % sum(1 for x in exc if not x['explained_by_slot'])))
if exc and not all_explained:
    log('설명되지 않는 불일치 — Test B 진행하지 않음')
    sys.exit(1)
with open(os.path.join(OUT, 'testB_candidates.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    cols = ['candidate_id', 'D_arm_time', 'P0', 'H1', 'D_size', 'R_low', 'R_high', 'R_size', 'R_confirm_time', 'entry_level', 'entry_time', 'stop_level',
            'stop_dist_pct', 'atr_idx', 'atr_end_time', 'decision_time', 'year', 'arm_index', 'partial_fine', 'in_A1']
    w.writerow(cols)
    a1_keys = {t['key'][1] for t in A1}
    for c in CANDS:
        w.writerow([c['candidate_id'], ts(c['D_arm_time']) if c['D_arm_time'] else '', '%.2f' % c['P0'], '%.2f' % c['H1'], '%.2f' % c['D_size'], '%.2f' % c['R_low'], '%.2f' % c['R_high'],
                    '%.2f' % c['R_size'], ts(c['R_confirm_time']), '%.2f' % c['entry_level'], ts(c['entry_time']), '%.2f' % c['stop_level'], '%.4f' % (c['stop_dist_pct'] * 100),
                    c['atr_idx'], ts(c['atr_end_time']), ts(c['decision_time']), c['year'], c['arm_index'], int(c['partial_fine']), int(c['R_t'] in a1_keys)])
if upto == 2:
    sys.exit(0)

# ================================================================== Test B (§3.3~3.7)
log('\n[B] baseline 생성 + 통계 (SEED=%d, N_R1=%d, horizon %d일, 부트스트랩 %d회)' % (B.SEED, B.N_R1, S.HORIZON_DAYS, B.BOOT_ITERS))
t0 = time.time()


def build_all(seed):
    rng = random.Random(seed)
    strat = B.strategy_records(D2, CANDS)
    r1 = B.gen_R1(D2, CANDS, rng)
    med = sorted(c['stop_dist_pct'] for c in CANDS)[len(CANDS) // 2]
    r2a, r2b, r2skip = B.gen_R2(D2, SH_EV, P_B, med)
    r3 = B.gen_R3(D2, P_B, rng)
    return {'strat': strat, 'r1': r1, 'r2a': r2a, 'r2b': r2b, 'r2skip': r2skip, 'r3': r3, 'median_stop': med}


X = build_all(B.SEED)
log('  생성 %.1fs: 전략 %d, R1 %d, R2a %d, R2b %d (skip %s), R3 %s' % (time.time() - t0, len(X['strat']), len(X['r1']), len(X['r2a']), len(X['r2b']), X['r2skip'], {k: len(v) for k, v in X['r3'].items()}))
# 불변식 9: 시드 고정 재현
X2 = build_all(B.SEED)
det_ok = all([x['entry_bar'] for x in X['r1']] == [x['entry_bar'] for x in X2['r1']] for _ in [0]) and \
    all(len(X['r3'][k]) == len(X2['r3'][k]) and [r['entry_bar'] for r in X['r3'][k]] == [r['entry_bar'] for r in X2['r3'][k]] for k in X['r3']) and \
    [round(r['max_R'], 9) for r in X['r1']] == [round(r['max_R'], 9) for r in X2['r1']]
INV['9_seed_determinism'] = 'PASS' if det_ok else 'FAIL'
assert det_ok
# 불변식 5·8: 참조 봉 open_time >= entry_time, baseline 진입 시각 데이터 범위 내
f0, f1 = D2.f_ot[0], D2.f_ot[-1]
allrecs = X['strat'] + X['r1'] + X['r2a'] + X['r2b'] + [r for v in X['r3'].values() for r in v]
INV['5_first_scanned_bar>=entry_time'] = 'PASS' if all(r['first_bar_time'] >= r['entry_time'] for r in allrecs) else 'FAIL'
INV['8_baseline_entry_in_range_same_horizon'] = 'PASS' if all(f0 <= r['entry_time'] <= f1 for r in allrecs) else 'FAIL'
assert INV['5_first_scanned_bar>=entry_time'] == 'PASS' and INV['8_baseline_entry_in_range_same_horizon'] == 'PASS'

strat_full = X['strat']
strat_nopartial = [r for r in strat_full if not r['partial_fine']]
CMP = OrderedDict()
CMP['R1'] = B.compare(strat_full, X['r1'], 'B-R1 시간매칭 무작위')
CMP['R2a'] = B.compare(strat_full, X['r2a'], 'B-R2a ARMED-only (구조 손절 P0)')
CMP['R2b'] = B.compare(strat_full, X['r2b'], 'B-R2b ARMED-only (손절폭 고정)')
level_rates = OrderedDict((k, B.rates(v)) for k, v in X['r3'].items() if k != 'random')
CMP['R3_random'] = B.compare(X['r3']['L0.236'], X['r3']['random'], 'B-R3 0.236 vs 무작위 레벨')
J1 = B.judge_R1(CMP['R1'])
J2 = B.judge_R2(CMP['R2a'], CMP['R2b'])
J3 = B.judge_R3(level_rates, X['r3']['random'], strat_full)
VERD, NEXT = B.verdict(J1, J2, J3)
# 결손 제외 버전 (§8.5)
CMP['R1_nopartial'] = B.compare(strat_nopartial, [r for r in X['r1'] if r['src'] in {s['src'] for s in strat_nopartial}], 'B-R1 (5분봉 결손 후보 제외)')


# ---- 보조 (지시서 외): V3 (Spot D/W + Futures 4H/5m, A2 config) 에서 동일 검정 — 데이터 의존성 확인용, 판정에는 사용하지 않음
D3, P_B3 = DATA['V3'], A_RES['A2']['run']['P']
CANDS3, SH_EV3 = S.generate(D3, P_B3)
rng3 = random.Random(B.SEED)
strat3 = B.strategy_records(D3, CANDS3)
med3 = sorted(c['stop_dist_pct'] for c in CANDS3)[len(CANDS3) // 2]
r2a_3, r2b_3, _ = B.gen_R2(D3, SH_EV3, P_B3, med3)
SUP = OrderedDict([('R1', B.compare(strat3, B.gen_R1(D3, CANDS3, rng3), 'V3 B-R1 시간매칭 무작위')),
                   ('R2a', B.compare(strat3, r2a_3, 'V3 B-R2a ARMED-only 구조손절')), ('R2b', B.compare(strat3, r2b_3, 'V3 B-R2b ARMED-only 손절폭 고정'))])
SUP_LV = OrderedDict()
for lvl in S.R_LEVELS:
    c_, _ = S.generate(D3, P_B3, level=lvl)
    SUP_LV['L%.3f' % lvl] = B.rates(B.strategy_records(D3, c_))
A2 = A_RES['A2']['run']['trades']
by3 = {c['R_t']: c for c in CANDS3}
sup_match = sum(1 for t in A2 if by3.get(t['key'][1]) is not None and by3[t['key'][1]]['entry_time'] == t['entry_time'])


def rate_line(lab, r):
    if not r.get('n'):
        return '%-40s | n=0' % lab
    return '%-40s | n=%4d cens %4.0f%% stop %4.0f%% | +1R %5.1f%% +2R %5.1f%% +3R %5.1f%% +5R %5.1f%% | med maxR %.2f | 손절폭 med %.2f%%%s' % (
        lab, r['n'], r['censored'], r['stopped'], r['reach1R'], r['reach2R'], r['reach3R'], r['reach5R'], r['median_maxR'], r['stop_median'], '  (n<20: 판단 근거 아님)' if r['small'] else '')


def testB_text():
    L = []
    o = L.append
    o('=' * 120)
    o('Test B — 진입 우위 전제 검정 (V2 Spot 5m, 교정 chronology, 비용·펀딩 미반영, horizon %d일, SEED %d)' % (S.HORIZON_DAYS, B.SEED))
    o('=' * 120)
    o('[4.1] shadow 후보 %d건 | A1 체결 %d건 중 일치 %d, 예외 %d (%s)' % (len(CANDS), len(A1), match, len(exc), INV['4_A1_subset_of_shadow']))
    o('\n[4.2] 도달률 (max_R 은 손절 전까지, 진입봉·손절봉 High 미반영)')
    o(rate_line('전략 shadow (0.236)', CMP['R1']['S']))
    o(rate_line('  └ 5분봉 결손 후보 제외', CMP['R1_nopartial']['S']))
    o(rate_line('B-R1 시간매칭 무작위 (±5일, x20)', CMP['R1']['B']))
    o(rate_line('B-R2a ARMED-only 구조손절 P0', CMP['R2a']['B']))
    o(rate_line('B-R2b ARMED-only 손절폭 %.2f%% 고정' % (X['median_stop'] * 100), CMP['R2b']['B']))
    for k, r in level_rates.items():
        o(rate_line('B-R3 레벨 %s' % k[1:], r))
    o(rate_line('B-R3 무작위 레벨 U(0,0.618) x%d' % B.N_RANDOM_LEVEL_RUNS, CMP['R3_random']['B']))
    o('\n[4.3] 전략 - baseline +2R 격차 (%%p) 와 블록 부트스트랩 95%% CI (%d회)' % B.BOOT_ITERS)
    for k in ('R1', 'R2a', 'R2b', 'R3_random', 'R1_nopartial'):
        c = CMP[k]
        o('%-40s | gap %+5.1f | 연도블록 CI [%+.1f, %+.1f] (%d블록) | 월블록 CI [%+.1f, %+.1f] (%d블록) | 꼬리5%%제거 gap %s | 2019-22 %s / 2023-26 %s | +1R gap %s +3R gap %s' % (
            c['label'], c['gap2R'], c['boot_year']['ci_low'], c['boot_year']['ci_high'], c['boot_year']['blocks'], c['boot_month']['ci_low'], c['boot_month']['ci_high'], c['boot_month']['blocks'],
            fmt(c['tail']['gap2R'], '%+.1f'), fmt(c['periods']['2019-2022']['gap2R'], '%+.1f'), fmt(c['periods']['2023-2026']['gap2R'], '%+.1f'), fmt(c['gap1R'], '%+.1f'), fmt(c['gap3R'], '%+.1f')))
    o('\n연도별 +2R 도달률: 전략 vs B-R1')
    for y, v in CMP['R1']['yearly'].items():
        o('  %d: 전략 %s (n=%d)  R1 %s (n=%d)%s' % (y, fmt(v['S'], '%.0f%%'), v['nS'], fmt(v['B'], '%.0f%%'), v['nB'], '  (n<20)' if v['nS'] < 20 else ''))
    o('\n기간 분할 (전략 / R1 도달률):')
    for p, v in CMP['R1']['periods'].items():
        o('  %s: 전략 +2R %s (n=%d) vs R1 %s (n=%d) gap %s' % (p, fmt(v['S'].get('reach2R'), '%.1f%%'), v['S'].get('n', 0), fmt(v['B'].get('reach2R'), '%.1f%%'), v['B'].get('n', 0), fmt(v['gap2R'], '%+.1f')))
    o('\n[보조 · 지시서 외] V3 (Futures 5m, A2 config) 동일 검정 — 데이터 의존성 확인용, 판정 미사용')
    o('  shadow 후보 %d건, A2 체결 %d건 중 일치 %d' % (len(CANDS3), len(A2), sup_match))
    o(rate_line('  V3 전략 shadow (0.236)', SUP['R1']['S']))
    o(rate_line('  V3 B-R1 시간매칭 무작위', SUP['R1']['B']))
    o(rate_line('  V3 B-R2a ARMED-only 구조손절', SUP['R2a']['B']))
    o(rate_line('  V3 B-R2b ARMED-only 손절폭 고정', SUP['R2b']['B']))
    for k, r in SUP_LV.items():
        o(rate_line('  V3 B-R3 레벨 %s' % k[1:], r))
    for k in ('R1', 'R2a', 'R2b'):
        c = SUP[k]
        o('  %-36s | gap %+5.1f | 연도블록 CI [%+.1f, %+.1f] | 월블록 CI [%+.1f, %+.1f] | 꼬리제거 %s | 2019-22 %s / 2023-26 %s' % (
            c['label'], c['gap2R'], c['boot_year']['ci_low'], c['boot_year']['ci_high'], c['boot_month']['ci_low'], c['boot_month']['ci_high'],
            fmt(c['tail']['gap2R'], '%+.1f'), fmt(c['periods']['2019-2022']['gap2R'], '%+.1f'), fmt(c['periods']['2023-2026']['gap2R'], '%+.1f')))
    o('\n[4.4] §3.6 통과 기준')
    o('  B-R1: ' + ', '.join('%s=%s' % (k, v) for k, v in J1['conds'].items()) + ' -> %s' % ('PASS' if J1['pass'] else 'FAIL'))
    o('  B-R2: 전략 +2R %.1f%% vs ARMED-only 최선(%s) %.1f%% gap %+.1f -> %s' % (J2['strategy2R'], J2['better'], J2['best_baseline2R'], J2['gap'], 'PASS' if J2['pass'] else 'FAIL'))
    o('  B-R3: 0.236 순위 %d/6 %s | 무작위 레벨 +2R %.1f%% (95%% 상한 %.1f%%, n=%d) -> %s' % (J3['rank_of_0.236'], J3['ranking'], J3['random2R'], J3['random_upper95'], J3['random_n'], 'PASS' if J3['pass'] else 'FAIL'))
    o('\n[5] 판정 (§3.7): %s — %s' % (VERD, NEXT))
    o('\n[§4] 불변식: ' + ' | '.join('%s: %s' % (k, v) for k, v in INV.items()))
    return '\n'.join(L)


TB = testB_text()
open(os.path.join(OUT, 'testB_result.txt'), 'w', encoding='utf-8').write(TB)
print(TB)
# ---- outcomes CSV
with open(os.path.join(OUT, 'testB_outcomes.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['group', 'src', 'entry_time', 'entry_px', 'stop_px', 'stop_dist_pct', 'year', 'block_year', 'stopped', 'censored', 'max_R', 't_1R', 't_2R', 't_3R', 't_5R', 'bars_to_exit', 'fib', 'partial_fine'])
    for r in allrecs:
        w.writerow([r['group'], r['src'], ts(r['entry_time']), '%.2f' % r['entry_px'], '%.2f' % r['stop_px'], '%.4f' % (r['stop_dist_pct'] * 100), r['year'], r['block_year'],
                    int(r['stopped']), int(r['censored']), '%.4f' % r['max_R'], ts(r['t_1R']) if r['t_1R'] else '', ts(r['t_2R']) if r['t_2R'] else '', ts(r['t_3R']) if r['t_3R'] else '',
                    ts(r['t_5R']) if r['t_5R'] else '', r['bars_to_exit'], fmt(r.get('fib'), '%.3f'), int(r.get('partial_fine', False))])


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, float):
        return round(o, 6)
    return o


summary = {'seed': B.SEED, 'n_r1': B.N_R1, 'window_days': B.WINDOW_DAYS, 'horizon_days': S.HORIZON_DAYS, 'bootstrap_iterations': B.BOOT_ITERS,
           'n_candidates': len(CANDS), 'subset_check': {'match': match, 'total': len(A1), 'exceptions': exc}, 'median_stop_pct': X['median_stop'] * 100,
           'compare': clean({k: {kk: vv for kk, vv in v.items()} for k, v in CMP.items()}), 'level_rates': clean(level_rates),
           'judge': clean({'R1': J1, 'R2': J2, 'R3': J3}), 'verdict': VERD, 'next': NEXT, 'invariants': dict(INV),
           'supplement_V3': clean({'n_candidates': len(CANDS3), 'A2_match': sup_match, 'compare': SUP, 'level_rates': SUP_LV})}
json.dump(summary, open(os.path.join(OUT, 'testB_summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2, default=str)

# ================================================================== ab_freeze.json (§7)
cfg_hash = hashlib.sha256(json.dumps({'A1': A_RES['A1']['run']['P'], 'A2': A_RES['A2']['run']['P']}, sort_keys=True).encode()).hexdigest()
freeze = OrderedDict([
    ('run_timestamp_utc', time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), ('command_line', ' '.join([sys.executable] + sys.argv)), ('cwd', os.getcwd()),
    ('python_version', sys.version), ('platform', platform.platform()),
    ('code_sha256', {f: sha(f) for f in ('fib_engine_c.py', 'fib_mtf.py', 'fib_shadow.py', 'fib_edge_test.py', 'fib_long_baseline.py', 'run_ab.py')}),
    ('config', {'P_A1': A_RES['A1']['run']['P'], 'P_A2': A_RES['A2']['run']['P'], 'config_sha256': cfg_hash}),
    ('data', {f: dict(m, period='%s ~ %s' % (ts(F.load_csv(f)[0][0] if 'funding' not in f else 0), '')) for f, m in data_meta.items()}),
    ('random_seed', B.SEED), ('bootstrap_iterations', B.BOOT_ITERS), ('horizon_days', S.HORIZON_DAYS), ('n_r1', B.N_R1),
    ('expected', {'A0': {V: {'n': RES[('A0', V)]['eval']['n'], 'pf': round(RES[('A0', V)]['eval']['pf'], 4), 'ret': round(RES[('A0', V)]['eval']['ret'], 2)} for V in ('V2', 'V3')},
                  'A1': {k: round(v, 4) for k, v in A_RES['A1']['an']['perf']['30%x10x'].items() if k in ('n', 'pf', 'ret', 'mdd', 'mtm_mdd_close')},
                  'A1_risk1': {k: round(v, 4) for k, v in A_RES['A1']['an']['perf']['risk1%'].items() if k in ('n', 'pf', 'ret', 'mdd', 'mtm_mdd_close', 'cagr')},
                  'A2': {k: round(v, 4) for k, v in A_RES['A2']['an']['perf']['30%x10x'].items() if k in ('n', 'pf', 'ret', 'mdd', 'mtm_mdd_close')},
                  'A2_risk1': {k: round(v, 4) for k, v in A_RES['A2']['an']['perf']['risk1%'].items() if k in ('n', 'pf', 'ret', 'mdd', 'mtm_mdd_close', 'cagr')},
                  'B': {'strategy_2R': round(CMP['R1']['S']['reach2R'], 3), 'R1_2R': round(CMP['R1']['B']['reach2R'], 3), 'gap': round(CMP['R1']['gap2R'], 3),
                        'ci_low': round(CMP['R1']['boot_year']['ci_low'], 3), 'ci_high': round(CMP['R1']['boot_year']['ci_high'], 3), 'verdict': VERD}}),
    ('pip_freeze', subprocess.run([sys.executable, '-m', 'pip', 'freeze'], capture_output=True, text=True).stdout.splitlines()),
    ('stdlib_only', True), ('invariants', dict(INV))])
# 데이터 기간 (첫/마지막 행)
for f in data_meta:
    rows = F.load_csv(f) if 'funding' not in f else None
    if rows:
        freeze['data'][f]['period'] = '%s ~ %s' % (ts(rows[0][0], 24), ts(rows[-1][0], 24))
    else:
        fr = F.load_funding(f)
        freeze['data'][f]['period'] = '%s ~ %s' % (ts(fr[0][0]), ts(fr[-1][0]))
json.dump(freeze, open(os.path.join(OUT, 'ab_freeze.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2, default=str)
open(os.path.join(OUT, 'run_ab.log'), 'w', encoding='utf-8').write('\n'.join(LOG))
print('\nsaved ->', OUT, '| verdict:', VERD)
