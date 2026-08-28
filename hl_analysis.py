# -*- coding: utf-8 -*-
# 저점 리테스트 패턴의 "정확도" 자체를 측정 (청산 방식과 무관)
#   1) 예시(2026-08-17) 탐지 확인
#   2) 리테스트 후 L 이탈 전에 +5/10/15/20% 도달 확률  vs  무작위 진입(같은 손절폭) 대비
#   3) 손절 폭별 / 지정가 진입별 +10% 도달 확률
import sys, random
from bisect import bisect_left, bisect_right
from tl_engine import build

sys.stdout.reconfigure(encoding='utf-8')
e = build('1d', '2023-01-15')
lo, hi, cl, lab = e.lo, e.hi, e.cl, e.label
EPS = 1e-9
GAP_MIN = 5
MAXD = 60      # 추적 최대 일수


def setups(k, gapmax, zone, gapmin=GAP_MIN):
    P = e.pivots(k)
    out = []
    for j in range(e.START_I, e.LAST + 1):
        cand = P[bisect_left(P, j - gapmax):bisect_right(P, j - gapmin)]
        best = None
        for T in cand:
            if T + k > j:
                continue
            L = lo[T]
            if lo[j] < L - EPS or lo[j] > L * (1 + zone) + EPS or cl[j] <= L:
                continue
            if min(lo[T + 1:j]) < L - EPS:
                continue
            if best is None or L < best[1]:
                best = (T, L)
        if best:
            out.append((j, best[0], best[1]))
    return out


# ---------------------------------------------------------------- 1) 예시 탐지
print('=' * 120)
print('1) 2026년 6~8월 리테스트 셋업 탐지 (k=2, 최대간격 30일)')
print('=' * 120)
for zone in (0.01, 0.02):
    print('zone %.0f%%:' % (zone * 100))
    for j, T, L in setups(2, 30, zone):
        if lab[j] >= '2026-06-01':
            print('   리테스트 %s 저가 %.0f 종가 %.0f | 기준저점 %s L=%.0f | 눌림 +%.2f%% | %d일 경과' % (
                lab[j], lo[j], cl[j], lab[T], L, (lo[j] / L - 1) * 100, j - T))


# ---------------------------------------------------------------- 2) 도달 확률
def outcome(i, entry, stop, targets):
    """i일 종가 진입 후 stop 이탈 전에 각 target 도달 여부. 5분봉으로 같은 날 선후 판정."""
    hit = {t: False for t in targets}
    pend = sorted(targets)
    for j in range(i + 1, min(i + MAXD, e.LAST) + 1):
        s = lo[j] <= stop + EPS
        while pend and hi[j] >= entry * (1 + pend[0]) - EPS:
            t = pend[0]
            if s:
                ev, _ = e.first_event(j, stop, entry * (1 + t))
                if ev != 'tp':
                    break
            hit[t] = True
            pend.pop(0)
        if s:
            return hit, j - i, True
    return hit, MAXD, False


TGT = [0.05, 0.10, 0.15, 0.20]
random.seed(3)
ALL_DAYS = list(range(e.START_I, e.LAST - MAXD))


def table(rows_, title):
    print('\n' + '=' * 120)
    print(title)
    print('=' * 120)
    print('%-34s %5s %7s | %6s %6s %6s %6s | %8s %7s' % (
        '조건', '표본', '손절폭%', '+5%', '+10%', '+15%', '+20%', '이탈비율', '평균일'))
    print('-' * 120)
    for name, res in rows_:
        n = len(res)
        if not n:
            continue
        print('%-34s %5d %7.2f | %5.0f%% %5.0f%% %5.0f%% %5.0f%% | %7.0f%% %7.1f' % (
            name, n, sum(r[3] for r in res) / n,
            *[sum(1 for r in res if r[0][t]) / n * 100 for t in TGT],
            sum(1 for r in res if r[2]) / n * 100, sum(r[1] for r in res) / n))


def run_setups(k, gapmax, zone, buf, gapmin=GAP_MIN, entry_mode='close'):
    res = []
    for j, T, L in setups(k, gapmax, zone, gapmin):
        stop = L * (1 - buf)
        entry = cl[j]
        res.append(outcome(j, entry, stop, TGT) + ((entry - stop) / entry * 100,))
    return res


def run_random(n, risk_pct):
    res = []
    for i in random.sample(ALL_DAYS, n):
        entry = cl[i]
        stop = entry * (1 - risk_pct / 100)
        res.append(outcome(i, entry, stop, TGT) + (risk_pct,))
    return res


rows = []
for k in (2, 3):
    for gm in (30, 60):
        for z in (0.01, 0.02, 0.03):
            rows.append(('패턴 k=%d gap<=%d zone %.0f%% 손절 L-0.5%%' % (k, gm, z * 100), run_setups(k, gm, z, 0.005)))
table(rows, '2) 리테스트 종가 진입 -> L-0.5% 이탈 전 목표 도달 확률')

base = run_setups(2, 30, 0.01, 0.005)
avg_risk = sum(r[3] for r in base) / len(base)
rows = [('패턴 k=2 gap<=30 zone 1%% (손절폭 %.2f%%)' % avg_risk, base)]
for rp in (2.0, 2.5, 3.0):
    rows.append(('무작위 진입, 손절 -%.1f%% (500회)' % rp, run_random(500, rp)))
table(rows, '   비교: 무작위 날 종가 진입 + 같은 손절폭')

rows = [('패턴 gap>=5  k=2 gap<=30 zone 1%', run_setups(2, 30, 0.01, 0.005, 5)),
        ('패턴 gap>=10 k=2 gap<=60 zone 1%', run_setups(2, 60, 0.01, 0.005, 10)),
        ('패턴 gap>=15 k=2 gap<=60 zone 1%', run_setups(2, 60, 0.01, 0.005, 15)),
        ('패턴 gap>=5  k=2 gap<=30 zone 3%', run_setups(2, 30, 0.03, 0.005, 5)),
        ('패턴 gap>=10 k=2 gap<=60 zone 3%', run_setups(2, 60, 0.03, 0.005, 10))]
table(rows, '   최소 간격(gap) 변화')

# ---------------------------------------------------------------- 3) 손절 폭 / 지정가 진입
rows = []
for buf in (0.005, 0.01, 0.02, 0.03, 0.05):
    rows.append(('종가진입, 손절 L-%.1f%%' % (buf * 100), run_setups(2, 30, 0.02, buf)))
table(rows, '3) 손절 폭을 넓히면? (k=2 gap<=30 zone 2%)')

# 지정가: L*(1+z_e) 에 걸어두고 리테스트 날 체결. 같은 날 체결 후 손절 터치는 5분봉으로 확인
def run_limit(k, gapmax, zone, z_entry, buf):
    res = []
    for j, T, L in setups(k, gapmax, zone):
        px = L * (1 + z_entry)
        if lo[j] > px + EPS:
            continue
        stop = L * (1 - buf)
        a, b = e.fine_range(j)
        m = next((x for x in range(a, b) if e.f_lo[x] <= px + EPS), None)
        if m is None:
            continue
        # 체결 후 같은 날 손절 터치
        if any(e.f_lo[x] <= stop + EPS for x in range(m, b)):
            res.append(({t: False for t in TGT}, 0, True, (px - stop) / px * 100))
            continue
        h, d, br = outcome(j, px, stop, TGT)
        # 체결 당일 남은 시간에 목표 도달했는지도 반영
        for t in TGT:
            if any(e.f_hi[x] >= px * (1 + t) - EPS for x in range(m, b)):
                h[t] = True
        res.append((h, d, br, (px - stop) / px * 100))
    return res


rows = []
for ze in (0.005, 0.01, 0.02):
    for buf in (0.005, 0.01, 0.02):
        rows.append(('지정가 L+%.1f%% 진입, 손절 L-%.1f%%' % (ze * 100, buf * 100), run_limit(2, 30, 0.03, ze, buf)))
table(rows, '   지정가 진입 (k=2 gap<=30, 리테스트 존 3%)')

# ---------------------------------------------------------------- 연도별
rows = []
for y in ('2023', '2024', '2025', '2026'):
    rows.append(('패턴 k=2 gap<=30 zone 2%% 손절 L-1%% %s년' % y,
                 [r for (j, T, L), r in zip(setups(2, 30, 0.02), run_setups(2, 30, 0.02, 0.01)) if lab[j][:4] == y]))
table(rows, '4) 연도별 (k=2 gap<=30 zone 2% 손절 L-1%)')
