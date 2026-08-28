# -*- coding: utf-8 -*-
# one-off patch: v3 engine features (fill models A/B/C, historical funding, target policy, risk sizing)
p = 'fib_mtf.py'
s = open(p, encoding='utf-8').read()
R = []
R.append(("    def __init__(self, d_rows, h4_rows, fine_rows, start='2019-03-01'):\n        self.D = d_rows\n",
          "    def __init__(self, d_rows, h4_rows, fine_rows, start='2019-03-01', funding=None):\n        self.D = d_rows\n        # funding: list of (time_ms, rate) for historical funding (v3); None -> fixed FUNDING\n        self.fund_ts = [f[0] for f in funding] if funding else []\n        self.fund_rate = [f[1] for f in funding] if funding else []\n"))
R.append(("        self.f_lo = [r[3] for r in fine_rows]\n        # 4H -> 일봉 인덱스\n",
          "        self.f_lo = [r[3] for r in fine_rows]\n        self.f_cl = [r[4] for r in fine_rows]\n        # 4H -> 일봉 인덱스\n"))
R.append(("        self.f_lo = data.f_lo if sg > 0 else [-x for x in data.f_hi]\n        self.dzz = new_zz(self.d_hi[0], self.d_lo[0])\n",
          "        self.f_lo = data.f_lo if sg > 0 else [-x for x in data.f_hi]\n        self.f_cl = [sg * x for x in data.f_cl]\n        self.sig_key = None\n        self.dzz = new_zz(self.d_hi[0], self.d_lo[0])\n"))
R.append(("""        r = 0.0
        fee = FEE_MAKER
        for (_, px, fr, kind) in pos['fills']:
            r += fr * (px - e) / abs(e)
            fee += fr * (FEE_MAKER if kind == 'tp' else FEE_TAKER)
            if kind == 'stop':
                r -= fr * SLIP
        hold_h = (data.h_ot[t] - data.h_ot[pos['t0']]) / H_MS + 4
        fund = FUNDING * hold_h / 8
        pos['r_net'] = r - fee - fund
""", """        r = 0.0
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
"""))
R.append(("""            if sd.R and not sd.R_broken and sd.h_lo[t] < sd.R[0] - EPS:
                sd.R_broken = True
        # ---- 진입 (R 은 t-1 이전 확정분만)
        if pos is None:
            for sd in sides:
                if not sd.armed or not sd.r_valid(t) or sd.R[3] >= t:
                    continue
                if not sd.m_ok(d):
                    continue
                lv = sd.entry_level()
                if sd.h_lo[t] > lv + EPS:
                    continue
                stop = sd.stop_level()
                if lv <= stop:
                    continue
""", """            if sd.R and not sd.R_broken and sd.h_lo[t] < sd.R[0] - EPS:
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
"""))
R.append(("""                a, b = data.fine_range(t)
                fill_m = None
                if a < b:
                    fill_m = next((m for m in range(a, b) if sd.f_lo[m] <= lv + EPS), None)
                    if fill_m is None:
                        continue
                ex = P['EXIT']
""", """                a, b = data.fine_range(t)
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
"""))
R.append(("""                pos = {'side': sd, 't0': t, 'entry': lv, 'stop': stop, 'stop0': stop, 'frac': 1.0,
                       'tgts': tg, 'd_exit': d_exit, 'be': be, 'fills': [], 'peak': lv, 'mae': 0.0,
                       'P0': sd.P0, 'H1': sd.H1, 'dsize': sd.dsize, 'R': sd.R, 'day': d}
""", """                pos = {'side': sd, 't0': t, 'entry': lv, 'stop': stop, 'stop0': stop, 'frac': 1.0,
                       'tgts': tg, 'd_exit': d_exit, 'be': be, 'fills': [], 'peak': lv, 'mae': 0.0,
                       'P0': sd.P0, 'H1': sd.H1, 'dsize': sd.dsize, 'R': sd.R, 'day': d,
                       'expected': expected, 'taker': taker, 'age': t - sd.R[3], 'key': (sd.s, sd.R[3])}
"""))
R.append(("""                    while pos and pos['tgts'] and sd.f_hi[m] >= pos['tgts'][0][0] - EPS:
                        px, fr = pos['tgts'].pop(0)
                        close_pos(t, px, min(fr, pos['frac']), 'tp')
                        if pos and pos['be']:
                            pos['stop'] = max(pos['stop'], pos['entry'] + 0.002 * abs(pos['entry']))
            else:   # 5분봉 없음: 손절 우선
""", """                    while pos and pos['tgts'] and sd.f_hi[m] >= pos['tgts'][0][0] - EPS:
                        px, fr = pos['tgts'].pop(0)
                        close_pos(t, px, min(fr, pos['frac']), 'tp')
                        if pos and pos['be']:
                            pos['stop'] = max(pos['stop'], pos['entry'] + 0.002 * abs(pos['entry']))
                        if pos:
                            apply_policy(t, m)
            else:   # 5분봉 없음: 손절 우선
"""))
R.append(("""                        while pos and pos['tgts'] and sd.f_hi[m] >= pos['tgts'][0][0] - EPS:
                            px, fr = pos['tgts'].pop(0)
                            close_pos(t, px, min(fr, pos['frac']), 'tp')
                            if pos and pos['be']:
                                pos['stop'] = max(pos['stop'], pos['entry'] + 0.002 * abs(pos['entry']))
                elif sd.h_lo[t] <= stop + EPS:
""", """                        while pos and pos['tgts'] and sd.f_hi[m] >= pos['tgts'][0][0] - EPS:
                            px, fr = pos['tgts'].pop(0)
                            close_pos(t, px, min(fr, pos['frac']), 'tp')
                            if pos and pos['be']:
                                pos['stop'] = max(pos['stop'], pos['entry'] + 0.002 * abs(pos['entry']))
                            if pos:
                                apply_policy(t, m)
                elif sd.h_lo[t] <= stop + EPS:
"""))
R.append(("""    def finish(t):
        nonlocal pos
""", """    def apply_policy(t, m):
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
"""))
for a, b in R:
    assert a in s, a[:80]
    s = s.replace(a, b)
s += '''

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
'''
open(p, 'w', encoding='utf-8').write(s)
print('engine v3 patch ok')
