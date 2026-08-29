# -*- coding: utf-8 -*-
"""fib_risk_ladder.py — Test H §6 위험 사다리 · 차등 배분 · 순서 MC · §8 0-엣지 분포 (표준 라이브러리만)

거래 순서·R_REAL 은 A1 실제 거래 그대로 (불변식 9). 위험 f 에서 거래당 자산 수익률 = min(f/손절폭, cap_lev) x r_net (fib_long_baseline.trade_returns 와 동일).
"""
import random
from collections import OrderedDict
import fib_mtf as F
import fib_long_baseline as A
from fib_mtf import MM, ts

RISKS = (0.005, 0.0075, 0.01, 0.015, 0.02)
CAP_LEV = 10.0
RISK_A, RISK_BC, CAP_CONCURRENT = 0.0075, 0.005, 0.015
SEED_SEQ, SEED_ZERO = 20261002, 20261001
MC_ITERS = 5000


def yearly_returns(trades_rets):
    """[(trade, ret, lev)] → {year: 복리 수익률%}"""
    out = OrderedDict()
    for t, r, _ in trades_rets:
        y = ts(t['entry_time'])[:4]
        out[y] = out.get(y, 1.0) * max(0.0, 1 + r)
    return OrderedDict((y, (v - 1) * 100) for y, v in out.items())


def ladder(trades, data, years, risks=RISKS, cap=CAP_LEV):
    out = OrderedDict()
    for f in risks:
        tr = A.trade_returns(trades, ('risk', f, cap))
        m = A.metrics([r for _, r, _ in tr], years)
        m['mtm_mdd_close'], m['mtm_mdd_low'] = A.mtm_mdd(trades, data, ('risk', f, cap))
        yr = yearly_returns(tr)
        m['worst_year'] = min(yr.items(), key=lambda kv: kv[1]) if yr else (None, 0.0)
        m['liq_count'] = sum(1 for _, r, _ in tr if r <= -1.0 + 1e-12)
        m['max_lev'] = max(l for _, _, l in tr)
        out[f] = m
    return out


def path_metrics(seq):
    """seq: [(ret_fraction, R)] 순서대로. 반환 dict(n, ret%, mdd%, worst streak, pf(R), mean_R, sum_R)"""
    eq, peak, mdd = 1.0, 1.0, 0.0
    s = w = 0
    gp = gl = 0.0
    for r, R in seq:
        eq *= max(0.0, 1 + r)
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak * 100)
        s = s + 1 if R <= 0 else 0
        w = max(w, s)
        if R > 0:
            gp += R
        else:
            gl -= R
    n = len(seq)
    return {'n': n, 'ret': (eq - 1) * 100, 'mdd': mdd, 'worst': w, 'pf_R': gp / gl if gl > 0 else (9.99 if gp > 0 else 0.0),
            'mean_R': sum(R for _, R in seq) / n if n else 0.0, 'sum_R': sum(R for _, R in seq)}


def tiered(recs, risk_A=RISK_A, risk_BC=RISK_BC, cap_conc=CAP_CONCURRENT, mode='tiered'):
    """recs: P-A 레코드(A1 순서, entry_time/exit_time/R_REAL/stop_pct/grade). mode: tiered | uniform | A_only(필터, 비교용)
    동시 오픈 위험 합 <= cap_conc, 초과 시 신규 진입 skip. 엔진이 동시 포지션 1개라 실제로는 최대 1건이 열려 있다."""
    open_ = []
    seq, skipped, taken = [], 0, []
    for r in sorted(recs, key=lambda x: x['entry_time']):
        open_ = [o for o in open_ if o[0] > r['entry_time']]
        if mode == 'uniform':
            f = risk_BC
        elif mode == 'A_only':
            if r['grade'] != 'A':
                continue
            f = risk_A
        else:
            f = risk_A if r['grade'] == 'A' else risk_BC
        if sum(o[1] for o in open_) + f > cap_conc + 1e-12:
            skipped += 1
            continue
        lev = min(f / r['stop_pct'], CAP_LEV)
        ret = lev * r['r_net']
        seq.append((ret, r['R_REAL']))
        taken.append(r)
        open_.append((r['exit_time'], f))
    m = path_metrics(seq)
    m['skipped'] = skipped
    return m, taken


def tiered_by_period(recs, **kw):
    out = OrderedDict()
    for p in ('DEV', 'TEST', 'ALL'):
        sub = [r for r in recs if p == 'ALL' or r['period'] == p]
        out[p] = tiered(sub, **kw)[0]
    return out


def sequence_mc(recs, seed=SEED_SEQ, iters=MC_ITERS, risk_A=RISK_A, risk_BC=RISK_BC):
    """A1 (R_REAL, grade, stop_pct, r_net) 을 복원추출 → 차등 배분 → 실현 MDD·최대 연패 분포."""
    rng = random.Random(seed)
    n = len(recs)
    mdds, worsts, rets = [], [], []
    for _ in range(iters):
        seq = []
        for _ in range(n):
            r = recs[rng.randrange(n)]
            f = risk_A if r['grade'] == 'A' else risk_BC
            lev = min(f / r['stop_pct'], CAP_LEV)
            seq.append((lev * r['r_net'], r['R_REAL']))
        m = path_metrics(seq)
        mdds.append(m['mdd']); worsts.append(m['worst']); rets.append(m['ret'])
    def pct(xs, q):
        xs = sorted(xs); i = int(round((len(xs) - 1) * q)); return xs[i]
    return {'mdd': {q: pct(mdds, q) for q in (0.5, 0.95, 0.99)}, 'worst': {q: pct(worsts, q) for q in (0.5, 0.95, 0.99)},
            'ret': {q: pct(rets, q) for q in (0.05, 0.5, 0.95)}, 'iters': iters, 'n': n}


def zero_edge(dev_R, seed=SEED_ZERO, iters=MC_ITERS, horizons=(15, 25, 50)):
    """DEV R_REAL 분포의 평균을 0 으로 이동시켜 복원추출한 누적 R 의 5/50/95 백분위."""
    m = sum(dev_R) / len(dev_R)
    shifted = [x - m for x in dev_R]
    rng = random.Random(seed)
    out = OrderedDict()
    sims = {h: [] for h in horizons}
    for _ in range(iters):
        draws = [shifted[rng.randrange(len(shifted))] for _ in range(max(horizons))]
        cum = 0.0
        for i, x in enumerate(draws, 1):
            cum += x
            if i in sims:
                sims[i].append(cum)
    for h in horizons:
        xs = sorted(sims[h])
        out[h] = {q: xs[int(round((len(xs) - 1) * q))] for q in (0.05, 0.5, 0.95)}
    return out, m


def n_for_edge(mean_R, sd_R, t=2.0):
    """평균 R 을 t-통계 2 로 확인하는 데 필요한 거래 수 (독립 가정)."""
    return int((t * sd_R / mean_R) ** 2) + 1 if mean_R > 0 else None
