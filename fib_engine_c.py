# -*- coding: utf-8 -*-
"""fib_engine_c.py — 교정 엔진 (5분봉 event cursor).  작업지시서: v2_v3_cross_validation_engine_fix_work_order §1~§27

레거시 fib_mtf.py 는 그대로 두고(Legacy Baseline Freeze), 신호 계산(일봉/4H ZigZag, Side 상태)은 재사용한다.
run() 만 다시 쓴다.

핵심 원칙
  * 모든 판단은 decision_time 에 알 수 있던 정보만 사용. 4H 봉 전체 High/Low 선행 판정 금지.
  * 4H 봉 안에서는 5분봉 cursor 를 앞으로만 진행 (이벤트 후 봉 시작으로 되돌아가 재스캔하지 않음).
  * 동일 5분봉 안에서 순서를 알 수 없으면 전략에 불리한 순서: 진입 -> 손절, 진입 -> R/P0 이탈.
  * ATR14 는 decision_time 이전에 종료된 4H 봉만 (봉 t 내부 판단 = atr[t-1]).  h4_update 는 봉 t 종료 후 호출되므로 atr[t] 사용 가능.
  * MAE/MFE/peak 는 actual_entry ~ actual_exit 구간의 5분봉만.
  * Funding 은 실제 체결 시각 기준: entry_time < funding_time <= exit_time, 잔여 수량 기준.
  * FILL=C(5분봉 종가 시장가) 진입은 같은 5분봉에서 SL/TP 검사 금지.
  * 포지션 보유 중 P0(진입 시 고정) 훼손 -> 다음 5분봉 시가에서 시장가 청산 ('v').

레거시 재현 플래그 (legacy= 집합에 넣으면 그 항목만 레거시 동작으로 되돌린다; 전부 넣으면 fib_mtf.run 과 동일해야 한다)
  R_4H      : 4H 전체 Low 로 R 무효화를 봉 시작 시 선행 판정
  V_4H      : 4H 전체 Low 로 V(P0 훼손) 를 봉 시작 시 선행 판정, 포지션은 4H 종가에 청산
  NOCURSOR  : 청산이 일어난 5분봉에서 반대편 진입 허용 (교정: 이벤트 봉 다음 5분봉부터, §6). 과거 5분봉 재스캔은 재현하지 않고 발생 가능 건수만 센다
  ATR_CUR   : r_valid 에 현재(미완성) 봉 포함 atr[t]
  MAE_4H    : MAE/peak 를 4H 봉 전체 Low/High 로 (진입 전 구간 포함)
  FUND_4H   : 펀딩/보유시간을 4H 봉 시각으로 근사
  SAMEBAR_C : FILL=C 진입 5분봉에서 SL/TP 검사 허용
  ENTRYBAR_TP: FILL=A/B 진입 5분봉에서 TP 체결 허용 (교정: 진입봉은 손절만, Entry->TP 순서는 알 수 없으므로 §10 불리한 쪽)
  NO_V_POS  : 포지션 자체 P0 훼손 청산 비활성 (레거시는 재-ARM 상태에서만 V 청산)
"""
import time
from bisect import bisect_left, bisect_right
from collections import Counter
import fib_mtf as F
from fib_mtf import (zigzag_step, new_zz, EPS, H_MS, D_MS, FEE_MAKER, FEE_TAKER, SLIP, FUNDING, MM, FIB_EXT,
                     ts, load_csv, load_funding, _pf, pm_of, evaluate, evaluate_risk)

LEGACY_FLAGS = ('R_4H', 'V_4H', 'NOCURSOR', 'ATR_CUR', 'MAE_4H', 'FUND_4H', 'SAMEBAR_C', 'ENTRYBAR_TP', 'NO_V_POS')
LEGACY_ALL = frozenset(LEGACY_FLAGS)
# 작업지시서 §18 수정 순서 (플래그를 이 순서로 제거하며 영향을 분해). MTM MDD 는 평가 단계라 엔진 플래그가 아님.
FIX_ORDER = [('R_4H', '1. R_INVALIDATION 5M chronology'),
             ('V_4H', '2. V/P0_BREAK 5M chronology (armed V)'),
             ('NO_V_POS', '2b. V/P0_BREAK: 보유 포지션 P0 훼손 청산'),
             ('NOCURSOR', '3. 5M event cursor'),
             ('ATR_CUR', '4. ATR confirmed-only'),
             ('MAE_4H', '5. MAE/MFE entry~exit window'),
             ('FUND_4H', '6. Funding actual timestamps'),
             ('SAMEBAR_C', '8. Market-close same-bar SL/TP'),
             ('ENTRYBAR_TP', '8b. Limit 진입 5분봉 Entry->TP 불리한 순서 (TP 는 다음 봉부터)')]


class Data(F.Data):
    """레거시 Data + 5분봉 시가/봉 길이."""
    def __init__(self, d_rows, h4_rows, fine_rows, start='2019-03-01', funding=None):
        super().__init__(d_rows, h4_rows, fine_rows, start, funding)
        self.f_op = [r[1] for r in fine_rows]
        diffs = sorted(b - a for a, b in zip(self.f_ot[:2000], self.f_ot[1:2001]))
        self.fine_ms = diffs[len(diffs) // 2] if diffs else 5 * 60000
        self.h_ct1 = list(self.h_ct)                 # 봉 종료 판단(R 확정 등) 의 시각 = 봉의 마지막 ms (h_ct)
        # 펀딩 스탬프는 정산 시각에서 1~7ms 뒤에 찍히는 경우가 있어 분 단위로 내림 (교정 경로 전용; 레거시 경로는 원본 유지)
        self.fund_ts_norm = [t - t % 60000 for t in self.fund_ts]


def load_data(start='2019-03-01', sym='btcusdt'):
    """fib_mtf.load_data 와 같은 파일 구성으로 교정 Data 를 만든다."""
    import os
    if sym == 'btcusdt':
        d = load_csv('btcusdt_1d_2017.csv') if os.path.exists('btcusdt_1d_2017.csv') else load_csv('btcusdt_1d.csv')
        h4 = load_csv('btcusdt_4h_2019.csv')
        fine = []
        if os.path.exists('btcusdt_5m_2019_2022.csv'):
            fine += load_csv('btcusdt_5m_2019_2022.csv')
        fine += load_csv('btcusdt_5m.csv')
    else:
        d = load_csv('%s_1d.csv' % sym)
        h4 = load_csv('%s_4h.csv' % sym)
        fine = load_csv('%s_5m.csv' % sym)
        start = max(start, ts(h4[0][0] + 90 * D_MS, 24))
    fine = [r for r in fine if r[0] >= h4[0][0]]
    return Data(d, h4, fine, start)


class Side(F.Side):
    def __init__(self, sign, data, P, legacy):
        super().__init__(sign, data, P)
        self.f_op = data.f_op if sign > 0 else [-x for x in data.f_op]
        self.atr_cur = 'ATR_CUR' in legacy
        self.order_key = None          # 대기 주문의 R 확정 봉 index
        self.order_level = self.order_stop = self.order_time = None
        self.arm_time = None
        self.last_atr_idx = None

    def atr_idx(self, t):
        """봉 t 내부 판단에 쓰는 ATR index. 교정: 봉 t 시작 전에 종료된 봉까지 (t-1)."""
        return t if self.atr_cur else max(0, t - 1)

    def r_valid(self, t):
        if self.R is None or self.R_broken or self.dsize is None:
            return False
        i = self.atr_idx(t)
        self.last_atr_idx = i
        need = max(self.dsize * self.P['R_RATIO'], self.d.atr[i] * self.P['ATR_MULT'])
        return self.R[2] >= need


def _targets(P, sd, d, lv, stop):
    ex = P['EXIT']
    tg, d_exit, be = [], False, False
    if ex == 'spec':
        tg = [(x, 0.25) for x in sd.targets(d, lv)]
        d_exit = True
    elif ex == 'trail':
        d_exit = True
    elif ex == 'tp10':
        tg = [(lv + 0.10 * abs(lv), 1.0)]
    elif ex == 'tp20':
        tg = [(lv + 0.20 * abs(lv), 1.0)]
    elif ex == 'half':
        tg = [(lv + 0.10 * abs(lv), 0.5)]
        d_exit, be = True, True
    elif ex in ('tpR2', 'tpR3'):
        tg = [(lv + (2.0 if ex == 'tpR2' else 3.0) * (lv - stop), 1.0)]
    elif ex == 'halfR2':
        tg = [(lv + 2.0 * (lv - stop), 0.5)]
        d_exit, be = True, True
    elif ex == 'halfR2spec':
        tg = [(lv + 2.0 * (lv - stop), 0.5)] + [(x, 0.125) for x in sd.targets(d, lv)]
        d_exit, be = True, True
    return tg, d_exit, be


# ------------------------------------------------------------------ 시뮬레이션
def run(data, P, legacy=frozenset(), init=None):
    """반환: trades, events, sides, diag
    events: (t, side_sign, kind, day, time_ms, detail)  — 앞 4개는 레거시 (t, s, kind, d) 와 호환
    trades: 레거시 키 + entry_time/exit_time/fill_m/exit_m/mfe/entry_R/fill_detail/funding_events/seq ...
    init(sides): 워밍업 직후 상태 주입 훅 (synthetic test 용)"""
    L = set(legacy)
    for x in L:
        assert x in LEGACY_ALL, x
    fine_ms = data.fine_ms
    sides = []
    if P['SIDES'] in ('both', 'long'):
        sides.append(Side(+1, data, P, L))
    if P['SIDES'] in ('both', 'short'):
        sides.append(Side(-1, data, P, L))
    d0 = data.h_day[data.start4]
    for sd in sides:
        for d in range(0, d0):
            sd.daily_update(d)
    cur_day = d0
    for sd in sides:
        for t in range(max(0, data.start4 - 300), data.start4):
            sd.track_anchor()
            sd.h4_update(t)
    if init:
        init(sides)
    fill_model = P.get('FILL', 'A')
    pen = P.get('PEN', 0.0)
    policy = P.get('TGT_POLICY', 'retro')
    pos = None
    pending = None                      # 다음 5분봉 시가에서 실행할 시장가 청산 (kind)
    trades, events = [], []
    diag = Counter()
    cur = {'t': 0, 'd': 0}
    sig_seq = [0]

    # ---- 5분봉 접근자. m=None 이면 4H 봉 t 자체를 하나의 봉으로 취급 (5분봉 결손 fallback)
    def bar(sd, m):
        if m is None:
            t = cur['t']
            return sd.h_op[t], sd.h_hi[t], sd.h_lo[t], sd.h_cl[t], data.h_ot[t], data.h_ct[t]
        return sd.f_op[m], sd.f_hi[m], sd.f_lo[m], sd.f_cl[m], data.f_ot[m], data.f_ot[m] + fine_ms - 1

    def ev(kind, sd, tm, **detail):
        events.append((cur['t'], sd.s if sd is not None else 0, kind, cur['d'], tm, detail))

    def cancel_order(sd, tm, reason):
        if sd.order_key is not None:
            ev('ORDER_CANCEL', sd, tm, key=sd.order_key, reason=reason, level=sd.order_level)
            sd.order_key = None

    def refresh_orders(t, d):
        """봉 t 시작(= 봉 t-1 종료 직후) 주문 상태 갱신. R 은 t-1 이전 확정분만."""
        tm = data.h_ot[t]
        for sd in sides:
            want = sd.armed and sd.r_valid(t) and sd.R[3] < t and sd.m_ok(d)
            key = sd.R[3] if want else None
            if sd.order_key is not None and sd.order_key != key:
                cancel_order(sd, tm, 'DISARMED' if not sd.armed else ('R_BROKEN' if (sd.R is None or sd.R_broken) else 'R_CHANGED'))
            if want and sd.order_key is None:
                lv, stop = sd.entry_level(), sd.stop_level()
                if lv > stop:
                    sd.order_key, sd.order_level, sd.order_stop, sd.order_time = key, lv, stop, tm
                    ev('ORDER_CREATE', sd, tm, key=key, level=lv, stop=stop, atr_idx=sd.last_atr_idx,
                       atr_end_time=data.h_ct[sd.last_atr_idx], r_confirm_time=data.h_ct1[sd.R[3]])
                    if sd.sig_key != key:
                        sd.sig_key = key
                        ev('SIGNAL', sd, tm, key=key)
            elif want and sd.order_key == key and sd.order_level != sd.entry_level():
                sd.order_level, sd.order_stop = sd.entry_level(), sd.stop_level()

    def close_pos(m, px, frac, kind, tm):
        nonlocal pos
        pos['fills'].append((cur['t'], px, frac, kind))
        pos['fill_detail'].append((m, tm, px, frac, kind))
        pos['frac'] -= frac
        e = pos['entry']
        if 'MAE_4H' not in L:
            x = (px - e) / abs(e)
            if kind == 'stop':
                pos['mae'] = min(pos['mae'], x)
            elif kind == 'tp':
                pos['mfe'] = max(pos['mfe'], x)
            else:
                pos['mae'], pos['mfe'] = min(pos['mae'], x), max(pos['mfe'], x)
        pos['seq'].append((tm, 'EXIT_' + kind.upper(), px, frac))
        ev('EXIT', pos['side'], tm, exit_kind=kind, px=px, frac=frac, signal_id=pos['signal_id'])
        if pos['frac'] <= 1e-9:
            finish(m, tm)

    def apply_policy(m):
        nonlocal pos
        if policy == 'retro' or pos.get('policy_done'):
            return
        pos['policy_done'] = True
        sd = pos['side']
        op, hi, lo, cl, ot, ct = bar(sd, m)
        passed = [x for x in pos['tgts'] if x[0] <= hi + EPS]
        pos['tgts'] = [x for x in pos['tgts'] if x[0] > hi + EPS]
        if policy == 'market':
            for px, fr in passed:
                if pos is None:
                    break
                close_pos(m, cl - SLIP * abs(cl), min(fr, pos['frac']), 'tpm', ct)

    def finish(m, tm):
        nonlocal pos, pending
        pending = None                      # 이 포지션에 예약된 시장가 청산은 포지션과 함께 소멸
        sd = pos['side']
        e = pos['entry']
        r = 0.0
        fee = FEE_TAKER if pos.get('taker') else FEE_MAKER
        for (_, px, fr, kind) in pos['fills']:
            r += fr * (px - e) / abs(e)
            fee += fr * (FEE_MAKER if kind == 'tp' else FEE_TAKER)
            if kind == 'stop':
                r -= fr * SLIP
        t = cur['t']
        pos['exit_time'], pos['exit_m'], pos['t1'] = tm, m, t
        fund, fev = 0.0, []
        if 'FUND_4H' in L:
            hold_h = (data.h_ot[t] - data.h_ot[pos['t0']]) / H_MS + 4
            if data.fund_ts:
                a = bisect_left(data.fund_ts, data.h_ot[pos['t0']] + 1)
                b = bisect_left(data.fund_ts, data.h_ot[t] + 4 * H_MS)
                for k in range(a, b):
                    ft = data.fund_ts[k]
                    rem = 1.0 - sum(fr for (j, _, fr, _) in pos['fills'] if data.h_ot[j] + 4 * H_MS <= ft)
                    if rem <= 0:
                        break
                    amt = data.fund_rate[k] * rem * (1 if sd.s > 0 else -1)
                    fund += amt
                    fev.append((ft, amt))
            else:
                fund = FUNDING * hold_h / 8
        else:
            et, xt = pos['entry_time'], tm
            hold_h = (xt - et) / H_MS
            if data.fund_ts:
                a = bisect_right(data.fund_ts_norm, et)     # ft > entry_time
                b = bisect_right(data.fund_ts_norm, xt)     # ft <= exit_time
                for k in range(a, b):
                    ft = data.fund_ts_norm[k]
                    rem = 1.0 - sum(fr for (_, ftm, _, fr, _) in pos['fill_detail'] if ftm < ft)
                    if rem <= 1e-9:
                        break
                    amt = data.fund_rate[k] * rem * (1 if sd.s > 0 else -1)      # >0 = 전략이 지불
                    fund += amt
                    fev.append((ft, amt))
            else:
                # 고정 펀딩(레거시 V2 비용모델: 양방향 모두 지불) 을 실제 8h 정산 시각(00/08/16 UTC) 에 잔여수량 기준으로
                k0 = et // (8 * H_MS) + 1
                ft = k0 * 8 * H_MS
                while ft <= xt:
                    rem = 1.0 - sum(fr for (_, ftm, _, fr, _) in pos['fill_detail'] if ftm < ft)
                    if rem <= 1e-9:
                        break
                    fund += FUNDING * rem
                    fev.append((ft, FUNDING * rem))
                    ft += 8 * H_MS
        pos['funding'], pos['fund_events'], pos['funding_events'] = fund, len(fev), fev
        pos['r_net'] = r - fee - fund
        pos['fee'] = fee
        pos['hold_h'] = hold_h
        pos['result'] = pos['fills'][-1][3]
        pos['exit_reason'] = pos['result']
        pos['stop_time'] = next((ftm for (_, ftm, _, _, k) in pos['fill_detail'] if k == 'stop'), None)
        pos['partial_exit_times'] = [ftm for (_, ftm, _, _, _) in pos['fill_detail'][:-1]]
        pos['final_exit_time'] = tm
        trades.append(pos)
        pos = None

    def manage(m):
        """포지션 보유 중 5분봉 m: 손절 -> 목표 (레거시와 같은 순서, 동일봉 동시 도달 시 손절 우선)."""
        nonlocal pos
        sd = pos['side']
        op, hi, lo, cl, ot, ct = bar(sd, m)
        if lo <= pos['stop'] + EPS:
            close_pos(m, pos['stop'], pos['frac'], 'stop', ct)
            return
        while pos and pos['tgts'] and hi >= pos['tgts'][0][0] - EPS:
            px, fr = pos['tgts'].pop(0)
            close_pos(m, px, min(fr, pos['frac']), 'tp', ct)
            if pos and pos['be']:
                pos['stop'] = max(pos['stop'], pos['entry'] + 0.002 * abs(pos['entry']))
            if pos:
                apply_policy(m)

    def try_entry(sd, m, t, d):
        nonlocal pos
        if sd.order_key is None:
            return False
        lv, stop = sd.order_level, sd.order_stop
        op, hi, lo, cl, ot, ct = bar(sd, m)
        need = lv - pen * abs(lv) if fill_model == 'B' else lv       # B: 레벨을 PEN 만큼 관통해야 체결
        if lo > need + EPS:
            return False
        other = [o for o in sides if o is not sd]
        if other and other[0].vflag:                                # 반대 side 의 vFlag -> 이 방향 첫 신호 스킵
            other[0].vflag = False
            ev('SKIP_V', sd, ot, key=sd.order_key)
            sd.R_broken = True
            cancel_order(sd, ot, 'SKIP_V')
            return False
        expected, taker, entry_time, at_close = lv, False, ot, False
        if fill_model == 'C':                                       # 터치 5분봉 종가 + 슬리피지 시장가
            lv = cl + SLIP * abs(lv)
            taker, entry_time, at_close = True, ct, True
            if lv <= stop:
                diag['C_entry_below_stop_skip'] += 1
                return False
        tg, d_exit, be = _targets(P, sd, d, lv, stop)
        sig_seq[0] += 1
        pos = {'side': sd, 't0': t, 'entry': lv, 'stop': stop, 'stop0': stop, 'frac': 1.0,
               'tgts': tg, 'd_exit': d_exit, 'be': be, 'fills': [], 'peak': lv, 'mae': 0.0, 'mfe': 0.0,
               'P0': sd.P0, 'H1': sd.H1, 'dsize': sd.dsize, 'R': sd.R, 'day': d,
               'expected': expected, 'taker': taker, 'age': t - sd.R[3], 'key': (sd.s, sd.R[3]),
               # ---- 교정 엔진 추가 필드 (작업지시서 §21)
               'signal_id': '%s-%s-%d' % ('L' if sd.s > 0 else 'S', ts(data.h_ct1[sd.R[3]]), sig_seq[0]),
               'entry_time': entry_time, 'fill_m': m, 'fill_at_close': at_close, 'fill_detail': [],
               'entry_R': {'ENTRY_R_LOW': sd.R[0], 'ENTRY_R_HIGH': sd.R[1], 'ENTRY_R_SIZE': sd.R[2],
                           'ENTRY_R_CONFIRM_TIME': data.h_ct1[sd.R[3]], 'ENTRY_R_T': sd.R[3]},
               'structural_stop': stop, 'order_create_time': sd.order_time,
               'r_confirm_time': data.h_ct1[sd.R[3]], 'D_arm_day': sd.arm_day, 'D_arm_time': data.d_ot[sd.arm_day] + D_MS if sd.arm_day is not None else None,
               'decision_time': ot, 'atr_idx': sd.last_atr_idx, 'atr_end_time': data.h_ct[sd.last_atr_idx],
               'targets0': list(tg), 'seq': [(entry_time, 'FILL', lv, 1.0)], 'funding_events': []}
        ev('FILL', sd, entry_time, signal_id=pos['signal_id'], expected=expected, entry=lv, stop=stop, key=sd.order_key)
        sd.armed = False                                            # 첫 눌림 1회 진입
        sd.R_broken = True
        sd.order_key = None
        return True

    def mark(m):
        """진입~청산 구간 5분봉 기준 MAE/MFE/peak."""
        sd = pos['side']
        if pos['fill_m'] == m and pos['fill_at_close']:
            return                                                  # 종가 진입: 이 봉의 High/Low 는 진입 전 가격
        op, hi, lo, cl, ot, ct = bar(sd, m)
        e = pos['entry']
        pos['peak'] = max(pos['peak'], hi)
        pos['mae'] = min(pos['mae'], (lo - e) / abs(e))
        pos['mfe'] = max(pos['mfe'], (hi - e) / abs(e))

    for t in range(data.start4, data.LAST + 1):
        d = data.h_day[t]
        cur['t'], cur['d'] = t, d
        a, b = data.fine_range(t)
        M = list(range(a, b)) if a < b else [None]
        if a >= b:
            diag['no_fine_bars'] += 1
        elif b - a < 4 * H_MS // fine_ms:
            diag['partial_fine_bars'] += 1
        # ---- 새 날: 직전 일봉 종가 처리 (00:00 에 알 수 있는 정보)
        if d != cur_day:
            for sd in sides:
                was_armed = sd.armed
                r = sd.daily_update(d - 1)
                if r:
                    ev('D_ARM' if r == 'ARM' else 'D_DISARM', sd, data.h_ot[t], day=ts(data.d_ot[d - 1], 24), P0=sd.P0, H1=sd.H1)
                    if r == 'ARM':
                        sd.arm_time = data.h_ot[t]
                    if r == 'DISARM' and sd.order_key is not None:
                        cancel_order(sd, data.h_ot[t], 'D_DISARMED')
                if pos and pos['side'] is sd and pos['frac'] > 0 and pos['d_exit']:
                    ref = sd.lastL if sd.lastL is not None else pos['P0']
                    if sd.d_cl[d - 1] < ref - EPS:
                        close_pos(M[0], sd.h_op[t], pos['frac'], 'dexit', data.h_ot[t])
            cur_day = d
        # ---- 레거시 4H 선행 판정 (플래그)
        v_end = []
        for sd in sides:
            if 'V_4H' in L and sd.armed and sd.h_lo[t] < sd.P0 - EPS:
                sd.armed, sd.vflag = False, True
                ev('V', sd, data.h_ot[t], P0=sd.P0, mode='4H')
                cancel_order(sd, data.h_ot[t], 'V')
                if pos and pos['side'] is sd:
                    v_end.append(sd)
            if 'R_4H' in L and sd.R and not sd.R_broken and sd.h_lo[t] < sd.R[0] - EPS:
                if sd.armed and sd.r_valid(t) and sd.sig_key == sd.R[3]:
                    ev('R_INVALID', sd, data.h_ot[t], key=sd.R[3], mode='4H')
                sd.R_broken = True
                cancel_order(sd, data.h_ot[t], 'R_INVALID')
        if pos and P['RATCHET']:
            pos['stop'] = max(pos['stop'], pos['peak'] - P['RATCHET'] * abs(pos['peak']))
        refresh_orders(t, d)
        exit_m_in_bar = None
        # ---- 5분봉 cursor
        for m in M:
            # 1) 예약된 시장가 청산 (직전 5분봉에서 감지) -> 이 봉 시가
            if pending is not None:
                if pos is not None and pending[0] == pos['signal_id']:
                    sd = pos['side']
                    op, hi, lo, cl, ot, ct = bar(sd, m)
                    close_pos(m, op, pos['frac'], pending[1], ot)
                else:
                    diag['pending_exit_dropped'] += 1
                pending = None
            # 2) 손절 / 목표
            if pos:
                manage(m)
                if pos is None:
                    exit_m_in_bar = m
            # 3) 진입 (같은 5분봉 안에서 진입 -> 손절 순서 = 전략에 불리한 쪽)
            if pos is None and (exit_m_in_bar != m or 'NOCURSOR' in L):     # 청산 봉에서는 신규 진입 없음 (§6: 이벤트 다음 봉부터)
                for sd in sides:
                    if try_entry(sd, m, t, d):
                        if exit_m_in_bar == m:
                            diag['reentry_same_5m_after_exit'] += 1
                        op, hi, lo, cl, ot, ct = bar(sd, m)
                        if pos['fill_at_close']:
                            if 'SAMEBAR_C' in L:
                                manage(m)
                            elif lo <= pos['stop'] + EPS or (pos['tgts'] and hi >= pos['tgts'][0][0] - EPS):
                                diag['samebar_C_sltp_skipped'] += 1
                        elif 'ENTRYBAR_TP' in L:
                            manage(m)
                        else:
                            # 진입 5분봉: Entry->Stop 만 (불리한 순서). Entry->TP 는 순서를 알 수 없으므로 다음 봉부터
                            if pos['tgts'] and hi >= pos['tgts'][0][0] - EPS:
                                diag['entrybar_tp_deferred'] += 1
                            if lo <= pos['stop'] + EPS:
                                close_pos(m, pos['stop'], pos['frac'], 'stop', ct)
                        break
            elif pos is None and exit_m_in_bar == m:
                for sd in sides:
                    if sd.order_key is not None:
                        op, hi, lo, cl, ot, ct = bar(sd, m)
                        need = sd.order_level - (pen * abs(sd.order_level) if fill_model == 'B' else 0.0)
                        if lo <= need + EPS:
                            diag['entry_skipped_on_exit_bar'] += 1
            # 4) V / R 이탈 (5분봉 Low 기준, 진입 판정 뒤에 -> 동일봉이면 진입 후 이탈로 취급)
            for sd in sides:
                lo = sd.h_lo[t] if m is None else sd.f_lo[m]
                ct = data.h_ct[t] if m is None else data.f_ot[m] + fine_ms - 1    # 봉 안에서 감지된 이벤트의 시각 = 봉 종료 (체결 시각과 같은 규약)
                if 'V_4H' not in L and sd.armed and lo < sd.P0 - EPS:
                    sd.armed, sd.vflag = False, True
                    ev('V', sd, ct, P0=sd.P0, mode='5M')
                    cancel_order(sd, ct, 'V')
                    if pos and pos['side'] is sd and pending is None:
                        pending = (pos['signal_id'], 'v')
                        pos['seq'].append((ct, 'V_DETECT', sd.P0, 0))
                if ('NO_V_POS' not in L and pos and pos['side'] is sd and pending is None
                        and not (pos['fill_m'] == m and pos['fill_at_close']) and lo < pos['P0'] - EPS):
                    pending = (pos['signal_id'], 'v')
                    pos['seq'].append((ct, 'V_DETECT', pos['P0'], 0))
                    ev('V_POS', sd, ct, P0=pos['P0'], signal_id=pos['signal_id'])
                if 'R_4H' not in L and sd.R and not sd.R_broken and lo < sd.R[0] - EPS:
                    if sd.order_key == sd.R[3]:
                        ev('R_INVALID', sd, ct, key=sd.R[3], mode='5M')
                    sd.R_broken = True
                    cancel_order(sd, ct, 'R_INVALID')
            # 5) MAE / MFE / peak
            if pos and 'MAE_4H' not in L:
                mark(m)
            # 진단: 레거시 NOCURSOR 였다면 과거 5분봉에 재진입했을 신호
            if exit_m_in_bar is not None and m == exit_m_in_bar and m is not None:
                for sd in sides:
                    if sd.order_key is not None and pos is None:
                        need = sd.order_level - (pen * abs(sd.order_level) if fill_model == 'B' else 0.0)
                        if any(sd.f_lo[mm] <= need + EPS for mm in range(a, m)):
                            diag['nocursor_past_reentry_possible'] += 1
        # ---- 봉 종료 처리
        if pos and 'MAE_4H' in L:                       # 레거시: 봉 종료 시 4H 전체 High/Low 로 갱신 (V 청산보다 먼저)
            sd = pos['side']
            pos['peak'] = max(pos['peak'], sd.h_hi[t])
            pos['mae'] = min(pos['mae'], (sd.h_lo[t] - pos['entry']) / abs(pos['entry']))
        if pos and v_end and pos['side'] in v_end:
            close_pos(M[-1], pos['side'].h_cl[t], pos['frac'], 'v', data.h_ct[t])
        # ---- 4H R 갱신 (봉 t 종료 후: atr[t] 사용 가능)
        for sd in sides:
            waiting = sd.order_key
            sd.track_anchor()
            if sd.h4_update(t):
                ev('R_CONFIRM', sd, data.h_ct1[t], low=sd.R[0], high=sd.R[1], size=sd.R[2], atr_end_time=data.h_ct[t])
                if waiting is not None:
                    ev('R_REPLACED', sd, data.h_ct1[t], old_key=waiting, new_key=t)
                    cancel_order(sd, data.h_ct1[t], 'R_REPLACED')
                if pos and pos['side'] is sd:
                    ev('R_CONFIRM_POS_FROZEN', sd, data.h_ct1[t], signal_id=pos['signal_id'])
    if pos:
        sd = pos['side']
        pos['fills'].append((data.LAST, sd.h_cl[data.LAST], pos['frac'], 'open'))
        pos['fill_detail'].append((M[-1], data.h_ct[data.LAST], sd.h_cl[data.LAST], pos['frac'], 'open'))
        pos['frac'] = 0.0
        pos['seq'].append((data.h_ct[data.LAST], 'EXIT_OPEN', sd.h_cl[data.LAST], 1.0))
        finish(M[-1], data.h_ct[data.LAST])
    return trades, events, sides, diag


# ------------------------------------------------------------------ 회귀 불변식 (작업지시서 §19)
def check_invariants(trades, events, data, legacy=frozenset()):
    """교정 모드 거래/이벤트에서 look-ahead·순서 위반을 센다. 전부 0 이어야 한다."""
    c = Counter()
    for tr in trades:
        et, xt = tr['entry_time'], tr['exit_time']
        if not et < xt:
            c['entry_time_lt_exit_time_fail'] += 1
        if not tr['atr_end_time'] < tr['decision_time']:
            c['atr_end_time_lt_decision_time_fail'] += 1
        if not tr['r_confirm_time'] <= tr['order_create_time'] <= et:
            c['r_confirm_time_lt_entry_time_fail'] += 1
        if tr['r_confirm_time'] >= et:
            c['r_confirm_time_lt_entry_time_fail'] += 1
        # MAE 창: fill_m 이전 5분봉 사용 여부 — 종가진입이면 fill 봉 자체도 제외
        m0 = tr['fill_m'] + (1 if tr['fill_at_close'] else 0) if tr['fill_m'] is not None else None
        if m0 is not None and tr['exit_m'] is not None:
            lows = [data.f_lo[m] if tr['side'].s > 0 else -data.f_hi[m] for m in range(m0, tr['exit_m'] + 1)]
            if lows:
                min_lo = (min(lows) - tr['entry']) / abs(tr['entry'])
                # 실측 MAE 는 창 안의 최저가보다 나쁠 수 없다 (손절가 도달 시 손절가로 capped)
                if tr['mae'] < min(min_lo, 0.0) - 1e-9:
                    c['pre_entry_price_used_for_mae'] += 1
        if tr['fill_at_close'] and tr['fill_detail'] and tr['fill_detail'][0][0] == tr['fill_m'] and tr['fill_detail'][0][4] in ('stop', 'tp'):
            c['market_close_same_bar_sltp'] += 1
        # 이벤트 순서 단조
        tms = [x[0] for x in tr['seq']]
        if any(b_ < a_ for a_, b_ in zip(tms, tms[1:])):
            c['invalid_event_order'] += 1
        for (_, ftm, _, _, _) in tr['fill_detail']:
            if ftm < et:
                c['fill_before_entry'] += 1
        for (ft, _) in tr['funding_events']:
            if not (et < ft <= xt):
                c['funding_outside_window'] += 1
        # 목표(전주 고저) = 진입일이 속한 주 '이전에 완성된 주' 의 일봉 집계여야 하고, 그 주는 진입 전에 끝나야 한다
        pw_day = tr['day']
        pw = data.prev_week[pw_day]
        if pw is not None:
            w_start = data.d_ot[pw_day] - ((data.d_ot[pw_day] // D_MS + 3) % 7) * D_MS
            prev_days = [i for i in range(pw_day, -1, -1) if data.d_ot[i] < w_start]
            if prev_days:
                pw_week = data.d_ot[prev_days[0]] - ((data.d_ot[prev_days[0]] // D_MS + 3) % 7) * D_MS
                days = [i for i in prev_days if data.d_ot[i] >= pw_week]
                hi, lo = max(data.d_hi[i] for i in days), min(data.d_lo[i] for i in days)
                if abs(hi - pw[0]) > 1e-9 or abs(lo - pw[1]) > 1e-9 or data.d_ot[days[0]] + D_MS > et:
                    c['weekly_target_lookahead'] += 1
        # 엔진이 찍은 index 를 독립적으로 재계산: ATR 은 진입 4H 봉 직전 봉, R 은 진입 봉 이전에 확정
        if not legacy and tr['atr_idx'] != tr['t0'] - 1:
            c['atr_idx_not_prev_bar'] += 1
        if tr['entry_R']['ENTRY_R_T'] >= tr['t0']:
            c['r_confirm_bar_not_before_entry_bar'] += 1
        # 'v' 청산은 같은 거래의 V_DETECT 가 선행해야 한다
        if any(k == 'v' for (_, _, _, _, k) in tr['fill_detail']):
            if not any(k == 'V_DETECT' for (_, k, _, _) in tr['seq']):
                c['v_exit_without_detect'] += 1
    # 거래 간 겹침 없음: 다음 거래 진입 >= 직전 거래 청산
    order = sorted(trades, key=lambda x: x['entry_time'])
    for x, y in zip(order, order[1:]):
        if y['entry_time'] < x['exit_time']:
            c['trade_overlap'] += 1
    # 이벤트 시각 단조 (side 별)
    last = {}
    for (t, s, kind, d, tm, det) in events:
        if tm < last.get(s, 0):
            c['event_time_regression'] += 1
        last[s] = max(last.get(s, 0), tm)
    lookahead = (c['atr_end_time_lt_decision_time_fail'] + c['r_confirm_time_lt_entry_time_fail'] + c['pre_entry_price_used_for_mae']
                 + c['market_close_same_bar_sltp'] + c['fill_before_entry'] + c['funding_outside_window'] + c['weekly_target_lookahead']
                 + c['atr_idx_not_prev_bar'] + c['r_confirm_bar_not_before_entry_bar'])
    c['lookahead_count'] = lookahead
    c['invalid_event_order_count'] = (c['invalid_event_order'] + c['event_time_regression'] + c['entry_time_lt_exit_time_fail']
                                      + c['trade_overlap'] + c['v_exit_without_detect'])
    return c


def assert_invariants(trades, events, data):
    c = check_invariants(trades, events, data)
    assert c['lookahead_count'] == 0, c
    assert c['invalid_event_order_count'] == 0, c
    assert all(t['entry_time'] < t['exit_time'] for t in trades)
    assert all(t['atr_end_time'] < t['decision_time'] for t in trades)
    assert all(t['r_confirm_time'] < t['entry_time'] for t in trades)
    assert c['pre_entry_price_used_for_mae'] == 0
    assert c['market_close_same_bar_sltp'] == 0
    return c


# ------------------------------------------------------------------ Mark-to-Market MDD (작업지시서 §15)
def evaluate_mtm(trades, data, pos_f=0.30, lev=10, seed=10000.0, step=1):
    """Equity(t) = wallet + unrealized PnL - accrued funding, 5분봉 해상도.
    청산 시점 equity 는 fib_mtf.evaluate 와 동일하게 pm_of 로 갱신(청산가 -100% 포함).
    반환: mdd_close(5분 종가 기준), mdd_low(봉 내 불리한 극값 기준), 레거시(청산시점) mdd, 곡선 요약."""
    closed = [t for t in trades if t['result'] != 'open']          # fib_mtf.evaluate 와 동일하게 미청산(강제종료) 거래 제외
    closed.sort(key=lambda t: t['entry_time'])
    eq, peak = seed, seed
    mdd_c = mdd_l = mdd_trade = 0.0
    worst_c = worst_l = None
    curve = []
    for tr in closed:
        sd = tr['side']
        e = tr['entry']
        margin = eq * pos_f
        notional = margin * lev
        fee_in = FEE_TAKER if tr.get('taker') else FEE_MAKER
        fills = sorted(tr['fill_detail'], key=lambda x: x[1])
        m0 = tr['fill_m'] + (1 if tr['fill_at_close'] else 0) if tr['fill_m'] is not None else None
        m1 = tr['exit_m']
        fe = tr['funding_events']
        if m0 is not None and m1 is not None and m0 <= m1:
            fi = 0
            realized, rem, fund_acc = 0.0, 1.0, 0.0
            fk = 0
            for m in range(m0, m1 + 1, step):
                bar_ct = data.f_ot[m] + data.fine_ms - 1
                while fi < len(fills) and fills[fi][1] <= bar_ct:
                    _, ftm, px, fr, kind = fills[fi]
                    realized += fr * ((px - e) / abs(e) - (FEE_MAKER if kind == 'tp' else FEE_TAKER) - (SLIP if kind == 'stop' else 0.0))
                    rem -= fr
                    fi += 1
                while fk < len(fe) and fe[fk][0] <= bar_ct:
                    fund_acc += fe[fk][1]
                    fk += 1
                cl = sd.f_cl[m]
                lo = sd.f_lo[m]
                r_close = realized + max(rem, 0.0) * (cl - e) / abs(e) - fee_in - fund_acc
                r_low = realized + max(rem, 0.0) * (lo - e) / abs(e) - fee_in - fund_acc
                eq_c = eq + margin * max(-1.0, r_close * lev)        # wallet + unrealized (마진 전손 시 -margin)
                eq_l = eq + margin * max(-1.0, r_low * lev)
                peak = max(peak, eq_c)
                dd_c = (peak - eq_c) / peak * 100
                dd_l = (peak - eq_l) / peak * 100
                if dd_c > mdd_c:
                    mdd_c, worst_c = dd_c, (data.f_ot[m], eq_c, peak, tr['signal_id'])
                if dd_l > mdd_l:
                    mdd_l, worst_l = dd_l, (data.f_ot[m], eq_l, peak, tr['signal_id'])
                if step > 1 or (m - m0) % 48 == 0:
                    curve.append((data.f_ot[m], eq_c))
        pm = pm_of(tr, lev)
        eq *= max(0.0, 1 + pos_f * pm / 100)
        peak = max(peak, eq)
        dd = (peak - eq) / peak * 100
        mdd_trade = max(mdd_trade, dd)
        mdd_c, mdd_l = max(mdd_c, dd), max(mdd_l, dd)
        curve.append((tr['exit_time'], eq))
    return {'mdd_close': mdd_c, 'mdd_low': mdd_l, 'mdd_trade_close': mdd_trade, 'eq': eq, 'ret': (eq / seed - 1) * 100,
            'worst_close': worst_c, 'worst_low': worst_l, 'curve': curve}


# ------------------------------------------------------------------ 보고 도우미
def summarize(trades, pos_f=0.30, lev=10, seed=10000.0, years=None, data=None):
    e = evaluate(trades, pos_f, lev, seed, years)
    closed = [t for t in trades if t['result'] != 'open']
    e['stop_n'] = sum(1 for t in closed if t['result'] == 'stop')
    e['tp_n'] = sum(1 for t in closed if t['result'] in ('tp', 'tpm'))
    e['dv_n'] = sum(1 for t in closed if t['result'] in ('dexit', 'v'))
    e['v_n'] = sum(1 for t in closed if t['result'] == 'v')
    e['d_n'] = sum(1 for t in closed if t['result'] == 'dexit')
    e['fund_pct'] = sum(t['funding'] for t in closed) / max(1, len(closed)) * 100
    e['mae_avg'] = sum(t['mae'] for t in closed) / max(1, len(closed)) * 100
    e['mfe_avg'] = sum(t.get('mfe', 0.0) for t in closed) / max(1, len(closed)) * 100
    if data is not None and trades and 'fill_detail' in trades[0]:
        m = evaluate_mtm(trades, data, pos_f, lev, seed)
        e['mtm_mdd_close'], e['mtm_mdd_low'] = m['mdd_close'], m['mdd_low']
    return e


def trade_key(t):
    return t['key']


def diff_trades(A, B):
    """key=(side, R 확정봉) 기준 추가/삭제/공통(결과 변화) 집계."""
    ka = {t['key']: t for t in A}
    kb = {t['key']: t for t in B}
    removed = [ka[k] for k in ka if k not in kb]
    added = [kb[k] for k in kb if k not in ka]
    common = [(ka[k], kb[k]) for k in ka if k in kb]
    changed = [(x, y) for x, y in common if abs(x['r_net'] - y['r_net']) > 1e-9 or x['result'] != y['result']]
    return {'removed': removed, 'added': added, 'common': common, 'changed': changed}
