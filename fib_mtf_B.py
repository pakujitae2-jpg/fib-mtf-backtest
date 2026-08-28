# -*- coding: utf-8 -*-
# 일봉 기반 다중 타임프레임 피보나치 전략 엔진 (daily_mtf_fibonacci_strategy_v1.0)
#
#   M  월봉  : 방향 필터 (월봉 38.2 ZigZag 방향 / 6개월 평균 / off)
#   W  주봉  : 전주 고가·저가·폭 -> 확장 목표 #1-1(.146) #1-2(.236) #1-3(.382) #1-6(.618)
#   D  일봉  : 38.2% 확정 ZigZag(고가/저가 기준, 비리페인팅) -> 첫 눌림 확정 시 LONG ARMED
#              구조 필터: HH_HL(고점·저점 모두 상승) / HH / none
#              V자: 눌림 중 leg 시작점(P0) 훼손 -> 포지션 청산, vFlag -> 반대방향 첫 신호 1회 스킵
#              하방전환: 일봉 종가 < 최근 확정 눌림 저점(또는 P0) -> 잔여 청산
#   R  4H    : 4H ZigZag(r4) 로 확정된 최근 임펄스 leg. 유효성 R_size >= max(D_size*R_RATIO, ATR14*ATR_MULT)
#              LONG 진입 = R.low + 0.236*R_size (레드라인) 에 지정가, 손절 = R.low*(1-BUF)
#   숏은 가격을 부호 반전한 미러 좌표계에서 동일 로직으로 처리한다.
#   같은 4H 봉 안의 체결 선후는 5분봉으로 판정 (없으면 손절 우선).
import csv, time
from bisect import bisect_left
from collections import defaultdict

FEE_MAKER, FEE_TAKER, SLIP, FUNDING, MM = 0.0002, 0.0005, 0.0005, 0.0001, 0.005
FIB_EXT = [0.146, 0.236, 0.382, 0.618]
H_MS, D_MS = 3600000, 86400000
EPS = 1e-9
NOW_MS = int(time.time() * 1000)


def load_csv(p):
    with open(p, encoding='utf-8') as f:
        return [(int(r['open_time']), float(r['open']), float(r['high']), float(r['low']), float(r['close']),
                 int(r['close_time']) if 'close_time' in r else 0) for r in csv.DictReader(f)]


def ts(ot, hours=4):
    t = time.gmtime(ot / 1000)
    return time.strftime('%Y-%m-%d', t) if hours >= 24 else time.strftime('%Y-%m-%d %H:%M', t)


def zigzag_step(st, h, l, ratio, min_size=0.0):
    """st = [dir, anc_i, anc_p, ext_i, ext_p, bar]. 확정 피벗 (i, p, kind) 또는 None 반환.
    leg 크기가 min_size 미만이면 '진행형': 확정하지 않고, 시작점이 훼손되면 leg 를 새로 시작한다."""
    st[5] += 1
    t = st[5]
    if st[0] == 'UP':
        if h > st[4]:
            st[3], st[4] = t, h
        size = st[4] - st[2]
        if size < min_size:
            if l < st[2]:
                st[1], st[2], st[3], st[4] = t, l, t, h
            return None
        if l <= st[4] - ratio * size + EPS:
            piv = (st[3], st[4], 'H')
            st[0], st[1], st[2], st[3], st[4] = 'DOWN', st[3], st[4], t, l
            return piv
    else:
        if l < st[4]:
            st[3], st[4] = t, l
        size = st[2] - st[4]
        if size < min_size:
            if h > st[2]:
                st[1], st[2], st[3], st[4] = t, h, t, l
            return None
        if h >= st[4] + ratio * size - EPS:
            piv = (st[3], st[4], 'L')
            st[0], st[1], st[2], st[3], st[4] = 'UP', st[3], st[4], t, h
            return piv
    return None


def new_zz(h0, l0):
    return ['UP', 0, l0, 0, h0, -1]


# ------------------------------------------------------------------ 데이터
class Data:
    def __init__(self, d_rows, h4_rows, fine_rows, start='2019-03-01', funding=None):
        self.D = d_rows
        # funding: list of (time_ms, rate) for historical funding (v3); None -> fixed FUNDING
        self.fund_ts = [f[0] for f in funding] if funding else []
        self.fund_rate = [f[1] for f in funding] if funding else []
        self.d_ot = [r[0] for r in d_rows]
        self.d_hi = [r[2] for r in d_rows]
        self.d_lo = [r[3] for r in d_rows]
        self.d_cl = [r[4] for r in d_rows]
        self.H = h4_rows
        self.h_ot = [r[0] for r in h4_rows]
        self.h_op = [r[1] for r in h4_rows]
        self.h_hi = [r[2] for r in h4_rows]
        self.h_lo = [r[3] for r in h4_rows]
        self.h_cl = [r[4] for r in h4_rows]
        self.h_ct = [r[0] + 4 * H_MS - 1 for r in h4_rows]
        self.n4 = len(h4_rows)
        self.LAST = max(i for i in range(self.n4) if self.h_ct[i] <= NOW_MS)
        self.f_ot = [r[0] for r in fine_rows]
        self.f_hi = [r[2] for r in fine_rows]
        self.f_lo = [r[3] for r in fine_rows]
        self.f_cl = [r[4] for r in fine_rows]
        # 4H -> 일봉 인덱스
        self.h_day = [bisect_left(self.d_ot, ot + 1) - 1 for ot in self.h_ot]
        self.start4 = next(i for i in range(self.n4) if ts(self.h_ot[i]) >= start)
        # ATR14 (4H)
        atr, tr_hist = [], []
        for i in range(self.n4):
            tr = self.h_hi[i] - self.h_lo[i] if i == 0 else max(
                self.h_hi[i] - self.h_lo[i], abs(self.h_hi[i] - self.h_cl[i - 1]), abs(self.h_lo[i] - self.h_cl[i - 1]))
            tr_hist.append(tr)
            atr.append(sum(tr_hist[-14:]) / min(len(tr_hist), 14))
        self.atr = atr
        # 주봉(월요일 00:00 UTC): 일봉 인덱스별 "직전 완성 주" 고/저
        wk = {}
        order = []
        for i, ot in enumerate(self.d_ot):
            w = ot - ((ot // D_MS + 3) % 7) * D_MS
            if w not in wk:
                wk[w] = [self.d_hi[i], self.d_lo[i], self.d_cl[i]]
                order.append(w)
            else:
                wk[w][0] = max(wk[w][0], self.d_hi[i])
                wk[w][1] = min(wk[w][1], self.d_lo[i])
                wk[w][2] = self.d_cl[i]
        self.prev_week = []
        for i, ot in enumerate(self.d_ot):
            w = ot - ((ot // D_MS + 3) % 7) * D_MS
            k = bisect_left(order, w) - 1
            self.prev_week.append((wk[order[k]][0], wk[order[k]][1]) if k >= 0 else None)
        # 월봉: 일봉 인덱스별 "직전 완성 월까지" 방향 (zz / sma)
        mo, morder = {}, []
        for i, ot in enumerate(self.d_ot):
            m = time.strftime('%Y-%m', time.gmtime(ot / 1000))
            if m not in mo:
                mo[m] = [self.d_hi[i], self.d_lo[i], self.d_cl[i]]
                morder.append(m)
            else:
                mo[m][0] = max(mo[m][0], self.d_hi[i])
                mo[m][1] = min(mo[m][1], self.d_lo[i])
                mo[m][2] = self.d_cl[i]
        zz_dir, sma_dir = {}, {}
        st = new_zz(mo[morder[0]][0], mo[morder[0]][1])
        closes = []
        for m in morder:
            zigzag_step(st, mo[m][0], mo[m][1], 0.382, 0.10 * abs(st[2]))
            closes.append(mo[m][2])
            zz_dir[m] = st[0]
            sma_dir[m] = 'UP' if closes[-1] > sum(closes[-6:]) / len(closes[-6:]) else 'DOWN'
        self.m_zz, self.m_sma = [], []
        for ot in self.d_ot:
            m = time.strftime('%Y-%m', time.gmtime(ot / 1000))
            k = morder.index(m) - 1
            self.m_zz.append(zz_dir[morder[k]] if k >= 0 else None)
            self.m_sma.append(sma_dir[morder[k]] if k >= 0 else None)

    def fine_range(self, t):
        a = bisect_left(self.f_ot, self.h_ot[t])
        b = bisect_left(self.f_ot, self.h_ct[t])
        return a, b


# ------------------------------------------------------------------ 한쪽 방향 상태 (미러 좌표계)
class Side:
    def __init__(self, sign, data, P):
        self.s, self.d, self.P = sign, data, P
        sg = sign
        # 미러 좌표: sign=-1 이면 hi' = -lo, lo' = -hi
        self.d_hi = data.d_hi if sg > 0 else [-x for x in data.d_lo]
        self.d_lo = data.d_lo if sg > 0 else [-x for x in data.d_hi]
        self.d_cl = [sg * x for x in data.d_cl]
        self.h_hi = data.h_hi if sg > 0 else [-x for x in data.h_lo]
        self.h_lo = data.h_lo if sg > 0 else [-x for x in data.h_hi]
        self.h_cl = [sg * x for x in data.h_cl]
        self.h_op = [sg * x for x in data.h_op]
        self.f_hi = data.f_hi if sg > 0 else [-x for x in data.f_lo]
        self.f_lo = data.f_lo if sg > 0 else [-x for x in data.f_hi]
        self.f_cl = [sg * x for x in data.f_cl]
        self.sig_key = None
        self.dzz = new_zz(self.d_hi[0], self.d_lo[0])
        self.hzz = None
        self.pivH, self.pivL = [], []          # 확정 일봉 피벗 (idx, price)
        self.armed, self.P0, self.H1, self.arm_day, self.dsize = False, None, None, None, None
        self.lastL = None                       # 확정된 눌림 저점 (arm 이후)
        self.vflag = False
        self.R = None                           # (low, high, size, confirm_t)
        self.R_broken = False
        self._leg_anchor = None

    def daily_update(self, d):
        """일봉 d 종가 처리."""
        anc_before = self.dzz[2] if self.dzz[0] == 'UP' else None    # flip 전 leg 시작 저점
        piv = zigzag_step(self.dzz, self.d_hi[d], self.d_lo[d], self.P['DCONF'], self.P['DMIN'] * abs(self.dzz[2]))
        ev = None
        if piv:
            i, p, kind = piv
            if kind == 'H':
                prevH = self.pivH[-1][1] if self.pivH else None
                prevL = self.pivL[-2][1] if len(self.pivL) >= 2 else None   # 현재 leg 의 anchor 는 pivL[-1]
                self.pivH.append((i, p))
                anchor = anc_before
                st = self.P['STRUCT']
                ok = True
                if st in ('HH', 'HH_HL') and prevH is not None and p <= prevH:
                    ok = False
                if st == 'HH_HL' and prevL is not None and anchor <= prevL:
                    ok = False
                if ok:
                    self.armed, self.P0, self.H1, self.arm_day = True, anchor, p, d
                    self.dsize = p - anchor
                    self.lastL = None
                    ev = 'ARM'
            else:
                self.pivL.append((i, p))
                self.lastL = p
                if self.armed:
                    self.armed = False           # 첫 눌림 종료
                    ev = 'DISARM'
        return ev

    def m_ok(self, d):
        f = self.P['MFILT']
        if f == 'off':
            return True
        dirs = self.d.m_zz if f == 'zz' else self.d.m_sma
        v = dirs[d]
        want = 'UP' if self.s > 0 else 'DOWN'
        return v == want

    def h4_update(self, t):
        """4H 봉 t 로 R 파동 갱신. 새 R 확정 시 True."""
        if self.hzz is None:
            self.hzz = new_zz(self.h_hi[t], self.h_lo[t])
            self.hzz[5] = t - 1
        piv = zigzag_step(self.hzz, self.h_hi[t], self.h_lo[t], self.P['R4'], self.d.atr[t] * self.P['ATR_MULT'])
        if piv and piv[2] == 'H' and self._leg_anchor is not None:
            # 확정된 UP leg: anchor(low) -> pivot(high). anchor 는 flip 직전 값이라 track_anchor 로 따로 보관
            self.R = (self._leg_anchor, piv[1], piv[1] - self._leg_anchor, t)
            self.R_broken = False
            return True
        return False

    def track_anchor(self):
        # zigzag 상태의 anchor 가 'UP' 상태일 때의 leg 시작 저점
        if self.hzz and self.hzz[0] == 'UP':
            self._leg_anchor = self.hzz[2]

    def r_valid(self, t):
        if self.R is None or self.R_broken or self.dsize is None:
            return False
        need = max(self.dsize * self.P['R_RATIO'], self.d.atr[t] * self.P['ATR_MULT'])
        return self.R[2] >= need

    def entry_level(self):
        low, high, size, _ = self.R
        lv = low + self.P.get('R_ENTRY_FIB', 0.236) * size      # R_ENTRY_FIB (v2: independent parameter)
        return lv + self.P['TOL'] * abs(lv)       # 레드라인 살짝 위에 지정가

    def stop_level(self):
        return self.R[0] - self.P['BUF'] * abs(self.R[0])

    def targets(self, d, entry):
        pw = self.d.prev_week[d]
        if pw is None:
            return []
        wh, wl = (pw[0], pw[1]) if self.s > 0 else (-pw[1], -pw[0])
        rng = wh - wl
        out = [wh + rng * f for f in FIB_EXT]
        return [x for x in out if x > entry + 0.003 * abs(entry)]


# ------------------------------------------------------------------ 시뮬레이션
def run(data, P):
    """P: dict(DCONF, R4, R_RATIO, ATR_MULT, TOL, BUF, EXIT, RATCHET, MFILT, STRUCT, SIDES)"""
    sides = []
    if P['SIDES'] in ('both', 'long'):
        sides.append(Side(+1, data, P))
    if P['SIDES'] in ('both', 'short'):
        sides.append(Side(-1, data, P))
    # 일봉 워밍업: start4 이전 일봉 전부 처리
    d0 = data.h_day[data.start4]
    for sd in sides:
        for d in range(0, d0):
            sd.daily_update(d)
    cur_day = d0
    # 4H ZigZag 워밍업 (start4 이전 300봉)
    for sd in sides:
        for t in range(max(0, data.start4 - 300), data.start4):
            sd.track_anchor()
            sd.h4_update(t)
    pos = None
    trades = []
    events = []                  # (t, text) 감지 로그

    def close_pos(t, px, frac, kind, fine_i=None):
        nonlocal pos
        sd = pos['side']
        pos['fills'].append((t, px, frac, kind))
        pos['frac'] -= frac
        if pos['frac'] <= 1e-9:
            finish(t)

    def apply_policy(t, m):
        # v3 TGT_POLICY: after the first TP fill, targets already passed in this 5m bar are
        #   'retro'  -> filled later at their own price (default, conservative)
        #   'skip'   -> dropped (record only, no retroactive exit)
        #   'market' -> closed now at the 5m close (taker)
        nonlocal pos
        policy = P.get('TGT_POLICY', 'retro')
        if policy == 'retro' or pos.get('policy_done'):
            return
        pos['policy_done'] = True
        sd = pos['side']
        passed = [x for x in pos['tgts'] if x[0] <= sd.f_hi[m] + EPS]
        pos['tgts'] = [x for x in pos['tgts'] if x[0] > sd.f_hi[m] + EPS]
        if policy == 'market':
            for px, fr in passed:
                if pos is None:
                    break
                close_pos(t, sd.f_cl[m] - SLIP * abs(sd.f_cl[m]), min(fr, pos['frac']), 'tpm')

    def finish(t):
        nonlocal pos
        sd = pos['side']
        e = pos['entry']
        r = 0.0
        fee = FEE_TAKER if pos.get('taker') else FEE_MAKER
        for (_, px, fr, kind) in pos['fills']:
            r += fr * (px - e) / abs(e)
            fee += fr * (FEE_MAKER if kind == 'tp' else FEE_TAKER)
            if kind == 'stop':
                r -= fr * SLIP
        hold_h = (data.h_ot[t] - data.h_ot[pos['t0']]) / H_MS + 4
        if data.fund_ts:
            # historical funding: sum(rate * remaining fraction) over funding stamps inside the holding window
            a = bisect_left(data.fund_ts, data.h_ot[pos['t0']] + 1)
            b = bisect_left(data.fund_ts, data.h_ot[t] + 4 * H_MS)
            fund, nev = 0.0, 0
            for k in range(a, b):
                ft = data.fund_ts[k]
                rem = 1.0 - sum(fr for (j, _, fr, _) in pos['fills'] if data.h_ot[j] + 4 * H_MS <= ft)
                if rem <= 0:
                    break
                fund += data.fund_rate[k] * rem * (1 if sd.s > 0 else -1)
                nev += 1
            pos['fund_events'] = nev
        else:
            fund = FUNDING * hold_h / 8
        pos['funding'] = fund
        pos['r_net'] = r - fee - fund
        pos['t1'] = t
        pos['hold_h'] = hold_h
        pos['result'] = pos['fills'][-1][3]
        trades.append(pos)
        pos = None

    for t in range(data.start4, data.LAST + 1):
        d = data.h_day[t]
        # ---- 새 날: 직전 일봉 종가 처리
        if d != cur_day:
            for sd in sides:
                ev = sd.daily_update(d - 1)
                if ev:
                    events.append((t, sd.s, ev, d - 1))
                if pos and pos['side'] is sd and pos['frac'] > 0:
                    # 하방(상방) 전환: 일봉 종가 < 확정 눌림 저점 (없으면 P0)
                    if pos['d_exit']:
                        ref = sd.lastL if sd.lastL is not None else pos['P0']
                        if sd.d_cl[d - 1] < ref - EPS:
                            close_pos(t, sd.h_op[t], pos['frac'], 'dexit')
            cur_day = d
        # ---- 포지션 관리 (봉 t 내부, 5분봉 순서)
        if pos:
            sd = pos['side']
            if P['RATCHET']:
                pos['stop'] = max(pos['stop'], pos['peak'] - P['RATCHET'] * abs(pos['peak']))
            a, b = data.fine_range(t)
            if a < b:
                for m in range(a, b):
                    if pos is None:
                        break
                    if sd.f_lo[m] <= pos['stop'] + EPS:
                        close_pos(t, pos['stop'], pos['frac'], 'stop')
                        break
                    while pos and pos['tgts'] and sd.f_hi[m] >= pos['tgts'][0][0] - EPS:
                        px, fr = pos['tgts'].pop(0)
                        close_pos(t, px, min(fr, pos['frac']), 'tp')
                        if pos and pos['be']:
                            pos['stop'] = max(pos['stop'], pos['entry'] + 0.002 * abs(pos['entry']))
                        if pos:
                            apply_policy(t, m)
            else:   # 5분봉 없음: 손절 우선
                if sd.h_lo[t] <= pos['stop'] + EPS:
                    close_pos(t, pos['stop'], pos['frac'], 'stop')
                else:
                    while pos and pos['tgts'] and sd.h_hi[t] >= pos['tgts'][0][0] - EPS:
                        px, fr = pos['tgts'].pop(0)
                        close_pos(t, px, min(fr, pos['frac']), 'tp')
                        if pos and pos['be']:
                            pos['stop'] = max(pos['stop'], pos['entry'] + 0.002 * abs(pos['entry']))
            if pos:
                pos['peak'] = max(pos['peak'], sd.h_hi[t])
                pos['mae'] = min(pos['mae'], (sd.h_lo[t] - pos['entry']) / abs(pos['entry']))
        for sd in sides:
            if sd.R and not sd.R_broken and sd.h_lo[t] < sd.R[0] - EPS:
                if sd.armed and sd.r_valid(t) and sd.sig_key == sd.R[3]:
                    events.append((t, sd.s, 'R_INVALID', d))      # valid signal lost before fill
                sd.R_broken = True
        # ---- signal events (armed + valid R, once per R)
        for sd in sides:
            if sd.armed and sd.R and not sd.R_broken and sd.r_valid(t) and sd.R[3] < t and sd.sig_key != sd.R[3]:
                sd.sig_key = sd.R[3]
                events.append((t, sd.s, 'SIGNAL', d))
        # ---- entry (R confirmed at t-1 or earlier)
        fill_model = P.get('FILL', 'A')
        pen = P.get('PEN', 0.0)
        if pos is None:
            for sd in sides:
                if not sd.armed or not sd.r_valid(t) or sd.R[3] >= t:
                    continue
                if not sd.m_ok(d):
                    continue
                lv = sd.entry_level()
                need = lv - pen * abs(lv) if fill_model == 'B' else lv     # B: must trade through the level
                if sd.h_lo[t] > need + EPS:
                    continue
                stop = sd.stop_level()
                if lv <= stop:
                    continue
                # 반대 side 의 vFlag -> 이 방향 첫 신호 스킵
                other = [o for o in sides if o is not sd]
                if other and other[0].vflag:
                    other[0].vflag = False
                    events.append((t, sd.s, 'SKIP_V', d))
                    sd.R_broken = True      # 이 R 로는 재진입 안 함
                    continue
                # 체결: 5분봉에서 레벨 첫 터치
                a, b = data.fine_range(t)
                fill_m = None
                if a < b:
                    fill_m = next((m for m in range(a, b) if sd.f_lo[m] <= need + EPS), None)
                    if fill_m is None:
                        continue
                expected = lv
                taker = False
                if fill_model == 'C':                                   # market right after the touch
                    lv = (sd.f_cl[fill_m] if fill_m is not None else sd.h_cl[t]) + SLIP * abs(lv)
                    taker = True
                    if lv <= stop:
                        continue
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
                elif ex in ('tpR2', 'tpR3'):                       # R-multiple take-profit (v2 validation)
                    tg = [(lv + (2.0 if ex == 'tpR2' else 3.0) * (lv - stop), 1.0)]
                elif ex == 'halfR2':                                # half at +2R, rest BE + daily reversal
                    tg = [(lv + 2.0 * (lv - stop), 0.5)]
                    d_exit, be = True, True
                elif ex == 'halfR2spec':                            # half at +2R, rest W-extension + daily reversal
                    tg = [(lv + 2.0 * (lv - stop), 0.5)] + [(x, 0.125) for x in sd.targets(d, lv)]
                    d_exit, be = True, True
                pos = {'side': sd, 't0': t, 'entry': lv, 'stop': stop, 'stop0': stop, 'frac': 1.0,
                       'tgts': tg, 'd_exit': d_exit, 'be': be, 'fills': [], 'peak': lv, 'mae': 0.0,
                       'P0': sd.P0, 'H1': sd.H1, 'dsize': sd.dsize, 'R': sd.R, 'day': d,
                       'expected': expected, 'taker': taker, 'age': t - sd.R[3], 'key': (sd.s, sd.R[3])}
                sd.armed = False                     # 첫 눌림 1회 진입
                sd.R_broken = True
                # 체결 봉 잔여 구간 손절/목표 확인
                if fill_m is not None:
                    for m in range(fill_m, b):
                        if pos is None:
                            break
                        if sd.f_lo[m] <= pos['stop'] + EPS:
                            close_pos(t, pos['stop'], pos['frac'], 'stop')
                            break
                        while pos and pos['tgts'] and sd.f_hi[m] >= pos['tgts'][0][0] - EPS:
                            px, fr = pos['tgts'].pop(0)
                            close_pos(t, px, min(fr, pos['frac']), 'tp')
                            if pos and pos['be']:
                                pos['stop'] = max(pos['stop'], pos['entry'] + 0.002 * abs(pos['entry']))
                            if pos:
                                apply_policy(t, m)
                elif sd.h_lo[t] <= stop + EPS:
                    close_pos(t, stop, 1.0, 'stop')
                if pos:
                    pos['peak'] = max(pos['peak'], sd.h_hi[t])
                    pos['mae'] = min(pos['mae'], (sd.h_lo[t] - lv) / abs(lv))
                break
        # ---- V자 (armed 중 P0 훼손) : 양쪽 side
        for sd in sides:
            if sd.armed and sd.h_lo[t] < sd.P0 - EPS:
                sd.armed = False
                sd.vflag = True
                events.append((t, sd.s, 'V', d))
                if pos and pos['side'] is sd:
                    close_pos(t, sd.h_cl[t], pos['frac'], 'v')
        # ---- 4H R 갱신
        for sd in sides:
            sd.track_anchor()
            sd.h4_update(t)
    if pos:
        pos['fills'].append((data.LAST, pos['side'].h_cl[data.LAST], pos['frac'], 'open'))
        pos['frac'] = 0.0
        finish(data.LAST)
    return trades, events, sides


# ------------------------------------------------------------------ 성과 계산
def pm_of(tr, lev):
    """마진 기준 손익 %. 청산가 도달(MAE) 시 -100."""
    if tr['mae'] <= -(1.0 / lev - MM):
        return -100.0
    return tr['r_net'] * lev * 100


def evaluate(trades, pos=0.30, lev=10, seed=10000.0, years=None):
    closed = [t for t in trades if t['result'] != 'open']
    eq, peak, mdd = seed, seed, 0.0
    streak = worst = 0
    gp = gl = 0.0
    pms = []
    for t in closed:
        pm = pm_of(t, lev)
        pms.append(pm)
        eq *= max(0.0, 1 + pos * pm / 100)
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak * 100)
        if pm > 0:
            gp += pm
            streak = 0
        else:
            gl -= pm
            streak += 1
            worst = max(worst, streak)
    n = len(closed)
    wins = [p for p in pms if p > 0]
    avg = lambda xs: sum(xs) / len(xs) if xs else 0.0
    sd = (sum((p - avg(pms)) ** 2 for p in pms) / n) ** 0.5 if n > 1 else 0.0
    return {'n': n, 'wr': len(wins) / n * 100 if n else 0.0, 'avg_win': avg(wins),
            'avg_loss': avg([p for p in pms if p <= 0]), 'pf': gp / gl if gl > 0 else (9.99 if gp > 0 else 0.0),
            'exp': avg(pms), 'eq': eq, 'ret': (eq / seed - 1) * 100, 'mdd': mdd, 'worst': worst,
            'sharpe': (avg(pms) / sd * (n / max(years, 0.5)) ** 0.5) if sd > 0 and years else 0.0,
            'hold_d': avg([t['hold_h'] / 24 for t in closed]),
            'long_n': sum(1 for t in closed if t['side'].s > 0),
            'short_n': sum(1 for t in closed if t['side'].s < 0),
            'long_pf': _pf([pm_of(t, lev) for t in closed if t['side'].s > 0]),
            'short_pf': _pf([pm_of(t, lev) for t in closed if t['side'].s < 0]),
            'liq': sum(1 for p in pms if p <= -100 + 1e-9)}


def _pf(pms):
    gp = sum(p for p in pms if p > 0)
    gl = -sum(p for p in pms if p <= 0)
    return gp / gl if gl > 0 else (9.99 if gp > 0 else 0.0)


def load_data(start='2019-03-01', sym='btcusdt'):
    import os
    if sym == 'btcusdt':
        d = load_csv('btcusdt_1d_2017.csv') if os.path.exists('btcusdt_1d_2017.csv') else load_csv('btcusdt_1d.csv')
        if os.path.exists('btcusdt_4h_2019.csv'):
            h4 = load_csv('btcusdt_4h_2019.csv')
        else:
            from tl_engine import resample
            h4 = resample(load_csv('btcusdt_1h.csv'), 4)
        fine = []
        if os.path.exists('btcusdt_5m_2019_2022.csv'):
            fine += load_csv('btcusdt_5m_2019_2022.csv')
        fine += load_csv('btcusdt_5m.csv')
    else:
        d = load_csv('%s_1d.csv' % sym)
        h4 = load_csv('%s_4h.csv' % sym)
        fine = load_csv('%s_5m.csv' % sym)
        start = max(start, ts(h4[0][0] + 90 * D_MS, 24))     # listing + 90d warm-up
    fine = [r for r in fine if r[0] >= h4[0][0]]
    return Data(d, h4, fine, start)


def evaluate_risk(trades, risk_f=0.01, seed=10000.0, cap_lev=10.0):
    """Fixed-fractional risk sizing: notional = equity * risk_f / stop_distance, leverage capped."""
    eq, peak, mdd = seed, seed, 0.0
    streak = worst = 0
    levs, rs = [], []
    for t in trades:
        if t['result'] == 'open':
            continue
        risk = (t['entry'] - t['stop0']) / abs(t['entry'])
        lev = min(risk_f / risk, cap_lev) if risk > 0 else cap_lev
        ret = lev * t['r_net']
        if t['mae'] <= -(1.0 / lev - MM):
            ret = -1.0
        eq *= max(0.0, 1 + ret)
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak * 100)
        streak = streak + 1 if ret <= 0 else 0
        worst = max(worst, streak)
        levs.append(lev)
        rs.append(ret * 100)
    n = len(rs)
    return {'n': n, 'ret': (eq / seed - 1) * 100, 'mdd': mdd, 'worst': worst, 'eq': eq,
            'avg_lev': sum(levs) / n if n else 0.0, 'avg_ret': sum(rs) / n if n else 0.0,
            'wr': sum(1 for x in rs if x > 0) / n * 100 if n else 0.0}


def load_funding(path):
    import os
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        return [(int(r['funding_time']), float(r['rate'])) for r in csv.DictReader(f)]
