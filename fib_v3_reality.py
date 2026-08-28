# -*- coding: utf-8 -*-
# v3 현실 패치 검증 (우선순위 1~5)
#   1) 신호시장 비교: S=Spot 전부 / B=Futures 전부 / C=Spot D+W, Futures 4H+체결
#   2) 실제 펀딩 이력 vs 고정 0.01%
#   3) 선물 가격 기준 손절/TP (B, C 변형에 포함)
#   4) 체결 모델 A(터치=체결) / B(관통 필요) / C(터치 후 시장가)
#   5) MISSED_BUT_VALID (A는 체결, B는 미체결) 의 성과
#   + W 목표 소급 정책 retro/skip/market, 신호 나이, 리스크 기반 사이징
import sys, time
from collections import Counter
import fib_mtf as F

sys.stdout.reconfigure(encoding='utf-8')
POS, LEV, SEED = 0.30, 10, 10000.0
START = '2019-12-15'
YEARS = [str(y) for y in range(2019, 2027)]
V3 = dict(DCONF=0.382, DMIN=0.08, R4=0.236, R_ENTRY_FIB=0.236, R_RATIO=0.1, ATR_MULT=1.0, TOL=0.003, BUF=0.003,
          EXIT='halfR2spec', RATCHET=0.0, MFILT='off', STRUCT='HH_HL', SIDES='both', FILL='A', PEN=0.0, TGT_POLICY='retro')

fund = F.load_funding('btcusdt_funding.csv')
d_spot = F.load_csv('btcusdt_1d_2017.csv')
h4_spot = F.load_csv('btcusdt_4h_2019.csv')
f_spot = F.load_csv('btcusdt_5m_2019_2022.csv') + F.load_csv('btcusdt_5m.csv')
d_fut = F.load_csv('btcusdt_fut_1d.csv')
h4_fut = F.load_csv('btcusdt_fut_4h.csv')
f_fut = F.load_csv('btcusdt_fut_5m.csv')
t0 = time.time()
DS = {
    'S (Spot 전부)': F.Data(d_spot, h4_spot, [r for r in f_spot if r[0] >= h4_spot[0][0]], START, funding=fund),
    'B (Futures 전부)': F.Data(d_fut, h4_fut, f_fut, START, funding=fund),
    'C (Spot D/W + Fut 4H/체결)': F.Data(d_spot, h4_fut, f_fut, START, funding=fund),
}
DS_FIXED = {'S (Spot 전부)': F.Data(d_spot, h4_spot, [r for r in f_spot if r[0] >= h4_spot[0][0]], START),
            'C (Spot D/W + Fut 4H/체결)': F.Data(d_spot, h4_fut, f_fut, START)}
print('데이터 로드 %.1fs | 펀딩 이력 %d건 (%s ~ %s) 평균 %.4f%%/8h, 중앙값 %.4f%%' % (
    time.time() - t0, len(fund), F.ts(fund[0][0]), F.ts(fund[-1][0]), sum(r for _, r in fund) / len(fund) * 100,
    sorted(r for _, r in fund)[len(fund) // 2] * 100))
for name, d in DS.items():
    print('  %-28s 4H %s ~ %s (%d봉)  5분봉 %d' % (name, F.ts(d.h_ot[d.start4]), F.ts(d.h_ot[d.LAST]), d.LAST - d.start4 + 1, len(d.f_ot)))


def yrs_of(d):
    return (d.h_ot[d.LAST] - d.h_ot[d.start4]) / F.D_MS / 365.25


def yline(d, trades):
    out = []
    for y in YEARS:
        pms = [F.pm_of(t, LEV) for t in trades if F.ts(d.h_ot[t['t0']])[:4] == y and t['result'] != 'open']
        out.append('%4.1f' % min(F._pf(pms), 9.9) if len(pms) >= 3 else '   -')
    pos = sum(1 for y in YEARS if len([t for t in trades if F.ts(d.h_ot[t['t0']])[:4] == y and t['result'] != 'open']) >= 3
              and F._pf([F.pm_of(t, LEV) for t in trades if F.ts(d.h_ot[t['t0']])[:4] == y and t['result'] != 'open']) > 1)
    return ' '.join(out), pos


def row(label, d, P):
    trades, events, _ = F.run(d, P)
    e = F.evaluate(trades, POS, LEV, SEED, yrs_of(d))
    yl, pos = yline(d, trades)
    c = Counter(x[2] for x in events)
    fund_avg = sum(t.get('funding', 0.0) for t in trades if t['result'] != 'open') / max(1, e['n']) * 100
    print('%-40s | %4d %5.1f %5.2f %+6.1f %+7.0f %5.0f %3d | %s (%d) | 신호 %3d 무효 %3d | 펀딩 %+.3f%%/거래' % (
        label, e['n'], e['wr'], e['pf'], e['exp'], e['ret'], e['mdd'], e['worst'], yl, pos, c['SIGNAL'], c['R_INVALID'], fund_avg))
    return trades, e


HDR = '%-40s | %4s %5s %5s %6s %7s %5s %3s | %s | %s | %s' % ('구성', '거래', '승률', 'PF', '기대값', '수익률', 'MDD', '연패', '연도별 PF 19~26 (양수)', '신호/무효', '펀딩')

# ---------------------------------------------------------------- 1) 신호시장 x 청산
print('\n' + '=' * 170)
print('1) 신호시장 비교  (%s ~, 30%% 투입 %dx, 실제 펀딩 이력 적용)' % (START, LEV))
print('=' * 170)
print(HDR)
print('-' * 170)
RES = {}
for ex in ('spec', 'halfR2spec'):
    for name, d in DS.items():
        RES[(ex, name)] = row('%-12s %s' % (ex, name), d, dict(V3, EXIT=ex))
    print('-' * 170)

# ---------------------------------------------------------------- 2) 펀딩: 고정 vs 이력
print('\n' + '=' * 170)
print('2) 펀딩 비용: 고정 0.01%/8h  vs  실제 이력  (halfR2spec)')
print('=' * 170)
print(HDR)
print('-' * 170)
for name in DS_FIXED:
    row('고정펀딩  %s' % name, DS_FIXED[name], V3)
    row('실제펀딩  %s' % name, DS[name], V3)
trades = RES[('halfR2spec', 'C (Spot D/W + Fut 4H/체결)')][0]
fl = [t for t in trades if t['result'] != 'open']
fund_l = [t['funding'] * 100 for t in fl if t['side'].s > 0]
fund_s = [t['funding'] * 100 for t in fl if t['side'].s < 0]
print('\n  C 구성 펀딩 상세: 롱 %d건 평균 %+.3f%% (최대 %+.2f%%), 숏 %d건 평균 %+.3f%% (최소 %+.2f%%)  |  보유 7일 이상 거래 %d건 평균 펀딩 %+.2f%%' % (
    len(fund_l), sum(fund_l) / len(fund_l), max(fund_l), len(fund_s), sum(fund_s) / len(fund_s), min(fund_s),
    sum(1 for t in fl if t['hold_h'] >= 168), sum(t['funding'] * 100 for t in fl if t['hold_h'] >= 168) / max(1, sum(1 for t in fl if t['hold_h'] >= 168))))
for ex in ('spec',):
    tr = RES[(ex, 'C (Spot D/W + Fut 4H/체결)')][0]
    big = sorted([t for t in tr if t['result'] != 'open'], key=lambda t: -t['r_net'])[:3]
    print('  spec 상위 3거래 펀딩: ' + ' | '.join('%s %s %.0f일 총수익 %+.1f%% 펀딩 %+.2f%%' % (
        'L' if t['side'].s > 0 else 'S', F.ts(d_spot[0][0]) and F.ts(DS['C (Spot D/W + Fut 4H/체결)'].h_ot[t['t0']]), t['hold_h'] / 24, t['r_net'] * 100, t['funding'] * 100) for t in big))

# ---------------------------------------------------------------- 4) 체결 모델 + 5) MISSED_BUT_VALID
print('\n' + '=' * 170)
print('4) 체결 모델 A/B/C  (C 구성, halfR2spec)   5) MISSED_BUT_VALID = A 는 체결됐지만 B 는 미체결인 신호의 A 기준 성과')
print('=' * 170)
print(HDR)
print('-' * 170)
dC = DS['C (Spot D/W + Fut 4H/체결)']
trA, eA = row('A  터치=체결 (지정가)', dC, dict(V3, FILL='A'))
keysA = {t['key']: t for t in trA}
for pen in (0.0005, 0.001, 0.002, 0.003):
    trB, eB = row('B  관통 %.2f%% 필요' % (pen * 100), dC, dict(V3, FILL='B', PEN=pen))
    keysB = {t['key'] for t in trB}
    mbv = [t for k, t in keysA.items() if k not in keysB and t['result'] != 'open']
    pms = [F.pm_of(t, LEV) for t in mbv]
    print('      -> MISSED_BUT_VALID %d건: A 기준 승률 %.0f%%  PF %.2f  기대값 %+.1f%%  (체결률 %.0f%%)' % (
        len(mbv), sum(1 for p in pms if p > 0) / max(1, len(pms)) * 100, F._pf(pms) if pms else 0, sum(pms) / max(1, len(pms)), eB['n'] / eA['n'] * 100))
trC, eC = row('C  터치 후 시장가 (taker+슬립)', dC, dict(V3, FILL='C'))
dev = [(t['entry'] - t['expected']) / abs(t['expected']) * 100 for t in trC]
print('      -> C 실제 진입가 vs 레벨: 평균 %+.3f%%  (레벨보다 유리 %d건 / 불리 %d건)' % (sum(dev) / len(dev), sum(1 for x in dev if x < 0), sum(1 for x in dev if x >= 0)))

# ---------------------------------------------------------------- W 목표 소급 정책
print('\n' + '=' * 170)
print('W 목표 소급 정책 (+2R 이전에 이미 지난 W 목표)  retro=지난 목표가에 체결(현재) / skip=기록만, 청산 안 함(v3 문서안) / market=+2R 시점 시장가')
print('=' * 170)
print(HDR)
print('-' * 170)
for name in ('S (Spot 전부)', 'C (Spot D/W + Fut 4H/체결)'):
    for pol in ('retro', 'skip', 'market'):
        row('%-6s %s' % (pol, name), DS[name], dict(V3, TGT_POLICY=pol))
    print('-' * 170)

# ---------------------------------------------------------------- 신호 나이 / 체결률
print('\n' + '=' * 170)
print('신호 나이 (R 확정 -> 체결까지 4H 봉 수)  |  C 구성 halfR2spec')
print('=' * 170)
ages = Counter(min(t['age'], 12) for t in trA)
print('  체결 %d건: ' % len(trA) + ', '.join('%s봉 %d' % ('12+' if a == 12 else a, ages[a]) for a in sorted(ages)))
_, evA, _ = F.run(dC, dict(V3, FILL='A'))
cA = Counter(x[2] for x in evA)
print('  신호(ARMED+유효 R) %d건 중 체결 %d (%.0f%%), 체결 전 R 무효화 %d, 나머지는 새 R 로 교체/ARM 해제' % (cA['SIGNAL'], len(trA), len(trA) / cA['SIGNAL'] * 100, cA['R_INVALID']))
by_age = {}
for t in trA:
    if t['result'] != 'open':
        by_age.setdefault('1' if t['age'] <= 1 else ('2-3' if t['age'] <= 3 else '4+'), []).append(F.pm_of(t, LEV))
for k in ('1', '2-3', '4+'):
    pms = by_age.get(k, [])
    if pms:
        print('  나이 %-4s: %3d건  승률 %.0f%%  PF %.2f  기대값 %+.1f%%' % (k, len(pms), sum(1 for p in pms if p > 0) / len(pms) * 100, F._pf(pms), sum(pms) / len(pms)))

# ---------------------------------------------------------------- 사이징
print('\n' + '=' * 170)
print('사이징: 고정 비중 x 배율  vs  거래당 리스크 고정 (notional = 자산 x f / 손절폭, 배율 상한 10x)   |  C 구성 halfR2spec, 실제 펀딩')
print('=' * 170)
for pos in (0.10, 0.15, 0.30):
    e = F.evaluate(trA, pos, 10, SEED, yrs_of(dC))
    print('  고정 %3.0f%% x 10x (실효 %.1fx): 수익률 %+6.0f%%  MDD %4.0f%%  연패 %2d' % (pos * 100, pos * 10, e['ret'], e['mdd'], e['worst']))
for f in (0.005, 0.01, 0.015, 0.02, 0.03):
    r = F.evaluate_risk(trA, f, SEED, 10.0)
    print('  리스크 %3.1f%%/거래 (평균 실효 %.2fx): 수익률 %+6.0f%%  MDD %4.0f%%  연패 %2d  거래당 평균 %+.2f%%' % (f * 100, r['avg_lev'], r['ret'], r['mdd'], r['worst'], r['avg_ret']))
risks = [(t['entry'] - t['stop0']) / abs(t['entry']) * 100 for t in trA]
print('  손절폭 분포: 평균 %.2f%%  중앙값 %.2f%%  최소 %.2f%%  최대 %.2f%%' % (sum(risks) / len(risks), sorted(risks)[len(risks) // 2], min(risks), max(risks)))
