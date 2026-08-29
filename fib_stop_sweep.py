# -*- coding: utf-8 -*-
"""fib_stop_sweep.py — B5: 손절폭 스윕 (작업지시서 testB4B5F §3)

진입·후보 집합은 5차 shadow 후보 그대로, 손절 정의만 6종 (S1~S6). 손절 정의마다 후보별 손절폭% 로 개별 매칭한
시간 매칭 무작위 baseline (±5일, 후보당 20개, 시드 20260830) 을 만들고 fib_shadow.outcome() 으로 측정한다.
비교는 같은 손절폭의 전략 vs baseline gap 끼리만 (§3.4). 표준 라이브러리만.
"""
import random
from bisect import bisect_left, bisect_right
from collections import OrderedDict
import fib_shadow as S
import fib_edge_test as B
from fib_mtf import D_MS, ts
from fib_fwd_return import holm

SEED_B5 = 20260830
STOP_IDS = ['S1', 'S2', 'S3', 'S4', 'S5', 'S6']
STOP_DESC = OrderedDict([('S1', 'R.low x (1-BUF)  [현행]'), ('S2', 'E - 2 x (E-S1)'), ('S3', 'E - 3 x (E-S1)'), ('S4', 'E - 1.5 x ATR14(4H, 완성봉)'),
                         ('S5', 'E - 2.5 x ATR14(4H, 완성봉)'), ('S6', 'P0 x (1-BUF)  [일봉 구조]')])


def stop_price(sid, c, data, P):
    E_ = c['entry_level']
    s1 = c['stop_level']
    if sid == 'S1':
        return s1
    if sid == 'S2':
        return E_ - 2 * (E_ - s1)
    if sid == 'S3':
        return E_ - 3 * (E_ - s1)
    A = data.atr[c['atr_idx']]                       # atr[t-1]: 진입 4H 봉 직전 완성봉까지
    if sid == 'S4':
        return E_ - 1.5 * A
    if sid == 'S5':
        return E_ - 2.5 * A
    if sid == 'S6':
        return c['P0'] * (1 - P['BUF'])
    raise ValueError(sid)


def draw_baseline_bars(data, cands, rng, n=B.N_R1, window_days=B.WINDOW_DAYS):
    """후보마다 ±5일 창에서 5분봉 n개 균등 추출 (손절 정의와 무관하게 한 번만 뽑아 전 스윕에 공유)."""
    f_ot = data.f_ot
    last = len(f_ot) - 1
    out = {}
    for c in cands:
        T = c['entry_time']
        lo = max(0, bisect_left(f_ot, T - window_days * D_MS))
        hi = min(last, bisect_right(f_ot, T + window_days * D_MS) - 1)
        out[c['candidate_id']] = [rng.randint(lo, hi) for _ in range(n)]
    return out


def _rec(group, src, data, m, entry, stop, c, extra=None):
    o = S.outcome(data, m, entry, stop)
    r = {'group': group, 'src': src, 'entry_time': data.f_ot[m], 'entry_bar': m, 'entry_px': entry, 'stop_px': stop, 'stop_dist_pct': (entry - stop) / entry,
         'year': c['year'], 'block_year': c['year'], 'block_month': ts(c['entry_time'])[:7]}
    r.update(o)
    if extra:
        r.update(extra)
    return r


def sweep(data, P, cands, base_bars):
    """손절 정의별 (전략 레코드, baseline 레코드, skipped). 손절가 >= 진입가인 후보는 그 정의에서 제외하고 센다 (불변식 6)."""
    out = OrderedDict()
    for sid in STOP_IDS:
        strat, base, skipped = [], [], 0
        for c in cands:
            stop = stop_price(sid, c, data, P)
            if not (stop < c['entry_level']):
                skipped += 1
                continue
            pct = (c['entry_level'] - stop) / c['entry_level']
            strat.append(_rec('STRAT_' + sid, c['candidate_id'], data, c['fill_m'], c['entry_level'], stop, c, {'stop_id': sid, 'partial_fine': c['partial_fine']}))
            for k, m in enumerate(base_bars[c['candidate_id']]):
                e = data.f_op[m]
                base.append(_rec('BASE_' + sid, c['candidate_id'], data, m, e, e * (1 - pct), c, {'stop_id': sid, 'draw': k, 'parent_entry_time': c['entry_time']}))
        out[sid] = {'strat': strat, 'base': base, 'skipped': skipped}
    return out


def analyze(sweep_out):
    """손절 정의별 compare (fib_edge_test.compare 재사용) + Holm 조정 p (연도블록 부트스트랩 양측 p)."""
    res = OrderedDict()
    pv = OrderedDict()
    for sid, v in sweep_out.items():
        cmp = B.compare(v['strat'], v['base'], sid)
        cmp['skipped'] = v['skipped']
        # 양측 p: 연도블록 부트스트랩 gap 분포로 (block_bootstrap 은 CI 만 주므로 재계산)
        cmp['p_year'] = boot_p(v['strat'], v['base'], 'block_year')
        pv[sid] = cmp['p_year']
        res[sid] = cmp
    adj = holm(pv)
    for sid in res:
        res[sid]['p_holm'] = adj[sid]
    return res


def boot_p(S_recs, B_recs, block_field, k=2, iters=B.BOOT_ITERS, seed=B.SEED):
    aS, aB = B._agg(S_recs, block_field, k), B._agg(B_recs, block_field, k)
    blocks = sorted(set(aS) | set(aB))
    rng = random.Random(seed)
    nb = len(blocks)
    gaps = []
    for _ in range(iters):
        nS = kS = nB = kB = 0
        for _ in range(nb):
            b = blocks[rng.randrange(nb)]
            if b in aS:
                nS += aS[b][0]; kS += aS[b][1]
            if b in aB:
                nB += aB[b][0]; kB += aB[b][1]
        if nS and nB:
            gaps.append(kS / nS - kB / nB)
    if not gaps:
        return 1.0
    le0 = sum(1 for g in gaps if g <= 0) / len(gaps)
    ge0 = sum(1 for g in gaps if g >= 0) / len(gaps)
    return min(1.0, 2 * min(le0, ge0))


def judge(res):
    """§3.5: 하나 이상의 손절 정의에서 gap>=8, 연도 CI 하한>0, 두 기간 부호 일치, 꼬리 제거 후 gap>0. Holm 조정 후 비유의면 '부분 통과(약)'."""
    passes, weak = [], []
    for sid, c in res.items():
        p = c['periods']
        g1, g2 = p['2019-2022']['gap2R'], p['2023-2026']['gap2R']
        conds = {'gap>=8': c['gap2R'] is not None and c['gap2R'] >= B.GAP_R1_MIN, 'ci_low>0': c['boot_year']['ci_low'] > 0,
                 'period_sign': g1 is not None and g2 is not None and (g1 > 0) == (g2 > 0), 'tail>0': c['tail']['gap2R'] is not None and c['tail']['gap2R'] > 0}
        c['conds'] = conds
        if all(conds.values()):
            (passes if c['p_holm'] < 0.05 else weak).append(sid)
    if passes:
        return 'PASS', passes, weak
    if weak:
        return 'PASS-WEAK', passes, weak
    return 'FAIL', passes, weak
