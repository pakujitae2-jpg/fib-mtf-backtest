# -*- coding: utf-8 -*-
"""fib_grade.py — Test H §5 등급 부여 · 등급별 통계 (표준 라이브러리만)

등급 규칙 (사전 등록, 가중치 없음):
  k = 생존 조건 수, c = 신호별 생존 조건 중 '좋은 분위' 충족 개수
  A: c >= ceil(2k/3)   C: c <= floor(k/3)   B: 그 외.   k=0 → 전부 B.  k=1 → A=충족, C=미충족.
등급은 필터가 아니라 위험 배분 기울기다 (C 급도 거래).
"""
import math
from collections import OrderedDict, Counter
from fib_cond_exp import tercile, cell, drop_top


def grade_of(c, k):
    if k == 0:
        return 'B'
    if c >= math.ceil(2 * k / 3):
        return 'A'
    if c <= math.floor(k / 3):
        return 'C'
    return 'B'


def assert_rule():
    """불변식 8: §5.1 진리표."""
    assert grade_of(0, 0) == 'B'
    assert grade_of(1, 1) == 'A' and grade_of(0, 1) == 'C'
    assert grade_of(2, 2) == 'A' and grade_of(1, 2) == 'B' and grade_of(0, 2) == 'C'
    assert grade_of(3, 3) == 'A' and grade_of(2, 3) == 'A' and grade_of(1, 3) == 'C' and grade_of(0, 3) == 'C'
    assert grade_of(4, 4) == 'A' and grade_of(3, 4) == 'A' and grade_of(2, 4) == 'B' and grade_of(1, 4) == 'C'
    return True


def assign(recs, survivors, cuts):
    """survivors: [(feature, good_tercile)]. 레코드에 tercile_<f>, c, k, grade 를 기록."""
    k = len(survivors)
    for r in recs:
        c = 0
        for f, good in survivors:
            q = tercile(r.get(f), cuts[f])
            r['tercile_' + f] = q
            if q == good:
                c += 1
        r['c'], r['k'], r['grade'] = c, k, grade_of(c, k)
    return recs


def max_consec_loss(recs):
    s = w = 0
    for r in sorted(recs, key=lambda x: x['entry_time']):
        s = s + 1 if r['R_REAL'] <= 0 else 0
        w = max(w, s)
    return w


def grade_table(recs, periods=('DEV', 'TEST', 'ALL')):
    out = OrderedDict()
    for p in periods:
        sub_p = [r for r in recs if p == 'ALL' or r['period'] == p]
        trimmed, top = drop_top(sub_p, 2)
        for g in ('A', 'B', 'C'):
            sub = [r for r in sub_p if r['grade'] == g]
            c = cell(sub)
            c['mean_R_top2rm'] = cell([r for r in trimmed if r['grade'] == g]).get('mean_R')
            c['max_consec_loss'] = max_consec_loss(sub) if sub else 0
            c['yearly_n'] = dict(sorted(Counter(r['year'] for r in sub).items()))
            c['sum_R'] = sum(r['R_REAL'] for r in sub)
            out[(p, g)] = c
        out[(p, 'ALL')] = dict(cell(sub_p), sum_R=sum(r['R_REAL'] for r in sub_p), max_consec_loss=max_consec_loss(sub_p) if sub_p else 0,
                               yearly_n=dict(sorted(Counter(r['year'] for r in sub_p).items())), top2=[(r['sid'], round(r['R_REAL'], 2), r['grade']) for r in top])
    return out
