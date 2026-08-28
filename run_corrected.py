# -*- coding: utf-8 -*-
"""교정 엔진으로 Corrected V2/V3 계산 + Legacy 대비 + 버그별 영향 분해 (작업지시서 §22~§23).
전략 파라미터는 baseline_legacy 의 freeze 값 그대로 (변경 금지).
출력: corrected_result.txt, corrected_summary.json, corrected_<V>_trades.csv, corrected_<V>_events.csv
"""
import sys, os, json, csv, time, hashlib
from collections import Counter
import fib_mtf as F
import fib_engine_c as E

sys.stdout.reconfigure(encoding='utf-8')
OUT = 'corrected'
os.makedirs(OUT, exist_ok=True)
POS, LEV, SEED = 0.30, 10, 10000.0
FREEZE = json.load(open('baseline_legacy/legacy_baseline_freeze.json', encoding='utf-8'))
V2 = FREEZE['versions']['V2']['config']
V3 = FREEZE['versions']['V3']['config']
lines = []


def out(s=''):
    print(s)
    lines.append(s)


def load_v2():
    return E.load_data('2019-03-01')


def load_v3():
    fund = F.load_funding('btcusdt_funding.csv')
    return E.Data(F.load_csv('btcusdt_1d_2017.csv'), F.load_csv('btcusdt_fut_4h.csv'), F.load_csv('btcusdt_fut_5m.csv'), '2019-12-15', funding=fund)


def yrs_of(d):
    return (d.h_ot[d.LAST] - d.h_ot[d.start4]) / F.D_MS / 365.25


def pm_sum(trades):
    return sum(F.pm_of(t, LEV) for t in trades if t['result'] != 'open')


def dump_trades(path, data, trades):
    cols = ['signal_id', 'symbol', 'side', 'D_arm_time', 'R_confirm_time', 'order_create_time', 'expected_entry', 'actual_entry',
            'actual_entry_time', 'ENTRY_R_LOW', 'ENTRY_R_HIGH', 'ENTRY_R_SIZE', 'structural_stop', 'stop_time', 'partial_exit_times',
            'final_exit_time', 'exit_reason', 'r_net', 'pm_margin_pct', 'fee', 'funding', 'funding_events', 'mae', 'mfe', 'hold_h', 'age_bars',
            'atr_idx', 'atr_end_time', 'decision_time', 'fills', 'event_sequence']
    sym = 'BTCUSDT'
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(cols)
        for t in trades:
            s = t['side'].s
            tf = lambda x: F.ts(x) if x else ''
            w.writerow([t['signal_id'], sym, 'LONG' if s > 0 else 'SHORT', tf(t['D_arm_time']), tf(t['r_confirm_time']), tf(t['order_create_time']),
                        '%.2f' % (s * t['expected']), '%.2f' % (s * t['entry']), tf(t['entry_time']),
                        '%.2f' % (s * t['entry_R']['ENTRY_R_LOW']), '%.2f' % (s * t['entry_R']['ENTRY_R_HIGH']), '%.2f' % t['entry_R']['ENTRY_R_SIZE'],
                        '%.2f' % (s * t['structural_stop']), tf(t['stop_time']), ';'.join(F.ts(x) for x in t['partial_exit_times']),
                        tf(t['final_exit_time']), t['exit_reason'], '%.6f' % t['r_net'], '%.3f' % F.pm_of(t, LEV), '%.6f' % t['fee'],
                        '%.6f' % t['funding'], ';'.join('%s:%+.6f' % (F.ts(ft), a) for ft, a in t['funding_events']),
                        '%.5f' % t['mae'], '%.5f' % t['mfe'], '%.2f' % t['hold_h'], t['age'], t['atr_idx'], tf(t['atr_end_time']), tf(t['decision_time']),
                        ';'.join('%s@%s:%.2f:%.3f' % (k, F.ts(tm), s * px, fr) for (m, tm, px, fr, k) in t['fill_detail']),
                        ';'.join('%s|%s|%.2f|%.3f' % (F.ts(tm), k, s * px, fr) for (tm, k, px, fr) in t['seq'])])


def dump_events(path, data, events):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['time', 'bar_t', 'side', 'event', 'detail'])
        for (t, s, kind, d, tm, det) in events:
            if kind in ('R_CONFIRM',):          # 1만 건 이상이라 요약 CSV 에서는 제외 (events 원본은 JSON 으로 별도 저장 안 함)
                continue
            w.writerow([F.ts(tm), t, 'L' if s > 0 else ('S' if s < 0 else '-'), kind,
                        json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in det.items()}, ensure_ascii=False)])


HDR = '%-44s | %4s %5s %5s %6s %7s %5s %5s %5s %3s | %5s %5s | %4s %4s %4s | %s'
ROW = '%-44s | %4d %5.1f %5.2f %+6.1f %+7.0f %5.0f %5.0f %5.0f %3d | %5.2f %5.2f | %4d %4d %4d | %s'


def hdr():
    out(HDR % ('구성', '거래', '승률', 'PF', '기대값', '수익률', 'MDD', 'MTMc', 'MTMl', '연패', 'L PF', 'S PF', 'STOP', 'TP', 'D/V', '비고'))
    out('-' * 150)


def row(label, e, note=''):
    out(ROW % (label, e['n'], e['wr'], e['pf'], e['exp'], e['ret'], e['mdd'], e.get('mtm_mdd_close', float('nan')), e.get('mtm_mdd_low', float('nan')),
               e['worst'], e['long_pf'], e['short_pf'], e['stop_n'], e['tp_n'], e['dv_n'], note))


# ---- 0) synthetic tests + 회귀 assert 를 먼저 실행 (실패하면 보고서 생성 중단)
import subprocess
_st = subprocess.run([sys.executable, 'synthetic_tests.py'], capture_output=True, text=True, encoding='utf-8', errors='replace')
_st_line = next((l for l in _st.stdout.splitlines() if l.startswith('Synthetic tests:')), 'Synthetic tests: (no summary line)')
print('[0] ' + _st_line)
assert _st.returncode == 0, 'synthetic tests failed:\n' + _st.stdout[-3000:] + _st.stderr[-2000:]

summary = {'run_timestamp_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'engine': 'fib_engine_c.py', 'synthetic_tests': _st_line,
           'engine_hash_sha256': hashlib.sha256(open('fib_engine_c.py', 'rb').read()).hexdigest(),
           'legacy_hash_sha256': FREEZE['code_hash_sha256'], 'eval': dict(pos=POS, lev=LEV, seed=SEED), 'versions': {}}

out('=' * 150)
out('Corrected V2/V3 — 교정 엔진 fib_engine_c.py (hash %s) vs Legacy fib_mtf.py (hash %s)' % (summary['engine_hash_sha256'][:12], FREEZE['code_hash_sha256'][:12]))
out('평가: 30%% 투입 %dx, 시드 $%.0f, 비용 maker %.2f%%/taker %.2f%%/slip %.2f%%. 전략 파라미터 = freeze 값 (변경 없음)' % (LEV, SEED, F.FEE_MAKER * 100, F.FEE_TAKER * 100, F.SLIP * 100))
out('MTMc = 5분 종가 mark-to-market MDD, MTMl = 5분봉 내 불리한 극값 기준 MDD, MDD = 레거시(청산시점) MDD')
out('=' * 150)

for V, loader, P in (('V2', load_v2, V2), ('V3', load_v3, V3)):
    t0 = time.time()
    D = loader()
    yrs = yrs_of(D)
    out('\n' + '#' * 150)
    out('%s  %s   4H %s ~ %s (%d봉, %.2f년)  5분봉 %d  펀딩 %s  로드 %.1fs' % (
        V, json.dumps(P, ensure_ascii=False), F.ts(D.h_ot[D.start4]), F.ts(D.h_ot[D.LAST]), D.LAST - D.start4 + 1, yrs, len(D.f_ot),
        '실제 이력' if D.fund_ts else '고정 %.2f%%/8h' % (F.FUNDING * 100), time.time() - t0))
    out('#' * 150)
    # ---- 1) legacy vs 새 엔진(legacy 플래그 전부) 동등성
    trL, evL, _ = F.run(D, P)
    eL = F.evaluate(trL, POS, LEV, SEED, yrs)
    trA, evA, _, dgA = E.run(D, P, legacy=E.LEGACY_ALL)
    eA = F.evaluate(trA, POS, LEV, SEED, yrs)
    dd = E.diff_trades(trL, trA)
    equiv = (len(dd['removed']) == 0 and len(dd['added']) == 0 and len(dd['changed']) == 0 and abs(eL['ret'] - eA['ret']) < 1e-6)
    exp = FREEZE['versions'][V]['expected']
    out('\n[1] Legacy freeze 재현: n=%d PF=%.2f ret=%+.0f%% (기대 %d / %.2f / %+d) -> %s' % (
        eL['n'], eL['pf'], eL['ret'], exp['n'], exp['pf'], exp['ret'], 'OK' if (eL['n'] == exp['n'] and round(eL['pf'], 2) == exp['pf'] and round(eL['ret']) == exp['ret']) else 'MISMATCH'))
    out('    새 엔진 legacy 플래그 전부 ON: n=%d PF=%.4f ret=%+.2f%%  거래별 비교 removed %d / added %d / changed %d -> %s' % (
        eA['n'], eA['pf'], eA['ret'], len(dd['removed']), len(dd['added']), len(dd['changed']), 'EQUIVALENT' if equiv else 'DIFF'))
    assert equiv, 'legacy equivalence failed for %s' % V

    # ---- 2) Corrected
    trC, evC, sidesC, dgC = E.run(D, P)
    eC = E.summarize(trC, POS, LEV, SEED, yrs, D)
    inv = E.check_invariants(trC, evC, D)
    E.assert_invariants(trC, evC, D)
    mtm = E.evaluate_mtm(trC, D, POS, LEV, SEED)
    eLs = E.summarize(trA, POS, LEV, SEED, yrs, D)     # legacy 재현본으로 stop/tp/dv 집계 (fill_detail 있음)
    mtmL = E.evaluate_mtm(trA, D, POS, LEV, SEED)
    eLs['mtm_mdd_close'], eLs['mtm_mdd_low'] = mtmL['mdd_close'], mtmL['mdd_low']
    trNV, evNV, _, dgNV = E.run(D, P, legacy=frozenset(['NO_V_POS']))
    eNV = E.summarize(trNV, POS, LEV, SEED, yrs, D)
    out('\n[2] Legacy vs Corrected (작업지시서 §22)')
    hdr()
    row('Legacy  ' + V, eLs, 'freeze')
    row('Corrected ' + V, eC, 'look-ahead 0, 5M chronology')
    row('Corrected ' + V + ' (V_POS 제외)', eNV, '보유 중 자체 P0 훼손 청산 규칙 없이 = 레거시 규칙 + chronology 만')
    out()
    out('    | 항목 | Legacy | Corrected | Corrected (V_POS 제외) |')
    out('    |---|---:|---:|---:|')
    for k, lab, fmt in (('n', 'Trades', '%d'), ('wr', 'Win Rate', '%.1f%%'), ('pf', 'PF', '%.2f'), ('exp', 'Expectancy (마진%/거래)', '%+.1f%%'),
                        ('ret', 'Net Return', '%+.0f%%'), ('mtm_mdd_close', 'MTM MDD (5m close)', '%.1f%%'), ('mtm_mdd_low', 'MTM MDD (5m low)', '%.1f%%'),
                        ('mdd', 'Legacy MDD (청산시점)', '%.1f%%'), ('worst', 'Max Losing Streak', '%d'), ('long_pf', 'Long PF', '%.2f'), ('short_pf', 'Short PF', '%.2f'),
                        ('long_n', 'Long N', '%d'), ('short_n', 'Short N', '%d'),
                        ('stop_n', 'Stop Trades', '%d'), ('tp_n', 'TP Trades', '%d'), ('dv_n', 'D/V Exit', '%d'), ('fund_pct', '펀딩/거래', '%+.3f%%'),
                        ('mae_avg', '평균 MAE', '%.2f%%'), ('mfe_avg', '평균 MFE', '%.2f%%'), ('sharpe', 'Sharpe(연)', '%.2f')):
        out('    | %s | %s | %s | %s |' % (lab, fmt % eLs[k], fmt % eC[k], fmt % eNV[k]))
    out('    MTM 최악 시점(close): %s  equity %.0f (peak %.0f) 거래 %s' % ((F.ts(mtm['worst_close'][0]), mtm['worst_close'][1], mtm['worst_close'][2], mtm['worst_close'][3]) if mtm['worst_close'] else ('-', 0, 0, '-')))
    out('    회귀 불변식: lookahead_count=%d invalid_event_order_count=%d pre_entry_price_used_for_mae=%d market_close_same_bar_sltp=%d  -> PASS' % (
        inv['lookahead_count'], inv['invalid_event_order_count'], inv['pre_entry_price_used_for_mae'], inv['market_close_same_bar_sltp']))
    out('    진단: %s' % dict(dgC))
    cnt = Counter(x[2] for x in evC)
    out('    이벤트: ' + ', '.join('%s %d' % (k, cnt[k]) for k in ('D_ARM', 'D_DISARM', 'R_CONFIRM', 'R_REPLACED', 'ORDER_CREATE', 'ORDER_CANCEL', 'SIGNAL', 'R_INVALID', 'V', 'V_POS', 'SKIP_V', 'FILL', 'EXIT')))
    yl = []
    for y in range(2019, 2027):
        pmsL = [F.pm_of(t, LEV) for t in trA if F.ts(D.h_ot[t['t0']])[:4] == str(y) and t['result'] != 'open']
        pmsC = [F.pm_of(t, LEV) for t in trC if F.ts(D.h_ot[t['t0']])[:4] == str(y) and t['result'] != 'open']
        yl.append('%d: L %d건 PF %.2f / C %d건 PF %.2f' % (y, len(pmsL), F._pf(pmsL) if pmsL else 0, len(pmsC), F._pf(pmsC) if pmsC else 0))
    out('    연도별: ' + ' | '.join(yl))

    # ---- 3) 버그별 영향 분해 (§23): 순차 제거 + 단독 제거
    out('\n[3] 버그별 영향 분해 (§23)  — key=(side, R확정봉) 로 거래 매칭. ΔPnL = 마진 기준 손익%% 합계 변화 (30%%x%dx 기준 %% 단위)' % LEV)
    out('    (a) 순차 적용: 레거시에서 작업지시서 §18 순서대로 하나씩 교정하며 직전 단계와 비교')
    out('    %-48s | %4s %5s %7s %5s | %5s %5s %5s | %8s | %s' % ('단계', '거래', 'PF', '수익률', 'MTMc', '추가', '삭제', '변경', 'ΔΣpm', '비고'))
    out('    ' + '-' * 140)
    flags = set(E.LEGACY_ALL)
    prev_tr, prev_e = trA, eLs
    seq_rows = []
    out('    %-48s | %4d %5.2f %+7.0f %5.0f | %5s %5s %5s | %8s |' % ('Legacy (플래그 전부)', prev_e['n'], prev_e['pf'], prev_e['ret'], prev_e['mtm_mdd_close'], '', '', '', ''))
    for flag, label in E.FIX_ORDER:
        flags.discard(flag)
        tr, ev_, _, dg = E.run(D, P, legacy=frozenset(flags))
        e = E.summarize(tr, POS, LEV, SEED, yrs, D)
        d_ = E.diff_trades(prev_tr, tr)
        dpm = pm_sum(tr) - pm_sum(prev_tr)
        note = ''
        if flag == 'NOCURSOR':
            note = '과거 5분봉 재진입 가능 건수(레거시) = %d' % dg.get('nocursor_past_reentry_possible', 0)
        if flag == 'SAMEBAR_C':
            note = 'FILL=A 라 해당 없음 (C 모델에서만 작동)'
        if flag == 'ENTRYBAR_TP':
            note = '진입봉 TP 보류 %d건' % dg.get('entrybar_tp_deferred', 0)
        if flag == 'MAE_4H':
            note = 'pm 변화 = 청산가(-100%%) 판정 변화만; 평균 MAE %.2f%% -> %.2f%%' % (prev_e['mae_avg'], e['mae_avg'])
        if flag == 'FUND_4H':
            note = '펀딩/거래 %+.3f%% -> %+.3f%%' % (prev_e['fund_pct'], e['fund_pct'])
        out('    %-48s | %4d %5.2f %+7.0f %5.0f | %+5d %+5d %5d | %+8.1f | %s' % (
            label, e['n'], e['pf'], e['ret'], e['mtm_mdd_close'], len(d_['added']), -len(d_['removed']), len(d_['changed']), dpm, note))
        seq_rows.append({'step': label, 'flag_removed': flag, 'n': e['n'], 'pf': round(e['pf'], 4), 'ret': round(e['ret'], 2), 'mtm_mdd_close': round(e['mtm_mdd_close'], 2),
                         'added': len(d_['added']), 'removed': len(d_['removed']), 'changed': len(d_['changed']), 'delta_sum_pm': round(dpm, 3),
                         'added_pm': round(sum(F.pm_of(t, LEV) for t in d_['added'] if t['result'] != 'open'), 3),
                         'removed_pm': round(sum(F.pm_of(t, LEV) for t in d_['removed'] if t['result'] != 'open'), 3),
                         'changed_pm': round(sum(F.pm_of(y, LEV) - F.pm_of(x, LEV) for x, y in d_['changed']), 3), 'diag': dict(dg)})
        prev_tr, prev_e = tr, e
    assert prev_e['n'] == eC['n'] and abs(prev_e['ret'] - eC['ret']) < 1e-6, 'sequential ablation must end at corrected'
    out('    %-48s | %4d %5.2f %+7.0f %5.0f |' % ('= Corrected', eC['n'], eC['pf'], eC['ret'], eC['mtm_mdd_close']))
    out()
    out('    (b) 단독 적용: 레거시에서 해당 항목 하나만 교정 (상호작용 없이 본 크기)')
    out('    %-48s | %4s %5s %7s %5s | %5s %5s %5s | %8s | %s' % ('항목', '거래', 'PF', '수익률', 'MTMc', '추가', '삭제', '변경', 'ΔΣpm', '추가거래 Σpm / 삭제거래 Σpm / 변경 Δpm'))
    out('    ' + '-' * 140)
    solo_rows = []
    for flag, label in E.FIX_ORDER:
        fl = set(E.LEGACY_ALL)
        fl.discard(flag)
        tr, ev_, _, dg = E.run(D, P, legacy=frozenset(fl))
        e = E.summarize(tr, POS, LEV, SEED, yrs, D)
        d_ = E.diff_trades(trA, tr)
        a_pm = sum(F.pm_of(t, LEV) for t in d_['added'] if t['result'] != 'open')
        r_pm = sum(F.pm_of(t, LEV) for t in d_['removed'] if t['result'] != 'open')
        c_pm = sum(F.pm_of(y, LEV) - F.pm_of(x, LEV) for x, y in d_['changed'])
        out('    %-48s | %4d %5.2f %+7.0f %5.0f | %+5d %+5d %5d | %+8.1f | %+.1f / %+.1f / %+.1f' % (
            label, e['n'], e['pf'], e['ret'], e['mtm_mdd_close'], len(d_['added']), -len(d_['removed']), len(d_['changed']), pm_sum(tr) - pm_sum(trA), a_pm, r_pm, c_pm))
        solo_rows.append({'item': label, 'flag_removed': flag, 'n': e['n'], 'pf': round(e['pf'], 4), 'ret': round(e['ret'], 2), 'mtm_mdd_close': round(e['mtm_mdd_close'], 2),
                          'added': len(d_['added']), 'removed': len(d_['removed']), 'changed': len(d_['changed']),
                          'added_pm': round(a_pm, 3), 'removed_pm': round(r_pm, 3), 'changed_pm': round(c_pm, 3), 'diag': dict(dg)})
        if flag == 'R_4H':
            addR = [t for t in d_['added'] if t['result'] != 'open']
            out('        R chronology 로 추가된 거래 %d건: 손절 %d / TP %d / 기타 %d, 승률 %.0f%%, Σpm %+.1f, 그중 진입 5분봉=이탈 5분봉 %d건' % (
                len(addR), sum(1 for t in addR if t['result'] == 'stop'), sum(1 for t in addR if t['result'] in ('tp', 'tpm')),
                sum(1 for t in addR if t['result'] not in ('stop', 'tp', 'tpm')), sum(1 for t in addR if F.pm_of(t, LEV) > 0) / max(1, len(addR)) * 100, a_pm,
                sum(1 for t in addR if t['fill_detail'] and t['fill_detail'][0][0] == t['fill_m'] and t['fill_detail'][0][4] == 'stop')))
            remR = d_['removed']
            out('        삭제된 거래 %d건 (추가 거래가 포지션을 점유해 밀려난 레거시 거래): Σpm %+.1f' % (len(remR), r_pm))
        if flag == 'ATR_CUR':
            out('        ATR confirmed-only 로 판정이 바뀐 거래: 추가 %d / 삭제 %d' % (len(d_['added']), len(d_['removed'])))
    # MTM MDD 변화 (평가 단계)
    out('\n    MTM MDD (7): Legacy 청산시점 MDD %.1f%% -> Legacy 거래를 5분 MTM 으로 %.1f%% (low 기준 %.1f%%) | Corrected 청산시점 %.1f%% -> MTM %.1f%% (low %.1f%%)' % (
        eLs['mdd'], eLs['mtm_mdd_close'], eLs['mtm_mdd_low'], eC['mdd'], eC['mtm_mdd_close'], eC['mtm_mdd_low']))
    # ---- 저장
    dump_trades(os.path.join(OUT, 'corrected_%s_trades.csv' % V), D, trC)
    dump_events(os.path.join(OUT, 'corrected_%s_events.csv' % V), D, evC)
    summary['versions'][V] = {
        'config': P, 'data': FREEZE['versions'][V]['data'],
        'legacy': {k: (round(v, 4) if isinstance(v, float) else v) for k, v in eLs.items()},
        'corrected': {k: (round(v, 4) if isinstance(v, float) else v) for k, v in eC.items()},
        'corrected_mtm': {'mdd_close': round(mtm['mdd_close'], 3), 'mdd_low': round(mtm['mdd_low'], 3)},
        'corrected_no_vpos': {k: (round(v, 4) if isinstance(v, float) else v) for k, v in eNV.items()},
        'invariants': dict(inv), 'diag': dict(dgC), 'events': dict(cnt),
        'impact_sequential': seq_rows, 'impact_solo': solo_rows,
        'legacy_equivalence': {'removed': len(dd['removed']), 'added': len(dd['added']), 'changed': len(dd['changed'])},
    }

out('\n' + '=' * 150)
out('해석 원칙(§26): 목표는 PF 복원이 아니라 정확한 chronology + look-ahead 0 + 재현 가능한 baseline. PF≈1.0 이면 현재 구조는 실전 edge 없음으로 판단.')
with open(os.path.join(OUT, 'corrected_result.txt'), 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
with open(os.path.join(OUT, 'corrected_summary.json'), 'w', encoding='utf-8') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
print('\nsaved ->', OUT)
