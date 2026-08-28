# -*- coding: utf-8 -*-
# 교차검증용 데이터: {sym}_1d.csv (2017-08~), {sym}_4h.csv (2019-01~), {sym}_5m.csv (2019-01~)
#   usage: python fetch_asset.py ETHUSDT
import sys, time, requests
from fetch_data import save, ms

sys.stdout.reconfigure(encoding='utf-8')
BASE = 'https://api.binance.com/api/v3/klines'


def fetch(symbol, interval, start_ms):
    out, cur = [], start_ms
    while True:
        data = None
        for _ in range(6):
            try:
                r = requests.get(BASE, params={'symbol': symbol, 'interval': interval, 'startTime': cur, 'limit': 1000}, timeout=30)
                if r.status_code == 200:
                    data = r.json()
                    break
                print('  http', r.status_code, r.text[:100])
                time.sleep(5)
            except Exception as e:
                print('  err', e)
                time.sleep(3)
        if data is None:
            raise RuntimeError('fetch failed')
        if not data:
            break
        out.extend(data)
        if len(out) % 100000 < 1000:
            print('  %s %s rows %d' % (symbol, interval, len(out)))
        if len(data) < 1000:
            break
        cur = data[-1][0] + 1
        time.sleep(0.05)
    return out


for symbol in sys.argv[1:]:
    low = symbol.lower()
    t0 = time.time()
    save(fetch(symbol, '1d', ms(2017, 8, 1)), '%s_1d.csv' % low)
    save(fetch(symbol, '4h', ms(2019, 1, 1)), '%s_4h.csv' % low)
    save(fetch(symbol, '5m', ms(2019, 1, 1)), '%s_5m.csv' % low)
    print('%s done in %.0fs' % (symbol, time.time() - t0))
