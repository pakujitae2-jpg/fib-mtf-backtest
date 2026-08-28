# -*- coding: utf-8 -*-
# 감지봇: 바이낸스 현물 BTCUSDT 최신 봉을 증분 수집 -> MTF 피보나치 엔진 실행 -> 현재 상태 / 대기 주문 출력
#   usage: python fib_bot.py            (증분 수집 + 상태)
#          python fib_bot.py --offline  (수집 생략)
import csv, sys, time
import requests
import fib_mtf as F

sys.stdout.reconfigure(encoding='utf-8')
BASE = 'https://api.binance.com/api/v3/klines'
SYMBOL = 'BTCUSDT'

# 백테스트 최종 후보 (fib_backtest.py)
PARAMS = dict(DCONF=0.382, DMIN=0.08, R4=0.236, R_RATIO=0.1, ATR_MULT=1.0, TOL=0.003, BUF=0.003,
              EXIT='spec', RATCHET=0.0, MFILT='off', STRUCT='HH_HL', SIDES='both')
FILES = [('btcusdt_1d_2017.csv', '1d'), ('btcusdt_4h_2019.csv', '4h'), ('btcusdt_5m.csv', '5m')]
# usage: python fib_bot.py [--offline] [--exit spec|tpR3|halfR2spec|halfR2|trail] [--ratchet 0.10]
if '--exit' in sys.argv:
    PARAMS['EXIT'] = sys.argv[sys.argv.index('--exit') + 1]
if '--ratchet' in sys.argv:
    PARAMS['RATCHET'] = float(sys.argv[sys.argv.index('--ratchet') + 1])


def update_csv(path, interval):
    with open(path, encoding='utf-8') as f:
        rd = csv.DictReader(f)
        cols = rd.fieldnames
        rows = list(rd)
    last = int(rows[-1]['open_time'])
    rows = rows[:-1]                                   # 마지막 봉은 미완성일 수 있으니 다시 받음
    cur, added = last, 0
    while True:
        r = requests.get(BASE, params={'symbol': SYMBOL, 'interval': interval, 'startTime': cur, 'limit': 1000}, timeout=30)
        r.raise_for_status()
        data = r.json()
        if not data:
            break
        for k in data:
            dt = time.strftime('%Y-%m-%d %H:%M', time.gmtime(k[0] / 1000))
            row = {'open_time': k[0], 'dt': dt, 'open': k[1], 'high': k[2], 'low': k[3], 'close': k[4],
                   'volume': k[5], 'close_time': k[6]}
            rows.append({c: row[c] for c in cols})
            added += 1
        if len(data) < 1000:
            break
        cur = data[-1][0] + 1
        time.sleep(0.2)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print('  %s: +%d rows -> %s' % (path, added, rows[-1]['dt']))


if '--offline' not in sys.argv:
    print('데이터 갱신 중...')
    for path, itv in FILES:
        update_csv(path, itv)

data = F.load_data('2019-03-01')
trades, events, sides = F.run(data, PARAMS)
L = data.LAST
dl = data.h_day[L]
px = data.h_cl[L]
print('\n' + '=' * 110)
print('MTF 피보나치 감지봇  |  마지막 확정 4H 봉 %s  종가 %.0f  |  일봉 %s 까지 반영  |  EXIT=%s 래칫 %.0f%%' % (F.ts(data.h_ot[L]), px, F.ts(data.d_ot[dl - 1], 24), PARAMS['EXIT'], PARAMS['RATCHET'] * 100))
print('=' * 110)
pw = data.prev_week[dl]
print('월봉 방향(참고): zz=%s  |  전주 고가 %.0f 저가 %.0f' % (data.m_zz[dl], pw[0], pw[1]))
print('  롱 목표(전주 고가 확장) #1-1 %.0f  #1-2 %.0f  #1-3 %.0f  #1-6 %.0f' % tuple(pw[0] + (pw[0] - pw[1]) * f for f in F.FIB_EXT))
print('  숏 목표(전주 저가 확장) #1-1 %.0f  #1-2 %.0f  #1-3 %.0f  #1-6 %.0f' % tuple(pw[1] - (pw[0] - pw[1]) * f for f in F.FIB_EXT))

orders = []
for sd in sides:
    sg = sd.s
    name = 'LONG ' if sg > 0 else 'SHORT'
    z = sd.dzz
    anc, ext = sg * z[2], sg * z[4]
    size = abs(z[4] - z[2])
    conf = sg * (z[4] - 0.382 * (z[4] - z[2]))
    if sg > 0:
        dirn = '상승 leg 진행 (고점 갱신 중, 저가가 %.0f 이하로 오면 눌림 확정=ARM 후보)' % conf if z[0] == 'UP' else \
               '눌림 진행 (고가가 %.0f 이상 반등하면 눌림 저점 확정)' % conf
    else:
        dirn = '하락 leg 진행 (저점 갱신 중, 고가가 %.0f 이상 오면 반등 확정=ARM 후보)' % conf if z[0] == 'UP' else \
               '반등 진행 (저가가 %.0f 이하로 내려오면 반등 고점 확정)' % conf
    print('\n[%s]  일봉: %s' % (name, dirn))
    print('        leg 시작 %.0f -> 극값 %.0f (폭 %.1f%%, 최소 %.0f%% 필요)' % (anc, ext, size / abs(z[2]) * 100, PARAMS['DMIN'] * 100))
    print('        ARMED=%s  P0=%s  H1=%s  vFlag=%s' % (
        sd.armed, '%.0f' % (sg * sd.P0) if sd.P0 else '-', '%.0f' % (sg * sd.H1) if sd.H1 else '-', sd.vflag))
    if sd.R:
        lo_r, hi_r = (sd.R[0], sd.R[1]) if sg > 0 else (-sd.R[1], -sd.R[0])
        valid = sd.r_valid(L)
        lv, st = sg * sd.entry_level(), sg * sd.stop_level()
        print('        4H R: %.0f ~ %.0f (폭 %.2f%%, 확정 %s)  유효=%s  훼손=%s' % (
            lo_r, hi_r, sd.R[2] / abs(sd.R[0]) * 100, F.ts(data.h_ot[sd.R[3]]), valid, sd.R_broken))
        print('        %s 레벨 %.0f  손절 %.0f  (손절폭 %.2f%%)' % ('23.6% 레드라인' if sg > 0 else '76.4% 블루라인', lv, st, abs(lv - st) / abs(lv) * 100))
        if sd.armed and valid and not sd.R_broken:
            tg = [sg * x for x in sd.targets(dl, sd.entry_level())]
            orders.append((name.strip(), lv, st, tg))
    else:
        print('        4H R: 없음')

opn = [t for t in trades if t['result'] == 'open']
print('\n' + '-' * 110)
if opn:
    t = opn[0]
    sg = t['side'].s
    print('보유 포지션: %s  진입 %s @%.0f  손절 %.0f  남은 목표 %s  잔여 %.0f%%' % (
        'LONG' if sg > 0 else 'SHORT', F.ts(data.h_ot[t['t0']]), sg * t['entry'], sg * t['stop'],
        ', '.join('%.0f' % (sg * x) for x, _ in t['tgts']) or '없음(일봉 전환 청산 대기)', t['frac'] * 100))
else:
    print('보유 포지션: 없음')
if orders:
    for name, lv, st, tg in orders:
        print('>>> 대기 주문 [%s]  지정가 %.0f  손절 %.0f  목표 %s  (25%% 씩 분할, 잔여는 일봉 전환 청산)' % (
            name, lv, st, ', '.join('%.0f' % x for x in tg) or '없음'))
else:
    print('대기 주문: 없음 (ARMED + 유효 R 조건 미충족)')

print('\n최근 이벤트:')
for t, sg, ev, d in events[-8:]:
    print('  %s  %s  %s' % (F.ts(data.h_ot[t]), 'LONG ' if sg > 0 else 'SHORT', ev))
print('\n최근 거래(백테스트 기준 최근 5건):')
for t in trades[-5:]:
    sg = t['side'].s
    print('  %s %s -> %s  %-5s  진입 %.0f  마진손익(10x) %+.1f%%' % (
        'L' if sg > 0 else 'S', F.ts(data.h_ot[t['t0']]), F.ts(data.h_ot[t['t1']]), t['result'], sg * t['entry'], F.pm_of(t, 10)))
