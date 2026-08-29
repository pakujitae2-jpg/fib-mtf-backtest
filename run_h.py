# -*- coding: utf-8 -*-
"""run_h.py — Test H: h0 → h1(동결) → h2 → h3 → h4 → h5 → h6 (작업지시서 testH_conditional_expectancy v1.0)

python run_h.py [--stage h0|h1|h2|h3|h4|h5|h6|all] [--runs 200]
  h1 이 조건 6개 원값과 DEV 3분위 경계를 계산해 ab3/h1_cutpoints.json 에 동결하고 sha256 을 ab3/ab3_freeze.json 에 기록한다.
  h2 이후 단계는 동결 해시가 일치하지 않으면 실행을 거부한다. h1 재실행 횟수·재동결 이벤트는 ab3_freeze.json 에 누적 기록한다.
읽기 전용: fib_mtf.py fib_engine_c.py synthetic_tests.py fib_shadow.py fib_edge_test.py fib_long_baseline.py run_ab.py
          fib_fwd_return.py fib_stop_sweep.py fib_exit_attrib.py run_b4b5f.py baseline_legacy/** ab/** ab2/**
산출: ab3/ (§1.3). 상대 분석이 남긴 ab3/ 의 다른 파일은 건드리지 않는다.
"""
import sys, os, json, csv, time, hashlib, platform, subprocess, argparse, math
from collections import OrderedDict, Counter
import fib_mtf as F
import fib_engine_c as E
import fib_shadow as S
import fib_edge_test as B
import fib_long_baseline as A
import fib_exit_attrib as X
import fib_features as FE
import fib_cond_exp as CE
import fib_grade as G
import fib_risk_ladder as RL
import fib_wf_long as WF
from fib_mtf import ts, D_MS, H_MS

sys.stdout.reconfigure(encoding='utf-8')
OUT = 'ab3'
os.makedirs(OUT, exist_ok=True)
STAGES = ['h0', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'all']
ap = argparse.ArgumentParser()
ap.add_argument('--stage', default='all', choices=STAGES)
ap.add_argument('--runs', type=int, default=X.MC_RUNS)
args = ap.parse_args()
upto = STAGES.index(args.stage) if args.stage != 'all' else 6
FREEZE = json.load(open('baseline_legacy/legacy_baseline_freeze.json', encoding='utf-8'))
AB_FREEZE = json.load(open('ab/ab_freeze.json', encoding='utf-8'))
AB2_FREEZE = json.load(open('ab2/ab2_freeze.json', encoding='utf-8'))
FZ_PATH = os.path.join(OUT, 'ab3_freeze.json')
CUT_PATH = os.path.join(OUT, 'h1_cutpoints.json')
LOG, INV = [], OrderedDict()
MY_FILES = ['ab3_freeze.json', 'h0_regression_audit.md', 'h1_features.csv', 'h1_cutpoints.json', 'h2_cond_exp.txt', 'h2_cond_exp.csv', 'h3_grades.csv',
            'h4_risk_ladder.txt', 'h4_risk_ladder.csv', 'h5_wf_long.txt', 'h5_wf_grid.csv', 'h6_forward_rules.md', 'run_h.log']


def log(s=''):
    print(s)
    LOG.append(s)


def save_log():
    open(os.path.join(OUT, 'run_h.log'), 'w', encoding='utf-8').write('\n'.join(LOG))


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
        save_log()
        sys.exit(1)


def load_fz():
    if os.path.exists(FZ_PATH):
        try:
            return json.load(open(FZ_PATH, encoding='utf-8'))
        except Exception:
            return {}
    return {}


def write_fz(fz):
    json.dump(fz, open(FZ_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=2, default=str)


def require_freeze(stage):
    """불변식 6: h2 이후 매 단계 동결 해시 확인."""
    fz = load_fz()
    if 'freeze_hash' not in fz or not os.path.exists(CUT_PATH):
        inv('6_freeze_hash_%s' % stage, False, 'h1 동결 기록 없음')
    cur = sha(CUT_PATH)
    inv('6_freeze_hash_%s' % stage, cur == fz['freeze_hash'], 'h1_cutpoints.json %s' % cur[:16])
    return json.load(open(CUT_PATH, encoding='utf-8'))


# ================================================================== 0. 무결성 (불변식 1) · 회귀 (불변식 2·3·11)
log('=' * 120)
log('Test H — run_h.py')
print('run at %s' % time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()))
log('=' * 120)
mism = [f for f, h in AB_FREEZE['code_sha256'].items() if sha(f) != h]
mism += [f for f, h in AB2_FREEZE['code_sha256'].items() if sha(f) != h]
mism += [f for f, m in AB_FREEZE['data'].items() if sha(f) != m['sha256']]
FROZEN = ['fib_mtf.py', 'fib_engine_c.py', 'synthetic_tests.py', 'fib_shadow.py', 'fib_edge_test.py', 'fib_long_baseline.py', 'run_ab.py', 'fib_fwd_return.py',
          'fib_stop_sweep.py', 'fib_exit_attrib.py', 'run_b4b5f.py', 'baseline_legacy', 'ab', 'ab2']
gs = subprocess.run(['git', 'status', '--short', '--'] + FROZEN, capture_output=True, text=True).stdout.strip()
inv('1_frozen_files', not mism and not gs, 'code+data sha256 = ab/ab2 freeze, git clean (%d paths)' % len(FROZEN) if not (mism or gs) else 'mismatch %s git:%s' % (mism, gs))

DATA, PL, LONG, CANDS, DAILY, YRS = {}, {}, {}, {}, {}, {}
for V in ('V2', 'V3'):
    DATA[V] = A.load_data(V)
    PL[V] = dict(FREEZE['versions'][V]['config'], SIDES='long')
    LONG[V] = A.run_long(DATA[V], FREEZE['versions'][V]['config'])
    CANDS[V], _ = S.generate(DATA[V], PL[V])
    DAILY[V] = X.replay_daily(DATA[V], PL[V])
    YRS[V] = A.years_of(DATA[V])
inv('2_shadow_A1_reproduced', len(CANDS['V2']) == 101 and len(CANDS['V3']) == 93 and len(LONG['V2']['trades']) == 82 and len(LONG['V3']['trades']) == 79,
    'shadow %d/%d, A1/A2 %d/%d' % (len(CANDS['V2']), len(CANDS['V3']), len(LONG['V2']['trades']), len(LONG['V3']['trades'])))
inv('11_V2_params_unchanged', all(LONG[V]['P'] == dict(FREEZE['versions'][V]['config'], SIDES='long') for V in ('V2', 'V3')), 'P-A/P-S config = freeze + SIDES=long')

# ---- P-R: F′-2 재생성 (seed 20260902) + 불변식 3
PR = {}
mc_rows = list(csv.DictReader(open('ab2/f_mc_runs.csv', encoding='utf-8')))
for V in ('V2', 'V3'):
    res, dg = X.mc_f2(DATA[V], PL[V], LONG[V]['trades'], DAILY[V], YRS[V], runs=args.runs, taker=True)
    PR[V] = res
    ref = {(int(r['run']), r['sizing']): r for r in mc_rows if r['version'] == V and r['test'] == 'F2'}
    bad = 0
    for r in res:
        for sz in ('risk1%', '30%x10x'):
            rr = ref.get((r['run'], sz))
            if rr is None:
                bad += 1
                continue
            for k in ('pf', 'sum_pm', 'ret', 'mdd', 'wr', 'exp', 'worst'):
                if abs(float(rr[k]) - round(r['metrics'][sz][k], 4)) > 1e-3:
                    bad += 1
    inv('3_F2_regenerated_matches_ab2_%s' % V, bad == 0 and len(res) == 200, '%d회 x 2 사이징 대조, 불일치 %d' % (len(res), bad))

# ---- 조건 계산 (h1 입력)
CTX = {V: FE.DailyContext(DATA[V]) for V in DATA}
PA, PS, PRR = {}, {}, {}
MAXTS = {V: OrderedDict((f, -1) for f in FE.FEATURES) for V in DATA}


def track(V, rec):
    for f, t in rec['max_ts'].items():
        MAXTS[V][f] = max(MAXTS[V][f], t - rec['entry_time'])


for V in ('V2', 'V3'):
    D, P = DATA[V], PL[V]
    PA[V] = []
    for t in LONG[V]['trades']:
        r = FE.record(CTX[V], 'P-A', t['entry_time'], t['entry'], t['stop0'], t['r_net'], t['hold_h'], t['result'], P0=t['P0'], H1=t['H1'],
                      r_confirm_time=t['r_confirm_time'], arm_time=t['D_arm_time'], sid=t['signal_id'])
        r['exit_time'], r['mae'], r['taker'] = t['exit_time'], t['mae'], bool(t.get('taker'))
        PA[V].append(r)
        track(V, r)
    PS[V] = []
    for c in CANDS[V]:
        sim = X.simulate_trade(D, P, c['fill_m'], c['entry_level'], c['stop_level'], c['P0'], DAILY[V], taker=False, entry_at_open=False, signal_id=c['candidate_id'])
        r = FE.record(CTX[V], 'P-S', c['entry_time'], c['entry_level'], c['stop_level'], sim['r_net'], sim['hold_h'], sim['result'], P0=c['P0'], H1=c['H1'],
                      r_confirm_time=c['R_confirm_time'], arm_time=c['D_arm_time'], sid=c['candidate_id'])
        r['exit_time'] = sim['exit_time']
        PS[V].append(r)
        track(V, r)
    PRR[V] = []
    for run in PR[V]:
        rr = []
        for t in run['trades']:
            r = FE.record(CTX[V], 'P-R', t['entry_time'], t['entry'], t['stop0'], t['r_net'], t['hold_h'], t['result'], sid=t['signal_id'], want=FE.REGIME_FEATURES)
            rr.append(r)
            track(V, r)
        PRR[V].append(rr)
inv('4_feature_data_before_decision', all(v < 0 for V in MAXTS for v in MAXTS[V].values()),
    'max(data_ts - decision_time) ms: ' + '; '.join('%s %s' % (V, {f: v for f, v in MAXTS[V].items()}) for V in MAXTS))
inv('5_VOL30_window_past_year', True, 'record() 에서 check_vol_window assert (참조창 [d-365, d-1])')

# ================================================================== h0
sub = json.load(open('ab3/risk_signal_summary.json', encoding='utf-8')) if os.path.exists('ab3/risk_signal_summary.json') else None
ex = json.load(open('ab3/exit_aware_summary.json', encoding='utf-8')) if os.path.exists('ab3/exit_aware_summary.json') else None
h0 = []
o = h0.append
o('# H0 — 기존 회귀점수 감사 (상대 분석)')
o('')
if sub is None or ex is None:
    o('상대 분석의 계산식·산출물을 확보하지 못함 → **재현 불가** 로 기록. §3 의 대응 조건(RET100/MA200/VOL30/RET14/STOPPCT/DDEPTH) 으로 대체한다.')
    H0_VERDICT = 'UNREPRODUCIBLE'
else:
    ch, chx = sub['chosen'], ex['chosen']
    o('감사 대상: `risk_signal_validation.py` (①, +2R 확률 로지스틱, script sha256 %s...) 와 `exit_aware_signal_validation.py` (②, 실제 청산 R 회귀). 산출물 `ab3/risk_signal_summary.json`, `ab3/exit_aware_summary.json`, `ab3/actual_trades_exit_aware_scores.csv` (열 `risk_tier`).' % sub.get('script_sha256', '')[:12])
    o('')
    o('| 확인 항목 | ① +2R 확률 모델 | ② exit-aware 회귀 (지시서의 "회귀점수 A급") |')
    o('|---|---|---|')
    o('| 피팅 표본 | V2 shadow 후보 101건 (`ab/testB_candidates.csv` + `ab2/b5_outcomes.csv` S1), DEV 66건 | 실제 A1 거래 중 shadow 매핑 81건 (DEV 56건), 목표 = 실제 청산 R 을 [−1.25, +5] 로 절단 |')
    o('| 피팅 구간 | **2019~2022 만** (연도 블록 CV 로 λ·상위비율 선택, 15 trial) | **2019~2022 만** (동일 방식, 18 trial), λ=%.0f 상위 %.0f%% | ' % (chx['lambda'], chx['top_fraction'] * 100))
    o('| 조건 원값 | 15개 원값(손절폭 log, D/R 구조, R/ATR, ARM·확정 경과, 일봉 7/30/90일 수익, 200일 이격, 일봉 20일 변동성, 4H 6/42봉 수익·변동성, 3일 펀딩). 상위 시간대 상승추세=d_ret_30/90·d_ma200_gap, 단기 비과열=d_ret_7·h_ret_6, 낮은 변동성=d_rv20·h_rv42, 짧은 손절=log_stop_pct | 동일 15개 |')
    o('| 정규화 | DEV 학습표본의 평균·표준편차로 표준화 (전 기간 백분위 아님) | 동일 |')
    o('| 점수→등급 경계 | DEV 학습점수의 상위 %.0f%% 분위값 %.4f (DEV 에서 결정) | DEV 학습점수의 상위 %.0f%% 분위값 %.4f (DEV 에서 결정) |' % (ch['top_fraction'] * 100, ch['score_threshold'], chx['top_fraction'] * 100, chx['score_threshold']))
    o('| 결과 (상대 분석 보고) | DEV A급 17건 +0.69R → TEST A급 4건 −0.33R: 필터로 **채택하지 않음** (자체 판정) | DEV A급 20건 +1.33R → TEST A급 7건 +5.32R (PF 10.1); 최대 1건(+36.5R) 제외 시 +0.73R |')
    o('| look-ahead | 일봉·4H 는 decision 이전 종료 봉만 (`feature_bars_close_before_decision: true`) | 동일 |')
    o('')
    o('**감사 결과: 형식 통과 (피팅 2019~22, 정규화 DEV 기준, 경계 DEV 결정).** 단, 다음 두 가지를 결과 해석에 반드시 붙인다.')
    o('1. ② 는 ① 의 TEST(2023~26) 결과를 관측한 뒤 설계된 2차 모델이다 (`exit_aware_signal_validation.py` 독스트링 및 상대 분석 §5 자인). 같은 TEST 블록을 두 번 본 것이므로 ② 의 "TEST A급 7건 +5.32R" 은 순수 검증값이 아니라 **참고(sequential, in-sample-adjacent)** 로 표기한다.')
    o('2. 목표변수가 본 지시서(RIDE7 / R_REAL) 와 다르고(① +2R 도달, ② 절단 R), 변수 15개 중 다수가 서로 상관이 높다. 따라서 §5 등급(6조건 3분위 개수 합) 과 나란히 보고하되 두 등급을 합치지 않는다.')
    o('')
    o('본 지시서 §2 의 분기: 피팅 구간 2019~22 + 과거 기준 정규화 → **감사 통과** → §5 등급과 `risk_tier` 를 `h3_grades.csv` 에 병기한다. 4조건(상위 추세·단기 비과열·낮은 변동성·짧은 손절) 은 §3 의 RET100/MA200 · RET14 · VOL30 · STOPPCT 가 대응한다.')
    H0_VERDICT = 'PASS_WITH_CAVEATS'
open(os.path.join(OUT, 'h0_regression_audit.md'), 'w', encoding='utf-8').write('\n'.join(h0) + '\n')
log('\n[h0] 회귀점수 감사: %s' % H0_VERDICT)
if upto == 0:
    save_log()
    sys.exit(0)

# ================================================================== h1 — 조건 원값 + DEV 경계 동결
log('\n[h1] 조건 6개 계산 + DEV x P-S 3분위 경계 동결')
CUTS = OrderedDict()
for V in ('V2', 'V3'):
    dev_ps = [r for r in PS[V] if r['period'] == 'DEV']
    assert all(r['period'] == 'DEV' for r in dev_ps)
    CUTS[V] = CE.cutpoints(dev_ps)
cut_doc = OrderedDict([('computed_on', 'DEV(2019-01-01..2022-12-31) x P-S'), ('quantiles', list(CE.TERCILE_Q)), ('features', FE.FEATURES),
                       ('direction', dict(FE.DIRECTION)), ('cutpoints', {V: {f: [round(c[0], 10), round(c[1], 10), c[2]] for f, c in CUTS[V].items()} for V in CUTS})])
cut_text = json.dumps(cut_doc, ensure_ascii=False, indent=2, sort_keys=True)
new_hash = hashlib.sha256(cut_text.encode('utf-8')).hexdigest()
fz = load_fz()
fz['h1_run_count'] = fz.get('h1_run_count', 0) + 1
fz.setdefault('refreeze_events', [])
if fz.get('freeze_hash') and fz['freeze_hash'] != new_hash:
    fz['refreeze_events'].append({'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'old': fz['freeze_hash'], 'new': new_hash})
    log('  !! 재동결: 조건 정의/경계가 이전 동결과 다름 (기록됨)')
fz['freeze_hash'] = new_hash
fz['freeze_time_utc'] = fz.get('freeze_time_utc') if fz.get('freeze_hash_first') == new_hash else time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
fz['freeze_hash_first'] = fz.get('freeze_hash_first') or new_hash
open(CUT_PATH, 'wb').write(cut_text.encode('utf-8'))          # 바이너리로 써서 파일 sha256 = 텍스트 sha256
write_fz(fz)
log('  동결 해시 %s (재동결 %d회; h1 실행 누적 횟수는 ab3_freeze.json)' % (new_hash[:16], len(fz['refreeze_events'])))
print('  h1 실행 누적 %d회' % fz['h1_run_count'])
for V in CUTS:
    log('  %s 경계: ' % V + ' | '.join('%s [%s, %s] n=%d' % (f, fmt(c[0], '%.4f'), fmt(c[1], '%.4f'), c[2]) for f, c in CUTS[V].items()))
with open(os.path.join(OUT, 'h1_features.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['version', 'population', 'sid', 'entry_time', 'period', 'year', 'entry', 'stop', 'stop_pct', 'r_net', 'R_REAL', 'WIN2R', 'hold_d', 'RIDE7', 'result'] + FE.FEATURES)
    for V in ('V2', 'V3'):
        for r in PA[V] + PS[V]:
            w.writerow([V, r['kind'], r['sid'], ts(r['entry_time']), r['period'], r['year'], '%.2f' % r['entry'], '%.2f' % r['stop'], '%.5f' % r['stop_pct'], '%.6f' % r['r_net'],
                        '%.4f' % r['R_REAL'], int(r['WIN2R']), '%.2f' % r['hold_d'], int(r['RIDE7']), r['result']] + [fmt(r.get(k), '%.6f') for k in FE.FEATURES])
if upto == 1:
    save_log()
    sys.exit(0)

# ================================================================== h2 — 조건부 기대값 · 생존
CUTF = require_freeze('h2')['cutpoints']
CUTS = {V: {f: (c[0], c[1]) for f, c in CUTF[V].items()} for V in CUTF}
inv('7_TEST_uses_DEV_cutpoints_only', True, 'tercile() 는 동결 파일의 경계만 사용, TEST 재계산 없음')
H2 = OrderedDict()
for V in ('V2', 'V3'):
    dev_ps = [r for r in PS[V] if r['period'] == 'DEV']
    test_ps = [r for r in PS[V] if r['period'] == 'TEST']
    H2[V] = CE.run_all(dev_ps, test_ps, PRR[V], CUTS[V])
    surv = [f for f, r in H2[V].items() if r['survive']]
    log('  %s 생존 조건 %d개: %s  (약: %s)' % (V, len(surv), surv, [f for f in surv if H2[V][f]['weak']]))


def h2_text():
    L = []
    o = L.append
    o('=' * 130)
    o('H2 — 조건부 기대값 (조건 x 분위 x 표본 x 구간).  분위 경계 = DEV x P-S 동결값 (TEST 에 그대로 적용).  P-R = 실행 200회 x ≈n̄ 건 (독립 표본 아님; 실행별 값의 중앙 [5, 95])')
    o('생존 기준: 1 DEV P(RIDE7) 상위−하위 >= +10pp(STOPPCT·DDEPTH +15pp) / 2 TEST 같은 부호 / 3 DEV 상위 2건 제거 후 부호 유지 / 4 P-R 200회 중 >=80% 양수 (국면 조건 4개만)')
    o('=' * 130)
    for V in ('V2', 'V3'):
        o('\n##### %s  (P-A %d, P-S %d, P-R %d회 x ≈%.0f)' % (V, len(PA[V]), len(PS[V]), len(PRR[V]), sum(len(x) for x in PRR[V]) / max(1, len(PRR[V]))))
        for f, r in H2[V].items():
            c = CUTS[V][f]
            o('\n[%s] %s  방향 %s  경계 [%.4f, %.4f]  | 생존 %s %s | 조건 %s | DEV diff %s TEST diff %s trim diff %s P-R 양수비율 %s | Fisher p RIDE7 %.3f (Holm %.3f) WIN2R %.3f (Holm %.3f)' % (
                f, FE.MAPS_TO[f], r['direction'], c[0], c[1], 'YES' if r['survive'] else 'no', '(약)' if r['weak'] else '', {k: v for k, v in r['conds'].items()},
                fmt(r['diff_dev'], '%+.1f'), fmt(r['diff_test'], '%+.1f'), fmt(r['diff_trim'], '%+.1f'), fmt(r['pr_frac_pos'], '%.2f'), r['p_ride7'], r['p_holm_ride7'], r['p_win2r'], r['p_holm_win2r']))
            o('  구간 | 표본 | 분위 |   n | mean R | mean R(top2 제거) | median R | P(WIN2R) | P(RIDE7) | 손절률')
            for per in ('DEV', 'TEST'):
                for pop, recs in (('P-A', [x for x in PA[V] if x['period'] == per]), ('P-S', [x for x in PS[V] if x['period'] == per])):
                    tbl, _ = CE.table(recs, f, CUTS[V])
                    for q in (0, 1, 2):
                        cc = tbl[q]
                        if cc['n'] == 0:
                            o('  %-4s | %-3s | %s | %3d |' % (per, pop, ['하', '중', '상'][q], 0))
                            continue
                        o('  %-4s | %-3s | %s | %3d | %+6.2f | %+6.2f (n%d) | %+6.2f | %5.1f%% | %5.1f%% | %5.1f%%' % (
                            per, pop, ['하', '중', '상'][q], cc['n'], cc['mean_R'], cc['mean_R_top2rm'] if cc['mean_R_top2rm'] is not None else 0, cc['n_top2rm'], cc['median_R'], cc['p_win2r'], cc['p_ride7'], cc['stop_rate']))
                if f in FE.REGIME_FEATURES:
                    runs = [[x for x in run if x['period'] == per] for run in PRR[V]]
                    dist = CE.pr_cell_dist(runs, f, CUTS[V])
                    for q in (0, 1, 2):
                        d = dist[q]
                        if d['n'][0] is None:
                            continue
                        o('  %-4s | P-R | %s | %3.0f | %+6.2f [%+.2f,%+.2f] | — | %+6.2f | %5.1f%% | %5.1f%% [%4.1f,%4.1f] | %5.1f%%' % (
                            per, ['하', '중', '상'][q], d['n'][0], d['mean_R'][0], d['mean_R'][1], d['mean_R'][2], d['median_R'][0], d['p_win2r'][0], d['p_ride7'][0], d['p_ride7'][1], d['p_ride7'][2], d['stop_rate'][0]))
    return '\n'.join(L)


T2 = h2_text()
open(os.path.join(OUT, 'h2_cond_exp.txt'), 'w', encoding='utf-8').write(T2)
print(T2)
with open(os.path.join(OUT, 'h2_cond_exp.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['version', 'feature', 'population', 'period', 'tercile', 'n', 'mean_R', 'mean_R_top2rm', 'median_R', 'p_win2r', 'p_ride7', 'stop_rate', 'pr_p5', 'pr_p95'])
    for V in ('V2', 'V3'):
        for fe in FE.FEATURES:
            for per in ('DEV', 'TEST'):
                for pop, recs in (('P-A', [x for x in PA[V] if x['period'] == per]), ('P-S', [x for x in PS[V] if x['period'] == per])):
                    tbl, _ = CE.table(recs, fe, CUTS[V])
                    for q in (0, 1, 2):
                        cc = tbl[q]
                        w.writerow([V, fe, pop, per, q, cc['n'], fmt(cc.get('mean_R'), '%.4f'), fmt(cc.get('mean_R_top2rm'), '%.4f'), fmt(cc.get('median_R'), '%.4f'),
                                    fmt(cc.get('p_win2r'), '%.2f'), fmt(cc.get('p_ride7'), '%.2f'), fmt(cc.get('stop_rate'), '%.2f'), '', ''])
                if fe in FE.REGIME_FEATURES:
                    dist = CE.pr_cell_dist([[x for x in run if x['period'] == per] for run in PRR[V]], fe, CUTS[V])
                    for q in (0, 1, 2):
                        d = dist[q]
                        w.writerow([V, fe, 'P-R(median of runs)', per, q, fmt(d['n'][0], '%.1f'), fmt(d['mean_R'][0], '%.4f'), '', fmt(d['median_R'][0], '%.4f'), fmt(d['p_win2r'][0], '%.2f'),
                                    fmt(d['p_ride7'][0], '%.2f'), fmt(d['stop_rate'][0], '%.2f'), fmt(d['p_ride7'][1], '%.2f'), fmt(d['p_ride7'][2], '%.2f')])
if upto == 2:
    save_log()
    sys.exit(0)

# ================================================================== h3 — 등급
require_freeze('h3')
inv('8_grade_rule', G.assert_rule(), '§5.1 진리표 통과, 가중치 없음')
H3 = OrderedDict()
tiers = {}
for fn, col in (('ab3/actual_trades_exit_aware_scores.csv', 'risk_tier'), ('ab3/actual_trades_with_signal.csv', 'signal_tier')):
    if os.path.exists(fn):
        for r in csv.DictReader(open(fn, encoding='utf-8-sig')):
            tiers.setdefault(r['signal_id'], {})[col] = r.get(col, '')
for V in ('V2', 'V3'):
    surv = [(f, H2[V][f]['good']) for f, r in H2[V].items() if r['survive']]
    G.assign(PA[V], surv, CUTS[V])
    G.assign(PS[V], surv, CUTS[V])
    for run in PRR[V]:
        G.assign(run, [(f, g) for f, g in surv if f in FE.REGIME_FEATURES], CUTS[V]) if surv else G.assign(run, [], CUTS[V])
    H3[V] = {'survivors': surv, 'k': len(surv), 'PA': G.grade_table(PA[V]), 'PS': G.grade_table(PS[V])}
    log('  %s k=%d 생존 %s | P-A 등급 분포 %s' % (V, len(surv), [f for f, _ in surv], dict(Counter(r['grade'] for r in PA[V]))))


def h3_text():
    L = []
    o = L.append
    for V in ('V2', 'V3'):
        h = H3[V]
        o('\n##### %s  k=%d 생존 조건 %s  (등급: A c>=%d, C c<=%d)' % (V, h['k'], [f for f, _ in h['survivors']], math.ceil(2 * h['k'] / 3) if h['k'] else 0, math.floor(h['k'] / 3)))
        for pop in ('PA', 'PS'):
            o('  [%s] 구간 | 등급 |  n | mean R | mean R(top2 제거) | median R | P(WIN2R) | P(RIDE7) | 손절률 | 연패 | ΣR | 연도별 n' % pop)
            for per in ('DEV', 'TEST', 'ALL'):
                for g in ('A', 'B', 'C', 'ALL'):
                    c = h[pop][(per, g)]
                    if c['n'] == 0:
                        o('  %-4s | %-3s | %2d |' % (per, g, 0))
                        continue
                    o('  %-4s | %-3s | %2d | %+6.2f | %+6.2f | %+6.2f | %5.1f%% | %5.1f%% | %5.1f%% | %2d | %+6.1f | %s' % (
                        per, g, c['n'], c['mean_R'], c['mean_R_top2rm'] if c.get('mean_R_top2rm') is not None else 0.0, c['median_R'], c['p_win2r'], c['p_ride7'], c['stop_rate'], c['max_consec_loss'], c['sum_R'], c['yearly_n']))
                    if g == 'ALL':
                        o('        상위 2건: %s' % c['top2'])
        # §5.3 확인
        pa = PA[V]
        y23 = sorted([r for r in pa if r['year'] == 2023], key=lambda r: r['R_REAL'], reverse=True)[:2]
        o('  §5.3 2023년 상위 2건: %s' % [(r['sid'], round(r['R_REAL'], 2), r['grade'], 'c=%d' % r['c']) for r in y23])
        ex_ids = set(id(r) for r in y23)
        a_wo = [r for r in pa if r['grade'] == 'A' and id(r) not in ex_ids]
        c = CE.cell(a_wo)
        o('  A급에서 2023 상위 2건 제외: n=%d mean R %s median %s P(WIN2R) %s P(RIDE7) %s' % (c['n'], fmt(c.get('mean_R'), '%+.2f'), fmt(c.get('median_R'), '%+.2f'), fmt(c.get('p_win2r'), '%.1f%%'), fmt(c.get('p_ride7'), '%.1f%%')))
        y22 = [r for r in pa if r['year'] == 2022]
        o('  §5.3 2022년 %d건 등급 분포: %s  (R: %s)' % (len(y22), dict(Counter(r['grade'] for r in y22)), [round(r['R_REAL'], 2) for r in y22]))
        H3[V]['y23_top2'] = [(r['sid'], r['R_REAL'], r['grade']) for r in y23]
        H3[V]['A_wo_top2'] = c
        H3[V]['y22'] = dict(Counter(r['grade'] for r in y22))
    return '\n'.join(L)


T3 = h3_text()
print(T3)
LOG.append(T3)
with open(os.path.join(OUT, 'h3_grades.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['version', 'signal_id', 'entry_date', 'year', 'period'] + FE.FEATURES + ['tercile_' + x for x in FE.FEATURES] + ['c', 'k', 'grade', 'R_REAL', 'hold_days', 'result', 'regression_risk_tier(exit-aware)', 'regression_signal_tier(+2R)'])
    for V in ('V2', 'V3'):
        for r in PA[V]:
            w.writerow([V, r['sid'], ts(r['entry_time']), r['year'], r['period']] + [fmt(r.get(x), '%.6f') for x in FE.FEATURES] + [CE.tercile(r.get(x), CUTS[V][x]) for x in FE.FEATURES]
                       + [r['c'], r['k'], r['grade'], '%.4f' % r['R_REAL'], '%.2f' % r['hold_d'], r['result'], tiers.get(r['sid'], {}).get('risk_tier', ''), tiers.get(r['sid'], {}).get('signal_tier', '')])
if upto == 3:
    save_log()
    sys.exit(0)

# ================================================================== h4 — 사다리 · 차등 · MC
require_freeze('h4')
pa = PA['V2']
order_before = [(r['sid'], r['R_REAL']) for r in pa]
LAD = RL.ladder(LONG['V2']['trades'], DATA['V2'], YRS['V2'])
TIER = {m: RL.tiered_by_period(pa, mode=m) for m in ('tiered', 'uniform', 'A_only')}
MC = RL.sequence_mc(pa)
inv('9_ladder_order_R_unchanged', [(r['sid'], r['R_REAL']) for r in pa] == order_before and [r['sid'] for r in pa] == [t['signal_id'] for t in LONG['V2']['trades']], 'A1 순서·R_REAL 동일')


def h4_text():
    L = []
    o = L.append
    o('=' * 120)
    o('H4 — 위험 사다리 (A1 V2 long 82건, 거래 순서 그대로, cap_lev 10)')
    o('=' * 120)
    o('위험 | 총수익 |  CAGR | 실현 MDD | MTM MDD(close/low) | 최대 연패 | 최악 연도 | 청산 위험 건수 | 최대 배율 | PF')
    for f, m in LAD.items():
        o('%4.2f%% | %+6.0f%% | %5.1f%% | %6.1f%% | %5.1f / %5.1f%% | %2d | %s %+.0f%% | %d | %.2fx | %.2f' % (
            f * 100, m['ret'], m['cagr'], m['mdd'], m['mtm_mdd_close'], m['mtm_mdd_low'], m['worst'], m['worst_year'][0], m['worst_year'][1], m['liq_count'], m['max_lev'], m['pf']))
    o('\n차등 배분 (B/C 0.50%%, A 0.75%%, 동시 오픈 위험 <= 1.5%%; 엔진이 동시 포지션 1개라 상한은 실질적으로 걸리지 않음)  k=%d' % H3['V2']['k'])
    o('방식      | 구간 |  n | skip | 총수익 | 실현 MDD | 연패 | PF(R) | mean R')
    for m in ('tiered', 'uniform', 'A_only'):
        for per, x in TIER[m].items():
            o('%-9s | %-4s | %2d | %4d | %+6.1f%% | %6.1f%% | %2d | %5.2f | %+5.2f' % ({'tiered': '차등', 'uniform': '균일0.5%', 'A_only': 'A만(필터·비교용)'}[m], per, x['n'], x['skipped'], x['ret'], x['mdd'], x['worst'], x['pf_R'], x['mean_R']))
    o('\n순서 MC (seed %d, %d회, A1 R_REAL 복원추출 + 차등 배분): 실현 MDD p50 %.1f%% p95 %.1f%% p99 %.1f%% | 최대 연패 p50 %d p95 %d p99 %d | 총수익 p5 %+.1f%% p50 %+.1f%% p95 %+.1f%%' % (
        RL.SEED_SEQ, MC['iters'], MC['mdd'][0.5], MC['mdd'][0.95], MC['mdd'][0.99], MC['worst'][0.5], MC['worst'][0.95], MC['worst'][0.99], MC['ret'][0.05], MC['ret'][0.5], MC['ret'][0.95]))
    return '\n'.join(L)


T4 = h4_text()
open(os.path.join(OUT, 'h4_risk_ladder.txt'), 'w', encoding='utf-8').write(T4)
print(T4)
with open(os.path.join(OUT, 'h4_risk_ladder.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['kind', 'risk_or_mode', 'period', 'n', 'skipped', 'ret_pct', 'cagr', 'mdd_realized', 'mtm_mdd_close', 'mtm_mdd_low', 'max_consec_loss', 'worst_year', 'worst_year_ret', 'liq_count', 'pf', 'mean_R'])
    for fr, m in LAD.items():
        w.writerow(['uniform_ladder', fr, 'ALL', m['n'], 0, '%.3f' % m['ret'], '%.3f' % m['cagr'], '%.3f' % m['mdd'], '%.3f' % m['mtm_mdd_close'], '%.3f' % m['mtm_mdd_low'], m['worst'], m['worst_year'][0], '%.3f' % m['worst_year'][1], m['liq_count'], '%.4f' % m['pf'], ''])
    for m, per_d in TIER.items():
        for per, x in per_d.items():
            w.writerow(['allocation', m, per, x['n'], x['skipped'], '%.3f' % x['ret'], '', '%.3f' % x['mdd'], '', '', x['worst'], '', '', '', '%.4f' % x['pf_R'], '%.4f' % x['mean_R']])
    for q, v in MC['mdd'].items():
        w.writerow(['sequence_mc_mdd', 'p%d' % int(q * 100), 'ALL', MC['n'], '', '', '', '%.3f' % v, '', '', MC['worst'][q], '', '', '', '', ''])
if upto == 4:
    save_log()
    sys.exit(0)

# ================================================================== h5 — WF
require_freeze('h5')
log('\n[h5] 64조합 롱 전용 WF (교정 엔진, EXIT=spec)')
t0 = time.time()
GRID = WF.run_grid(DATA['V2'], FREEZE['versions']['V2']['config'])
print('  grid %.0fs' % (time.time() - t0))
inv('10_grid_assert_invariants', len(GRID) == 64, '64조합 전부 E.assert_invariants 통과')
WFR = {tb: WF.walk_forward(GRID, tb) for tb in ('first', 'last')}
v2_recs = [WF.trade_rec(t) for t in LONG['V2']['trades'] if int(ts(t['entry_time'])[:4]) >= 2022]
V2FIX = WF.metrics_risk(v2_recs)
pfs = [WF.pooled(r['yr'], [str(y) for y in WF.TEST_YEARS])['pf'] for r in GRID]
grid_dist = {'min': min(pfs), 'median': sorted(pfs)[32], 'max': max(pfs), 'pos_ratio': sum(1 for p in pfs if p > 1) / len(pfs) * 100}
BASE_R = min(WFR['first'][2]['mean_R'], WFR['last'][2]['mean_R'])
BASE_PF = min(WFR['first'][2]['pf'], WFR['last'][2]['pf'])


def h5_text():
    L = []
    o = L.append
    o('=' * 120)
    o('H5 — 교정 엔진 롱 전용 Walk-forward (확장창, 선택 = PF>1 연도 수 → 최악 연도 → PF, 학습 2019..t-1, 검증 t=2022..2026)')
    o('그리드 64: DMIN{6,8,10,12} x R4{.236,.382} x R_RATIO{.1,.2} x ATR{1,1.5} x TOL{.3,.5}, EXIT=spec, SIDES=long. 연말 걸친 거래는 진입 연도 귀속 (조합당 %d~%d건)' % (min(r['cross_year'] for r in GRID), max(r['cross_year'] for r in GRID)))
    o('=' * 120)
    for tb in ('first', 'last'):
        rows, pool, m = WFR[tb]
        o('\n--- 동점 처리: %s ---' % tb)
        o('검증연도 | 학습 | 선택 파라미터 | 학습 n/양수연도/PF/수익률 | 동점 수/후보 | 검증 n / PF / 수익률(30%x10x) / 건당 R')
        for r in rows:
            o('%d | %s | %s | %3d %d/%d %.2f %+.0f%% | %d/%d | %3d  %s  %s  %s' % (r['test_year'], r['train'], r['params'], r['train_n'], r['train_pos'], r['train_cnt'], r['train_pf'], r['train_ret'],
                                                                              r['ties'], r['candidates'], r['test_n'], fmt(r['test_pf']), fmt(r['test_ret'], '%+.0f%%'), fmt(r['test_mean_R'], '%+.2f')))
        o('WF 합산 2022~26: n %d 승률 %.1f%% PF %.2f 건당 R %+.3f ΣR %+.1f | risk1%% 총수익 %+.1f%% MDD %.1f%% | 30%%x10x 총수익 %+.0f%% MDD %.0f%%' % (
            m['n'], m['wr'], m['pf'], m['mean_R'], m['sum_R'], m['ret_risk1'], m['mdd_risk1'], m['ret_30x10'], m['mdd_30x10']))
    o('\nV2 고정 같은 구간(2022~26, A1 거래): n %d 승률 %.1f%% PF %.2f 건당 R %+.3f | risk1%% %+.1f%% MDD %.1f%% | 30%%x10x %+.0f%% MDD %.0f%%' % (
        V2FIX['n'], V2FIX['wr'], V2FIX['pf'], V2FIX['mean_R'], V2FIX['ret_risk1'], V2FIX['mdd_risk1'], V2FIX['ret_30x10'], V2FIX['mdd_30x10']))
    o('64그리드 2022~26 합산 PF 분포: 최소 %.2f / 중앙 %.2f / 최대 %.2f / PF>1 비율 %.0f%%' % (grid_dist['min'], grid_dist['median'], grid_dist['max'], grid_dist['pos_ratio']))
    o('\n운용 기준선 = WF 두 값의 낮은 쪽: 건당 %+.3fR, PF %.2f' % (BASE_R, BASE_PF))
    return '\n'.join(L)


T5 = h5_text()
open(os.path.join(OUT, 'h5_wf_long.txt'), 'w', encoding='utf-8').write(T5)
print(T5)
with open(os.path.join(OUT, 'h5_wf_grid.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['idx', 'DMIN', 'R4', 'R_RATIO', 'ATR_MULT', 'TOL', 'n', 'cross_year'] + ['pf_%s' % y for y in WF.YEARS] + ['n_%s' % y for y in WF.YEARS] + ['pf_2022_26', 'ret_2022_26_30x10'])
    for i, r in enumerate(GRID):
        pl = WF.pooled(r['yr'], [str(y) for y in WF.TEST_YEARS])
        w.writerow([i, r['P']['DMIN'], r['P']['R4'], r['P']['R_RATIO'], r['P']['ATR_MULT'], r['P']['TOL'], r['n'], r['cross_year']] + ['%.3f' % r['yr'][y]['pf'] for y in WF.YEARS]
                   + [r['yr'][y]['n'] for y in WF.YEARS] + ['%.4f' % pl['pf'], '%.2f' % pl['ret']])
if upto == 5:
    save_log()
    sys.exit(0)

# ================================================================== h6 — 순방향 규칙
require_freeze('h6')
dev_R = [r['R_REAL'] for r in pa if r['period'] == 'DEV']
ZE, dev_mean = RL.zero_edge(dev_R)
sd_R = (sum((x - dev_mean) ** 2 for x in dev_R) / (len(dev_R) - 1)) ** 0.5
n_edge = RL.n_for_edge(BASE_R, sd_R)
promo_dd = MC['mdd'][0.5]
stop_dd = MC['mdd'][0.99]
stop_cum25 = ZE[25][0.05]
h6 = []
o = h6.append
o('# H6 — 순방향 운용 기준 (거래 시작 전 확정)')
o('')
o('- 대상: V2 롱 신호(교정 엔진), 등급별 차등 위험 배분 (A %.2f%% / B·C %.2f%%, 동시 오픈 위험 ≤ %.1f%%), cap_lev 10. 생존 조건 k=%d → %s' % (
    RL.RISK_A * 100, RL.RISK_BC * 100, RL.CAP_CONCURRENT * 100, H3['V2']['k'], ('등급 있음: ' + str([f for f, _ in H3['V2']['survivors']])) if H3['V2']['k'] else '등급 없음 → 전부 B, 균일 0.5% 운용'))
o('')
o('## 8.1 기대 기준선')
o('- **건당 기대 R = %+.3fR** (H5 교정 엔진 롱 전용 WF 2022~26, 동점 처리 두 값 %+.3f / %+.3f 중 낮은 쪽; PF %.2f). 운용 문서의 PF 4.32 / +2.28R 은 삭제한다 (2023~26 실제 거래의 in-sample 값).' % (BASE_R, WFR['first'][2]['mean_R'], WFR['last'][2]['mean_R'], BASE_PF))
o('- 참고: A1 DEV(2019~22) 실현 mean R %+.3f (sd %.2f), 전체 82건 mean R %+.3f.' % (dev_mean, sd_R, sum(r['R_REAL'] for r in pa) / len(pa)))
o('- "0 엣지" 누적 R 분포 (DEV R_REAL 분포를 평균 0 으로 이동, 복원추출 %d회, seed %d):' % (RL.MC_ITERS, RL.SEED_ZERO))
o('')
o('| 거래 수 | p5 | p50 | p95 |')
o('|---|---:|---:|---:|')
for h, v in ZE.items():
    o('| %d건 | %+.1fR | %+.1fR | %+.1fR |' % (h, v[0.05], v[0.5], v[0.95]))
o('')
o('## 8.2 중단선 (둘 중 먼저 오는 것)')
o('1. **낙폭**: 차등 배분 기준 실현 낙폭이 **%.1f%%** (H4 순서 MC 99백분위) 를 초과하면 즉시 중단·재검토. (참고: MC p50 %.1f%%, p95 %.1f%%; 과거 실제 차등 배분 전체 구간 실현 MDD %.1f%%)' % (stop_dd, promo_dd, MC['mdd'][0.95], TIER['tiered']['ALL']['mdd']))
o('2. **누적 R**: 순방향 25건 누적 R 이 **%+.1fR** (0 엣지 분포 5백분위) 미만이면 중단·재검토.' % stop_cum25)
o('')
o('- 15건은 검증이 아니라 재앙 감지용이다 (0 엣지에서도 15건 누적 R 의 90%% 구간은 %+.1f ~ %+.1fR 로 넓다).' % (ZE[15][0.05], ZE[15][0.95]))
all_mean = sum(r['R_REAL'] for r in pa) / len(pa)
n_dev, n_all = RL.n_for_edge(dev_mean, sd_R), RL.n_for_edge(all_mean, sd_R)
if n_edge:
    o('- 엣지 확인에 필요한 건수: 건당 %+.3fR, sd %.2f 를 t=2 로 확인하려면 약 **%d건** (독립 가정). 즉 50건 이전에는 어떤 결과도 엣지의 확인이 아니다.' % (BASE_R, sd_R, n_edge))
else:
    o('- 엣지 확인에 필요한 건수: WF 기준선이 %+.3fR 로 0 이하라 **확인할 엣지가 없다.** 참고로 DEV 실현 평균 %+.3fR 이 진짜라면 t=2 확인에 약 %s건, 전체 82건 평균 %+.3fR 이 진짜라면 약 %s건이 필요하다 (sd %.2f, 독립 가정). 즉 50건 이전에는 어떤 결과도 엣지의 확인이 아니다.' % (
        BASE_R, dev_mean, n_dev if n_dev else '∞', all_mean, n_all if n_all else '∞', sd_R))
o('')
o('## 8.3 승격 조건')
o('- 순방향 15건 후 실현 낙폭이 **%.1f%%** (MC 50백분위) 이내이고 누적 R > 0 이면 건당 상한을 1.0%% 로 승격 가능. 그 전까지 1.0%% 초과 금지.' % promo_dd)
o('- 승격 후에도 동시 오픈 위험 합 1.5% 상한과 §8.2 중단선은 유지한다.')
open(os.path.join(OUT, 'h6_forward_rules.md'), 'w', encoding='utf-8').write('\n'.join(h6) + '\n')
print('\n'.join(h6))

# ================================================================== freeze 기록 · 요약
fz = load_fz()
fz.update(OrderedDict([
    ('run_timestamp_utc', time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), ('command_line', ' '.join([sys.executable] + sys.argv)), ('cwd', os.getcwd()),
    ('python_version', sys.version), ('platform', platform.platform()),
    ('code_sha256', {f: sha(f) for f in ('fib_engine_c.py', 'fib_mtf.py', 'fib_shadow.py', 'fib_edge_test.py', 'fib_long_baseline.py', 'fib_exit_attrib.py', 'fib_features.py', 'fib_cond_exp.py',
                                          'fib_grade.py', 'fib_risk_ladder.py', 'fib_wf_long.py', 'run_h.py')}),
    ('data', AB_FREEZE['data']), ('seeds', {'F2_regenerate': X.SEED_F2, 'forward_stop_mc': RL.SEED_ZERO, 'risk_ladder_sequence_mc': RL.SEED_SEQ}), ('mc_runs', args.runs),
    ('config', {'P_A': PL['V2'], 'P_A_V3': PL['V3']}), ('h0_verdict', H0_VERDICT),
    ('survivors', {V: [f for f, _ in H3[V]['survivors']] for V in H3}), ('weak', {V: [f for f in H2[V] if H2[V][f]['weak']] for V in H2}),
    ('grades_PA_V2', dict(Counter(r['grade'] for r in PA['V2']))), ('y23_top2', H3['V2']['y23_top2']), ('y22_grades', H3['V2']['y22']),
    ('wf', {'first': {k: v for k, v in WFR['first'][2].items()}, 'last': {k: v for k, v in WFR['last'][2].items()}, 'v2_fixed_2022_26': V2FIX, 'grid_pf_2022_26': grid_dist, 'baseline_R': BASE_R, 'baseline_PF': BASE_PF}),
    ('forward_rules', {'stop_dd_pct': stop_dd, 'promo_dd_pct': promo_dd, 'stop_cum25_R': stop_cum25, 'zero_edge': {str(h): v for h, v in ZE.items()}, 'n_for_edge': n_edge}),
    ('invariants', dict(INV)), ('pip_freeze', subprocess.run([sys.executable, '-m', 'pip', 'freeze'], capture_output=True, text=True).stdout.splitlines()), ('stdlib_only', True)]))
write_fz(fz)
log('\n[§9] 불변식: ' + ' | '.join('%s: %s' % (k, v) for k, v in INV.items()))
save_log()
print('\nsaved ->', OUT)
