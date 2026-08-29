# -*- coding: utf-8 -*-
"""fib_features.py — Test H §3 조건 6개 계산 (look-ahead assert 포함)

모든 값은 진입 decision_time 이전에 완성된 데이터만 쓴다. 일봉은 진입일 전일 종가(d-1)까지.
  RET100  = ln(C[d-1] / C[d-101])                    high_is_good
  MA200   = entry / SMA200[d-1] - 1                  high_is_good
  VOL30   = SD(daily log ret, 30 일)[d-1] 의 롤링 과거 1년 [d-365, d-1] 백분위   low_is_good
  RET14   = ln(C[d-1] / C[d-15])                     low_is_good
  STOPPCT = (entry - stop) / entry                   low_is_good            (P-A, P-S)
  DDEPTH  = (H1 - entry) / (H1 - P0)                 방향 미지정            (P-A, P-S)
표준 라이브러리만. 조건은 이 6개 외에 추가하지 않는다 (§3.2).
"""
import math
from bisect import bisect_right
from collections import OrderedDict
from fib_mtf import D_MS, ts

FEATURES = ['RET100', 'MA200', 'VOL30', 'RET14', 'STOPPCT', 'DDEPTH']
DIRECTION = OrderedDict([('RET100', 'high'), ('MA200', 'high'), ('VOL30', 'low'), ('RET14', 'low'), ('STOPPCT', 'low'), ('DDEPTH', None)])
REGIME_FEATURES = ['RET100', 'MA200', 'VOL30', 'RET14']          # P-R 에도 적용 (진입 무관)
MAPS_TO = OrderedDict([('RET100', '상위 시간대 상승추세'), ('MA200', '상위 시간대 상승추세'), ('VOL30', '낮은 변동성'), ('RET14', '단기 비과열 눌림'),
                       ('STOPPCT', '짧은 구조적 손절'), ('DDEPTH', '눌림 위치')])
VOL_WIN, VOL_LOOKBACK = 30, 365


class DailyContext:
    """일봉 파생 시계열 (index = 일봉 index, 값은 그 날 종가까지로 계산)."""
    def __init__(self, data):
        self.data = data
        C = data.d_cl
        n = len(C)
        self.logret = [0.0] + [math.log(C[i] / C[i - 1]) for i in range(1, n)]
        self.sd30 = [None] * n
        for i in range(VOL_WIN, n):
            xs = self.logret[i - VOL_WIN + 1:i + 1]
            m = sum(xs) / VOL_WIN
            self.sd30[i] = (sum((x - m) ** 2 for x in xs) / (VOL_WIN - 1)) ** 0.5
        cs = [0.0]
        for c in C:
            cs.append(cs[-1] + c)
        self.cumsum = cs

    def sma(self, j, w):
        return (self.cumsum[j + 1] - self.cumsum[j + 1 - w]) / w

    def day_close_time(self, j):
        return self.data.d_ot[j] + D_MS - 1

    def last_completed_day(self, entry_time):
        """진입 시각 이전에 종료된 마지막 일봉 index (= 진입일 d 의 전일 d-1)."""
        t = bisect_right(self.data.h_ot, entry_time) - 1
        d = self.data.h_day[t]
        j = d - 1
        assert self.day_close_time(j) < entry_time, (ts(entry_time), j)
        return j


def compute(ctx, entry_time, entry, stop=None, P0=None, H1=None, r_confirm_time=None, arm_time=None, want=FEATURES):
    """반환 (values dict, max_ts dict). 각 조건이 참조한 데이터의 최대 timestamp 를 함께 돌려 look-ahead 를 검증한다."""
    data = ctx.data
    C = data.d_cl
    j = ctx.last_completed_day(entry_time)
    vals, max_ts = OrderedDict(), OrderedDict()
    day_ct = ctx.day_close_time(j)
    if 'RET100' in want:
        assert j - 100 >= 0
        vals['RET100'] = math.log(C[j] / C[j - 100])
        max_ts['RET100'] = day_ct
    if 'MA200' in want:
        assert j - 199 >= 0
        vals['MA200'] = entry / ctx.sma(j, 200) - 1
        max_ts['MA200'] = day_ct
    if 'VOL30' in want:
        cur = ctx.sd30[j]
        lo = max(VOL_WIN, j - (VOL_LOOKBACK - 1))                # 참조창 [d-365, d-1] = index j-364 .. j
        ref = [ctx.sd30[i] for i in range(lo, j + 1) if ctx.sd30[i] is not None]
        assert cur is not None and ref and lo >= j - (VOL_LOOKBACK - 1)
        vals['VOL30'] = sum(1 for x in ref if x <= cur) / len(ref) * 100
        max_ts['VOL30'] = day_ct
        vals['_VOL30_win'] = (data.d_ot[lo], data.d_ot[j])
    if 'RET14' in want:
        vals['RET14'] = math.log(C[j] / C[j - 14])
        max_ts['RET14'] = day_ct
    if 'STOPPCT' in want:
        vals['STOPPCT'] = (entry - stop) / entry
        max_ts['STOPPCT'] = r_confirm_time if r_confirm_time else entry_time - 1
    if 'DDEPTH' in want:
        vals['DDEPTH'] = (H1 - entry) / (H1 - P0) if (H1 is not None and P0 is not None and H1 != P0) else None
        max_ts['DDEPTH'] = (arm_time - 1) if arm_time else entry_time - 1     # ARM 은 전일 일봉 종가(= 4H 시가 직전 ms) 정보
    for k, t in max_ts.items():
        assert t < entry_time, ('lookahead', k, ts(t), ts(entry_time))
    return vals, max_ts


def check_vol_window(vals, entry_time, ctx):
    """불변식 5: VOL30 참조창 ⊂ [d-365, d-1]."""
    if '_VOL30_win' not in vals:
        return True
    a, b = vals['_VOL30_win']
    j = ctx.last_completed_day(entry_time)
    return ctx.data.d_ot[j] == b and a >= ctx.data.d_ot[j] - (VOL_LOOKBACK - 1) * D_MS and b + D_MS - 1 < entry_time


def record(ctx, kind, entry_time, entry, stop, r_net, hold_h, result, P0=None, H1=None, r_confirm_time=None, arm_time=None, sid=None, want=FEATURES):
    """조건 + 결과변수 레코드. R_REAL = r_net / 손절폭, WIN2R = R_REAL >= 2, RIDE7 = hold >= 7일."""
    vals, mts = compute(ctx, entry_time, entry, stop, P0, H1, r_confirm_time, arm_time, want)
    assert check_vol_window(vals, entry_time, ctx)
    stop_pct = (entry - stop) / entry
    R = r_net / stop_pct
    y = int(ts(entry_time)[:4])
    rec = {'kind': kind, 'sid': sid, 'entry_time': entry_time, 'year': y, 'period': 'DEV' if y <= 2022 else 'TEST', 'entry': entry, 'stop': stop,
           'stop_pct': stop_pct, 'r_net': r_net, 'R_REAL': R, 'WIN2R': R >= 2.0, 'hold_d': hold_h / 24.0, 'RIDE7': hold_h >= 168.0, 'result': result,
           'stopped': result == 'stop', 'max_ts': mts}
    rec.update({k: v for k, v in vals.items() if not k.startswith('_')})
    return rec
