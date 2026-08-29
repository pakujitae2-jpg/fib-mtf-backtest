# -*- coding: utf-8 -*-
"""fib_cond_exp.py — Test H §4 조건부 기대값 · 생존 판정 · Holm (표준 라이브러리만)

분위 경계는 DEV × P-S 에서만 계산해 동결(h1)하고, DEV/TEST 모두 그 경계로만 배정한다 (TEST 재계산 0회).
생존 기준 (§4.2, 사전 등록):
  1 DEV 단조성 : P-S DEV 에서 사전 방향으로 P(RIDE7) 상위 − 하위 >= +10pp (STOPPCT·DDEPTH 는 +15pp)
  2 TEST 유지  : P-S TEST 에서 같은 방향 차이 > 0
  3 꼬리 독립  : DEV 에서 R_REAL 상위 2건 제거 후 조건 1 부호 유지
  4 국면 정합  : (RET100·MA200·VOL30·RET14) P-R 200회 중 >= 80% 에서 같은 방향 차이 양수
"""
import math
from collections import OrderedDict
from fib_features import FEATURES, DIRECTION, REGIME_FEATURES
from fib_fwd_return import holm

TERCILE_Q = (33.3, 66.7)
MIN_PP = {'default': 10.0, 'STOPPCT': 15.0, 'DDEPTH': 15.0}
PR_FRACTION = 0.80


def percentile(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    i = (len(xs) - 1) * q / 100.0
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


def cutpoints(dev_ps):
    """DEV × P-S 에서 조건별 3분위 경계 [q33.3, q66.7]."""
    out = OrderedDict()
    for f in FEATURES:
        xs = [r[f] for r in dev_ps if r.get(f) is not None]
        out[f] = [percentile(xs, TERCILE_Q[0]), percentile(xs, TERCILE_Q[1]), len(xs)]
    return out


def tercile(x, cuts):
    """0 = 하 (x <= q33), 1 = 중, 2 = 상 (x > q67). 경계는 동결값만 사용."""
    if x is None:
        return None
    return 0 if x <= cuts[0] else (2 if x > cuts[1] else 1)


def cell(recs):
    n = len(recs)
    if n == 0:
        return {'n': 0}
    Rs = sorted(r['R_REAL'] for r in recs)
    return {'n': n, 'mean_R': sum(Rs) / n, 'median_R': Rs[n // 2] if n % 2 else (Rs[n // 2 - 1] + Rs[n // 2]) / 2,
            'p_win2r': sum(1 for r in recs if r['WIN2R']) / n * 100, 'p_ride7': sum(1 for r in recs if r['RIDE7']) / n * 100,
            'stop_rate': sum(1 for r in recs if r['stopped']) / n * 100}


def drop_top(recs, k=2):
    top = sorted(recs, key=lambda r: r['R_REAL'], reverse=True)[:k]
    ids = set(id(r) for r in top)
    return [r for r in recs if id(r) not in ids], top


def table(recs, f, cuts):
    """조건 f 의 3분위별 셀 통계 + 상위 2건 제거 버전."""
    out = OrderedDict()
    trimmed, top = drop_top(recs, 2)
    for q in (0, 1, 2):
        sub = [r for r in recs if tercile(r.get(f), cuts[f]) == q]
        c = cell(sub)
        sub_t = [r for r in trimmed if tercile(r.get(f), cuts[f]) == q]
        c['mean_R_top2rm'] = cell(sub_t).get('mean_R')
        c['n_top2rm'] = len(sub_t)
        out[q] = c
    return out, top


def good_bad(f, dev_table):
    """좋은/나쁜 분위 index. 사전 방향이 있으면 그대로, DDEPTH 는 DEV 관측 방향."""
    d = DIRECTION[f]
    if d == 'high':
        return 2, 0, 'high'
    if d == 'low':
        return 0, 2, 'low'
    hi, lo = dev_table[2].get('p_ride7'), dev_table[0].get('p_ride7')
    if hi is None or lo is None:
        return 2, 0, 'high(unobserved)'
    return (2, 0, 'high(DEV)') if hi >= lo else (0, 2, 'low(DEV)')


def diff_pp(tbl, good, bad, key='p_ride7'):
    a, b = tbl[good].get(key), tbl[bad].get(key)
    return None if a is None or b is None else a - b


def pr_diffs(pr_runs, f, cuts, good, bad):
    """P-R 실행별 P(RIDE7) 차이 (good − bad) 리스트."""
    out = []
    for run in pr_runs:
        g = [r for r in run if tercile(r.get(f), cuts[f]) == good]
        b = [r for r in run if tercile(r.get(f), cuts[f]) == bad]
        if g and b:
            out.append(sum(1 for r in g if r['RIDE7']) / len(g) * 100 - sum(1 for r in b if r['RIDE7']) / len(b) * 100)
    return out


def pr_cell_dist(pr_runs, f, cuts):
    """P-R 셀 통계: 실행별 값의 중앙·5·95 백분위."""
    out = OrderedDict()
    for q in (0, 1, 2):
        per = {'n': [], 'mean_R': [], 'median_R': [], 'p_win2r': [], 'p_ride7': [], 'stop_rate': []}
        for run in pr_runs:
            sub = [r for r in run if tercile(r.get(f), cuts[f]) == q]
            c = cell(sub)
            if c['n']:
                for k in per:
                    per[k].append(c[k])
        out[q] = {k: (percentile(v, 50), percentile(v, 5), percentile(v, 95)) if v else (None, None, None) for k, v in per.items()}
    return out


# ------------------------------------------------------------------ Fisher exact (양측)
def _hyper(a, r1, r2, c1):
    n = r1 + r2
    return math.comb(r1, a) * math.comb(r2, c1 - a) / math.comb(n, c1)


def fisher_two_sided(a, b, c, d):
    """2x2 [[a,b],[c,d]] (행 = good/bad 분위, 열 = 성공/실패)."""
    r1, r2, c1 = a + b, c + d, a + c
    if r1 == 0 or r2 == 0 or c1 == 0 or (b + d) == 0:
        return 1.0
    p_obs = _hyper(a, r1, r2, c1)
    lo, hi = max(0, c1 - r2), min(r1, c1)
    return min(1.0, sum(_hyper(x, r1, r2, c1) for x in range(lo, hi + 1) if _hyper(x, r1, r2, c1) <= p_obs + 1e-12))


def survival(f, dev_ps, test_ps, pr_runs, cuts):
    dev_tbl, dev_top = table(dev_ps, f, cuts)
    test_tbl, _ = table(test_ps, f, cuts)
    good, bad, dirn = good_bad(f, dev_tbl)
    d_dev = diff_pp(dev_tbl, good, bad)
    d_test = diff_pp(test_tbl, good, bad)
    trimmed, _ = drop_top(dev_ps, 2)
    tr_tbl, _ = table(trimmed, f, cuts)
    d_trim = diff_pp(tr_tbl, good, bad)
    thr = MIN_PP.get(f, MIN_PP['default'])
    conds = OrderedDict()
    conds['1_dev_monotone_>=%.0fpp' % thr] = d_dev is not None and d_dev >= thr
    conds['2_test_same_sign'] = d_test is not None and d_test > 0
    conds['3_tail_top2_sign'] = d_trim is not None and d_trim > 0
    prd = None
    if f in REGIME_FEATURES:
        prd = pr_diffs(pr_runs, f, cuts, good, bad)
        conds['4_regime_PR_>=80%'] = bool(prd) and sum(1 for x in prd if x > 0) / len(prd) >= PR_FRACTION
    # Fisher p (DEV, good vs bad 분위) — RIDE7 / WIN2R
    def p_for(key):
        g = [r for r in dev_ps if tercile(r.get(f), cuts[f]) == good]
        b = [r for r in dev_ps if tercile(r.get(f), cuts[f]) == bad]
        a_ = sum(1 for r in g if r[key]); c_ = sum(1 for r in b if r[key])
        return fisher_two_sided(a_, len(g) - a_, c_, len(b) - c_)
    return {'feature': f, 'direction': dirn, 'good': good, 'bad': bad, 'dev': dev_tbl, 'test': test_tbl, 'dev_top2': [(r['sid'], round(r['R_REAL'], 2)) for r in dev_top],
            'diff_dev': d_dev, 'diff_test': d_test, 'diff_trim': d_trim, 'pr_diffs': prd, 'pr_frac_pos': (sum(1 for x in prd if x > 0) / len(prd)) if prd else None,
            'conds': conds, 'survive': all(conds.values()), 'p_ride7': p_for('RIDE7'), 'p_win2r': p_for('WIN2R')}


def run_all(dev_ps, test_ps, pr_runs, cuts):
    res = OrderedDict((f, survival(f, dev_ps, test_ps, pr_runs, cuts)) for f in FEATURES)
    pv = OrderedDict()
    for f, r in res.items():
        pv[f + '/RIDE7'] = r['p_ride7']
        pv[f + '/WIN2R'] = r['p_win2r']
    adj = holm(pv)
    for f, r in res.items():
        r['p_holm_ride7'] = adj[f + '/RIDE7']
        r['p_holm_win2r'] = adj[f + '/WIN2R']
        r['weak'] = r['survive'] and not (r['p_holm_ride7'] < 0.05)
    return res
