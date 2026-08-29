# -*- coding: utf-8 -*-
"""fib_fwd_return.py — B4: 손절 없는 순방향 수익률 (작업지시서 testB4B5F §2)

r_H = ln(close(entry_time + H) / entry_px), H ∈ {6h, 24h, 3d, 7d, 14d, 30d}. 손절·익절·청산 없음, 비용 없음.
주 통계 = 후보당 짝지은 창 내 초과수익 excess_H(i) = r_H(전략 i) − mean_j r_H(무작위 j of i).
블록 부트스트랩(연도/월) 으로 mean excess 의 95% CI 와 p 값, Holm–Bonferroni 로 6개 지평 보정.
표준 라이브러리만.
"""
import math
import random
from bisect import bisect_right
from collections import OrderedDict
from fib_mtf import H_MS, D_MS, ts

HORIZONS = OrderedDict([('6h', 6 * H_MS), ('24h', 24 * H_MS), ('3d', 3 * D_MS), ('7d', 7 * D_MS), ('14d', 14 * D_MS), ('30d', 30 * D_MS)])
BOOT_ITERS = 5000
SEED_BOOT = 20260829


def fwd_return(data, entry_time, entry_px, H):
    """entry_time + H 시점 5분봉 종가 대비 로그수익. 그 시점 봉이 없으면 직전 봉 종가(gap_filled). 데이터 종료 이후면 censored."""
    T = entry_time + H
    idx = bisect_right(data.f_ot, T) - 1
    if idx < 0 or T > data.f_ot[-1]:
        return None, False, True
    gap = data.f_ot[idx] != T
    return math.log(data.f_cl[idx] / entry_px), gap, False, data.f_ot[idx]


def measure(data, strat_recs, base_recs):
    """strat_recs: fib_edge_test.strategy_records 출력 (entry_time, entry_px, src=candidate_id, year, block_year/month)
    base_recs : fib_edge_test.gen_R1 출력 (src = parent candidate_id).
    반환 rows(후보별·지평별 r_H) 와 paired(후보별 excess)"""
    by_parent = {}
    for r in base_recs:
        by_parent.setdefault(r['src'], []).append(r)
    rows, paired = [], OrderedDict((h, []) for h in HORIZONS)
    counts = OrderedDict((h, {'censored_s': 0, 'gap_s': 0, 'censored_b': 0, 'gap_b': 0, 'n_pairs': 0}) for h in HORIZONS)
    inv5_bad = 0
    for s in strat_recs:
        row = {'candidate_id': s['src'], 'entry_time': s['entry_time'], 'entry_px': s['entry_px'], 'year': s['year'], 'block_year': s['block_year'], 'block_month': s['block_month']}
        for h, H in HORIZONS.items():
            res = fwd_return(data, s['entry_time'], s['entry_px'], H)
            if res[2]:
                counts[h]['censored_s'] += 1
                row['r_%s' % h] = None
                row['excess_%s' % h] = None
                continue
            r_s, gap_s, _, bar_t = res
            if bar_t <= s['entry_time']:
                inv5_bad += 1
            counts[h]['gap_s'] += gap_s
            row['r_%s' % h] = r_s
            bs = []
            for b in by_parent.get(s['src'], []):
                rb = fwd_return(data, b['entry_time'], b['entry_px'], H)
                if rb[2]:
                    counts[h]['censored_b'] += 1
                    continue
                if rb[3] <= b['entry_time']:
                    inv5_bad += 1
                counts[h]['gap_b'] += rb[1]
                bs.append(rb[0])
            if bs:
                ex = r_s - sum(bs) / len(bs)
                row['excess_%s' % h] = ex
                row['base_mean_%s' % h] = sum(bs) / len(bs)
                paired[h].append({'x': ex, 'r_s': r_s, 'r_b': sum(bs) / len(bs), 'year': s['year'], 'block_year': s['block_year'], 'block_month': s['block_month'], 'cid': s['src']})
                counts[h]['n_pairs'] += 1
            else:
                row['excess_%s' % h] = None
        rows.append(row)
    return rows, paired, counts, inv5_bad


def _agg(items, key):
    agg = {}
    for it in items:
        a = agg.setdefault(it[key], [0, 0.0])
        a[0] += 1
        a[1] += it['x']
    return agg


def block_boot_mean(items, block_field, iters=BOOT_ITERS, seed=SEED_BOOT):
    """블록 리샘플 → 가중 평균 excess 의 분포. 반환 mean, ci_low, ci_high, p_two_sided(부트스트랩 분포가 0 을 넘는 비율 기반)."""
    agg = _agg(items, block_field)
    blocks = sorted(agg)
    if not blocks:
        return {'mean': 0.0, 'ci_low': 0.0, 'ci_high': 0.0, 'p': 1.0, 'blocks': 0}
    rng = random.Random(seed)
    nb = len(blocks)
    means = []
    for _ in range(iters):
        n = s = 0.0
        for _ in range(nb):
            b = blocks[rng.randrange(nb)]
            n += agg[b][0]
            s += agg[b][1]
        if n > 0:
            means.append(s / n)
    means.sort()
    g = len(means)
    point = sum(it['x'] for it in items) / len(items)
    le0 = sum(1 for m in means if m <= 0) / g
    ge0 = sum(1 for m in means if m >= 0) / g
    return {'mean': point, 'ci_low': means[int(0.025 * g)], 'ci_high': means[min(g - 1, int(0.975 * g))], 'p': min(1.0, 2 * min(le0, ge0)), 'blocks': nb}


def holm(pvals):
    """Holm–Bonferroni 조정. pvals: OrderedDict name->p. 반환 name->adjusted p."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    adj, running = {}, 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, (m - i) * p)
        adj[k] = min(1.0, running)
    return adj


def stats(paired):
    """지평별 통계 묶음."""
    out = OrderedDict()
    for h, items in paired.items():
        if not items:
            out[h] = {'n': 0}
            continue
        xs = sorted(it['x'] for it in items)
        n = len(xs)
        st = OrderedDict()
        st['n'] = n
        st['mean_excess'] = sum(xs) / n
        st['median_excess'] = xs[n // 2]
        st['p_pos'] = sum(1 for x in xs if x > 0) / n * 100
        st['mean_r_s'] = sum(it['r_s'] for it in items) / n
        st['mean_r_b'] = sum(it['r_b'] for it in items) / n
        st['raw_gap'] = st['mean_r_s'] - st['mean_r_b']
        st['boot_year'] = block_boot_mean(items, 'block_year')
        st['boot_month'] = block_boot_mean(items, 'block_month')
        cut = int(round(n * 0.05))
        trimmed = xs[cut:n - cut] if n - 2 * cut > 0 else xs
        st['trim_mean'] = sum(trimmed) / len(trimmed)
        p1 = [it['x'] for it in items if it['year'] <= 2022]
        p2 = [it['x'] for it in items if it['year'] >= 2023]
        st['period'] = {'2019-2022': (sum(p1) / len(p1) if p1 else None, len(p1)), '2023-2026': (sum(p2) / len(p2) if p2 else None, len(p2))}
        yr = OrderedDict()
        for it in items:
            yr.setdefault(it['year'], []).append(it['x'])
        st['yearly'] = OrderedDict((y, (sum(v) / len(v), len(v))) for y, v in sorted(yr.items()))
        out[h] = st
    pv = OrderedDict((h, s['boot_year']['p']) for h, s in out.items() if s.get('n'))
    adj = holm(pv)
    for h in out:
        if out[h].get('n'):
            out[h]['p_year'] = pv[h]
            out[h]['p_holm'] = adj[h]
    return out


def judge(st, min_h_ms=3 * D_MS):
    """§2.6: H >= 3d 중 하나 이상에서 mean>0, 연도블록 CI 하한>0, 두 기간 부호 일치, 트림 후 부호 유지. Holm 조정 후 유의하지 않으면 '부분 통과(약)'."""
    passes, weak = [], []
    for h, H in HORIZONS.items():
        s = st.get(h, {})
        if not s.get('n') or H < min_h_ms:
            continue
        p1, p2 = s['period']['2019-2022'][0], s['period']['2023-2026'][0]
        conds = {'mean>0': s['mean_excess'] > 0, 'ci_low>0': s['boot_year']['ci_low'] > 0,
                 'period_sign': p1 is not None and p2 is not None and (p1 > 0) == (p2 > 0) == (s['mean_excess'] > 0),
                 'trim_sign': (s['trim_mean'] > 0) == (s['mean_excess'] > 0)}
        s['conds'] = conds
        if all(conds.values()):
            (passes if s['p_holm'] < 0.05 else weak).append(h)
    if passes:
        return 'PASS', passes, weak
    if weak:
        return 'PASS-WEAK', passes, weak
    return 'FAIL', passes, weak


def overlap_ratio(strat_recs, H=30 * D_MS):
    """후보 쌍 중 [T, T+H) 구간이 겹치는 비율."""
    ts_ = sorted(r['entry_time'] for r in strat_recs)
    n = len(ts_)
    if n < 2:
        return 0.0
    pairs = n * (n - 1) // 2
    ov = 0
    for i in range(n):
        for j in range(i + 1, n):
            if ts_[j] - ts_[i] < H:
                ov += 1
            else:
                break
    return ov / pairs * 100
