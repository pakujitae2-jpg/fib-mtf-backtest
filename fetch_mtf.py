# -*- coding: utf-8 -*-
# 다중 타임프레임 백테스트용 장기 데이터: 일봉 2017-08~, 4시간봉 2019-01~, 5분봉 2019-01~2022-12 (2023~는 기존 파일)
import sys
from fetch_data import fetch, save, ms

sys.stdout.reconfigure(encoding='utf-8')

print('== daily 2017 ==')
save(fetch('BTCUSDT', '1d', ms(2017, 8, 17)), 'btcusdt_1d_2017.csv')
print('== 4h 2019 ==')
save(fetch('BTCUSDT', '4h', ms(2019, 1, 1)), 'btcusdt_4h_2019.csv')
print('== 5m 2019-2022 ==')
rows = fetch('BTCUSDT', '5m', ms(2019, 1, 1)) if False else None
# fetch()는 현재까지 받으므로 2022-12-31 까지만 잘라서 저장
import requests, time
BASE = 'https://api.binance.com/api/v3/klines'
END = ms(2023, 1, 1)
out, cur = [], ms(2019, 1, 1)
while cur < END:
    data = None
    for _ in range(6):
        try:
            r = requests.get(BASE, params={'symbol': 'BTCUSDT', 'interval': '5m', 'startTime': cur,
                                           'endTime': END - 1, 'limit': 1000}, timeout=30)
            if r.status_code == 200:
                data = r.json()
                break
            print('  http', r.status_code)
        except Exception as e:
            print('  err', e)
        time.sleep(3)
    if not data:
        break
    out.extend(data)
    if len(out) % 20000 < 1000:
        print('  5m rows', len(out))
    if len(data) < 1000:
        break
    cur = data[-1][0] + 1
    time.sleep(0.15)
save(out, 'btcusdt_5m_2019_2022.csv')
print('done')
