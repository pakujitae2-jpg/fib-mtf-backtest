# -*- coding: utf-8 -*-
"""fib_wf_long.py — Test H §7 교정 엔진 롱 전용 Walk-forward (운용 기준선)

2차(fib_v2_validate.py) 와 동일한 그리드 64조합·선택 규칙을 교정 엔진(fib_engine_c) 롱 전용에 적용한다.
  그리드: DMIN {6,8,10,12%} x R4 {.236,.382} x R_RATIO {.1,.2} x ATR_MULT {1,1.5} x TOL {.3,.5%}, EXIT=spec, SIDES=long
  연도 통계: 2차와 동일 (거래 진입 연도 귀속, pm = 30%x10x 마진 손익%, 연도 PF>1 판정은 n>=3 인 연도만)
  선택(확장창): 학습 2019..(t-1) 의 합산 n>=15 인 조합 중 (PF>1 연도 수, 최악 연도 수익률, PF) 최대. 동점: first / last.
표준 라이브러리만.
"""
from collections import OrderedDict
import fib_mtf as F
import fib_engine_c as E
import fib_long_baseline as A
from fib_mtf import ts, MM

POS, LEV = 0.30, 10
YEARS = [str(y) for y in range(2019, 2027)]
TEST_YEARS = [2022, 2023, 2024, 2025, 2026]


def grid(base):
    out = []
    for DMIN in (0.06, 0.08, 0.10, 0.12):
        for R4 in (0.236, 0.382):
            for RR in (0.1, 0.2):
                for AM in (1.0, 1.5):
                    for TOL in (0.003, 0.005):
                        out.append(dict(base, DMIN=DMIN, R4=R4, R_RATIO=RR, ATR_MULT=AM, TOL=TOL, EXIT='spec', SIDES='long'))
    return out


def pname(P):
    return 'DMIN %.2f R4 %.3f Rr %.1f ATR %.1f TOL %.3f' % (P['DMIN'], P['R4'], P['R_RATIO'], P['ATR_MULT'], P['TOL'])


def trade_rec(t):
    stop_pct = (t['entry'] - t['stop0']) / abs(t['entry'])
    return {'year': ts(t['entry_time'])[:4], 'exit_year': ts(t['exit_time'])[:4], 'pm': F.pm_of(t, LEV), 'r_net': t['r_net'], 'stop_pct': stop_pct,
            'R': t['r_net'] / stop_pct, 'entry_time': t['entry_time'], 'mae': t['mae'], 'open': t['result'] == 'open'}


def yearly(recs):
    out = {}
    for y in YEARS:
        pms = [r['pm'] for r in recs if r['year'] == y and not r['open']]
        ret = 1.0
        for p in pms:
            ret *= max(0.0, 1 + POS * p / 100)
        out[y] = {'n': len(pms), 'pf': F._pf(pms), 'ret': (ret - 1) * 100, 'pms': pms, 'recs': [r for r in recs if r['year'] == y and not r['open']]}
    return out


def pooled(yr, ys):
    pms = [p for y in ys for p in yr[y]['pms']]
    ret = 1.0
    for p in pms:
        ret *= max(0.0, 1 + POS * p / 100)
    pos = sum(1 for y in ys if yr[y]['n'] >= 3 and yr[y]['pf'] > 1)
    cnt = sum(1 for y in ys if yr[y]['n'] >= 3)
    return {'n': len(pms), 'pf': F._pf(pms), 'ret': (ret - 1) * 100, 'pos': pos, 'cnt': cnt, 'min': min((yr[y]['ret'] for y in ys if yr[y]['n'] >= 3), default=-999)}


def run_grid(data, base):
    """64조합 전 기간 1회 실행 (assert_invariants 포함). 반환 [{'P','recs','yr','cross_year'}]"""
    res = []
    for P in grid(base):
        trades, events, sides, diag = E.run(data, P)
        E.assert_invariants(trades, events, data)
        recs = [trade_rec(t) for t in trades]
        res.append({'P': P, 'recs': recs, 'yr': yearly(recs), 'cross_year': sum(1 for r in recs if r['year'] != r['exit_year'] and not r['open']), 'n': len(recs)})
    return res


def select(res, train, tiebreak):
    cands = []
    for i, r in enumerate(res):
        pl = pooled(r['yr'], train)
        if pl['n'] < 15:
            continue
        cands.append((i, r, pl))
    key = lambda c: (c[2]['pos'], c[2]['min'], c[2]['pf'])
    best = max(key(c) for c in cands)
    ties = [c for c in cands if key(c) == best]
    return (ties[0] if tiebreak == 'first' else ties[-1]), len(ties), len(cands)


def metrics_risk(recs, f=0.01, cap=10.0):
    """WF 검증 거래 묶음의 지표: 승률, PF(pm), 건당 R, risk f 총수익/실현 MDD, 30%x10x 총수익/MDD."""
    out = {'n': len(recs)}
    if not recs:
        return out
    pms = [r['pm'] for r in recs]
    out['wr'] = sum(1 for p in pms if p > 0) / len(pms) * 100
    out['pf'] = F._pf(pms)
    out['mean_R'] = sum(r['R'] for r in recs) / len(recs)
    out['sum_R'] = sum(r['R'] for r in recs)
    for lab, seq in (('risk1', [(min(f / r['stop_pct'], cap) * r['r_net'] if r['mae'] > -(1.0 / min(f / r['stop_pct'], cap) - MM) else -1.0) for r in recs]),
                     ('30x10', [POS * p / 100 for p in pms])):
        eq, peak, mdd = 1.0, 1.0, 0.0
        for x in seq:
            eq *= max(0.0, 1 + x)
            peak = max(peak, eq)
            mdd = max(mdd, (peak - eq) / peak * 100)
        out['ret_' + lab] = (eq - 1) * 100
        out['mdd_' + lab] = mdd
    return out


def walk_forward(res, tiebreak):
    rows, pool = [], []
    for ty in TEST_YEARS:
        train = [str(y) for y in range(2019, ty)]
        (i, r, pl), nties, ncand = select(res, train, tiebreak)
        te = r['yr'][str(ty)]
        pool += te['recs']
        rows.append({'test_year': ty, 'train': '%s~%s' % (train[0], train[-1]), 'combo_idx': i, 'params': pname(r['P']), 'train_n': pl['n'], 'train_pos': pl['pos'], 'train_cnt': pl['cnt'],
                     'train_pf': pl['pf'], 'train_ret': pl['ret'], 'ties': nties, 'candidates': ncand, 'test_n': te['n'], 'test_pf': te['pf'], 'test_ret': te['ret'],
                     'test_mean_R': (sum(x['R'] for x in te['recs']) / te['n']) if te['n'] else None})
    return rows, pool, metrics_risk(sorted(pool, key=lambda r: r['entry_time']))
