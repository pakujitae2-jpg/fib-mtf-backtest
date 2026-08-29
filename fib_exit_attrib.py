# -*- coding: utf-8 -*-
"""fib_exit_attrib.py — F′: 청산 귀속(F′-1 setup 내 진입 무작위화, F′-2 캘린더 무작위 진입) + F′-0 벤치마크
(작업지시서 testB4B5F §4)

엔진 fib_engine_c.run() 은 신호 없이 쓸 수 없으므로, 포지션 관리 규칙만 떼어 낸 시뮬레이터 simulate_trade() 를 둔다.
규칙은 엔진과 동일 (5분봉 순서: 예약 시장가 청산 → 손절 → 목표(+BE) → V/P0 훼손 감지 → MAE/MFE; 일 전환 시 dexit 를 4H 시가에;
데이터 종료 시 강제 종료; 비용 FEE_MAKER/FEE_TAKER/SLIP, 펀딩 실제 시각·잔여수량). 실제 A1/A2 거래에 같은 진입을 넣으면
엔진 결과를 그대로 재현해야 하며 (validate_simulator), 그 회귀를 통과한 뒤에만 몬테카를로에 쓴다.

일봉 ARM/P0/lastL 상태와 4H R 확정 시각은 가격 경로만의 함수(체결 무관) 라 별도 재생(replay_daily / replay_r_confirms) 으로 얻는다.
표준 라이브러리만.
"""
import math
import random
from bisect import bisect_left, bisect_right
from collections import OrderedDict
import fib_mtf as F
import fib_engine_c as E
import fib_long_baseline as A
from fib_mtf import EPS, H_MS, D_MS, FEE_MAKER, FEE_TAKER, SLIP, FUNDING, MM, FIB_EXT, ts

SEED_F1, SEED_F2, SEED_F0 = 20260901, 20260902, 20260903
MC_RUNS = 200
COST = dict(FEE_MAKER=FEE_MAKER, FEE_TAKER=FEE_TAKER, SLIP=SLIP, MM=MM)


class _LongSide:
    """A.mtm_mdd / A.trade_returns 가 요구하는 side 인터페이스 (롱 = 실제 가격)."""
    def __init__(self, data):
        self.s, self.f_cl, self.f_lo, self.f_hi = 1, data.f_cl, data.f_lo, data.f_hi


# ------------------------------------------------------------------ 상태 재생 (체결과 무관한 가격 함수)
def replay_daily(data, P):
    """일봉 ZigZag 를 엔진과 같은 순서로 재생. 반환 state[d] = dict(armed, P0, H1, lastL, arm_day, pivL_last, ev)
    (엔진은 각 날짜 전환 시 daily_update(d-1) 을 호출하므로 state[d] = d 일 종가까지 처리한 상태)."""
    sd = E.Side(+1, data, dict(P, SIDES='long'), frozenset())
    n_days = len(data.d_ot)
    state = []
    piv_any = None
    for d in range(n_days):
        ev = sd.daily_update(d)
        if sd.pivL:
            piv_any = sd.pivL[-1][1]
        state.append({'armed': sd.armed, 'P0': sd.P0, 'H1': sd.H1, 'lastL': sd.lastL, 'arm_day': sd.arm_day, 'ev': ev,
                      'zz_low_any': piv_any})
    return state


def replay_r_confirms(data, P):
    """4H ZigZag 를 엔진 워밍업(start4-300)부터 재생해 롱 R 확정봉 index 목록(오름차순) 과 R 값을 반환."""
    sd = E.Side(+1, data, dict(P, SIDES='long'), frozenset())
    out = []
    for t in range(max(0, data.start4 - 300), data.LAST + 1):
        sd.track_anchor()
        if sd.h4_update(t):
            out.append((t, sd.R))
    return out


# ------------------------------------------------------------------ 청산 기계
def w_targets(data, d, entry):
    pw = data.prev_week[d]
    if pw is None:
        return []
    wh, wl = pw[0], pw[1]
    rng_ = wh - wl
    return [x for x in [wh + rng_ * f for f in FIB_EXT] if x > entry + 0.003 * abs(entry)]


def build_targets(P, data, d, entry, stop):
    ex = P['EXIT']
    if ex == 'spec':
        return [(x, 0.25) for x in w_targets(data, d, entry)], True, False
    if ex == 'halfR2spec':
        return [(entry + 2.0 * (entry - stop), 0.5)] + [(x, 0.125) for x in w_targets(data, d, entry)], True, True
    if ex == 'halfR2':
        return [(entry + 2.0 * (entry - stop), 0.5)], True, True
    if ex in ('tpR2', 'tpR3'):
        return [(entry + (2.0 if ex == 'tpR2' else 3.0) * (entry - stop), 1.0)], False, False
    raise ValueError(ex)


def simulate_trade(data, P, m_entry, entry, stop, P0, daily_state, taker, entry_at_open,
                   v_ref_fn=None, dexit_ref_fn=None, signal_id='sim', limit_hi_ref=None):
    """엔진 규칙으로 한 포지션을 청산까지 진행. 반환 trade dict (A.trade_returns / A.mtm_mdd 호환).
    m_entry     : 진입 5분봉 index
    entry_at_open: True 면 봉 시가 시장가 진입(무작위 진입), False 면 지정가 터치(실제 거래 재현)
    v_ref_fn(d)  : (F′-2) V 기준선 함수 — None 이면 엔진 규칙(고정 P0 또는 armed 상태의 현재 P0)
    dexit_ref_fn(d): (F′-2) dexit 기준선 함수 — None 이면 엔진 규칙(lastL 없으면 P0)
    진입 5분봉: 손절만 검사 (Entry→Stop 불리한 순서, TP 는 다음 봉부터) — 엔진 ENTRYBAR_TP off 와 동일 규칙"""
    f_ot, f_op, f_hi, f_lo, f_cl = data.f_ot, data.f_op, data.f_hi, data.f_lo, data.f_cl
    fine_ms = data.fine_ms
    t0 = bisect_right(data.h_ot, f_ot[m_entry]) - 1
    d0 = data.h_day[t0]
    tg, d_exit, be = build_targets(P, data, d0, entry, stop)
    entry_time = f_ot[m_entry]
    pos = {'side': _LongSide(data), 't0': t0, 'entry': entry, 'stop': stop, 'stop0': stop, 'frac': 1.0, 'tgts': tg, 'd_exit': d_exit, 'be': be,
           'fills': [], 'fill_detail': [], 'peak': entry, 'mae': 0.0, 'mfe': 0.0, 'P0': P0, 'taker': taker, 'entry_time': entry_time,
           'fill_m': m_entry, 'fill_at_close': False, 'signal_id': signal_id, 'funding_events': [], 'seq': [(entry_time, 'FILL', entry, 1.0)],
           'day': d0, 'targets0': list(tg), 'entry_at_open': entry_at_open}
    done = {'v': False}

    def close(m, px, fr, kind, tm):
        pos['fills'].append((bisect_right(data.h_ot, f_ot[m]) - 1, px, fr, kind))
        pos['fill_detail'].append((m, tm, px, fr, kind))
        pos['frac'] -= fr
        x = (px - entry) / abs(entry)
        if kind == 'stop':
            pos['mae'] = min(pos['mae'], x)
        elif kind == 'tp':
            pos['mfe'] = max(pos['mfe'], x)
        else:
            pos['mae'], pos['mfe'] = min(pos['mae'], x), max(pos['mfe'], x)
        pos['seq'].append((tm, 'EXIT_' + kind.upper(), px, fr))
        if pos['frac'] <= 1e-9:
            done['v'] = True
            finish(m, tm)

    def finish(m, tm):
        r, fee = 0.0, (FEE_TAKER if taker else FEE_MAKER)
        for (_, px, fr, kind) in pos['fills']:
            r += fr * (px - entry) / abs(entry)
            fee += fr * (FEE_MAKER if kind == 'tp' else FEE_TAKER)
            if kind == 'stop':
                r -= fr * SLIP
        et, xt = entry_time, tm
        fund, fev = 0.0, []
        if data.fund_ts:
            a = bisect_right(data.fund_ts_norm, et)
            b = bisect_right(data.fund_ts_norm, xt)
            for k in range(a, b):
                ft = data.fund_ts_norm[k]
                rem = 1.0 - sum(fr for (_, ftm, _, fr, _) in pos['fill_detail'] if ftm < ft)
                if rem <= 1e-9:
                    break
                amt = data.fund_rate[k] * rem
                fund += amt
                fev.append((ft, amt))
        else:
            ft = (et // (8 * H_MS) + 1) * 8 * H_MS
            while ft <= xt:
                rem = 1.0 - sum(fr for (_, ftm, _, fr, _) in pos['fill_detail'] if ftm < ft)
                if rem <= 1e-9:
                    break
                fund += FUNDING * rem
                fev.append((ft, FUNDING * rem))
                ft += 8 * H_MS
        pos.update(funding=fund, funding_events=fev, fee=fee, r_net=r - fee - fund, exit_time=tm, exit_m=m, hold_h=(tm - et) / H_MS,
                   result=pos['fills'][-1][3], exit_reason=pos['fills'][-1][3], t1=bisect_right(data.h_ot, f_ot[m]) - 1)

    def manage(m, stop_only=False):
        lo, hi, ct = f_lo[m], f_hi[m], f_ot[m] + fine_ms - 1
        if lo <= pos['stop'] + EPS:
            close(m, pos['stop'], pos['frac'], 'stop', ct)
            return
        if stop_only:
            return
        while not done['v'] and pos['tgts'] and hi >= pos['tgts'][0][0] - EPS:
            px, fr = pos['tgts'].pop(0)
            close(m, px, min(fr, pos['frac']), 'tp', ct)
            if not done['v'] and pos['be']:
                pos['stop'] = max(pos['stop'], entry + 0.002 * abs(entry))

    # ---- 진입 봉
    manage(m_entry, stop_only=True)
    if done['v']:
        return pos
    pending = None
    cur_t, cur_day = t0, d0
    # entry bar: V / P0-break detection too (engine step 4 runs after the fill in the same bar)
    st0 = daily_state[d0 - 1] if d0 - 1 >= 0 else None
    lo0 = f_lo[m_entry]
    if v_ref_fn is not None:
        ref0 = v_ref_fn(d0 - 1)
        hit0 = ref0 is not None and lo0 < ref0 - EPS
    else:
        hit0 = lo0 < P0 - EPS or (st0 is not None and st0['armed'] and st0['P0'] is not None and lo0 < st0['P0'] - EPS)
    if hit0:
        pending = 'v'
        pos['seq'].append((f_ot[m_entry] + fine_ms - 1, 'V_DETECT', P0, 0))
    pos['peak'] = max(pos['peak'], f_hi[m_entry])
    pos['mae'] = min(pos['mae'], (f_lo[m_entry] - entry) / abs(entry))
    pos['mfe'] = max(pos['mfe'], (f_hi[m_entry] - entry) / abs(entry))
    m = m_entry + 1
    n = len(f_ot)
    while m < n:
        t = cur_t
        while t + 1 <= data.LAST and f_ot[m] >= data.h_ot[t + 1]:
            t += 1
        if t > data.LAST:
            break
        if t != cur_t:
            cur_t = t
            d = data.h_day[t]
            if d != cur_day:                                            # 새 날: 일봉 종가 처리 -> dexit (4H 시가)
                st = daily_state[d - 1]
                if pos['d_exit']:
                    if dexit_ref_fn is not None:
                        ref = dexit_ref_fn(d - 1)
                    else:
                        ref = st['lastL'] if st['lastL'] is not None else P0
                    if ref is not None and data.d_cl[d - 1] < ref - EPS:
                        close(m, data.h_op[t], pos['frac'], 'dexit', data.h_ot[t])
                        if done['v']:
                            return pos
                cur_day = d
        # 1) 예약 V 청산 (다음 5분봉 시가)
        if pending is not None:
            close(m, f_op[m], pos['frac'], pending, f_ot[m])
            if done['v']:
                return pos
            pending = None
        # 2) 손절 / 목표
        manage(m)
        if done['v']:
            return pos
        # 3) V / P0 훼손 감지 (다음 봉 시가 실행)
        lo = f_lo[m]
        ct = f_ot[m] + fine_ms - 1
        st = daily_state[cur_day - 1] if cur_day - 1 >= 0 else None
        if v_ref_fn is not None:
            ref = v_ref_fn(cur_day - 1)
            hit = ref is not None and lo < ref - EPS
        else:
            hit = lo < P0 - EPS or (st is not None and st['armed'] and st['P0'] is not None and lo < st['P0'] - EPS)
        if hit and pending is None:
            pending = 'v'
            pos['seq'].append((ct, 'V_DETECT', P0, 0))
        # 4) MAE/MFE
        pos['peak'] = max(pos['peak'], f_hi[m])
        pos['mae'] = min(pos['mae'], (lo - entry) / abs(entry))
        pos['mfe'] = max(pos['mfe'], (f_hi[m] - entry) / abs(entry))
        m += 1
        if m < n and f_ot[m] > data.h_ct[data.LAST]:
            break
    # 데이터 종료: 강제 종료
    mL = min(bisect_right(f_ot, data.h_ct[data.LAST]) - 1, n - 1)
    pos['fills'].append((data.LAST, data.h_cl[data.LAST], pos['frac'], 'open'))
    pos['fill_detail'].append((mL, data.h_ct[data.LAST], data.h_cl[data.LAST], pos['frac'], 'open'))
    pos['seq'].append((data.h_ct[data.LAST], 'EXIT_OPEN', data.h_cl[data.LAST], pos['frac']))
    pos['frac'] = 0.0
    finish(mL, data.h_ct[data.LAST])
    return pos


def validate_simulator(data, P, trades, daily_state):
    """실제 거래(엔진) 를 같은 진입으로 재현 — r_net/청산사유/exit_time 일치 여부."""
    mism = []
    for t in trades:
        s = simulate_trade(data, P, t['fill_m'], t['entry'], t['stop0'], t['P0'], daily_state, taker=bool(t.get('taker')), entry_at_open=False,
                           signal_id=t['signal_id'])
        if abs(s['r_net'] - t['r_net']) > 1e-9 or s['result'] != t['result'] or s['exit_time'] != t['exit_time']:
            mism.append((t['signal_id'], t['result'], s['result'], round(t['r_net'], 6), round(s['r_net'], 6), ts(t['exit_time']), ts(s['exit_time'])))
    return mism


# ------------------------------------------------------------------ F′-1: R 유효 구간
def r_windows(data, P, trades, daily_state, r_confirms):
    """각 실제 거래의 R 유효 구간 [start, end) (ms). start = R 확정 다음 4H봉 시가.
    end = min(다음 R 확정봉 종료+1, R.low 이탈 5분봉 종료+1(그 봉 진입 가능), P0 훼손 5분봉 종료+1, DISARM 4H봉 시가, 데이터 끝)."""
    conf_bars = [t for t, _ in r_confirms]
    out = []
    for tr in trades:
        R_t = tr['key'][1]
        R_low, P0 = tr['entry_R']['ENTRY_R_LOW'], tr['P0']
        start = data.h_ot[R_t + 1]
        ends = {'data_end': data.h_ct[data.LAST] + 1}
        i = bisect_right(conf_bars, R_t)
        if i < len(conf_bars):
            ends['R_replaced'] = data.h_ct[conf_bars[i]] + 1
        m0 = bisect_left(data.f_ot, start)
        for m in range(m0, len(data.f_ot)):
            if data.f_lo[m] < R_low - EPS:
                ends['R_invalid'] = data.f_ot[m] + data.fine_ms
                break
        for m in range(m0, len(data.f_ot)):
            if data.f_lo[m] < P0 - EPS:
                ends['V'] = data.f_ot[m] + data.fine_ms
                break
        # DISARM: ARM 이후 첫 L 피벗(=lastL 이 새로 생김) 다음날 4H 시가
        arm_day = tr['D_arm_day'] if tr.get('D_arm_day') is not None else data.h_day[R_t]
        for d in range(data.h_day[R_t + 1], len(daily_state)):
            if daily_state[d]['ev'] == 'DISARM' or (d > arm_day and daily_state[d]['lastL'] is not None and not daily_state[d]['armed']):
                nd = bisect_left(data.h_ot, data.d_ot[d] + D_MS)
                if nd <= data.LAST:
                    ends['DISARM'] = data.h_ot[nd]
                break
        end_key = min(ends, key=lambda k: ends[k])
        end = ends[end_key]
        assert start <= tr['entry_time'] < end, (tr['signal_id'], ts(start), ts(tr['entry_time']), ts(end), end_key)
        out.append({'trade': tr, 'start': start, 'end': end, 'end_reason': end_key, 'R_low': R_low, 'P0': P0, 'R_t': R_t})
    return out


def draw_window_entry(data, w, rng, stop, max_try=20):
    """유효 구간 안에서 5분봉 균등 추출, 시가 진입. 시가 <= 손절이면 재추출(최대 max_try) 후 None."""
    a = bisect_left(data.f_ot, w['start'])
    b = bisect_left(data.f_ot, w['end'])
    if b <= a:
        return None
    for _ in range(max_try):
        m = rng.randint(a, b - 1)
        if data.f_op[m] > stop:
            return m
    return None


# ------------------------------------------------------------------ 몬테카를로 공통
def run_sequence(data, P, entries, daily_state, taker, v_ref_fn=None, dexit_ref_fn=None):
    """entries: [(m_entry, entry_px, stop, P0, signal_id, extra)] 를 진입 시각 순으로 처리, 동시 포지션 1개 (겹치면 skip)."""
    entries = sorted(entries, key=lambda x: x[0])
    trades, blocked = [], 0
    last_exit = -1
    for (m, e, stop, P0, sid, extra) in entries:
        if data.f_ot[m] < last_exit:
            blocked += 1
            continue
        tr = simulate_trade(data, P, m, e, stop, P0, daily_state, taker=taker, entry_at_open=True, v_ref_fn=v_ref_fn, dexit_ref_fn=dexit_ref_fn, signal_id=sid)
        tr['extra'] = extra
        trades.append(tr)
        last_exit = tr['exit_time']
    return trades, blocked


def run_metrics(trades, data, years, with_mtm=True):
    out = OrderedDict()
    for name, sz in (('risk1%', ('risk', 0.01, 10.0)), ('30%x10x', ('fixed', 0.30, 10))):
        rets = [r for _, r, _ in A.trade_returns(trades, sz)]
        m = A.metrics(rets, years)
        m['sum_pm'] = sum(F.pm_of(t, 10) for t in trades if t['result'] != 'open')
        if with_mtm:
            m['mtm_mdd_close'], m['mtm_mdd_low'] = A.mtm_mdd(trades, data, sz)
        out[name] = m
    return out


def mc_f1(data, P, trades, daily_state, r_confirms, years, runs=MC_RUNS, seed=SEED_F1, taker=True, stop_mode='fixed'):
    """stop_mode='fixed'  : 손절 = R.low(1-BUF) 고정 (지시서 §4.3, 주 검정)
       stop_mode='matched': 손절폭% 를 짝지은 실제 거래에 매칭 (보조 진단 F′-1b, 지시서 외) — 진입가 수준 차이(R배수 효과) 를 제거"""
    wins = r_windows(data, P, trades, daily_state, r_confirms)
    rng = random.Random(seed)
    results, diag = [], {'skipped_no_valid_open': 0, 'blocked': 0, 'inv7_violations': 0, 'entry_premium_sum': 0.0, 'entry_premium_n': 0, 'stop_pct_sum': 0.0}
    for k in range(runs):
        entries = []
        for w in wins:
            tr = w['trade']
            pct = (tr['entry'] - tr['stop0']) / tr['entry']
            if stop_mode == 'matched':
                a_, b_ = bisect_left(data.f_ot, w['start']), bisect_left(data.f_ot, w['end'])
                m = rng.randint(a_, b_ - 1) if b_ > a_ else None
                stop = data.f_op[m] * (1 - pct) if m is not None else None
            else:
                m = draw_window_entry(data, w, rng, tr['stop0'])
                stop = tr['stop0']
            if m is None:
                diag['skipped_no_valid_open'] += 1
                continue
            tm = data.f_ot[m]
            if not (w['start'] <= tm < w['end'] and tm > data.h_ct[w['R_t']]):
                diag['inv7_violations'] += 1
            e = data.f_op[m]
            diag['entry_premium_sum'] += e / tr['entry'] - 1
            diag['entry_premium_n'] += 1
            diag['stop_pct_sum'] += (e - stop) / e
            entries.append((m, e, stop, tr['P0'], tr['signal_id'], {'run': k, 'window_end': w['end_reason']}))
        sim, blocked = run_sequence(data, P, entries, daily_state, taker)
        diag['blocked'] += blocked
        results.append({'run': k, 'n': len(sim), 'blocked': blocked, 'metrics': run_metrics(sim, data, years), 'trades': sim})
    if diag['entry_premium_n']:
        diag['entry_premium_mean_pct'] = diag['entry_premium_sum'] / diag['entry_premium_n'] * 100
        diag['stop_pct_mean'] = diag['stop_pct_sum'] / diag['entry_premium_n'] * 100
    for k_ in ('entry_premium_sum', 'entry_premium_n', 'stop_pct_sum'):
        diag.pop(k_, None)
    return results, diag, wins


def mc_f2(data, P, trades, daily_state, years, runs=MC_RUNS, seed=SEED_F2, taker=True, window_days=5):
    """캘린더 무작위: 실제 거래 i 마다 [T-5일, T+5일] 균등 5분봉 시가 진입, 손절폭 % = 짝지은 실제 거래.
    dexit / V 기준선 = 그 시점까지 확정된 일봉 ZigZag 최근 저점 (확정 피벗만)."""
    def ref_fn(d):
        return daily_state[d]['zz_low_any'] if d >= 0 else None
    rng = random.Random(seed)
    f_ot = data.f_ot
    last = len(f_ot) - 1
    results, diag = [], {'blocked': 0, 'skipped': 0}
    for k in range(runs):
        entries = []
        for tr in trades:
            T = tr['entry_time']
            lo = max(bisect_left(f_ot, T - window_days * D_MS), bisect_left(f_ot, data.h_ot[data.start4]))
            hi = min(last, bisect_right(f_ot, T + window_days * D_MS) - 1)
            pct = (tr['entry'] - tr['stop0']) / abs(tr['entry'])
            m = rng.randint(lo, hi)
            e = data.f_op[m]
            stop = e * (1 - pct)
            entries.append((m, e, stop, None, tr['signal_id'], {'run': k, 'paired': tr['signal_id']}))
        # P0 없음 -> V/dexit 는 ref_fn 로 치환
        ents = [(m, e, stop, (ref_fn(data.h_day[bisect_right(data.h_ot, data.f_ot[m]) - 1] - 1) or 0.0), sid, ex) for (m, e, stop, _, sid, ex) in entries]
        sim, blocked = run_sequence(data, P, ents, daily_state, taker, v_ref_fn=ref_fn, dexit_ref_fn=ref_fn)
        diag['blocked'] += blocked
        results.append({'run': k, 'n': len(sim), 'blocked': blocked, 'metrics': run_metrics(sim, data, years), 'trades': sim})
    return results, diag


def percentile_rank(values, x):
    """x 가 values 분포에서 차지하는 백분위 (values 중 x 이하 비율 ×100)."""
    n = len(values)
    return sum(1 for v in values if v <= x) / n * 100 if n else 0.0


def pct(values, q):
    xs = sorted(values)
    if not xs:
        return 0.0
    i = (len(xs) - 1) * q
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


# ------------------------------------------------------------------ F′-0 벤치마크
def daily_series(data):
    """평가 구간의 일봉 종가 (start4 봉의 날짜부터 LAST 봉의 날짜까지)."""
    d0, d1 = data.h_day[data.start4], data.h_day[data.LAST]
    return [(data.d_ot[d], data.d_cl[d]) for d in range(d0, d1 + 1)]


def _curve_metrics(curve, years, seed=A.SEED_EQ):
    """curve: [(time, equity)] 일 단위. 반환 CAGR, ret, mdd, sharpe, sortino(일수익률, √365), 최대 연속 하락일."""
    eq = [e for _, e in curve]
    peak, mdd = eq[0], 0.0
    for e in eq:
        peak = max(peak, e)
        mdd = max(mdd, (peak - e) / peak * 100)
    rets = [math.log(eq[i] / eq[i - 1]) if eq[i] > 0 and eq[i - 1] > 0 else -1.0 for i in range(1, len(eq))]
    n = len(rets)
    mean = sum(rets) / n if n else 0.0
    sd = (sum((r - mean) ** 2 for r in rets) / n) ** 0.5 if n > 1 else 0.0
    dsd = (sum(min(0.0, r) ** 2 for r in rets) / n) ** 0.5 if n > 1 else 0.0
    streak = worst = 0
    for r in rets:
        streak = streak + 1 if r <= 0 else 0
        worst = max(worst, streak)
    final = eq[-1]
    return OrderedDict([('ret', (final / seed - 1) * 100), ('cagr', ((final / seed) ** (1 / years) - 1) * 100 if final > 0 else -100.0), ('mdd', mdd),
                        ('sharpe', mean / sd * 365 ** 0.5 if sd > 0 else 0.0), ('sortino', mean / dsd * 365 ** 0.5 if dsd > 0 else 0.0),
                        ('worst_streak_days', worst), ('eq', final)])


def funding_between(data, t_a, t_b):
    """(t_a, t_b] 의 펀딩률 합 (V2: 고정 0.01%/8h 스케줄, V3: 실제 이력)."""
    if data.fund_ts:
        a, b = bisect_right(data.fund_ts_norm, t_a), bisect_right(data.fund_ts_norm, t_b)
        return sum(data.fund_rate[k] for k in range(a, b))
    ft = (t_a // (8 * H_MS) + 1) * 8 * H_MS
    n = 0
    while ft <= t_b:
        n += 1
        ft += 8 * H_MS
    return FUNDING * n


def bench_bh(data, years, lev=None):
    """BH: 현물 매수 후 보유(무레버리지, taker 비용 진입·청산 1회씩, 펀딩 없음).
    BH-x: 상시 레버리지 lev (일 단위 리밸런스, 펀딩·taker 진입/청산 반영, 리밸런스 비용은 미반영)."""
    ds = daily_series(data)
    px0 = data.f_op[bisect_left(data.f_ot, data.h_ot[data.start4])]
    seed = A.SEED_EQ
    curve = []
    if lev is None:
        eq0 = seed * (1 - FEE_TAKER)
        for tm, cl in ds:
            curve.append((tm, eq0 * cl / px0))
        curve[-1] = (curve[-1][0], curve[-1][1] * (1 - FEE_TAKER))
    else:
        eq = seed * (1 - FEE_TAKER * lev)
        prev_px, prev_tm = px0, data.h_ot[data.start4]
        for tm, cl in ds:
            r = cl / prev_px - 1
            fund = funding_between(data, prev_tm, tm + D_MS - 1) * lev
            eq *= max(0.0, 1 + lev * r - fund)
            curve.append((tm, eq))
            prev_px, prev_tm = cl, tm + D_MS - 1
        curve[-1] = (curve[-1][0], curve[-1][1] * (1 - FEE_TAKER * lev))
    m = _curve_metrics(curve, years)
    m['lev'] = lev if lev is not None else 1.0
    return m, curve


def bench_em(data, trades, years, lev, runs=MC_RUNS, seed=SEED_F0):
    """BH-EM: 노출 매칭 무작위 진입 buy & hold. 보유기간은 실제 거래 hold_h 를 복원추출, 개수 = 실제 거래 수,
    진입 시각 균등 무작위(정렬 후 겹치면 직전 청산 직후로 밀어 붙임), 시가 진입/종가 청산, taker 왕복, 펀딩, 레버리지 lev."""
    holds = [t['hold_h'] for t in trades if t['result'] != 'open']
    n = len(holds)
    rng = random.Random(seed)
    f_ot, f_op, f_cl = data.f_ot, data.f_op, data.f_cl
    m_start = bisect_left(f_ot, data.h_ot[data.start4])
    m_end = bisect_right(f_ot, data.h_ct[data.LAST]) - 1
    results = []
    for k in range(runs):
        ents = sorted(rng.randint(m_start, m_end) for _ in range(n))
        hs = [rng.choice(holds) for _ in range(n)]
        eq, peak, mdd_c = A.SEED_EQ, A.SEED_EQ, 0.0
        rets, last_exit_m = [], -1
        tim = 0.0
        for me, h in zip(ents, hs):
            if me <= last_exit_m:
                me = last_exit_m + 1
            if me > m_end:
                break
            mx = min(m_end, me + max(1, int(round(h * 12))))
            e, x = f_op[me], f_cl[mx]
            fund = funding_between(data, f_ot[me], f_ot[mx] + data.fine_ms - 1)
            r = lev * ((x - e) / e - 2 * FEE_TAKER - fund)
            # MTM (5분 종가) 로 보유 중 drawdown
            for m in range(me, mx + 1):
                eqm = eq * (1 + lev * ((f_cl[m] - e) / e))
                peak = max(peak, eqm)
                mdd_c = max(mdd_c, (peak - eqm) / peak * 100)
            eq *= max(0.0, 1 + r)
            peak = max(peak, eq)
            mdd_c = max(mdd_c, (peak - eq) / peak * 100)
            rets.append(r)
            tim += (f_ot[mx] - f_ot[me]) / H_MS
            last_exit_m = mx
        m = A.metrics(rets, years)
        m['mtm_mdd_close'] = mdd_c
        m['time_in_market'] = tim / ((data.h_ct[data.LAST] - data.h_ot[data.start4]) / H_MS) * 100
        results.append(m)
    return results


def time_in_market(data, trades):
    tot = (data.h_ct[data.LAST] - data.h_ot[data.start4]) / H_MS
    return sum(t['hold_h'] for t in trades) / tot * 100
