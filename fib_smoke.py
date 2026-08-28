# -*- coding: utf-8 -*-
import sys, time
import fib_mtf as F
sys.stdout.reconfigure(encoding='utf-8')
t0 = time.time()
data = F.load_data('2019-03-01')
print('load %.1fs | daily %d (%s~%s) | 4h %d (%s~%s) | fine %d' % (time.time()-t0, len(data.D), F.ts(data.d_ot[0],24), F.ts(data.d_ot[-1],24), data.n4, F.ts(data.h_ot[0]), F.ts(data.h_ot[data.LAST]), len(data.f_ot)))
P = dict(DCONF=0.382, DMIN=0.08, R4=0.382, R_RATIO=0.2, ATR_MULT=1.5, TOL=0.003, BUF=0.003, EXIT='spec', RATCHET=0.0, MFILT='off', STRUCT='none', SIDES='both')
t0 = time.time()
trades, events, sides = F.run(data, P)
print('run %.2fs | trades %d | events %d' % (time.time()-t0, len(trades), len(events)))
from collections import Counter
print(Counter(e[2] for e in events))
print(Counter((t['side'].s, t['result']) for t in trades))
for t in trades[:12] + trades[-6:]:
    sg = t['side'].s
    print('%s %-5s in %s @%.0f stop %.0f | out %s | r %+.2f%% mae %+.1f%% hold %.1fd | fills %s' % (
        'L' if sg>0 else 'S', t['result'], F.ts(data.h_ot[t['t0']]), sg*t['entry'], sg*t['stop0'], F.ts(data.h_ot[t['t1']]), t['r_net']*100, t['mae']*100, t['hold_h']/24,
        ' '.join('%s@%.0f' % (k, sg*px) for _, px, fr, k in t['fills'])))
yrs = (data.h_ot[data.LAST]-data.h_ot[data.start4])/D_MS/365 if False else None
ev = F.evaluate(trades, 0.3, 10, years=7.5)
print({k: (round(v,2) if isinstance(v,float) else v) for k,v in ev.items()})
