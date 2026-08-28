# Fetch Binance SPOT klines for BTCUSDT and cache to CSV.
import requests, time, csv, os, sys
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding='utf-8')

BASE = 'https://api.binance.com/api/v3/klines'
SYMBOL = 'BTCUSDT'

def ms(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)

def fetch(symbol, interval, start_ms):
    out, cur = [], start_ms
    while True:
        params = {'symbol': symbol, 'interval': interval,
                  'startTime': cur, 'limit': 1000}
        data = None
        for _ in range(6):
            try:
                r = requests.get(BASE, params=params, timeout=30)
                if r.status_code == 200:
                    data = r.json()
                    break
                print('  http', r.status_code, r.text[:120])
            except Exception as e:
                print('  err', e)
            time.sleep(3)
        if data is None:
            raise RuntimeError('fetch failed at %d' % cur)
        if not data:
            break
        out.extend(data)
        print('  %s %s -> %d rows (last %s)' % (
            symbol, interval, len(out),
            datetime.fromtimestamp(data[-1][0] / 1000, timezone.utc).strftime('%Y-%m-%d %H:%M')))
        if len(data) < 1000:
            break
        cur = data[-1][0] + 1
        time.sleep(0.2)
    return out

def save(rows, path):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['open_time', 'dt', 'open', 'high', 'low', 'close', 'volume', 'close_time'])
        for k in rows:
            dt = datetime.fromtimestamp(k[0] / 1000, timezone.utc)
            w.writerow([k[0], dt.strftime('%Y-%m-%d %H:%M'), k[1], k[2], k[3], k[4], k[5], k[6]])
    print('saved %s (%d rows)' % (path, len(rows)))

if __name__ == '__main__':
    print('== daily ==')
    d = fetch(SYMBOL, '1d', ms(2022, 10, 1))
    save(d, 'btcusdt_1d.csv')
    print('== hourly ==')
    h = fetch(SYMBOL, '1h', ms(2023, 1, 1))
    save(h, 'btcusdt_1h.csv')
