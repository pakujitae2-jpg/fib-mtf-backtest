# -*- coding: utf-8 -*-
"""fib_long_baseline.py — Test A: 롱 전용 교정 baseline (작업지시서 testAB §2)

fib_engine_c 는 읽기 전용으로 쓴다. 여기에는
  * A0 회귀 확인 (양방향 Corrected V2/V3 = 4차 보고서 값)
  * A1/A2 실행 (freeze config + SIDES='long')
  * 성과표: 30%x10x 및 리스크 고정(0.5/1/2%) — 청산시점 MDD + MTM MDD(5m close/low), Sharpe/Sortino, 손절폭·청산사유 분포
  * 추가 표: 연도별 / 보유기간별 기여 / 꼬리 의존성 / MFE 도달률 / 신호 퍼널
  * §2.3 롱 전환으로 추가·삭제된 거래의 사유 태깅
"""
import json
from collections import Counter, OrderedDict
import fib_mtf as F
import fib_engine_c as E
from fib_mtf import D_MS, H_MS, FEE_MAKER, FEE_TAKER, SLIP, MM, ts

SEED_EQ = 10000.0
EXPECT_A0 = {'V2': dict(n=150, pf=1.40, ret=96), 'V3': dict(n=141, pf=1.10, ret=-16)}


# ------------------------------------------------------------------ 데이터
def load_data(V):
    if V == 'V2':
        return E.load_data('2019-03-01')
    return E.Data(F.load_csv('btcusdt_1d_2017.csv'), F.load_csv('btcusdt_fut_4h.csv'), F.load_csv('btcusdt_fut_5m.csv'), '2019-12-15',
                  funding=F.load_funding('btcusdt_funding.csv'))


def years_of(data):
    return (data.h_ot[data.LAST] - data.h_ot[data.start4]) / D_MS / 365.25


# ------------------------------------------------------------------ 사이징 -> 거래별 자산 수익률
def trade_returns(trades, sizing):
    """sizing = ('fixed', pos_f, lev) | ('risk', f, cap_lev).  반환 [(trade, ret_fraction, lev_used)] (미청산 제외)"""
    out = []
    for t in trades:
        if t['result'] == 'open':
            continue
        if sizing[0] == 'fixed':
            _, pos_f, lev = sizing
            out.append((t, pos_f * F.pm_of(t, lev) / 100.0, lev))
        else:
            _, f, cap = sizing
            risk = (t['entry'] - t['stop0']) / abs(t['entry'])
            lev = min(f / risk, cap) if risk > 0 else cap
            ret = lev * t['r_net']
            if t['mae'] <= -(1.0 / lev - MM):
                ret = -1.0
            out.append((t, ret, lev))
    return out


def metrics(rets, years, seed=SEED_EQ):
    """rets: 거래별 자산 수익률(분수) 리스트. 청산시점 equity 기준 지표."""
    n = len(rets)
    eq, peak, mdd = seed, seed, 0.0
    streak = worst = 0
    gp = gl = 0.0
    for r in rets:
        eq *= max(0.0, 1 + r)
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak * 100)
        if r > 0:
            gp += r
            streak = 0
        else:
            gl -= r
            streak += 1
            worst = max(worst, streak)
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    avg = lambda xs: sum(xs) / len(xs) if xs else 0.0
    mean = avg(rets)
    sd = (sum((r - mean) ** 2 for r in rets) / n) ** 0.5 if n > 1 else 0.0
    dsd = (sum(min(0.0, r) ** 2 for r in rets) / n) ** 0.5 if n > 1 else 0.0
    per_year = n / max(years, 0.5)
    return OrderedDict([
        ('n', n), ('wr', len(wins) / n * 100 if n else 0.0), ('pf', gp / gl if gl > 0 else (9.99 if gp > 0 else 0.0)),
        ('exp', mean * 100), ('ret', (eq / seed - 1) * 100), ('cagr', ((eq / seed) ** (1 / years) - 1) * 100 if eq > 0 and years > 0 else -100.0),
        ('mdd', mdd), ('avg_win', avg(wins) * 100), ('avg_loss', avg(losses) * 100),
        ('rr', (avg(wins) / -avg(losses)) if losses and avg(losses) < 0 else 0.0), ('worst', worst),
        ('sharpe', mean / sd * per_year ** 0.5 if sd > 0 else 0.0), ('sortino', mean / dsd * per_year ** 0.5 if dsd > 0 else 0.0),
        ('eq', eq)])


def mtm_mdd(trades, data, sizing, seed=SEED_EQ):
    """Mark-to-market MDD (5m close / 5m low) — fib_engine_c.evaluate_mtm 와 같은 공식, 사이징만 일반화.
    fixed: margin = eq*pos_f, lev 고정 / risk: margin = eq(전체), lev = min(f/risk, cap)."""
    eq, peak = seed, seed
    mdd_c = mdd_l = 0.0
    for t, ret, lev in trade_returns(trades, sizing):
        e = t['entry']
        sd = t['side']
        margin = eq * sizing[1] if sizing[0] == 'fixed' else eq
        fee_in = FEE_TAKER if t.get('taker') else FEE_MAKER
        fills = sorted(t['fill_detail'], key=lambda x: x[1])
        m0 = t['fill_m'] + (1 if t['fill_at_close'] else 0) if t['fill_m'] is not None else None
        m1 = t['exit_m']
        fe = t['funding_events']
        if m0 is not None and m1 is not None and m0 <= m1:
            fi = fk = 0
            realized, rem, fund_acc = 0.0, 1.0, 0.0
            for m in range(m0, m1 + 1):
                bar_ct = data.f_ot[m] + data.fine_ms - 1
                while fi < len(fills) and fills[fi][1] <= bar_ct:
                    _, ftm, px, fr, kind = fills[fi]
                    realized += fr * ((px - e) / abs(e) - (FEE_MAKER if kind == 'tp' else FEE_TAKER) - (SLIP if kind == 'stop' else 0.0))
                    rem -= fr
                    fi += 1
                while fk < len(fe) and fe[fk][0] <= bar_ct:
                    fund_acc += fe[fk][1]
                    fk += 1
                r_close = realized + max(rem, 0.0) * (sd.f_cl[m] - e) / abs(e) - fee_in - fund_acc
                r_low = realized + max(rem, 0.0) * (sd.f_lo[m] - e) / abs(e) - fee_in - fund_acc
                eq_c = eq + margin * max(-1.0, r_close * lev)
                eq_l = eq + margin * max(-1.0, r_low * lev)
                peak = max(peak, eq_c)
                mdd_c = max(mdd_c, (peak - eq_c) / peak * 100)
                mdd_l = max(mdd_l, (peak - eq_l) / peak * 100)
        eq *= max(0.0, 1 + ret)
        peak = max(peak, eq)
        dd = (peak - eq) / peak * 100
        mdd_c, mdd_l = max(mdd_c, dd), max(mdd_l, dd)
    return mdd_c, mdd_l


SIZINGS = OrderedDict([('30%x10x', ('fixed', 0.30, 10)), ('risk0.5%', ('risk', 0.005, 10.0)), ('risk1%', ('risk', 0.01, 10.0)), ('risk2%', ('risk', 0.02, 10.0))])


def perf_table(trades, data):
    yrs = years_of(data)
    out = OrderedDict()
    for name, sz in SIZINGS.items():
        rets = [r for _, r, _ in trade_returns(trades, sz)]
        m = metrics(rets, yrs)
        m['mtm_mdd_close'], m['mtm_mdd_low'] = mtm_mdd(trades, data, sz)
        m['avg_lev'] = sum(l for _, _, l in trade_returns(trades, sz)) / max(1, len(rets))
        out[name] = m
    return out


def stop_dist_stats(trades):
    xs = sorted((t['entry'] - t['stop0']) / abs(t['entry']) * 100 for t in trades)
    if not xs:
        return {}
    n = len(xs)
    return {'median': xs[n // 2], 'mean': sum(xs) / n, 'p95': xs[min(n - 1, int(round(0.95 * (n - 1))))], 'max': xs[-1], 'min': xs[0]}


def exit_reasons(trades):
    return dict(Counter(t['result'] for t in trades))


# ------------------------------------------------------------------ 추가 표 (§2.4)
def pm(t, lev=10):
    return F.pm_of(t, lev)


def yearly(trades):
    out = OrderedDict()
    for t in trades:
        if t['result'] == 'open':
            continue
        y = ts(t['entry_time'])[:4]
        r = out.setdefault(y, {'n': 0, 'wins': 0, 'sum_pm': 0.0, 'gp': 0.0, 'gl': 0.0})
        p = pm(t)
        r['n'] += 1
        r['wins'] += p > 0
        r['sum_pm'] += p
        if p > 0:
            r['gp'] += p
        else:
            r['gl'] -= p
    for y, r in out.items():
        r['pf'] = r['gp'] / r['gl'] if r['gl'] > 0 else (9.99 if r['gp'] > 0 else 0.0)
        r['wr'] = r['wins'] / r['n'] * 100
    return out


HOLD_BUCKETS = [('<1일', 0, 24), ('1~7일', 24, 168), ('7~30일', 168, 720), ('30일+', 720, 1e9)]


def holding_contrib(trades):
    closed = [t for t in trades if t['result'] != 'open']
    total = sum(pm(t) for t in closed)
    out = OrderedDict()
    for lab, lo, hi in HOLD_BUCKETS:
        xs = [t for t in closed if lo <= t['hold_h'] < hi]
        s = sum(pm(t) for t in xs)
        out[lab] = {'n': len(xs), 'wins': sum(1 for t in xs if pm(t) > 0), 'sum_pm': s, 'contrib_pct': s / total * 100 if total else 0.0}
    return out, total


def tail_dependency(trades, ks=(0, 1, 2, 3, 5, 10)):
    pms = sorted((pm(t) for t in trades if t['result'] != 'open'), reverse=True)
    out = OrderedDict()
    for k in ks:
        rest = pms[k:]
        out[k] = {'pf': F._pf(rest) if rest else 0.0, 'sum_pm': sum(rest), 'n': len(rest)}
    return out


def mfe_reach(trades, ks=(1, 2, 3, 5, 10)):
    closed = [t for t in trades if t['result'] != 'open']
    rs = []
    for t in closed:
        dist = (t['entry'] - t['stop0']) / abs(t['entry'])
        rs.append(t.get('mfe', 0.0) / dist if dist > 0 else 0.0)
    out = OrderedDict((k, sum(1 for r in rs if r >= k) / len(rs) * 100 if rs else 0.0) for k in ks)
    out['median_R'] = sorted(rs)[len(rs) // 2] if rs else 0.0
    out['n'] = len(rs)
    return out


def funnel(events, side=1):
    c = Counter()
    cancel = Counter()
    for (t, s, kind, d, tm, det) in events:
        if s != side:
            continue
        if kind in ('D_ARM', 'D_DISARM', 'SIGNAL', 'ORDER_CREATE', 'FILL', 'R_INVALID', 'V', 'V_POS', 'SKIP_V', 'R_REPLACED', 'R_CONFIRM'):
            c[kind] += 1
        if kind == 'ORDER_CANCEL':
            cancel[det.get('reason', '?')] += 1
    return {'counts': dict(c), 'cancel_reasons': dict(cancel)}


# ------------------------------------------------------------------ §2.3 롱 전환 추가 거래 사유
def tag_added(a0_trades, a0_events, a1_trades):
    """diff_trades(long_subset_of_A0, A1) + added/removed 사유.
    SKIP_V_REMOVED : A0 에서 같은 R 키에 SKIP_V 이벤트(롱)가 있었음
    SLOT_FREED     : A1 체결 시각에 A0 의 숏 포지션이 열려 있었음
    OTHER          : 위 둘 다 아님 (연쇄 효과 등)"""
    a0_long = [t for t in a0_trades if t['side'].s > 0]
    dd = E.diff_trades(a0_long, a1_trades)
    skip_keys = {det.get('key') for (t, s, kind, d, tm, det) in a0_events if kind == 'SKIP_V' and s > 0}
    short_iv = [(t['entry_time'], t['exit_time']) for t in a0_trades if t['side'].s < 0]
    added = []
    for t in dd['added']:
        k = t['key'][1]
        if k in skip_keys:
            reason = 'SKIP_V_REMOVED'
        elif any(a <= t['entry_time'] <= b for a, b in short_iv):
            reason = 'SLOT_FREED'
        else:
            reason = 'OTHER'
        added.append((t, reason))
    a1_by_arm = {}
    for t in a1_trades:
        a1_by_arm.setdefault(t['D_arm_time'], []).append(t)
    removed = []
    for t in dd['removed']:
        earlier = [u for u in a1_by_arm.get(t['D_arm_time'], []) if u['entry_time'] < t['entry_time']]
        removed.append((t, 'CASCADE_EARLIER_FILL_SAME_ARM' if earlier else 'OTHER'))
    changed = []
    for x, y in dd['changed']:
        why = 'ENTRY_TIME_SHIFT' if x['entry_time'] != y['entry_time'] else 'EXIT_DIFF'
        if x['entry_time'] != y['entry_time'] and any(a <= y['entry_time'] <= b or a <= x['entry_time'] <= b for a, b in short_iv):
            why = 'ENTRY_TIME_SHIFT(SLOT)'
        changed.append((x, y, why))
    return {'added': added, 'removed': removed, 'changed': changed, 'common': len(dd['common']),
            'sum_pm_a0_long': sum(pm(t) for t in a0_long if t['result'] != 'open'), 'sum_pm_a1': sum(pm(t) for t in a1_trades if t['result'] != 'open')}


# ------------------------------------------------------------------ 실행
def run_A0(V, data, config):
    trades, events, sides, diag = E.run(data, config)
    e = F.evaluate(trades, 0.30, 10, SEED_EQ, years_of(data))
    E.assert_invariants(trades, events, data)
    exp = EXPECT_A0[V]
    ok = e['n'] == exp['n'] and round(e['pf'], 2) == exp['pf'] and round(e['ret']) == exp['ret']
    return {'trades': trades, 'events': events, 'eval': e, 'ok': ok, 'expected': exp, 'diag': dict(diag)}


def run_long(data, config):
    P = dict(config, SIDES='long')
    trades, events, sides, diag = E.run(data, P)
    E.assert_invariants(trades, events, data)
    return {'P': P, 'trades': trades, 'events': events, 'diag': dict(diag)}


def analyze(res, data, events):
    tr = res['trades']
    hold, total = holding_contrib(tr)
    return OrderedDict([
        ('perf', perf_table(tr, data)), ('stop_dist', stop_dist_stats(tr)), ('exit_reasons', exit_reasons(tr)),
        ('yearly', yearly(tr)), ('holding', hold), ('holding_total_pm', total), ('tail', tail_dependency(tr)),
        ('mfe', mfe_reach(tr)), ('funnel', funnel(events, 1))])
