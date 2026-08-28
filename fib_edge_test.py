# -*- coding: utf-8 -*-
"""fib_edge_test.py — Test B: 진입 우위 전제 검정 (작업지시서 testAB §3)

baseline 생성 (모두 fib_shadow.outcome() 공용):
  B-R1 시간 매칭 무작위 : 전략 후보마다 [T-5일, T+5일] 5분봉 균등 무작위 N=20, 진입=시가, 손절폭% 동일
  B-R2 ARMED-only      : D_ARM 직후 첫 5분봉 시가 진입. a) 손절 P0*(1-BUF)  b) 손절 = 진입가*(1-median(stop_dist_pct))
  B-R3 레벨 스윕        : R_ENTRY_FIB in {0, .146, .236, .382, .5, .618} + Uniform(0, .618) 무작위 레벨 5회
통계: 연도/월 블록 부트스트랩 5,000회, 꼬리(max_R 상위 5%) 제거, 기간 분할(2019~2022 / 2023~2026), 연도별 표.
난수 시드 고정 SEED=20260829. 표준 라이브러리만.
"""
import random
from bisect import bisect_left, bisect_right
from collections import OrderedDict, Counter
import fib_mtf as F
import fib_engine_c as E
import fib_shadow as S
from fib_mtf import D_MS, H_MS, ts

SEED = 20260829
N_R1 = 20
WINDOW_DAYS = 5
BOOT_ITERS = 5000
N_RANDOM_LEVEL_RUNS = 5
GAP_R1_MIN, GAP_R2_MIN = 8.0, 5.0
MIN_CELL = 20


# ------------------------------------------------------------------ 레코드
def _rec(group, src, data, m, entry, stop, block_year, block_month, extra=None):
    o = S.outcome(data, m, entry, stop)
    r = {'group': group, 'src': src, 'entry_time': data.f_ot[m], 'entry_bar': m, 'entry_px': entry, 'stop_px': stop,
         'stop_dist_pct': (entry - stop) / entry, 'year': int(ts(data.f_ot[m])[:4]), 'block_year': block_year, 'block_month': block_month}
    r.update(o)
    if extra:
        r.update(extra)
    return r


def strategy_records(data, cands, group='STRATEGY'):
    out = []
    for c in cands:
        y, ym = c['year'], ts(c['entry_time'])[:7]
        out.append(_rec(group, c['candidate_id'], data, c['fill_m'], c['entry_level'], c['stop_level'], y, ym,
                        {'fib': c['fib'], 'partial_fine': c['partial_fine'], 'arm_seq': c['arm_seq'], 'R_t': c['R_t']}))
    return out


def gen_R1(data, cands, rng, n=N_R1, window_days=WINDOW_DAYS):
    """시간 매칭 무작위. 창 안에 전략 진입 시각이 포함되어도 그대로 둔다 (§8.2)."""
    out = []
    f_ot = data.f_ot
    last = len(f_ot) - 1
    for c in cands:
        T = c['entry_time']
        lo = bisect_left(f_ot, T - window_days * D_MS)
        hi = bisect_right(f_ot, T + window_days * D_MS) - 1
        lo, hi = max(0, lo), min(last, hi)
        for k in range(n):
            m = rng.randint(lo, hi)
            entry = data.f_op[m]
            stop = entry * (1 - c['stop_dist_pct'])
            out.append(_rec('R1', c['candidate_id'], data, m, entry, stop, c['year'], ts(c['entry_time'])[:7], {'draw': k, 'parent_entry_time': T}))
    return out


def gen_R2(data, shadow_events, P, median_stop_pct):
    """ARMED-only: D_ARM 결정 시각(다음 4H 봉 시가) 직후 첫 5분봉 시가 진입."""
    a_recs, b_recs, skipped = [], [], Counter()
    for (kind, tm, t, det) in shadow_events:
        if kind != 'D_ARM':
            continue
        a, b = data.fine_range(t)
        if a >= b:
            skipped['no_fine_bars'] += 1
            continue
        m = a
        entry = data.f_op[m]
        y, ym = int(ts(tm)[:4]), ts(tm)[:7]
        stop_a = det['P0'] * (1 - P['BUF'])
        if stop_a < entry:
            a_recs.append(_rec('R2a', 'ARM%d' % det['arm_seq'], data, m, entry, stop_a, y, ym, {'P0': det['P0']}))
        else:
            skipped['P0_stop_above_entry'] += 1
        b_recs.append(_rec('R2b', 'ARM%d' % det['arm_seq'], data, m, entry, entry * (1 - median_stop_pct), y, ym, {'P0': det['P0']}))
    return a_recs, b_recs, dict(skipped)


def gen_R3(data, P, rng):
    """레벨 스윕 + 무작위 레벨. 손절은 모두 R.low*(1-BUF)."""
    out = OrderedDict()
    for lvl in S.R_LEVELS:
        cands, _ = S.generate(data, P, level=lvl)
        out['L%.3f' % lvl] = strategy_records(data, cands, group='R3_%.3f' % lvl)
    rand = []
    for k in range(N_RANDOM_LEVEL_RUNS):
        cands, _ = S.generate(data, P, level='random', rng=rng, tag='rand%d' % k)
        rand += strategy_records(data, cands, group='R3_random')
    out['random'] = rand
    return out


# ------------------------------------------------------------------ 통계
def rates(recs, ks=(1, 2, 3, 5)):
    n = len(recs)
    if n == 0:
        return {'n': 0}
    out = {'n': n, 'censored': sum(1 for r in recs if r['censored']) / n * 100, 'stopped': sum(1 for r in recs if r['stopped']) / n * 100}
    for k in ks:
        out['reach%dR' % k] = sum(1 for r in recs if r['max_R'] >= k) / n * 100
    xs = sorted(r['max_R'] for r in recs)
    out['median_maxR'] = xs[n // 2]
    sd = sorted(r['stop_dist_pct'] * 100 for r in recs)
    out['stop_median'] = sd[n // 2]
    out['stop_mean'] = sum(sd) / n
    out['small'] = n < MIN_CELL
    return out


def _agg(recs, block_field, k):
    agg = {}
    for r in recs:
        b = r[block_field]
        a = agg.setdefault(b, [0, 0])
        a[0] += 1
        a[1] += r['max_R'] >= k
    return agg


def block_bootstrap(S_recs, B_recs, block_field='block_year', k=2, iters=BOOT_ITERS, seed=SEED):
    """전략-baseline 도달률 격차(%p) 의 블록 부트스트랩 95% CI. 블록 = 연도 또는 연-월."""
    aS, aB = _agg(S_recs, block_field, k), _agg(B_recs, block_field, k)
    blocks = sorted(set(aS) | set(aB))
    if not blocks:
        return {'gap': 0.0, 'ci_low': 0.0, 'ci_high': 0.0, 'blocks': 0, 'skipped': iters}
    rng = random.Random(seed)
    gaps, skipped = [], 0
    nb = len(blocks)
    for _ in range(iters):
        nS = kS = nB = kB = 0
        for _ in range(nb):
            b = blocks[rng.randrange(nb)]
            if b in aS:
                nS += aS[b][0]; kS += aS[b][1]
            if b in aB:
                nB += aB[b][0]; kB += aB[b][1]
        if nS == 0 or nB == 0:
            skipped += 1
            continue
        gaps.append((kS / nS - kB / nB) * 100)
    gaps.sort()
    g = len(gaps)
    point = (sum(a[1] for a in aS.values()) / max(1, sum(a[0] for a in aS.values())) - sum(a[1] for a in aB.values()) / max(1, sum(a[0] for a in aB.values()))) * 100
    return {'gap': point, 'ci_low': gaps[int(0.025 * g)] if g else 0.0, 'ci_high': gaps[min(g - 1, int(0.975 * g))] if g else 0.0,
            'blocks': nb, 'skipped': skipped, 'iters': g}


def tail_trim(recs, q=0.05):
    """max_R 상위 q 제거."""
    xs = sorted(recs, key=lambda r: r['max_R'], reverse=True)
    cut = int(round(len(xs) * q))
    return xs[cut:]


def period_split(recs):
    return {'2019-2022': [r for r in recs if r['year'] <= 2022], '2023-2026': [r for r in recs if r['year'] >= 2023]}


def yearly_table(S_recs, B_recs, k=2):
    years = sorted(set(r['year'] for r in S_recs) | set(r['year'] for r in B_recs))
    out = OrderedDict()
    for y in years:
        s = [r for r in S_recs if r['year'] == y]
        b = [r for r in B_recs if r['block_year'] == y] if B_recs and 'parent_entry_time' in B_recs[0] else [r for r in B_recs if r['year'] == y]
        out[y] = {'nS': len(s), 'S': sum(1 for r in s if r['max_R'] >= k) / len(s) * 100 if s else None,
                  'nB': len(b), 'B': sum(1 for r in b if r['max_R'] >= k) / len(b) * 100 if b else None}
    return out


def compare(S_recs, B_recs, label, k=2):
    """전략 vs baseline 전체 비교 묶음 (§3.5)."""
    rs, rb = rates(S_recs), rates(B_recs)
    res = OrderedDict([('label', label), ('S', rs), ('B', rb), ('gap2R', (rs.get('reach2R', 0) - rb.get('reach2R', 0)) if rb.get('n') else None)])
    res['boot_year'] = block_bootstrap(S_recs, B_recs, 'block_year', k)
    res['boot_month'] = block_bootstrap(S_recs, B_recs, 'block_month', k)
    tS, tB = tail_trim(S_recs), tail_trim(B_recs)
    res['tail'] = {'S': rates(tS), 'B': rates(tB), 'gap2R': (rates(tS).get('reach2R', 0) - rates(tB).get('reach2R', 0)) if tB else None}
    pS, pB = period_split(S_recs), period_split(B_recs)
    res['periods'] = OrderedDict()
    for p in pS:
        s, b = rates(pS[p]), rates(pB[p])
        res['periods'][p] = {'S': s, 'B': b, 'gap2R': (s.get('reach2R', 0) - b.get('reach2R', 0)) if (s.get('n') and b.get('n')) else None}
    res['yearly'] = yearly_table(S_recs, B_recs, k)
    for kk in (1, 3):
        res['gap%dR' % kk] = (rs.get('reach%dR' % kk, 0) - rb.get('reach%dR' % kk, 0)) if rb.get('n') else None
    return res


# ------------------------------------------------------------------ 판정 (§3.6, §3.7)
def judge_R1(cmp):
    p = cmp['periods']
    signs = [v['gap2R'] for v in p.values() if v['gap2R'] is not None]
    same_sign = len(signs) == 2 and (signs[0] > 0) == (signs[1] > 0)
    conds = OrderedDict([
        ('gap>=8pp', cmp['gap2R'] is not None and cmp['gap2R'] >= GAP_R1_MIN),
        ('ci_low_year>0', cmp['boot_year']['ci_low'] > 0),
        ('ci_low_month>0', cmp['boot_month']['ci_low'] > 0),
        ('period_sign_same', same_sign),
        ('tail_trim_gap>0', cmp['tail']['gap2R'] is not None and cmp['tail']['gap2R'] > 0)])
    passed = conds['gap>=8pp'] and conds['ci_low_year>0'] and conds['period_sign_same'] and conds['tail_trim_gap>0']
    return {'conds': conds, 'pass': passed}


def judge_R2(cmp_a, cmp_b):
    best = max(cmp_a['B'].get('reach2R', 0), cmp_b['B'].get('reach2R', 0))
    s = cmp_a['S'].get('reach2R', 0)
    return {'strategy2R': s, 'best_baseline2R': best, 'gap': s - best, 'pass': (s - best) >= GAP_R2_MIN,
            'better': 'R2a' if cmp_a['B'].get('reach2R', 0) >= cmp_b['B'].get('reach2R', 0) else 'R2b'}


def judge_R3(level_rates, random_recs, strategy_recs):
    """0.236 이 6개 레벨 중 상위 2위 이내, 또는 무작위 레벨 추출의 95% 상한 초과."""
    ranked = sorted(level_rates.items(), key=lambda kv: kv[1].get('reach2R', 0), reverse=True)
    rank = [k for k, _ in ranked].index('L0.236') + 1
    rand = rates(random_recs)
    # 무작위 레벨 집합의 2R 도달률 95% 상한 (연도 블록 부트스트랩, 자기 자신)
    aB = _agg(random_recs, 'block_year', 2)
    blocks = sorted(aB)
    rng = random.Random(SEED + 1)
    vals = []
    for _ in range(BOOT_ITERS):
        n = k = 0
        for _ in range(len(blocks)):
            b = blocks[rng.randrange(len(blocks))]
            n += aB[b][0]; k += aB[b][1]
        if n:
            vals.append(k / n * 100)
    vals.sort()
    upper = vals[min(len(vals) - 1, int(0.975 * len(vals)))] if vals else 0.0
    s236 = level_rates['L0.236'].get('reach2R', 0)
    return {'rank_of_0.236': rank, 'ranking': [(k, round(v.get('reach2R', 0), 1), v.get('n', 0)) for k, v in ranked],
            'random2R': rand.get('reach2R', 0), 'random_upper95': upper, 'random_n': rand.get('n', 0),
            'pass': rank <= 2 or s236 > upper}


def verdict(r1, r2, r3):
    if r1['pass'] and r2['pass'] and r3['pass']:
        return 'PASS', 'Test C(꼬리 의존성) → D → E~H 진행. 원문 전제가 데이터로 지지됨'
    if r1['pass'] and r2['pass'] and not r3['pass']:
        return 'CONDITIONAL', '우위는 있으나 23.6 특이성 없음 → R_ENTRY_FIB 를 Test E 에서 정식 최적화 대상으로 승격'
    if r1['pass'] and not r2['pass']:
        return 'CONDITIONAL', '우위의 출처가 D 층(일봉 HH_HL 눌림). R 층을 단순화/제거한 변형을 Test E 에 추가. 4H R 유지 근거 별도 제시'
    if not r1['pass'] and r2['pass']:
        return 'CONDITIONAL', '진입 자체는 무작위 수준이나 R 이 D 보다 나음 → 성과 출처는 청산일 가능성. Test F(청산) 로 우회, "진입 우위 전략" 서술 폐기'
    return 'FAIL', '진입에 방향 예측력 없음. 등급화·빈도 확장(I/J) 중단. 구조 재설계 또는 "청산 전략" 으로 재정의'
