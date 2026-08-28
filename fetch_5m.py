# -*- coding: utf-8 -*-
# 5m klines are needed because the TP (+1.0%) and SL (-1.478%) are close enough
# that 1h bars cannot tell which was touched first.
import requests, time, csv, sys
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding='utf-8')
BASE = 'https://api.binance.com/api/v3/klines'
start = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

out, cur, n = [], start, 0
with open('btcusdt_5m.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['open_time', 'dt', 'open', 'high', 'low', 'close'])
    while True:
        data = None
        for _ in range(6):
            try:
                r = requests.get(BASE, params={'symbol': 'BTCUSDT', 'interval': '5m',
                                               'startTime': cur, 'limit': 1000}, timeout=30)
                if r.status_code == 200:
                    data = r.json()
                    break
                print('http', r.status_code, r.text[:100])
            except Exception as e:
                print('err', e)
            time.sleep(3)
        if not data:
            break
        for k in data:
            dt = datetime.fromtimestamp(k[0] / 1000, timezone.utc)
            w.writerow([k[0], dt.strftime('%Y-%m-%d %H:%M'), k[1], k[2], k[3], k[4]])
        n += len(data)
        if n % 50000 < 1000:
            print('%d rows, at %s' % (n, datetime.fromtimestamp(
                data[-1][0] / 1000, timezone.utc).strftime('%Y-%m-%d')))
        if len(data) < 1000:
            break
        cur = data[-1][0] + 1
        time.sleep(0.12)
print('DONE %d rows' % n)
