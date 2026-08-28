# -*- coding: utf-8 -*-
"""Legacy V2/V3 baseline freeze (작업지시서 §16).
교정 전 엔진(fib_mtf.py)으로 V2/V3 를 실행해 결과·거래목록과
code/config/data hash, command line, python version, dependencies, timestamp 를 저장한다.
"""
import sys, os, json, hashlib, platform, subprocess, time, csv
from collections import Counter
import fib_mtf as F

sys.stdout.reconfigure(encoding='utf-8')
OUT_DIR = 'baseline_legacy'
os.makedirs(OUT_DIR, exist_ok=True)

V2 = dict(DCONF=0.382, DMIN=0.08, R4=0.236, R_ENTRY_FIB=0.236, R_RATIO=0.1, ATR_MULT=1.0, TOL=0.003, BUF=0.003,
          EXIT='spec', RATCHET=0.0, MFILT='off', STRUCT='HH_HL', SIDES='both')
V3 = dict(DCONF=0.382, DMIN=0.08, R4=0.236, R_ENTRY_FIB=0.236, R_RATIO=0.1, ATR_MULT=1.0, TOL=0.003, BUF=0.003,
          EXIT='halfR2spec', RATCHET=0.0, MFILT='off', STRUCT='HH_HL', SIDES='both', FILL='A', PEN=0.0, TGT_POLICY='retro')
EVAL = dict(pos=0.30, lev=10, seed=10000.0)
DATA = {
    'V2': dict(daily='btcusdt_1d_2017.csv', h4='btcusdt_4h_2019.csv', fine=['btcusdt_5m_2019_2022.csv', 'btcusdt_5m.csv'],
               funding=None, start='2019-03-01', loader="F.load_data('2019-03-01')"),
    'V3': dict(daily='btcusdt_1d_2017.csv', h4='btcusdt_fut_4h.csv', fine=['btcusdt_fut_5m.csv'],
               funding='btcusdt_funding.csv', start='2019-12-15',
               loader="F.Data(d_spot, h4_fut, f_fut, '2019-12-15', funding=fund)  # 3차 보고서 구성 C"),
}
EXPECT = {'V2': dict(n=122, pf=1.99, ret=1316), 'V3': dict(n=115, pf=1.70, ret=465)}


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def build(v):
    c = DATA[v]
    d = F.load_csv(c['daily'])
    h4 = F.load_csv(c['h4'])
    fine = []
    for p in c['fine']:
        fine += F.load_csv(p)
    fine = [r for r in fine if r[0] >= h4[0][0]]
    fund = F.load_funding(c['funding']) if c['funding'] else None
    return F.Data(d, h4, fine, c['start'], funding=fund)


def dump_trades(path, data, trades):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['i', 'side', 'entry_bar', 'exit_bar', 'entry', 'stop0', 'expected', 'result', 'r_net', 'funding', 'mae', 'hold_h', 'age', 'fills'])
        for i, t in enumerate(trades):
            w.writerow([i, 'L' if t['side'].s > 0 else 'S', F.ts(data.h_ot[t['t0']]), F.ts(data.h_ot[t['t1']]),
                        '%.4f' % (t['side'].s * t['entry']), '%.4f' % (t['side'].s * t['stop0']), '%.4f' % (t['side'].s * t['expected']),
                        t['result'], '%.6f' % t['r_net'], '%.6f' % t['funding'], '%.6f' % t['mae'], t['hold_h'], t['age'],
                        ';'.join('%s@%s:%.4f:%.3f' % (k, F.ts(data.h_ot[j]), t['side'].s * px, fr) for (j, px, fr, k) in t['fills'])])


meta = {
    'run_timestamp_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    'command_line': ' '.join([sys.executable] + sys.argv),
    'cwd': os.getcwd(),
    'python_version': sys.version,
    'platform': platform.platform(),
    'engine_file': 'fib_mtf.py',
    'code_hash_sha256': sha256('fib_mtf.py'),
    'engine_constants': dict(FEE_MAKER=F.FEE_MAKER, FEE_TAKER=F.FEE_TAKER, SLIP=F.SLIP, FUNDING=F.FUNDING, MM=F.MM, FIB_EXT=F.FIB_EXT),
    'eval': EVAL,
    'dependencies': {'stdlib_only': True, 'imports': ['csv', 'time', 'bisect', 'collections']},
    'pip_freeze': subprocess.run([sys.executable, '-m', 'pip', 'freeze'], capture_output=True, text=True).stdout.splitlines(),
    'versions': {},
}
for v, P in (('V2', V2), ('V3', V3)):
    c = DATA[v]
    files = [c['daily'], c['h4']] + c['fine'] + ([c['funding']] if c['funding'] else [])
    data = build(v)
    yrs = (data.h_ot[data.LAST] - data.h_ot[data.start4]) / F.D_MS / 365.25
    trades, events, _ = F.run(data, P)
    e = F.evaluate(trades, EVAL['pos'], EVAL['lev'], EVAL['seed'], yrs)
    ok = e['n'] == EXPECT[v]['n'] and round(e['pf'], 2) == EXPECT[v]['pf'] and round(e['ret']) == EXPECT[v]['ret']
    res = {k: (round(x, 4) if isinstance(x, float) else x) for k, x in e.items()}
    cfg = dict(P)
    meta['versions'][v] = {
        'status': 'LEGACY_REPRODUCIBLE_FREEZE' if ok else 'MISMATCH',
        'config': cfg,
        'config_hash_sha256': hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest(),
        'data': {'files': {p: {'sha256': sha256(p), 'bytes': os.path.getsize(p)} for p in files}, 'start': c['start'],
                 'loader': c['loader'], 'first_4h': F.ts(data.h_ot[data.start4]), 'last_4h': F.ts(data.h_ot[data.LAST]),
                 'n_4h': data.LAST - data.start4 + 1, 'n_5m': len(data.f_ot), 'years': round(yrs, 3)},
        'expected': EXPECT[v], 'result': res,
        'results_by_kind': dict(Counter(t['result'] for t in trades)),
        'events': dict(Counter(x[2] for x in events)),
    }
    dump_trades(os.path.join(OUT_DIR, 'legacy_%s_trades.csv' % v), data, trades)
    print('%s legacy: n=%d pf=%.2f ret=%+.0f%% mdd=%.0f%%  -> %s' % (v, e['n'], e['pf'], e['ret'], e['mdd'], 'FREEZE OK' if ok else 'MISMATCH!'))
with open(os.path.join(OUT_DIR, 'legacy_baseline_freeze.json'), 'w', encoding='utf-8') as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)
import shutil
shutil.copy('fib_mtf.py', os.path.join(OUT_DIR, 'fib_mtf_legacy_frozen.py'))
print('saved ->', OUT_DIR, '| code hash', meta['code_hash_sha256'][:16])
