# -*- coding: utf-8 -*-
# 추세선 신호 무결성 검사: 모든 신호가 규칙을 만족하는지 전수 확인 + 샘플 상세 출력
import sys
import trendline_core as c

sys.stdout.reconfigure(encoding='utf-8')

CASES = [(60, 3, 0.01, 'low'), (60, 2, 0.02, 'close'), (30, 2, 0.03, 'low')]
bad = 0
for N, k, zone, vm in CASES:
    sigs = c.gen_signals(N, k, zone, vm)
    for i, (p1, p2, slope) in sigs:
        L = c.line_val((p1, p2, slope), i)
        # 1) 피벗 정의
        for p in (p1, p2):
            assert all(c.lo[p] < c.lo[p - j] for j in range(1, k + 1)), ('left pivot', c.day[p])
            assert all(c.lo[p] <= c.lo[p + j] for j in range(1, k + 1)), ('right pivot', c.day[p])
        # 2) 선행편향 없음: p2 우측 k봉이 i 이전에 닫혀 있어야
        assert p2 + k <= i, ('lookahead', c.day[p2], c.day[i])
        assert i - p1 <= N, ('lookback', c.day[p1], c.day[i])
        # 3) 상승선 + 각도 제한
        r = slope / c.lo[p1]
        assert c.lo[p2] > c.lo[p1] and c.MIN_SLOPE <= r <= c.MAX_SLOPE, ('slope', r)
        # 4) p1..i 구간 저점 미훼손
        src = c.lo if vm == 'low' else c.cl
        for t in range(p1, i + 1):
            if src[t] < c.line_val((p1, p2, slope), t) - c.EPS:
                bad += 1
                print('훼손 발견', N, k, vm, c.day[i], c.day[t])
        # 5) 신호 조건
        assert c.lo[i] <= L * (1 + zone) + c.EPS and c.cl[i] > L, ('signal', c.day[i])
    print('N=%d k=%d zone=%.0f%% valid=%-5s : 신호 %3d건 전수 검사 통과' % (N, k, zone * 100, vm, len(sigs)))
print('훼손 위반 건수:', bad)

print('\n샘플 상세 (N=60 k=3 zone=1% low) - 앞 3건')
sigs = c.gen_signals(60, 3, 0.01, 'low')
for i, tl in sigs[:3]:
    p1, p2, slope = tl
    print('\n신호일 %s  종가 %.0f  저가 %.0f  추세선값 %.0f  (저가/선 = %+.2f%%)' % (
        c.day[i], c.cl[i], c.lo[i], c.line_val(tl, i), (c.lo[i] / c.line_val(tl, i) - 1) * 100))
    print('  p1 %s 저가 %.0f   p2 %s 저가 %.0f   기울기 %.2f$/일 (%.3f%%/일)' % (
        c.day[p1], c.lo[p1], c.day[p2], c.lo[p2], slope, slope / c.lo[p1] * 100))
    print('  구간 %s~%s 저가와 추세선의 최소 간격: %+.3f%%' % (
        c.day[p1], c.day[i],
        min((c.lo[t] / c.line_val(tl, t) - 1) * 100 for t in range(p1, i + 1))))
    touches = [c.day[t] for t in range(p1, i + 1) if c.lo[t] <= c.line_val(tl, t) * 1.01]
    print('  선 근처(1% 이내) 터치 봉:', ', '.join(touches))
