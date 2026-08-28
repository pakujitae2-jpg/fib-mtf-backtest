# -*- coding: utf-8 -*-
import sys
from collections import Counter
import fib_mtf as F

sys.stdout.reconfigure(encoding='utf-8')
d = F.load_data('2019-03-01')
V2 = dict(DCONF=0.382, DMIN=0.08, R4=0.236, R_ENTRY_FIB=0.236, R_RATIO=0.1, ATR_MULT=1.0, TOL=0.003, BUF=0.003,
          EXIT='halfR2spec', RATCHET=0.0, MFILT='off', STRUCT='HH_HL', SIDES='both')
for fm in ('A', 'B', 'C'):
    t, ev, _ = F.run(d, dict(V2, FILL=fm, PEN=0.001))
    e = F.evaluate(t, 0.3, 10, 10000.0, 7.5)
    c = Counter(x[2] for x in ev)
    print('FILL %s n=%d pf=%.2f ret=%.0f%% | SIGNAL %d R_INVALID %d | age avg %.1f bars' % (
        fm, e['n'], e['pf'], e['ret'], c['SIGNAL'], c['R_INVALID'], sum(x['age'] for x in t) / len(t)))
for pol in ('retro', 'skip', 'market'):
    t, ev, _ = F.run(d, dict(V2, TGT_POLICY=pol))
    e = F.evaluate(t, 0.3, 10, 10000.0, 7.5)
    print('policy %-6s n=%d pf=%.2f ret=%.0f%%' % (pol, e['n'], e['pf'], e['ret']))
r = F.evaluate_risk(t, 0.01)
print('risk 1%%: ret %.0f%% mdd %.0f%% avg_lev %.2f' % (r['ret'], r['mdd'], r['avg_lev']))
