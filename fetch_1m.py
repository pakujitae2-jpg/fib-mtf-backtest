# -*- coding: utf-8 -*-
# With a 0.3% stop, even 5m bars are too coarse to tell a fill from a stop-out.
import requests, time, csv, sys
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding='utf-8')
BASE = 'https://api.binance.com/api/v3/klines'
cur = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

n = 0
with open('btcusdt_1m.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['open_time', 'high', 'low'])
    while True:
        data = None
        for _ in range(6):
            try:
                r = requests.get(BASE, params={'symbol': 'BTCUSDT', 'interval': '1m',
                                               'startTime': cur, 'limit': 1000}, timeout=30)
                if r.status_code == 200:
                    data = r.json()
                    break
                print('http', r.status_code, r.text[:100], flush=True)
                time.sleep(5)
            except Exception as e:
                print('err', e, flush=True)
                time.sleep(3)
        if not data:
            break
        for k in data:
            w.writerow([k[0], k[2], k[3]])
        n += len(data)
        if n % 200000 < 1000:
            print('%d rows, at %s' % (n, datetime.fromtimestamp(
                data[-1][0] / 1000, timezone.utc).strftime('%Y-%m-%d')), flush=True)
        if len(data) < 1000:
            break
        cur = data[-1][0] + 1
        time.sleep(0.08)
print('DONE %d rows' % n)
