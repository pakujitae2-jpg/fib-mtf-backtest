# -*- coding: utf-8 -*-
# 상승 추세선 리테스트 매매 시뮬레이션 - 파라미터 스윕 (탐지/체결 로직은 trendline_core.py)
import csv, time
from trendline_core import *

# ---------------------------------------------------------------- 스윕
NS = [30, 60, 90]
KS = [2, 3]
ZONES = [0.01, 0.02, 0.03]
VMODES = ['low', 'close']
SMODES = ['trail', 'fixed']
LEVS = [10, 20]
SBUF = 0.01

print('=' * 110)
print('상승 추세선 리테스트 매매 시뮬레이션  |  Binance SPOT BTCUSDT 일봉  |  %s ~ %s' % (START, day[LAST]))
print('=' * 110)
print('시드 $%.0f, 투입 %.0f%%, 익절 +%.0f%%, 손절 = 추세선 아래 %.1f%%, 수수료 taker %.2f%%/maker %.2f%%, '
      '슬리피지 %.2f%%, 펀딩 %.2f%%/8h' % (SEED, POS * 100, TP * 100, SBUF * 100, FEE_TAKER * 100,
                                         FEE_MAKER * 100, SLIP * 100, FUNDING * 100))
print('강제청산가 = 진입가*(1 - 1/배율 + %.1f%%)  ->  10x: -%.1f%%  20x: -%.1f%%'
      % (MM * 100, (1 / 10 - MM) * 100, (1 / 20 - MM) * 100))

rows = []
t0 = time.time()
for N in NS:
    for k in KS:
        for vm in VMODES:
            for z in ZONES:
                sigs = gen_signals(N, k, z, vm)
                for sm in SMODES:
                    for lev in LEVS:
                        STAT['amb_day'] = STAT['amb_1h'] = 0
                        r = simulate(sigs, sm, SBUF, lev)
                        r.update({'N': N, 'k': k, 'valid': vm, 'zone': z, 'stop': sm, 'lev': lev,
                                  'amb_day': STAT['amb_day'], 'amb_1h': STAT['amb_1h']})
                        rows.append(r)
print('\n조합 %d개 계산 완료 (%.1fs)' % (len(rows), time.time() - t0))

COLS = ['N', 'k', 'valid', 'zone', 'stop', 'lev', 'sig', 'n', 'tp', 'sp', 'sl', 'liq', 'open',
        'wr', 'risk', 'pnl_m', 'hold', 'eq', 'ret', 'mdd', 'worst', 'amb_day', 'amb_1h']
with open('trendline_sweep.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    w.writerow(COLS)
    for r in rows:
        w.writerow([r[c] if not isinstance(r[c], float) else '%.4f' % r[c] for c in COLS])


def show(rs, title):
    print('\n' + '=' * 110)
    print(title)
    print('=' * 110)
    print('%3s %2s %-5s %4s %-5s %3s | %4s %4s %3s %3s %3s %3s %3s | %6s %6s %7s %5s | %10s %8s %6s %4s' % (
        'N', 'k', '유효', 'zone', '손절', 'lev', '신호', '거래', 'TP', '익손', '손절', '청산', '미결',
        '승률%', '손절폭', '마진손익', '보유', '최종자산$', '수익률%', 'MDD%', '연패'))
    print('-' * 110)
    for r in rs:
        print('%3d %2d %-5s %3.0f%% %-5s %3d | %4d %4d %3d %3d %3d %3d %3d | %6.1f %6.2f %7.1f %5.1f | %10.0f %8.1f %6.1f %4d' % (
            r['N'], r['k'], r['valid'], r['zone'] * 100, r['stop'], r['lev'], r['sig'], r['n'],
            r['tp'], r['sp'], r['sl'], r['liq'], r['open'], r['wr'], r['risk'], r['pnl_m'],
            r['hold'], r['eq'], r['ret'], r['mdd'], r['worst']))


show(sorted(rows, key=lambda r: -r['eq'])[:15], '최종자산 상위 15개 조합')
show(sorted(rows, key=lambda r: r['eq'])[:8], '최종자산 하위 8개 조합')
show([r for r in rows if r['lev'] == 10 and r['zone'] == 0.02 and r['k'] == 2],
     '기준 슬라이스: 10x, zone 2%, k=2  (N / 유효성 / 손절방식 비교)')
show([r for r in rows if r['N'] == 60 and r['k'] == 2 and r['valid'] == 'low' and r['stop'] == 'trail'],
     '기준 슬라이스: N=60, k=2, 저가유효, 트레일 손절  (zone / 배율 비교)')

# 승률·기대값 기준 안정성 (거래 20건 이상)
robust = [r for r in rows if r['n'] >= 20]
print('\n' + '=' * 110)
print('거래 20건 이상 조합 %d개 요약: 수익 조합 %d개 / 손실 조합 %d개 / 청산 발생 조합 %d개' % (
    len(robust), sum(1 for r in robust if r['ret'] > 0), sum(1 for r in robust if r['ret'] <= 0),
    sum(1 for r in robust if r['liq'] > 0)))
for lev in LEVS:
    rs = [r for r in robust if r['lev'] == lev]
    if rs:
        print('  %2dx : 중앙값 수익률 %+.1f%%  중앙값 MDD %.1f%%  평균 승률 %.1f%%' % (
            lev, sorted(r['ret'] for r in rs)[len(rs) // 2], sorted(r['mdd'] for r in rs)[len(rs) // 2],
            sum(r['wr'] for r in rs) / len(rs)))
for sm in SMODES:
    rs = [r for r in robust if r['stop'] == sm]
    print('  손절 %-5s: 중앙값 수익률 %+.1f%%  평균 승률 %.1f%%  평균 보유 %.1f일' % (
        sm, sorted(r['ret'] for r in rs)[len(rs) // 2], sum(r['wr'] for r in rs) / len(rs),
        sum(r['hold'] for r in rs) / len(rs)))
for vm in VMODES:
    rs = [r for r in robust if r['valid'] == vm]
    print('  유효 %-5s: 중앙값 수익률 %+.1f%%  평균 승률 %.1f%%  평균 신호수 %.0f' % (
        vm, sorted(r['ret'] for r in rs)[len(rs) // 2], sum(r['wr'] for r in rs) / len(rs),
        sum(r['sig'] for r in rs) / len(rs)))

# ---------------------------------------------------------------- 베스트 조합 상세
best = max(robust, key=lambda r: r['eq'])
print('\n' + '=' * 110)
print('베스트 조합 상세: N=%d k=%d valid=%s zone=%.0f%% stop=%s lev=%dx' % (
    best['N'], best['k'], best['valid'], best['zone'] * 100, best['stop'], best['lev']))
print('=' * 110)
print('%-11s %-11s %-4s %10s %10s %10s %8s %8s %5s  %s' % (
    '진입일', '청산일', '결과', '진입가', '초기손절', '청산가', '손절폭%', '마진손익%', '보유', '추세선(p1->p2, 일상승률)'))
print('-' * 110)
for i, j, res, entry, st, ex, pm, tl in best['trades']:
    print('%-11s %-11s %-4s %10.0f %10.0f %10.0f %8.2f %8.1f %5d  %s->%s %.2f%%/일' % (
        day[i], day[j], res, entry, st, ex, (entry - st) / entry * 100, pm, j - i,
        day[tl[0]], day[tl[1]], tl[2] / lo[tl[0]] * 100))
print('-' * 110)
print('결과 코드: tp=익절(+10%) / sp=추세선 트레일 손절이 진입가 위에서 체결(이익) / sl=손절 / liq=강제청산 / open=보유중')

print('\n연도별 (베스트 조합):')
for y in ('2023', '2024', '2025', '2026'):
    ts = [t for t in best['trades'] if day[t[0]][:4] == y and t[2] != 'open']
    if not ts:
        continue
    w = sum(1 for t in ts if t[2] in ('tp', 'sp'))
    print('  %s: 거래 %2d  승 %2d  패 %2d  승률 %5.1f%%  마진손익 합계 %+.0f%%' % (
        y, len(ts), w, len(ts) - w, w / len(ts) * 100, sum(t[6] for t in ts)))

with open('trendline_trades.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    w.writerow(['entry_day', 'exit_day', 'result', 'entry', 'init_stop', 'exit', 'risk_pct',
                'margin_pnl_pct', 'hold_days', 'p1_day', 'p2_day', 'slope_pct_per_day'])
    for i, j, res, entry, st, ex, pm, tl in best['trades']:
        w.writerow([day[i], day[j], res, '%.2f' % entry, '%.2f' % st, '%.2f' % ex,
                    '%.3f' % ((entry - st) / entry * 100), '%.2f' % pm, j - i,
                    day[tl[0]], day[tl[1]], '%.3f' % (tl[2] / lo[tl[0]] * 100)])

# ---------------------------------------------------------------- 손절 버퍼 민감도
print('\n' + '=' * 110)
print('손절 버퍼 민감도 (베스트 조합의 N/k/valid/zone/stop 고정)')
print('=' * 110)
sigs = gen_signals(best['N'], best['k'], best['zone'], best['valid'])
print('%-7s %4s | %3s %3s %3s %3s | %6s %6s %7s | %10s %8s %6s %4s' % (
    '버퍼', 'lev', 'TP', '익손', '손절', '청산', '승률%', '손절폭', '마진손익', '최종자산$', '수익률%', 'MDD%', '연패'))
print('-' * 110)
for sb in (0.005, 0.01, 0.015, 0.02, 0.03):
    for lev in LEVS:
        r = simulate(sigs, best['stop'], sb, lev)
        print('%-7s %3dx | %3d %3d %3d %3d | %6.1f %6.2f %7.1f | %10.0f %8.1f %6.1f %4d' % (
            '%.1f%%' % (sb * 100), lev, r['tp'], r['sp'], r['sl'], r['liq'], r['wr'], r['risk'],
            r['pnl_m'], r['eq'], r['ret'], r['mdd'], r['worst']))

print('\n스윕 전체: trendline_sweep.csv / 베스트 거래내역: trendline_trades.csv')
