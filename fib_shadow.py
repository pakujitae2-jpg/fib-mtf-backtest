# -*- coding: utf-8 -*-
"""fib_shadow.py — Test B 공용: shadow 후보 생성기 + 결과 측정 함수 (작업지시서 testAB §3.2, §3.3)

Shadow 후보 = 포지션 제약 없이 모든 롱 신호를 첫 터치에서 독립 체결한 집합.
fib_engine_c.run() 은 수정하지 않고 E.Data / E.Side (상태 계산 부품) 만 재사용해 별도 루프를 돈다.
chronology 는 교정 엔진과 동일:
  * 4H 봉 t → 5분봉 cursor 전진 (되돌아가기 없음)
  * r_valid 의 ATR = atr[t-1] (E.Side(legacy=frozenset()) 가 보장)
  * R 확정 = 4H 봉 종료 후 h4_update, 주문은 R[3] < t 인 봉부터
  * 진입 판정(5분봉 Low <= entry_level) 뒤에 R 무효화 / V(P0 훼손) 를 5분봉 Low 로 판정
  * 체결 후 sd.armed=False, sd.R_broken=True (첫 눌림 1회 / 같은 R 재진입 금지) — §8.1
표준 라이브러리만 사용.
"""
import random
from bisect import bisect_left
import fib_mtf as F
import fib_engine_c as E
from fib_mtf import EPS, D_MS, H_MS, ts

HORIZON_DAYS = 60
R_LEVELS = [0.0, 0.146, 0.236, 0.382, 0.500, 0.618]
RANDOM_LEVEL_MAX = 0.618


def generate(data, P, level=None, rng=None, tag=None):
    """Shadow 후보 생성.
    level: None -> P['R_ENTRY_FIB'] 그대로 / float -> R_ENTRY_FIB 덮어쓰기 / 'random' -> 주문마다 rng.uniform(0, 0.618)
    반환: (candidates, events)
      candidate: dict(candidate_id, tag, D_arm_time, P0, H1, D_size, R_low, R_high, R_size, R_confirm_time, R_t,
                      fib, entry_level, entry_time, fill_m, t, stop_level, stop_dist_pct, atr_idx, atr_end_time,
                      decision_time, order_create_time, year, arm_index, partial_fine)
      events: (kind, time_ms, t, detail)  — D_ARM / D_DISARM / ORDER_CREATE / ORDER_CANCEL(reason) / FILL / R_INVALID / V
    """
    P = dict(P, SIDES='long')
    if isinstance(level, float):
        P = dict(P, R_ENTRY_FIB=level)
    tag = tag if tag is not None else ('random' if level == 'random' else '%.3f' % P.get('R_ENTRY_FIB', 0.236))
    sd = E.Side(+1, data, P, frozenset())
    d0 = data.h_day[data.start4]
    for d in range(0, d0):
        sd.daily_update(d)
    cur_day = d0
    for t in range(max(0, data.start4 - 300), data.start4):
        sd.track_anchor()
        sd.h4_update(t)
    cands, events = [], []
    order = None
    arm_time, arm_seq, r_in_arm = None, 0, 0
    fine_ms = data.fine_ms
    full = 4 * H_MS // fine_ms

    def cancel(reason, tm):
        nonlocal order
        if order is not None:
            events.append(('ORDER_CANCEL', tm, cur_t[0], {'key': order['key'], 'reason': reason}))
            order = None

    cur_t = [data.start4]
    for t in range(data.start4, data.LAST + 1):
        cur_t[0] = t
        d = data.h_day[t]
        a, b = data.fine_range(t)
        M = list(range(a, b)) if a < b else [None]
        partial = (a >= b) or (b - a < full)
        if d != cur_day:
            r = sd.daily_update(d - 1)
            if r == 'ARM':
                arm_seq += 1
                arm_time, r_in_arm = data.h_ot[t], 0
                events.append(('D_ARM', data.h_ot[t], t, {'P0': sd.P0, 'H1': sd.H1, 'arm_seq': arm_seq, 'day': ts(data.d_ot[d - 1], 24)}))
            elif r == 'DISARM':
                events.append(('D_DISARM', data.h_ot[t], t, {}))
                cancel('D_DISARMED', data.h_ot[t])
            cur_day = d
        # ---- 봉 시작: 주문 갱신 (R 은 t-1 이전 확정분, ATR 은 atr[t-1])
        want = sd.armed and sd.r_valid(t) and sd.R[3] < t and sd.m_ok(d)
        key = sd.R[3] if want else None
        if order is not None and order['key'] != key:
            cancel('DISARMED' if not sd.armed else ('R_BROKEN' if (sd.R is None or sd.R_broken) else ('R_REPLACED' if key is not None else 'R_NOT_VALID')), data.h_ot[t])
        if want and order is None:
            fib = rng.uniform(0.0, RANDOM_LEVEL_MAX) if level == 'random' else P.get('R_ENTRY_FIB', 0.236)
            lv = sd.R[0] + fib * sd.R[2]
            lv = lv + P['TOL'] * abs(lv)
            stop = sd.stop_level()
            if lv > stop:
                r_in_arm += 1
                order = {'key': key, 'level': lv, 'stop': stop, 'fib': fib, 'create_time': data.h_ot[t], 'atr_idx': sd.last_atr_idx,
                         'arm_index': r_in_arm, 'arm_time': arm_time, 'arm_seq': arm_seq}
                events.append(('ORDER_CREATE', data.h_ot[t], t, {'key': key, 'level': lv, 'stop': stop, 'fib': fib}))
        for m in M:
            if m is None:
                lo, ot, ct = sd.h_lo[t], data.h_ot[t], data.h_ct[t]
            else:
                lo, ot, ct = sd.f_lo[m], data.f_ot[m], data.f_ot[m] + fine_ms - 1
            # 1) 진입 판정 (포지션 제약 없음)
            if order is not None and lo <= order['level'] + EPS:
                lv, stop = order['level'], order['stop']
                cands.append({
                    'candidate_id': '%s-%d' % (tag, len(cands) + 1), 'tag': tag,
                    'D_arm_time': order['arm_time'], 'arm_seq': order['arm_seq'], 'P0': sd.P0, 'H1': sd.H1, 'D_size': sd.dsize,
                    'R_low': sd.R[0], 'R_high': sd.R[1], 'R_size': sd.R[2], 'R_confirm_time': data.h_ct[sd.R[3]], 'R_t': sd.R[3],
                    'fib': order['fib'], 'entry_level': lv, 'entry_time': ot, 'fill_m': m, 't': t,
                    'stop_level': stop, 'stop_dist_pct': (lv - stop) / abs(lv),
                    'atr_idx': order['atr_idx'], 'atr_end_time': data.h_ct[order['atr_idx']], 'decision_time': ot,
                    'order_create_time': order['create_time'], 'year': int(ts(ot)[:4]), 'arm_index': order['arm_index'],
                    'partial_fine': partial})
                events.append(('FILL', ot, t, {'key': order['key'], 'level': lv}))
                sd.armed = False                    # 첫 눌림 1회 진입
                sd.R_broken = True                  # 같은 R 재진입 금지
                order = None
            # 2) V / R 이탈 (진입 판정 뒤)
            if sd.armed and lo < sd.P0 - EPS:
                sd.armed, sd.vflag = False, True
                events.append(('V', ct, t, {'P0': sd.P0}))
                cancel('V', ct)
            if sd.R and not sd.R_broken and lo < sd.R[0] - EPS:
                if order is not None and order['key'] == sd.R[3]:
                    events.append(('R_INVALID', ct, t, {'key': sd.R[3]}))
                sd.R_broken = True
                cancel('R_INVALID', ct)
        sd.track_anchor()
        sd.h4_update(t)
    return cands, events


# ------------------------------------------------------------------ 결과 측정 (§3.3)
def outcome(data, m_entry, entry_px, stop_px, horizon_days=HORIZON_DAYS, levels=(1, 2, 3, 5)):
    """진입 5분봉 m_entry 부터 순방향 스캔.
      * 진입 봉: 손절만 검사, High 는 max_R 에 반영하지 않음
      * 이후 봉: low <= stop 이면 손절 확정 (그 봉의 High 미반영), 아니면 max_R 갱신
      * horizon_days 경과 또는 데이터 종료 -> censored=True
    비용·펀딩 미반영. 반환 dict(stopped, censored, max_R, t_1R, t_2R, t_3R, t_5R, bars_to_exit, exit_time, first_bar_time)"""
    R_dist = entry_px - stop_px
    assert R_dist > 0, (entry_px, stop_px)
    f_hi, f_lo, f_ot = data.f_hi, data.f_lo, data.f_ot
    n = len(f_ot)
    t_end = f_ot[m_entry] + horizon_days * D_MS
    max_R = 0.0
    hit = {k: None for k in levels}
    res = {'stopped': False, 'censored': False, 'max_R': 0.0, 'bars_to_exit': 0, 'exit_time': None, 'first_bar_time': f_ot[m_entry]}
    if f_lo[m_entry] <= stop_px + EPS:                      # 진입 봉 손절 (High 미반영)
        res.update(stopped=True, bars_to_exit=0, exit_time=f_ot[m_entry])
    else:
        m = m_entry + 1
        while m < n and f_ot[m] < t_end:
            if f_lo[m] <= stop_px + EPS:
                res.update(stopped=True, bars_to_exit=m - m_entry, exit_time=f_ot[m])
                break
            r = (f_hi[m] - entry_px) / R_dist
            if r > max_R:
                max_R = r
                for k in levels:
                    if hit[k] is None and r >= k:
                        hit[k] = f_ot[m]
            m += 1
        else:
            res.update(censored=True, bars_to_exit=m - m_entry, exit_time=f_ot[min(m, n - 1)])
    res['max_R'] = max_R
    for k in levels:
        res['t_%dR' % k] = hit[k]
    return res


def bar_index_at(data, tm):
    """time_ms 이상인 첫 5분봉 index."""
    return bisect_left(data.f_ot, tm)


# ------------------------------------------------------------------ 하네스 자체 회귀 (§4 불변식 5·6·7)
class _Mini:
    def __init__(self, ot, hi, lo):
        self.f_ot, self.f_hi, self.f_lo = ot, hi, lo


def self_test():
    """outcome() 규칙 검증: 진입봉 High 미반영 / 손절봉 High 미반영 / 참조 봉 open_time >= entry_time / horizon censored."""
    FIVE = 300000
    ot = [i * FIVE for i in range(40)]
    hi = [100.0] * 40
    lo = [100.0] * 40
    hi[5] = 200.0                                   # 진입 봉(m=5) 의 High 가 크지만 반영되면 안 됨
    hi[6], lo[6] = 103.0, 99.5
    hi[7], lo[7] = 105.0, 99.5
    hi[8], lo[8] = 150.0, 90.0                      # 손절 봉의 High 는 미반영
    d = _Mini(ot, hi, lo)
    r = outcome(d, 5, 100.0, 95.0, horizon_days=60)
    assert r['stopped'] and r['bars_to_exit'] == 3 and abs(r['max_R'] - 1.0) < 1e-12, r      # (105-100)/5 = 1.0 ; 200, 150 미반영
    assert r['t_1R'] == ot[7] and r['t_2R'] is None, r
    assert r['first_bar_time'] >= ot[5]
    # 진입 봉 손절
    lo2 = list(lo); lo2[5] = 94.0
    r2 = outcome(_Mini(ot, hi, lo2), 5, 100.0, 95.0)
    assert r2['stopped'] and r2['bars_to_exit'] == 0 and r2['max_R'] == 0.0, r2
    # horizon censored (데이터 끝)
    r3 = outcome(_Mini(ot, [100.0] * 40, [100.0] * 40), 5, 100.0, 95.0, horizon_days=60)
    assert r3['censored'] and not r3['stopped'] and r3['max_R'] == 0.0, r3
    # horizon 도달 (1일 = 288봉 > 40봉 이므로 데이터 종료로 censored; 봉이 많은 경우)
    ot4 = [i * FIVE for i in range(300)]
    r4 = outcome(_Mini(ot4, [100.0] * 300, [100.0] * 300), 0, 100.0, 95.0, horizon_days=1)
    assert r4['censored'] and r4['bars_to_exit'] == 288, r4
    return True
