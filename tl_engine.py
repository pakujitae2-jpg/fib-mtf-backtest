# -*- coding: utf-8 -*-
# 상승 추세선 리테스트 엔진 (타임프레임 독립)
#   bars : 일봉 또는 4시간봉 (1시간봉을 합성)
#   fine : 5분봉 - 같은 봉 안에서 손절/익절 선후 판정용
#
# 청산 모드(exit)
#   tp10f : 익절 +10%,  손절 = 진입 시점 추세선 -buf 고정
#   tp10t : 익절 +10%,  손절 = 추세선을 따라 상향(트레일)
#   tp20t : 익절 +20%,  트레일 손절
#   trail : 익절 없음.  추세선 트레일 손절이 걸릴 때까지 보유
#   half  : +10%에서 절반 익절 -> 나머지는 본절(진입가+0.2%) 이상으로 올린 트레일 손절
import csv, time
from bisect import bisect_left, bisect_right
from collections import defaultdict

FEE_MAKER = 0.0002
FEE_TAKER = 0.0005
SLIP = 0.0005
FUNDING = 0.0001      # 8시간당
MM = 0.005            # 유지증거금 근사 -> 청산가 = entry*(1-1/lev+MM)
MIN_GAP = 5
MAX_SLOPE_D = 0.03    # 일 상승률 상한 (봉 단위로 환산)
MIN_SLOPE_D = 0.0005
EPS = 1e-9
NOW_MS = int(time.time() * 1000)
H_MS = 3600000


def load_csv(p):
    with open(p, encoding='utf-8') as f:
        return [(int(r['open_time']), float(r['open']), float(r['high']),
                 float(r['low']), float(r['close']),
                 int(r['close_time']) if 'close_time' in r else 0) for r in csv.DictReader(f)]


def resample(rows, hours):
    """1시간봉 -> hours시간봉 (UTC 00:00 기준 정렬)"""
    span = hours * H_MS
    out, cur = [], None
    for ot, o, h, l, c, ct in rows:
        key = ot - ot % span
        if cur is None or cur[0] != key:
            if cur:
                out.append(tuple(cur))
            cur = [key, o, h, l, c, key + span - 1]
        else:
            cur[2] = max(cur[2], h)
            cur[3] = min(cur[3], l)
            cur[4] = c
    if cur:
        out.append(tuple(cur))
    return out


def fmt(ot, hours):
    t = time.gmtime(ot / 1000)
    return time.strftime('%Y-%m-%d', t) if hours >= 24 else time.strftime('%Y-%m-%d %H:%M', t)


class Engine:
    def __init__(self, bars, fine, hours, start):
        self.hours = hours
        self.ot = [b[0] for b in bars]
        self.op = [b[1] for b in bars]
        self.hi = [b[2] for b in bars]
        self.lo = [b[3] for b in bars]
        self.cl = [b[4] for b in bars]
        self.ct = [b[5] for b in bars]
        self.n = len(bars)
        self.label = [fmt(o, hours) for o in self.ot]
        self.LAST = max(i for i in range(self.n) if self.ct[i] <= NOW_MS)
        self.START_I = next(i for i in range(self.n) if self.label[i][:10] >= start)
        self.f_ot = [b[0] for b in fine]
        self.f_hi = [b[2] for b in fine]
        self.f_lo = [b[3] for b in fine]
        self.max_slope = MAX_SLOPE_D * hours / 24
        self.min_slope = MIN_SLOPE_D * hours / 24
        self._piv, self._vu = {}, {}

    # ------------------------------------------------------------ 추세선
    def pivots(self, k):
        if k not in self._piv:
            lo, out = self.lo, []
            for i in range(k, self.n - k):
                v = lo[i]
                if all(v < lo[i - j] for j in range(1, k + 1)) and all(v <= lo[i + j] for j in range(1, k + 1)):
                    out.append(i)
            self._piv[k] = out
        return self._piv[k]

    def line(self, tl, t):
        return self.lo[tl[0]] + tl[2] * (t - tl[0])

    def valid_until(self, p1, p2, vmode, N):
        key = (p1, p2, vmode)
        if key not in self._vu:
            slope = (self.lo[p2] - self.lo[p1]) / (p2 - p1)
            src = self.lo if vmode == 'low' else self.cl
            base = self.lo[p1]
            end = min(self.n, p1 + N + 1)       # 신호는 i-p1<=N 이므로 그 이후 유효성은 불필요
            vu = end
            for t in range(p1 + 1, end):
                if src[t] < base + slope * (t - p1) - EPS:
                    vu = t
                    break
            self._vu[key] = vu
        return self._vu[key]

    def best_line(self, i, N, k, vmode):
        P = self.pivots(k)
        cand = P[bisect_left(P, i - N):bisect_right(P, i - k)]
        best, best_v = None, -1.0
        lo = self.lo
        for x in range(len(cand)):
            p1 = cand[x]
            for y in range(x + 1, len(cand)):
                p2 = cand[y]
                if p2 - p1 < MIN_GAP or lo[p2] <= lo[p1]:
                    continue
                slope = (lo[p2] - lo[p1]) / (p2 - p1)
                r = slope / lo[p1]
                if r < self.min_slope or r > self.max_slope:
                    continue
                if i >= self.valid_until(p1, p2, vmode, N):
                    continue
                v = lo[p1] + slope * (i - p1)
                if v > best_v:
                    best, best_v = (p1, p2, slope), v
        return best

    def signals(self, N, k, zone, vmode):
        out = []
        for i in range(self.START_I, self.LAST + 1):
            tl = self.best_line(i, N, k, vmode)
            if tl is None:
                continue
            L = self.line(tl, i)
            if self.lo[i] <= L * (1 + zone) + EPS and self.cl[i] > L:
                out.append((i, tl))
        return out

    # ------------------------------------------------------------ 체결
    def fine_range(self, j):
        a = bisect_left(self.f_ot, self.ot[j])
        b = bisect_left(self.f_ot, self.ct[j])
        return a, b

    def first_event(self, j, stop, target, from_idx=None):
        """봉 j 안에서 stop/target 중 먼저 닿은 것과 그 5분봉 인덱스. 같은 5분봉이면 stop."""
        a, b = self.fine_range(j)
        if from_idx is not None:
            a = from_idx
        if a >= b:
            return 'stop', b
        for m in range(a, b):
            s = self.f_lo[m] <= stop + EPS
            t = target is not None and self.f_hi[m] >= target - EPS
            if s:
                return 'stop', m
            if t:
                return 'tp', m
        return None, b

    def walk(self, i, tl, exit_mode, sbuf, liq, ratchet=None):
        entry = self.cl[i]
        tp = {'tp10f': 0.10, 'tp10t': 0.10, 'tp15t': 0.15, 'tp20t': 0.20, 'half': 0.10}.get(exit_mode)
        target = entry * (1 + tp) if tp else None
        trail = exit_mode != 'tp10f'
        partial = exit_mode == 'half'
        if isinstance(tl, tuple):
            init_stop = self.line(tl, i) * (1 - sbuf)
        else:
            init_stop, trail = tl, False        # 고정 손절가가 직접 주어진 경우 (저점 리테스트 패턴)
        frac, be, fills = 1.0, False, []
        peak = self.hi[i]
        for j in range(i + 1, self.LAST + 1):
            stop = self.line(tl, j) * (1 - sbuf) if trail else init_stop
            if ratchet:
                stop = max(stop, peak * (1 - ratchet))   # 직전 봉까지의 최고가 기준
            peak = max(peak, self.hi[j])
            if be:
                stop = max(stop, entry * 1.002)
            stop = max(stop, liq)
            s = self.lo[j] <= stop + EPS
            t = target is not None and self.hi[j] >= target - EPS
            if not s and not t:
                continue
            if s and t:
                ev, m = self.first_event(j, stop, target)
                if ev is None:
                    ev = 'stop'
            else:
                ev, m = ('stop' if s else 'tp'), None
            if ev == 'tp':
                if not partial:
                    fills.append((j, target, frac, 'tp'))
                    return fills, init_stop
                fills.append((j, target, 0.5, 'tp'))
                frac, target, be = 0.5, None, True
                stop2 = max(stop, entry * 1.002)
                # 같은 봉에서 절반 익절 후 남은 구간에 손절이 닿았는지
                a, b = self.fine_range(j)
                if m is not None and any(self.f_lo[x] <= stop2 + EPS for x in range(m + 1, b)):
                    fills.append((j, stop2 * (1 - SLIP), frac, 'stop'))
                    return fills, init_stop
                continue
            if stop <= liq + EPS:
                fills.append((j, liq, frac, 'liq'))
            else:
                fills.append((j, stop * (1 - SLIP), frac, 'stop'))
            return fills, init_stop
        fills.append((self.LAST, self.cl[self.LAST], frac, 'open'))
        return fills, init_stop

    def simulate(self, sigs, exit_mode, sbuf, pos, lev, seed=10000.0, lo_i=None, hi_i=None, ratchet=None):
        """lo_i~hi_i 범위의 신호만 진입 (IS/OOS 분리용)"""
        eq, peak, mdd, busy = seed, seed, 0.0, -1
        cnt = defaultdict(int)
        streak = worst = 0
        trades, gp, gl = [], 0.0, 0.0
        for i, tl in sigs:
            if i <= busy or (lo_i is not None and i < lo_i) or (hi_i is not None and i > hi_i):
                continue
            entry = self.cl[i]
            liq = entry * (1 - 1.0 / lev + MM)
            fills, init_stop = self.walk(i, tl, exit_mode, sbuf, liq, ratchet)
            j_end = fills[-1][0]
            busy = j_end
            margin = eq * pos
            notional = margin * lev
            qty = notional / entry
            pnl = -notional * FEE_TAKER
            for j, px, fr, kind in fills:
                pnl += qty * fr * (px - entry) - qty * fr * px * (FEE_MAKER if kind == 'tp' else FEE_TAKER)
                pnl -= qty * fr * entry * FUNDING * ((j - i) * self.hours / 8)
            if fills[-1][3] == 'liq':
                pnl = -margin
            last = fills[-1][3]
            if last == 'open':
                res = 'open'
            elif last == 'liq':
                res = 'liq'
            elif last == 'tp':
                res = 'tp'
            else:
                res = 'sp' if pnl > 0 else 'sl'
            pm = pnl / margin * 100
            trades.append({'i': i, 'j': j_end, 'res': res, 'entry': entry, 'stop': init_stop,
                           'exit': fills[-1][1], 'pm': pm, 'tl': tl, 'fills': fills,
                           'risk': (entry - init_stop) / entry * 100})
            if res == 'open':
                continue
            cnt[res] += 1
            eq += pnl
            peak = max(peak, eq)
            mdd = max(mdd, (peak - eq) / peak * 100)
            if pnl > 0:
                gp += pnl
                streak = 0
            else:
                gl -= pnl
                streak += 1
                worst = max(worst, streak)
            if eq <= 0:
                break
        closed = [t for t in trades if t['res'] != 'open']
        n = len(closed)
        wins = [t for t in closed if t['pm'] > 0]
        avg = lambda xs: sum(xs) / len(xs) if xs else 0.0
        return {'n': n, 'sig': len(sigs), 'tp': cnt['tp'], 'sp': cnt['sp'], 'sl': cnt['sl'],
                'liq': cnt['liq'], 'open': sum(1 for t in trades if t['res'] == 'open'),
                'wr': len(wins) / n * 100 if n else 0.0,
                'pnl_m': avg([t['pm'] for t in closed]),
                'avg_win': avg([t['pm'] for t in wins]),
                'avg_loss': avg([t['pm'] for t in closed if t['pm'] <= 0]),
                'pf': (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0),
                'risk': avg([t['risk'] for t in closed]),
                'hold': avg([(t['j'] - t['i']) * self.hours / 24 for t in closed]),
                'eq': eq, 'ret': (eq / seed - 1) * 100, 'mdd': mdd, 'worst': worst,
                'trades': trades}


def build(tf, start):
    h1 = load_csv('btcusdt_1h.csv')
    fine = load_csv('btcusdt_5m.csv')
    if tf == '1d':
        bars = load_csv('btcusdt_1d.csv')
        return Engine(bars, fine, 24, start)
    return Engine(resample(h1, 4), fine, 4, start)
