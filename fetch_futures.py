# -*- coding: utf-8 -*-
# Binance USDS-M Futures: klines (1d/4h/5m, 2019-09-08~) + historical funding rate
#   -> btcusdt_fut_1d.csv / btcusdt_fut_4h.csv / btcusdt_fut_5m.csv / btcusdt_funding.csv
import sys, time, csv, requests
from fetch_data import save, ms

sys.stdout.reconfigure(encoding='utf-8')
FAPI = 'https://fapi.binance.com/fapi/v1'
SYMBOL = sys.argv[1] if len(sys.argv) > 1 else 'BTCUSDT'
low = SYMBOL.lower()


def get(url, params):
    for _ in range(6):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            print('  http', r.status_code, r.text[:100])
            time.sleep(5)
        except Exception as e:
            print('  err', e)
            time.sleep(3)
    raise RuntimeError('fetch failed')


def klines(interval, start_ms):
    out, cur = [], start_ms
    while True:
        data = get(FAPI + '/klines', {'symbol': SYMBOL, 'interval': interval, 'startTime': cur, 'limit': 1000})
        if not data:
            break
        out.extend(data)
        if len(out) % 100000 < 1000:
            print('  %s %s rows %d' % (SYMBOL, interval, len(out)))
        if len(data) < 1000:
            break
        cur = data[-1][0] + 1
        time.sleep(0.05)
    return out


t0 = time.time()
save(klines('1d', ms(2019, 9, 8)), '%s_fut_1d.csv' % low)
save(klines('4h', ms(2019, 9, 8)), '%s_fut_4h.csv' % low)
# funding history
rows, cur = [], ms(2019, 9, 8)
while True:
    data = get(FAPI + '/fundingRate', {'symbol': SYMBOL, 'startTime': cur, 'limit': 1000})
    if not data:
        break
    rows.extend(data)
    if len(data) < 1000:
        break
    cur = data[-1]['fundingTime'] + 1
    time.sleep(0.1)
with open('%s_funding.csv' % low, 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['funding_time', 'dt', 'rate'])
    for r in rows:
        w.writerow([r['fundingTime'], time.strftime('%Y-%m-%d %H:%M', time.gmtime(r['fundingTime'] / 1000)), r['fundingRate']])
print('funding rows %d' % len(rows))
save(klines('5m', ms(2019, 9, 8)), '%s_fut_5m.csv' % low)
print('%s futures done in %.0fs' % (SYMBOL, time.time() - t0))
