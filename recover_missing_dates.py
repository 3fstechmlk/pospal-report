#!/usr/bin/env python3
"""
One-off recovery script: fetch April 12 and April 14 data for all merchants.
Run on the server: python3 recover_missing_dates.py
"""
import hashlib, json, time, urllib.request, ssl, os
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR    = os.path.join(BASE_DIR, 'data')
CACHE_DIR   = os.path.join(BASE_DIR, 'cache')
MERCHANTS_F = os.path.join(DATA_DIR, 'merchants.json')
SSL_CTX     = ssl._create_unverified_context()

POSPAL      = 'https://area9-win.pospal.cn'
TICKET_PATH = '/pospal-api2/openapi/v1/ticketOpenApi/queryTicketPages'

RECOVER_DATES = ['2026-04-12', '2026-04-14']

def pospal_post(app_key, path, body, host=None):
    compact = json.dumps(body, ensure_ascii=False, separators=(',', ':'))
    sig     = hashlib.md5((app_key + compact).encode()).hexdigest().upper()
    ts      = str(int(time.time() * 1000))
    base    = (host.rstrip('/') if host else POSPAL)
    req     = urllib.request.Request(
        base + path,
        data=compact.encode(),
        headers={'Content-Type': 'application/json', 'time-stamp': ts, 'data-signature': sig},
        method='POST'
    )
    with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
        return json.loads(r.read().decode())

def biz_day_range(bdate_str):
    d   = date.fromisoformat(bdate_str)
    nxt = d + timedelta(days=1)
    return f'{bdate_str} 06:00:00', f'{nxt} 05:59:59'

def fetch_date(merchant, bdate):
    mid     = merchant['id']
    app_id  = merchant.get('appId', '')
    app_key = merchant.get('appKey', '')
    host    = merchant.get('host')
    if not app_key:
        return mid, bdate, None, 'no appKey'

    cache_path = os.path.join(CACHE_DIR, mid, f'{bdate}.json')
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            existing = json.load(f)
        return mid, bdate, len(existing), 'already cached'

    st, et    = biz_day_range(bdate)
    all_t     = []
    post_back = None
    pages     = 0
    try:
        while pages < 100:
            body = {'appId': app_id, 'startTime': st, 'endTime': et}
            if post_back:
                body['postBackParameter'] = post_back
            res = pospal_post(app_key, TICKET_PATH, body, host)
            pages += 1
            if res.get('status') != 'success':
                msgs = res.get('messages', [])
                return mid, bdate, None, f'API error: {msgs}'
            data      = res.get('data', {})
            tickets   = data.get('result', data.get('ticketList', []))
            all_t.extend(tickets)
            post_back = data.get('postBackParameter')
            if not post_back or not post_back.get('parameterValue'):
                break
            time.sleep(0.3)
    except Exception as ex:
        return mid, bdate, None, str(ex)

    os.makedirs(os.path.join(CACHE_DIR, mid), exist_ok=True)
    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(all_t, f, ensure_ascii=False)
    return mid, bdate, len(all_t), 'fetched'

def main():
    with open(MERCHANTS_F) as f:
        merchants = json.load(f)

    active = [m for m in merchants if m.get('appKey') and not m.get('deactivated')]
    print(f'Recovering {RECOVER_DATES} for {len(active)} active merchants...')

    tasks = [(m, d) for m in active for d in RECOVER_DATES]
    ok = skip = fail = 0

    with ThreadPoolExecutor(max_workers=20) as ex:
        futs = {ex.submit(fetch_date, m, d): (m['name'], d) for m, d in tasks}
        for fut in as_completed(futs):
            mid, bdate, count, msg = fut.result()
            name, d = futs[fut]
            if msg == 'already cached':
                skip += 1
            elif count is None:
                fail += 1
                print(f'  FAIL  {name} {bdate}: {msg}')
            else:
                ok += 1
                if count > 0:
                    print(f'  OK    {name} {bdate}: {count} tickets')

    print(f'\nDone. fetched={ok} (new files) skipped={skip} (already had data) failed={fail}')

if __name__ == '__main__':
    main()
