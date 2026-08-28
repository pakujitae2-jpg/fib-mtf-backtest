# -*- coding: utf-8 -*-
# 상승 추세선(Higher-Low 연결선) 리테스트 매매 시뮬레이션
#
#   피벗 저점  : 좌우 k봉보다 낮은 일봉 저가. 우측 k봉이 닫혀야 확정 (선행편향 없음)
#   추세선     : 룩백 N봉 안의 피벗 저점 2개(p1<p2, low[p2]>low[p1])를 잇는 상승선.
#                p1 이후 현재까지 모든 봉이 선 아래를 훼손하지 않아야 유효
#                  valid='low'   -> 저가가 선 아래로 한 번도 안 내려감 (엄격)
#                  valid='close' -> 종가가 선 아래로 안 내려감 (꼬리 허용)
#                유효선이 여러 개면 현재가에 가장 가까운(선 값이 가장 높은) 선 채택
#   신호       : 당일 저가 <= 선*(1+zone)  AND  종가 > 선     -> 그 날 종가 진입
#   손절       : 선*(1-sbuf).  stop='trail' 은 매일 추세선을 따라 상향, 'fixed' 는 진입일 값 고정
#   익절       : 진입가*(1+TP) 지정가
#   같은 일봉에 손절/익절 공존 -> 1시간봉으로 선후 판정 (같은 1h 안이면 손절 처리)
#   자금       : 시드의 POS(30%)만 증거금으로 투입, 레버리지 LEV, 강제청산가 반영
import csv, sys, time
from bisect import bisect_left, bisect_right
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

START = '2023-01-01'
TP = 0.10            # 목표 +10%  (10x -> 마진 기준 +100%)
POS = 0.30           # 시드 대비 투입 비중
SEED = 10000.0
FEE_MAKER = 0.0002
FEE_TAKER = 0.0005
SLIP = 0.0005        # 손절 체결 슬리피지
FUNDING = 0.0001     # 8시간당
MM = 0.005           # 유지증거금률(근사) -> 청산가 = entry*(1 - 1/lev + MM)
MIN_GAP = 5          # 피벗 간 최소 거리(봉)
MAX_SLOPE = 0.03     # 추세선 일 상승률 상한 (너무 가파른 선 제외)
MIN_SLOPE = 0.0005   # 일 상승률 하한 (거의 수평선 제외)
EPS = 1e-9
NOW_MS = int(time.time() * 1000)


def load(p):
    with open(p, encoding='utf-8') as f:
        return [{'ot': int(r['open_time']), 'day': r['dt'][:10], 'dt': r['dt'],
                 'o': float(r['open']), 'h': float(r['high']),
                 'l': float(r['low']), 'c': float(r['close']),
                 'ct': int(r['close_time'])} for r in csv.DictReader(f)]


D = load('btcusdt_1d.csv')
H = load('btcusdt_1h.csv')
hour_by_day = defaultdict(list)
for b in H:
    hour_by_day[b['day']].append(b)

lo = [d['l'] for d in D]
hi = [d['h'] for d in D]
cl = [d['c'] for d in D]
day = [d['day'] for d in D]
LAST = max(i for i, d in enumerate(D) if d['ct'] <= NOW_MS)   # 마지막 확정 일봉
START_I = next(i for i in range(len(D)) if day[i] >= START)

# ---------------------------------------------------------------- 추세선 탐지
_piv_cache = {}


def pivots(k):
    if k in _piv_cache:
        return _piv_cache[k]
    out = []
    for i in range(k, len(D) - k):
        v = lo[i]
        if all(v < lo[i - j] for j in range(1, k + 1)) and all(v <= lo[i + j] for j in range(1, k + 1)):
            out.append(i)
    _piv_cache[k] = out
    return out


def line_val(tl, t):
    p1, slope = tl[0], tl[2]
    return lo[p1] + slope * (t - p1)


_valid_cache = {}


def valid_until(p1, p2, vmode):
    """(p1,p2) 선이 처음 훼손되는 봉 인덱스. 그 전까지 유효."""
    key = (p1, p2, vmode)
    if key in _valid_cache:
        return _valid_cache[key]
    slope = (lo[p2] - lo[p1]) / (p2 - p1)
    src = lo if vmode == 'low' else cl
    vu = len(D)
    for t in range(p1 + 1, len(D)):
        if src[t] < lo[p1] + slope * (t - p1) - EPS:
            vu = t
            break
    _valid_cache[key] = vu
    return vu


def best_line(i, N, k, vmode):
    """i일 종가 시점에 알 수 있는 유효 상승 추세선 중 현재가에 가장 가까운 것."""
    P = pivots(k)
    a = bisect_left(P, i - N)
    b = bisect_right(P, i - k)          # 확정된 피벗만
    cand = P[a:b]
    best, best_v = None, -1.0
    for x in range(len(cand)):
        p1 = cand[x]
        for y in range(x + 1, len(cand)):
            p2 = cand[y]
            if p2 - p1 < MIN_GAP or lo[p2] <= lo[p1]:
                continue
            slope = (lo[p2] - lo[p1]) / (p2 - p1)
            r = slope / lo[p1]
            if r < MIN_SLOPE or r > MAX_SLOPE:
                continue
            if i >= valid_until(p1, p2, vmode):
                continue
            v = lo[p1] + slope * (i - p1)
            if v > best_v:
                best, best_v = (p1, p2, slope), v
    return best


def gen_signals(N, k, zone, vmode):
    sigs = []
    for i in range(START_I, LAST + 1):
        tl = best_line(i, N, k, vmode)
        if tl is None:
            continue
        L = line_val(tl, i)
        if lo[i] <= L * (1 + zone) + EPS and cl[i] > L:
            sigs.append((i, tl))
    return sigs

# ---------------------------------------------------------------- 체결 시뮬
STAT = {'amb_day': 0, 'amb_1h': 0}


def resolve_day(j, stop, target):
    bars = hour_by_day.get(day[j], [])
    if not bars:
        return 'stop'
    for b in bars:
        s = b['l'] <= stop + EPS
        t = b['h'] >= target - EPS
        if s and t:
            STAT['amb_1h'] += 1
            return 'stop'
        if s:
            return 'stop'
        if t:
            return 'tp'
    return 'stop'


def walk(i, tl, smode, sbuf, liq):
    """진입 i 이후 청산 시점/가격 판정. return (res, j, exit_px, init_stop)"""
    entry = cl[i]
    target = entry * (1 + TP)
    init_stop = line_val(tl, i) * (1 - sbuf)
    for j in range(i + 1, LAST + 1):
        stop = line_val(tl, j) * (1 - sbuf) if smode == 'trail' else init_stop
        stop = max(stop, liq)             # 청산가가 손절보다 위면 청산가에서 끝남
        s = lo[j] <= stop + EPS
        t = hi[j] >= target - EPS
        if s and t:
            STAT['amb_day'] += 1
            r = resolve_day(j, stop, target)
        elif s:
            r = 'stop'
        elif t:
            r = 'tp'
        else:
            continue
        if r == 'tp':
            return 'tp', j, target, init_stop
        if stop <= liq + EPS:
            return 'liq', j, liq, init_stop
        return ('sp' if stop > entry else 'sl'), j, stop * (1 - SLIP), init_stop
    return 'open', LAST, cl[LAST], init_stop


def simulate(sigs, smode, sbuf, lev):
    eq, peak, mdd = SEED, SEED, 0.0
    busy = -1
    cnt = defaultdict(int)
    streak = worst = 0
    risks, holds, pnls, trades = [], [], [], []
    for i, tl in sigs:
        if i <= busy:
            continue
        entry = cl[i]
        liq = entry * (1 - 1.0 / lev + MM)
        res, j, ex, init_stop = walk(i, tl, smode, sbuf, liq)
        busy = j
        cnt[res] += 1
        margin = eq * POS
        notional = margin * lev
        qty = notional / entry
        fee = notional * FEE_TAKER + qty * ex * (FEE_MAKER if res == 'tp' else FEE_TAKER)
        fund = notional * FUNDING * 3 * (j - i)
        pnl = qty * (ex - entry) - fee - fund
        if res == 'liq':
            pnl = -margin
        if res == 'open':
            trades.append((i, j, res, entry, init_stop, ex, pnl / margin * 100, tl))
            continue
        eq += pnl
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak * 100)
        if res in ('sl', 'liq'):
            streak += 1
            worst = max(worst, streak)
        else:
            streak = 0
        risks.append((entry - init_stop) / entry * 100)
        holds.append(j - i)
        pnls.append(pnl / margin * 100)
        trades.append((i, j, res, entry, init_stop, ex, pnl / margin * 100, tl))
    dec = cnt['tp'] + cnt['sp'] + cnt['sl'] + cnt['liq']
    avg = lambda xs: sum(xs) / len(xs) if xs else 0.0
    return {'sig': len(sigs), 'n': dec, 'tp': cnt['tp'], 'sp': cnt['sp'], 'sl': cnt['sl'],
            'liq': cnt['liq'], 'open': cnt['open'],
            'wr': ((cnt['tp'] + cnt['sp']) / dec * 100) if dec else 0.0,
            'risk': avg(risks), 'pnl_m': avg(pnls), 'hold': avg(holds),
            'eq': eq, 'ret': (eq / SEED - 1) * 100, 'mdd': mdd, 'worst': worst,
            'trades': trades}


