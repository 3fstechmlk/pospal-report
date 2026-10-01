#!/usr/bin/env python3
"""
3FS Technology — Pospal Multi-Merchant Sales Report
─────────────────────────────────────────────────────────
Run:   python3 run.py
Merchant portal : http://localhost:8080
Admin portal    : http://localhost:8080/admin
Stop:  Ctrl + C
"""

import hashlib, json, time, urllib.request, ssl, traceback
import os, threading, uuid, signal, io, math
from datetime import datetime as _dt
from datetime import date, timedelta, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

VERSION  = '1.3.1'
SSL_CTX  = ssl._create_unverified_context()
PORT     = int(os.environ.get('PORT') or 8080)   # env override so a local copy can run beside 8080
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUB_DIR  = os.path.join(BASE_DIR, 'public')
DATA_DIR = os.path.join(BASE_DIR, 'data')
CACHE_DIR= os.path.join(BASE_DIR, 'cache')

for _d in (PUB_DIR, DATA_DIR, CACHE_DIR):
    os.makedirs(_d, exist_ok=True)

MERCHANTS_FILE   = os.path.join(DATA_DIR, 'merchants.json')
CONFIG_FILE      = os.path.join(DATA_DIR, 'config.json')
SYNC_STATE_FILE  = os.path.join(DATA_DIR, 'sync_state.json')
PAY_METHODS_FILE = os.path.join(DATA_DIR, 'pay_methods.json')
CUSTOMERS_FILE   = os.path.join(DATA_DIR, 'customers.json')


SYNC_API_LIMIT      = 250   # max sync API calls per merchant per day
BACKFILL_STOP_DAYS  = 30    # consecutive empty days before backfill stops (covers long holidays)
DEACTIVATE_DAYS     = 90    # consecutive recent empty days → deactivate merchant (stop syncing)
SYNC_INTERVAL_SECS  = 3600  # run sync loop every hour
SYNC_WORKERS        = 100   # merchants synced in parallel
TODAY_FETCH_CD_SECS = 1800  # cooldown between live re-fetches of today's data per merchant

# ── Config ─────────────────────────────────────────────────────────────────────
def _load_cfg():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, encoding='utf-8') as f:
            return json.load(f)
    cfg = {'adminPassword': 'admin123'}
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)
    return cfg

CONFIG = _load_cfg()

# ── Workflow pending-setup integration ────────────────────────────────────────
import sqlite3 as _sqlite3

WORKFLOW_DB_PATHS = [
    '/opt/workflow/data/workflow.db',                             # server
    os.path.join(BASE_DIR, '..', 'workflow', 'data', 'workflow.db'),  # local dev
]
PENDING_DISMISSED_FILE = os.path.join(DATA_DIR, 'pending_dismissed.json')

def _workflow_db_path():
    for p in WORKFLOW_DB_PATHS:
        if os.path.exists(p):
            return p
    return None

def _pending_dismissed():
    if os.path.exists(PENDING_DISMISSED_FILE):
        try:
            with open(PENDING_DISMISSED_FILE, encoding='utf-8') as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()

def _pending_dismiss(wf_id, account=None):
    d = _pending_dismissed()
    d.add(str(wf_id))
    if account:
        d.add(account.strip().lower())
    with open(PENDING_DISMISSED_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(d), f)

def _pending_undismiss(account):
    """Remove an account and its workflow wf_id(s) from the dismissed set."""
    if not account:
        return
    acct_lower = account.strip().lower()
    d = _pending_dismissed()
    d.discard(acct_lower)
    db = _workflow_db_path()
    if db:
        try:
            conn = _sqlite3.connect(db)
            rows = conn.execute(
                "SELECT id FROM clients WHERE LOWER(TRIM(account_name)) = ?",
                (acct_lower,)
            ).fetchall()
            conn.close()
            for row in rows:
                d.discard(str(row[0]))
        except Exception:
            pass
    with open(PENDING_DISMISSED_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(d), f)

def fetch_workflow_pending():
    """
    Read clients from workflow SQLite DB that have account_name set,
    are not already in pospal-report merchants, and not dismissed.
    'Done' section is still shown if the merchant hasn't been added yet —
    clients sometimes get marked Done before credentials are entered here.
    Only 'Failed' entries are excluded.
    """
    db = _workflow_db_path()
    if not db:
        return [], False   # (results, db_found)
    dismissed = _pending_dismissed()
    existing  = {m.get('account', '').strip().lower() for m in get_all_merchants()}
    try:
        conn = _sqlite3.connect(db)
        conn.row_factory = _sqlite3.Row
        rows = conn.execute('''
            SELECT id, name, company_name, account_name, section, created_at
            FROM clients
            WHERE TRIM(account_name) != ''
              AND section NOT IN ('Failed')
              AND source = 'form'
            ORDER BY created_at DESC
        ''').fetchall()
        conn.close()
        results = []
        for r in rows:
            wf_id   = str(r['id'])
            account = (r['account_name'] or '').strip()
            if wf_id in dismissed or account.lower() in existing or account.lower() in dismissed:
                continue
            display = (r['company_name'] or r['name'] or '').strip()
            results.append({
                'wf_id'  : wf_id,
                'name'   : display,
                'account': account,
                'section': r['section'] or '',
            })
        return results, True
    except Exception as e:
        print(f'[workflow] fetch_workflow_pending failed: {e}')
        return [], True

# ── Telegram notify + bot handler ──────────────────────────────────────────────
def tg_send(text, chat_id=None):
    """Send a Telegram message. Silently ignores errors."""
    token = CONFIG.get('telegramBotToken', '')
    cid   = chat_id or CONFIG.get('telegramChatId', '')
    if not token or not cid:
        return
    try:
        body = json.dumps({'chat_id': cid, 'text': text, 'parse_mode': 'HTML'}).encode()
        req  = urllib.request.Request(
            f'https://api.telegram.org/bot{token}/sendMessage',
            data=body,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=10, context=SSL_CTX):
            pass
    except Exception:
        pass

def _tg_status_text():
    """Build sync status message."""
    ms       = get_all_merchants()
    active   = [m for m in ms if not m.get('deactivated')]
    s        = _sync_state_mem
    today    = str(date.today())

    synced_today   = sum(1 for v in s.values() if v.get('last_daily_sync_date') == today)
    bf_active      = sum(1 for v in s.values()
                         if not v.get('deactivated') and not v.get('backfill_completed'))
    bf_done        = sum(1 for v in s.values()
                         if not v.get('deactivated') and v.get('backfill_completed'))
    quota_used_avg = 0
    quota_cnt      = 0
    for v in s.values():
        if v.get('api_calls_reset_date') == today and v.get('api_calls_total_today', 0) > 0:
            quota_used_avg += v['api_calls_total_today']
            quota_cnt += 1
    avg_str = f'{quota_used_avg // quota_cnt}' if quota_cnt else 'N/A'

    myt_now  = datetime.utcnow() + timedelta(hours=8)
    nxt_secs = _secs_until_next_sync()
    nh, nm   = divmod(int(nxt_secs) // 60, 60)

    total_active = len(active)
    if synced_today == 0:
        sync_line = f'Today\'s sync: not run yet'
    elif synced_today >= total_active:
        sync_line = f'Today\'s sync: {synced_today} / {total_active} ✅'
    else:
        sync_line = f'Today\'s sync: {synced_today} / {total_active} (in progress…)'

    return (
        f'📊 <b>Pospal Sync Status</b>\n'
        f'🕐 {myt_now.strftime("%Y-%m-%d %H:%M MYT")}\n\n'
        f'Merchants active: {total_active}\n'
        f'{sync_line}\n'
        f'Backfill active: {bf_active}\n'
        f'Backfill done: {bf_done}\n'
        f'Avg API calls today: {avg_str}/250\n\n'
        f'⏰ Next sync in {nh}h {nm}m ({SYNC_HOUR:02d}:00 MYT)'
    )

_tg_last_update_id = 0

def start_tg_bot():
    """Background thread: long-poll Telegram for commands."""
    token   = CONFIG.get('telegramBotToken', '')
    allowed = CONFIG.get('telegramChatId', '')
    if not token or not allowed:
        return

    def _loop():
        global _tg_last_update_id
        print('  [telegram] bot polling started')
        while True:
            try:
                url  = (f'https://api.telegram.org/bot{token}/getUpdates'
                        f'?timeout=30&offset={_tg_last_update_id + 1}')
                req  = urllib.request.Request(url, method='GET')
                with urllib.request.urlopen(req, timeout=35, context=SSL_CTX) as r:
                    data = json.loads(r.read().decode())
                for upd in data.get('result', []):
                    _tg_last_update_id = upd['update_id']
                    msg  = upd.get('message', {})
                    cid  = str(msg.get('chat', {}).get('id', ''))
                    text = (msg.get('text') or '').strip().lower().split()[0] if msg.get('text') else ''
                    if cid != allowed:
                        continue
                    if text in ('/status', '/sync_status'):
                        tg_send(_tg_status_text(), chat_id=cid)
                    elif text == '/help':
                        tg_send(
                            '🤖 <b>Pospal Bot Commands</b>\n\n'
                            '/status — sync status & next run time\n'
                            '/help — show this help',
                            chat_id=cid
                        )
            except Exception:
                time.sleep(5)

    threading.Thread(target=_loop, daemon=True).start()

# ── Password helpers ───────────────────────────────────────────────────────────
def hash_pw(pw):
    return hashlib.sha256(str(pw).encode()).hexdigest()

DEFAULT_PW = hash_pw('123456')

# ── Merchant CRUD ──────────────────────────────────────────────────────────────
_m_lock = threading.Lock()

# Temp PNG store: token -> (filename, png_bytes, expire_epoch)
import base64 as _b64mod
_tmp_png      = {}
_tmp_png_lock = threading.Lock()

def _store_tmp_png(filename, png_bytes, ttl=120):
    token = uuid.uuid4().hex
    with _tmp_png_lock:
        _tmp_png[token] = (filename, png_bytes, time.time() + ttl)
        # Purge expired entries
        now = time.time()
        expired = [k for k, v in _tmp_png.items() if now > v[2]]
        for k in expired:
            del _tmp_png[k]
    return token

def _fetch_tmp_png(token):
    with _tmp_png_lock:
        entry = _tmp_png.pop(token, None)
    if entry is None:
        return None, None
    filename, png_bytes, expire = entry
    if time.time() > expire:
        return None, None
    return filename, png_bytes

# Temp Invoice store: token -> (html_content, expire_epoch) — 24h TTL
_tmp_inv      = {}
_tmp_inv_lock = threading.Lock()

def _store_tmp_inv(html_content, ttl=86400):
    token = uuid.uuid4().hex
    with _tmp_inv_lock:
        _tmp_inv[token] = (html_content, time.time() + ttl)
        now = time.time()
        expired = [k for k, v in _tmp_inv.items() if now > v[1]]
        for k in expired:
            del _tmp_inv[k]
    return token

def _fetch_tmp_inv(token):
    with _tmp_inv_lock:
        entry = _tmp_inv.get(token)
    if entry is None:
        return None
    html_content, expire = entry
    if time.time() > expire:
        with _tmp_inv_lock:
            _tmp_inv.pop(token, None)
        return None
    return html_content

# ── Invoice template settings (data/inv_settings_<mid>.json) ──────────────────
INV_TEXT_FIELDS = {'name', 'ssm', 'sst', 'addr1', 'addr2', 'post', 'city', 'state',
                   'phone', 'email', 'footer', 'logo_url', 'accent', 'title'}
INV_BOOL_FIELDS = {'show_member', 'show_cashier', 'show_table', 'show_discount',
                   'show_payment', 'show_subtotal'}
INV_BLOCK_TYPES = {'header', 'meta', 'items', 'totals', 'payment', 'footer',
                   'text', 'divider', 'spacer'}

def _sanitize_inv_el(v):
    """Validate per-element overrides {key: {text, size, bold, italic, color, family}}."""
    if not isinstance(v, dict):
        return None
    out = {}
    for k, o in list(v.items())[:120]:
        if not isinstance(o, dict):
            continue
        e = {}
        for f, val in o.items():
            if f == 'text':
                e['text'] = str(val)[:1000]
            elif f in ('bold', 'italic'):
                e[f] = bool(val)
            elif f == 'size':
                try:
                    e['size'] = max(6.0, min(60.0, float(val)))
                except (TypeError, ValueError):
                    pass
            elif f == 'color':
                e['color'] = str(val)[:20]
            elif f == 'family' and val in ('serif', 'mono'):
                e['family'] = val
        if e:
            out[str(k)[:40]] = e
    return out

def _sanitize_inv_blocks(v):
    """Validate the block-based template layout posted by the admin editor."""
    if not isinstance(v, list):
        return None
    out = []
    for b in v[:40]:
        if not isinstance(b, dict) or b.get('type') not in INV_BLOCK_TYPES:
            continue
        opts = {}
        for k, val in list((b.get('opts') or {}).items())[:20]:
            k = str(k)[:30]
            if isinstance(val, bool):
                opts[k] = val
            elif isinstance(val, (int, float)):
                opts[k] = val
            else:
                opts[k] = str(val)[:2000]
        out.append({'id': str(b.get('id', ''))[:20], 'type': b['type'],
                    'show': bool(b.get('show', True)), 'opts': opts})
    return out

def _load_inv_settings(mid):
    fpath = os.path.join(DATA_DIR, f'inv_settings_{mid}.json')
    if os.path.exists(fpath):
        try:
            with open(fpath, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_inv_settings(mid, body):
    """Sanitize posted fields and merge into the existing settings file, so a
    partial save (e.g. merchant info-only form) never wipes other fields."""
    settings = _load_inv_settings(mid)
    for k, v in body.items():
        if k in INV_TEXT_FIELDS:
            settings[k] = str(v)[:500]
        elif k in INV_BOOL_FIELDS:
            settings[k] = bool(v)
        elif k == 'blocks':
            blocks = _sanitize_inv_blocks(v)
            if blocks is not None:
                settings['blocks'] = blocks
        elif k == 'el':
            el = _sanitize_inv_el(v)
            if el is not None:
                settings['el'] = el
    fpath = os.path.join(DATA_DIR, f'inv_settings_{mid}.json')
    with open(fpath, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
    return settings

def _load_ms():
    if os.path.exists(MERCHANTS_FILE):
        with open(MERCHANTS_FILE, encoding='utf-8') as f:
            return json.load(f)
    return []

def _save_ms(ms):
    tmp = MERCHANTS_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(ms, f, indent=2, ensure_ascii=False)
    os.replace(tmp, MERCHANTS_FILE)   # atomic rename — prevents partial-write corruption

def get_all_merchants():
    with _m_lock:
        return _load_ms()

def get_merchant(mid):
    for m in get_all_merchants():
        if m['id'] == mid:
            return m
    return None

def get_merchant_by_account(account):
    for m in get_all_merchants():
        if m.get('account', '').lower() == account.lower():
            return m
    return None

def get_merchant_by_id(mid):
    for m in get_all_merchants():
        if m.get('id') == mid:
            return m
    return None

def add_merchant(name, account, app_id, app_key, password=None, debtor_code='', day_start_hour=6):
    with _m_lock:
        ms = _load_ms()
        m  = {
            'id'           : str(uuid.uuid4()),
            'name'         : name,
            'account'      : account,
            'password'     : hash_pw(password) if password else DEFAULT_PW,
            'debtorCode'   : debtor_code,
            'appId'        : app_id,
            'appKey'       : app_key,
            'dayStartHour' : int(day_start_hour),
        }
        ms.append(m)
        _save_ms(ms)
    # Initialize sync state and kick off first sync in background
    init_sync_state(m['id'])
    trigger_sync_for(m)
    return m

def update_merchant(mid, name, account, app_id, app_key, debtor_code=None, day_start_hour=None, member_portal=None, join_member=None):
    with _m_lock:
        ms = _load_ms()
        for m in ms:
            if m['id'] == mid:
                m['name']    = name
                m['account'] = account
                m['appId']   = app_id
                if app_key:          # empty = keep existing key
                    m['appKey'] = app_key
                if debtor_code is not None:
                    m['debtorCode'] = debtor_code
                if day_start_hour is not None:
                    m['dayStartHour'] = int(day_start_hour)
                if member_portal is not None:
                    m['member_portal'] = bool(member_portal)
                if join_member is not None:
                    m['join_member'] = bool(join_member)
                _save_ms(ms)
                return m
    return None

def reset_merchant_password(mid, new_password='123456'):
    with _m_lock:
        ms = _load_ms()
        for m in ms:
            if m['id'] == mid:
                m['password'] = hash_pw(new_password)
                _save_ms(ms)
                return True
    return False

def delete_merchant(mid):
    with _m_lock:
        ms  = _load_ms()
        new = [m for m in ms if m['id'] != mid]
        if len(new) == len(ms):
            return False
        deleted = next((m for m in ms if m['id'] == mid), None)
        _save_ms(new)
    if deleted and deleted.get('account'):
        _pending_undismiss(deleted['account'])
    return True

# ── Admin sessions ─────────────────────────────────────────────────────────────
_admin_sessions = set()
_as_lock        = threading.Lock()

def new_admin_session():
    t = str(uuid.uuid4())
    with _as_lock: _admin_sessions.add(t)
    return t

def check_admin_session(t):
    with _as_lock: return bool(t) and t in _admin_sessions

# ── Merchant sessions ──────────────────────────────────────────────────────────
_merch_sessions = {}   # token → merchant_id
_ms_sess_lock   = threading.Lock()

def new_merch_session(mid):
    t = str(uuid.uuid4())
    with _ms_sess_lock: _merch_sessions[t] = mid
    return t

def check_merch_session(t):
    with _ms_sess_lock: return _merch_sessions.get(t) if t else None

# ── Business day helpers ───────────────────────────────────────────────────────
# Sync always uses 06:00 – next day 05:59 (MYT, UTC+8) regardless of merchant.
# Per-merchant dayStartHour only affects report aggregation (see collect_day_tickets).
# Server runs UTC — always convert to MYT before checking the cutoff hour.
def current_business_date(start_hour=6):
    now_myt = datetime.utcnow() + timedelta(hours=8)
    d       = now_myt.date()
    if start_hour == 0:
        return d  # midnight boundary — always current calendar day
    return d if now_myt.hour >= start_hour else d - timedelta(days=1)

def biz_day_range(bdate_str):
    """Return (startTime, endTime) for sync — always 06:00 to next-day 05:59."""
    d   = date.fromisoformat(bdate_str)
    nxt = d + timedelta(days=1)
    return f'{bdate_str} 06:00:00', f'{nxt} 05:59:59'

# ── Pospal API ─────────────────────────────────────────────────────────────────
POSPAL          = 'https://area9-win.pospal.cn'
TICKET_PATH     = '/pospal-api2/openapi/v1/ticketOpenApi/queryTicketPages'
QUOTA_PATH      = '/pospal-api2/openapi/v1/openApiLimitAccess/queryDailyAccessTimesLog'
PAY_METHOD_PATH = '/pospal-api2/openapi/v1/ticketOpenApi/queryMyPayMethod'

_api_calls = {}
_api_lock  = threading.Lock()

def _count_call(mid):
    """Count every API call (sync + report pages). Persists via sync state so count survives restart."""
    with _api_lock:
        _api_calls[mid] = _api_calls.get(mid, 0) + 1
    # Also persist in sync state so the count survives a restart
    global _sync_state_dirty
    today = str(date.today())
    with _sync_state_lock:
        s = _sync_state_mem.setdefault(mid, {})
        # Reset if it's a new day
        if s.get('api_calls_reset_date') != today:
            s['api_calls_total_today'] = 0
            s['api_calls_reset_date']  = today
        s['api_calls_total_today'] = s.get('api_calls_total_today', 0) + 1
        _sync_state_dirty = True

# ── Pospal real quota (cached 5 min per merchant) ──────────────────────────────
_quota_cache = {}   # {mid: {'used': int, 'limit': int, 'left': int, 'ts': float}}
_qc_lock     = threading.Lock()

def _invalidate_quota_cache(mid):
    """Mark the reading as due for a refresh without discarding it.

    Re-reading costs a call (queryDailyAccessTimesLog counts against the same
    limit), so the old number has to survive: it is the baseline quota_snapshot()
    adds this app's own calls onto.  Only the timestamp is cleared, which is what
    lets the next explicit refresh through the 5-minute throttle."""
    with _qc_lock:
        c = _quota_cache.get(mid)
        if c:
            c['ts'] = 0

def _invalidate_stats_cache(mid):
    with _stats_lock:
        _stats_cache.pop(mid, None)

def fetch_pospal_quota(merchant):
    mid = merchant['id']
    now = time.time()
    with _qc_lock:
        c = _quota_cache.get(mid)
        if c and now - c['ts'] < 300:   # 5-min cache
            return c

    today = str(date.today())
    try:
        _count_call(mid)   # this very query counts against the merchant's daily limit
        res   = pospal_post(merchant['appId'], merchant['appKey'], QUOTA_PATH,
                            {'appId': merchant['appId'],
                             'beginDate': today, 'endDate': today},
                            host=merchant.get('host'))
        items = res.get('data') or []
        if isinstance(items, list) and items:
            row   = items[0]
            used  = int(row.get('haveAcessTimes', 0))
            limit = int(row.get('limitTimes', 300))
        else:
            used, limit = 0, 300
        with _api_lock:
            local_now = _api_calls.get(mid, 0)
        result = {'used': used, 'limit': limit, 'left': max(0, limit - used), 'ts': now,
                  # date: Pospal's counter resets at midnight, so a reading from
                  # yesterday is not a usable baseline.
                  # local_at_read: this app's own call counter at the moment of the
                  # reading -- the difference from it is what has been spent since.
                  'date': today, 'local_at_read': local_now}
        with _qc_lock:
            _quota_cache[mid] = result
        return result
    except Exception as ex:
        print(f'  [quota] {merchant.get("name","?")} error: {ex}')
        return None

def quota_snapshot(mid):
    """Best estimate of the merchant's Pospal quota use, costing no API call.

    Only Pospal knows the true figure, and asking for it spends a call, so the last
    reading is treated as a baseline and this app's own calls since then are added
    on top.  The estimate is a floor: calls made by anything else sharing the appId
    (the member portal, other tools) land in Pospal's count but not in ours, so the
    real number can only be higher.  Returns None when no reading from today exists
    to build on -- the caller then has nothing but its own counter to show.
    """
    with _qc_lock:
        c    = _quota_cache.get(mid)
        base = dict(c) if c and c.get('date') == str(date.today()) else None
    if not base:
        return None
    with _api_lock:
        local_now = _api_calls.get(mid, 0)
    since = max(0, local_now - base.get('local_at_read', local_now))
    est   = base['used'] + since
    return {'estUsed': est, 'limit': base['limit'], 'estLeft': max(0, base['limit'] - est),
            'baseUsed': base['used'], 'baseTs': base['ts'], 'sinceBase': since}

QUOTA_LOG_MAX_DAYS = 7   # Pospal rejects the query when endDate-beginDate > 7

def fetch_pospal_quota_log(merchant, days=QUOTA_LOG_MAX_DAYS):
    """Last `days` days of API usage, fetched from Pospal in ONE call.

    Costs exactly 1 API call no matter how many days are asked for, and the row
    for today doubles as a live quota reading. Deliberately NOT cached — this
    only runs when an admin clicks Refresh, so a stale answer would defeat the
    point. Raises on a Pospal-level error.
    """
    days  = max(1, min(int(days), QUOTA_LOG_MAX_DAYS))
    end   = date.today()
    begin = end - timedelta(days=days - 1)
    _count_call(merchant['id'])
    res = pospal_post(merchant['appId'], merchant['appKey'], QUOTA_PATH,
                      {'appId'    : merchant['appId'],
                       'beginDate': str(begin), 'endDate': str(end)},
                      host=merchant.get('host'))
    if str(res.get('status', '')).lower() != 'success':
        msgs = res.get('messages') or []
        raise RuntimeError(msgs[0] if msgs else 'Pospal returned an error')

    raw  = res.get('data') or []
    mine = str(merchant['appId'] or '').upper()
    # Pospal answers with one row per appId in the merchant's CHAIN, not just the
    # one we authenticated with — a Butter & Olive query comes back with all 8
    # outlets. Resolve each foreign appId against merchants.json so the UI can
    # name the outlet instead of showing a bare hex string; anything that does
    # not resolve is genuinely someone else's application.
    known = {}
    for m in get_all_merchants():
        a = str(m.get('appId') or '').upper()
        if a:
            known[a] = m

    by_date, mine_rows   = {}, 0
    chain_ids, chain_use = set(), 0     # sibling outlets — our own sync, not noise worth listing
    for r in raw:
        d    = r.get('accessDate')
        used = int(r.get('haveAcessTimes', 0) or 0)
        lim  = int(r.get('limitTimes', 300) or 300)
        aid  = str(r.get('appId') or '')
        slot = by_date.setdefault(d, {'date': d, 'used': 0, 'limit': lim,
                                      'others': [], 'otherUsed': 0})
        if mine and aid.upper() != mine:
            if aid.upper() in known:
                # A sibling outlet of the same chain. It is this project syncing
                # another store, so it tells you nothing about THIS merchant's
                # usage — count it for context only, never list it.
                chain_ids.add(aid.upper())
                chain_use += used
            else:
                # Genuinely someone else's application on this merchant.
                slot['others'].append({'appId': aid, 'used': used})
                slot['otherUsed'] += used
        else:
            slot['used']  = used
            slot['limit'] = lim
            mine_rows    += 1

    if not mine_rows and raw:
        # Defensive: our appId matched nothing (unexpected casing or format).
        # Show every row as ours rather than a page of zeros.
        by_date, chain_ids, chain_use = {}, set(), 0
        for r in raw:
            d = r.get('accessDate')
            by_date[d] = {'date'  : d,
                          'used'  : int(r.get('haveAcessTimes', 0) or 0),
                          'limit' : int(r.get('limitTimes', 300) or 300),
                          'others': [], 'otherUsed': 0}

    rows = sorted(by_date.values(), key=lambda r: r['date'] or '')
    info = {'externalRows' : sum(len(r['others']) for r in rows),
            'chainOutlets' : len(chain_ids),
            'chainUsed'    : chain_use}
    return rows, info

# ── Payment method name cache (per merchant, permanent until server restart) ────
_pay_methods       = {}   # {mid: {code: name}}
_pm_lock           = threading.Lock()
_pm_disk_lock      = threading.Lock()
_pm_refresh_dates  = {}   # {mid: 'YYYY-MM-DD'} — track last force-refresh date

def _load_pay_methods_from_disk():
    try:
        with open(PAY_METHODS_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def _save_pay_methods_to_disk():
    with _pm_disk_lock:
        with _pm_lock:
            snapshot = dict(_pay_methods)
        tmp = PAY_METHODS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PAY_METHODS_FILE)   # atomic rename — prevents partial-write corruption

# Fixed overrides for codes whose meaning is consistent across all Malaysian merchants.
# payCode numbers that vary per-merchant are NOT listed here — their names are
# translated from Chinese via CHINESE_PAY_NAMES below instead.
KNOWN_PAY_CODES = {
    'payCode_1'  : 'Cash',
    'payCode_2'  : 'Card',
    'payCode_101': 'TNG',
    'payCode_102': 'Boost',
    'payCode_103': 'GrabPay',
    'payCode_104': 'ShopeePay',
    'payCode_105': 'DuitNow QR',
    'payCode_106': 'MAE',
}

# Chinese payment method name → English translation.
# Applied to any API-returned name that contains Chinese characters.
CHINESE_PAY_NAMES = {
    '现金'      : 'Cash',
    '刷卡'      : 'Card',
    '信用卡'    : 'Credit Card',
    '借记卡'    : 'Debit Card',
    '退换货'    : 'Returns',
    '积分抵现'  : 'Points Redemption',
    '积分兑换'  : 'Points Redemption',
    '会员余额'  : 'Member Balance',
    '会员卡'    : 'Member Card',
    '储值卡'    : 'Stored Value Card',
    '代金券'    : 'Voucher',
    '优惠券'    : 'Coupon',
    '微信支付'  : 'WeChatPay',
    '支付宝'    : 'Alipay',
    '银联支付'  : 'UnionPay',
    '银联'      : 'UnionPay',
    '银行转账'  : 'Bank Transfer',
    '网上银行'  : 'Online Banking',
    '扫码付'    : 'QR Pay',
    '挂账'      : 'Credit Account',
    '赊账'      : 'Credit Account',
    '记账'      : 'Tab',
    '外卖平台'  : 'Delivery Platform',
    '免单'      : 'Complimentary',
    '赠送'      : 'Gift',
    '员工餐'    : 'Staff Meal',
    '折扣'      : 'Discount',
}

def _is_chinese(s):
    return any('\u4e00' <= c <= '\u9fff' for c in (s or ''))

def _translate_pay_name(name):
    """Translate Chinese payment method names to English. Pass through non-Chinese names."""
    if not _is_chinese(name):
        return name
    # Exact match first
    if name in CHINESE_PAY_NAMES:
        return CHINESE_PAY_NAMES[name]
    # Partial match (e.g. "微信支付(小程序)" → WeChatPay)
    for zh, en in CHINESE_PAY_NAMES.items():
        if zh in name:
            return en
    # No match — return as-is (admin will see the Chinese name)
    return name

def fetch_pay_methods(merchant, force=False):
    mid = merchant['id']
    with _pm_lock:
        if not force and mid in _pay_methods:
            return _pay_methods[mid]
    try:
        app_id  = merchant['appId']
        app_key = merchant['appKey']
        host    = merchant.get('host')

        # Step 1: queryAllPayMethod — all system-level codes with names (no date filter)
        _count_call(mid)
        res_all  = pospal_post(app_id, app_key,
                               '/pospal-api2/openapi/v1/ticketOpenApi/queryAllPayMethod',
                               {'appId': app_id}, host=host)
        # Step 2: queryMyPayMethod — merchant-configured codes with custom showName
        _count_call(mid)
        res_mine = pospal_post(app_id, app_key,
                               '/pospal-api2/openapi/v1/ticketOpenApi/queryMyPayMethod',
                               {'appId': app_id}, host=host)

        # Priority (lowest → highest): KNOWN_PAY_CODES → queryAllPayMethod → queryMyPayMethod showName → payOverrides
        m = dict(KNOWN_PAY_CODES)
        for d in (res_all.get('data') or []):
            code = d.get('code')
            name = d.get('showName') or d.get('name')
            if code and name:
                m[code] = _translate_pay_name(name)
        for d in (res_mine.get('data') or []):
            code = d.get('code')
            name = d.get('showName') or d.get('name')
            if code and name:
                m[code] = _translate_pay_name(name)
        m.update(merchant.get('payOverrides') or {})

        with _pm_lock:
            _pay_methods[mid] = m
        _save_pay_methods_to_disk()
        total = len(res_all.get('data') or []) + len(res_mine.get('data') or [])
        print(f'  [pay_methods] {merchant.get("name","?")} fetched {total} methods total')
        return m
    except Exception as ex:
        print(f'  [pay_methods] {merchant.get("name","?")} error: {ex}, using disk/fallback')
        with _pm_lock:
            if mid in _pay_methods:
                return _pay_methods[mid]
        m = {**KNOWN_PAY_CODES, **(merchant.get('payOverrides') or {})}
        with _pm_lock:
            _pay_methods[mid] = m
        return m

def refresh_pay_methods_daily(merchant):
    """Force-refresh pay methods once per calendar day per merchant.
    Uses sync_state for persistence so restarts don't trigger duplicate fetches."""
    mid   = merchant['id']
    today = str(date.today())
    # Check in-memory cache first (fastest)
    if _pm_refresh_dates.get(mid) == today:
        return
    # Check persisted sync_state (survives restarts)
    st = get_sync_state(mid) or {}
    if st.get('pm_refresh_date') == today:
        _pm_refresh_dates[mid] = today  # warm up memory cache
        return
    fetch_pay_methods(merchant, force=True)
    _pm_refresh_dates[mid] = today
    # Persist to sync_state so next restart knows we already fetched today
    st['pm_refresh_date'] = today
    update_sync_state(mid, st)

def pay_name(code, methods):
    n = methods.get(code) or KNOWN_PAY_CODES.get(code) or code
    return _translate_pay_name(n)

def pospal_post(app_id, app_key, path, body, host=None):
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

# ── Customer (member) cache ────────────────────────────────────────────────────
# Tickets carry only customerUid, so member names need a separate API call — one
# per member.  Names are cached on disk so a member looked up once never costs
# quota again; point/balance do change, so records keep their fetch time and the
# caller decides how stale is acceptable.
CUSTOMER_PATH   = '/pospal-api2/openapi/v1/customerOpenApi/queryByUid'
CUSTOMER_FIELDS = ('name', 'phone', 'point', 'balance', 'number')
CUST_NAME_TTL   = 30 * 86400   # orders table: a month-old name is fine
CUST_FRESH_TTL  = 300          # invoice print: re-fetch point/balance if older
CUST_MAX_FETCH  = 60           # cap on members fetched per browser request

_customers      = {}   # {mid: {uid_str: {name, phone, point, balance, number, ts}}}
_cust_lock      = threading.Lock()
_cust_disk_lock = threading.Lock()

def _load_customers_from_disk():
    try:
        with open(CUSTOMERS_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def _save_customers_to_disk():
    with _cust_disk_lock:
        with _cust_lock:
            snapshot = {mid: dict(c) for mid, c in _customers.items()}
        tmp = CUSTOMERS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, ensure_ascii=False)
        os.replace(tmp, CUSTOMERS_FILE)   # atomic rename — prevents partial-write corruption

def cached_customer(mid, uid, max_age):
    """Cached record for one member, or None if unknown or staler than max_age."""
    with _cust_lock:
        c = _customers.get(mid, {}).get(str(uid))
    return c if c and time.time() - c.get('ts', 0) < max_age else None

def get_customers(merchant, uids, max_age):
    """{uid_str: record} for uids, fetching whatever is missing or too stale.
    One API call per fetched member; members that fail are left out."""
    mid       = merchant['id']
    out, todo = {}, []
    for u in {str(u) for u in uids}:
        c = cached_customer(mid, u, max_age)
        if c is not None: out[u] = c
        else:             todo.append(u)
    if not todo:
        return out

    def fetch_one(u):
        try:
            _count_call(mid)
            res = pospal_post(merchant['appId'], merchant['appKey'], CUSTOMER_PATH,
                              {'appId': merchant['appId'], 'customerUid': int(u)},
                              host=merchant.get('host'))
            if res.get('status') == 'success':
                d   = res.get('data') or {}
                rec = {k: d.get(k) for k in CUSTOMER_FIELDS}
                rec['ts'] = time.time()
                return u, rec   # a deleted member yields a blank record — cached, so we stop asking
        except Exception as ex:
            print(f'  [customer] {merchant.get("name","?")} uid {u}: {ex}')
        return u, None          # transient failure — leave uncached so the next request retries

    with ThreadPoolExecutor(max_workers=8) as ex:
        fetched = [r for r in ex.map(fetch_one, todo[:CUST_MAX_FETCH]) if r[1] is not None]
    if fetched:
        with _cust_lock:
            _customers.setdefault(mid, {}).update(dict(fetched))
        _save_customers_to_disk()
        out.update(dict(fetched))
    return out

# ── Per-merchant cache ─────────────────────────────────────────────────────────
_mem    = {}
_mem_ts = {}   # {mid: {bdate: epoch}} — when today's data was last fetched (cooldown)
_c_lock = threading.Lock()

def _cpath(mid, d):
    p = os.path.join(CACHE_DIR, mid)
    os.makedirs(p, exist_ok=True)
    return os.path.join(p, f'{d}.json')

def _from_disk(mid, d):
    p = _cpath(mid, d)
    if os.path.exists(p):
        try:
            with open(p, encoding='utf-8') as f: return json.load(f)
        except: pass
    return None

def _to_disk(mid, d, tickets):
    with open(_cpath(mid, d), 'w', encoding='utf-8') as f:
        json.dump(tickets, f, ensure_ascii=False)

def cached_count(mid):
    p = os.path.join(CACHE_DIR, mid)
    if not os.path.exists(p): return 0
    return len([f for f in os.listdir(p) if f.endswith('.json')])

# ── Activity stats (cached 5 min) ──────────────────────────────────────────────
_stats_cache = {}   # {mid: {'data': {...}, 'ts': float}}
_stats_lock  = threading.Lock()

def merchant_activity_stats(merchant):
    """Consecutive empty days + current-month total sales from disk cache."""
    mid       = merchant['id']
    now       = time.time()
    with _stats_lock:
        c = _stats_cache.get(mid)
        if c and now - c['ts'] < 300:
            return c['data']

    cache_dir = os.path.join(CACHE_DIR, mid)
    today_d   = date.today()
    yesterday = today_d - timedelta(days=1)
    cur_month = today_d.strftime('%Y-%m')

    # Consecutive empty days from yesterday backwards (stop at first day with sales or uncached)
    consecutive_empty = 0
    for i in range(35):
        ds = str(yesterday - timedelta(days=i))
        p  = os.path.join(cache_dir, ds + '.json')
        if not os.path.exists(p):
            break
        try:
            with open(p, encoding='utf-8') as f:
                tickets = json.load(f)
        except Exception:
            break
        valid = [t for t in tickets if int(t.get('invalid', 0) or 0) == 0]
        if not valid:
            consecutive_empty += 1
        else:
            break

    # Current month total sales from all cached files for this month
    month_sales = 0.0
    if os.path.exists(cache_dir):
        for fname in os.listdir(cache_dir):
            if not fname.startswith(cur_month) or not fname.endswith('.json'):
                continue
            try:
                with open(os.path.join(cache_dir, fname), encoding='utf-8') as f:
                    tickets = json.load(f)
                for t in tickets:
                    if int(t.get('invalid', 0) or 0) != 0:
                        continue
                    sign = -1 if (t.get('ticketType') or '').upper() == 'SELL_RETURN' else 1
                    month_sales += float(t.get('totalAmount', 0) or 0) * sign
            except Exception:
                pass

    sync_s = get_sync_state(mid)
    status = ('deactivated' if sync_s.get('deactivated')
              else 'inactive_30' if consecutive_empty >= 30
              else 'inactive_10' if consecutive_empty >= 10
              else 'active')

    result = {
        'mid': mid,
        'consecutive_empty_days': consecutive_empty,
        'status': status,
        'month_sales': round(month_sales, 2),
    }
    with _stats_lock:
        _stats_cache[mid] = {'data': result, 'ts': now}
    return result

def fetch_tickets(merchant, bdate, cache_only=False, force=False):
    """Fetch tickets for one business date.
    cache_only=True: return [] instead of hitting Pospal API if date is not cached.
                     Used by report endpoints to avoid consuming sync quota.
    force=True:      ignore whatever is cached and re-fetch from the API.  The cache
                     is overwritten only once the call succeeds, so a failed re-fetch
                     leaves the existing copy intact (the daily sync relies on this).

    Memory strategy: only today's (current business date) data is kept in _mem,
    because it hasn't been written to disk yet.  All other dates are read from
    disk on demand and never loaded into _mem, to prevent OOM during full syncs.
    """
    mid   = merchant['id']
    today = str(current_business_date())

    # A business day that hasn't started yet cannot have tickets, and querying it
    # returns an empty page that must never reach the disk: _to_disk below only
    # asks "is this today?", so a future date used to land in the historical
    # branch and get cached as [].  On the day itself _from_disk then served that
    # [] (an empty list is not None), returning before the live fetch was ever
    # reached -- a full day of sales read as zero until the next 06:00 sync
    # force-refetched it as "yesterday".  Bailing out here also stops a future
    # date from spending a call per day on guaranteed-empty pages.
    if bdate > today:
        return []

    # Only use _mem for today's incomplete data (not yet on disk).
    # A fetched copy is served for TODAY_FETCH_CD_SECS before the API is hit
    # again, so repeated report views can't burn quota all day.
    stale = None
    if bdate == today:
        with _c_lock:
            stale = _mem.get(mid, {}).get(bdate)
            ts    = _mem_ts.get(mid, {}).get(bdate, 0)
        if stale is not None and not force and (cache_only or time.time() - ts < TODAY_FETCH_CD_SECS):
            return stale

    # For all other dates, always read from disk — never cache in _mem
    on_disk = _from_disk(mid, bdate)
    if on_disk is not None and not force:
        return on_disk

    if cache_only:
        return []   # not yet synced — skip API call to preserve quota

    all_t = []; post_back = None; pages = 0
    st, et = biz_day_range(bdate)
    try:
        while pages < 100:   # safety: max 100 pages (~10,000 tickets) per day
            body = {'appId': merchant['appId'], 'startTime': st, 'endTime': et}
            if post_back: body['postBackParameter'] = post_back
            _count_call(mid)
            pages += 1
            res = pospal_post(merchant['appId'], merchant['appKey'], TICKET_PATH, body,
                              host=merchant.get('host'))
            if res.get('status') != 'success':
                msgs = res.get('messages', [])
                raise RuntimeError(f"[{merchant['name']} {bdate}] " +
                                   ', '.join(str(m) for m in (msgs or ['API error'])))
            data      = res.get('data', {})
            tickets   = data.get('result', data.get('ticketList', []))
            all_t.extend(tickets)
            post_back = data.get('postBackParameter')
            if not post_back or not post_back.get('parameterValue'): break
            time.sleep(0.5)
        else:
            print(f'  [sync] {merchant["name"]} {bdate} hit 100-page limit ({len(all_t)} tickets)')
    except Exception:
        if stale is not None:
            return stale   # API failed — keep serving the last fetched copy of today
        raise

    if bdate == today:
        # Today's data is incomplete (day still running) — keep in memory only
        with _c_lock:
            _mem.setdefault(mid, {})[bdate] = all_t
            _mem_ts.setdefault(mid, {})[bdate] = time.time()
    else:
        # Historical data — write to disk, don't accumulate in memory
        _to_disk(mid, bdate, all_t)
    _invalidate_quota_cache(mid)
    _invalidate_stats_cache(mid)   # force stats (month sales) to recompute on next request
    return all_t

def collect_day_tickets(merchant, display_date, cache_only=False):
    """Return tickets for a display date, honouring merchant's dayStartHour.

    dayStartHour=6 (default): cache file for display_date already covers 06:00–05:59,
    so just return fetch_tickets(display_date) directly.

    dayStartHour=0 (midnight-to-midnight): cache files are still 06:00–05:59 splits.
    To get calendar date X we read two cache files and filter by ticket datetime:
      - cache[X-1]: tickets whose datetime falls on X 00:00–05:59
      - cache[X]:   tickets whose datetime falls on X 06:00–23:59
    """
    start_hour = int(merchant.get('dayStartHour', 6))
    if start_hour == 6:
        return fetch_tickets(merchant, display_date, cache_only=cache_only)

    # Generic midnight-boundary logic: collect from prev and curr cache files,
    # keep only tickets whose datetime (MYT) matches the display_date calendar day.
    d         = date.fromisoformat(display_date)
    prev_date = str(d - timedelta(days=1))
    result    = []
    for bdate in (prev_date, display_date):
        for t in (fetch_tickets(merchant, bdate, cache_only=True) or []):
            try:
                if t.get('datetime', '')[:10] == display_date:
                    result.append(t)
            except Exception:
                pass
    # If the current display date is not yet fully synced, also hit the live API
    # for today's data (same as normal fetch_tickets behaviour).
    if not cache_only:
        biz_today = str(current_business_date(start_hour))
        if display_date == biz_today:
            # refresh live data for today
            live = fetch_tickets(merchant, display_date, cache_only=False)
            seen = {id(t) for t in result}
            for t in (live or []):
                if t.get('datetime', '')[:10] == display_date and id(t) not in seen:
                    result.append(t)
    return result


# ── Aggregation ────────────────────────────────────────────────────────────────
def r2(n): return round(float(n or 0), 2)

def aggregate(bdate, tickets):
    ttl = rnd = dis = tax = chg = 0.0
    tx_count = 0
    for t in tickets:
        # Skip voided / invalid transactions (C# line: if (invalid != 0) continue)
        if int(t.get('invalid', 0) or 0) != 0:
            continue
        ticket_type = (t.get('ticketType') or '').upper()
        sign = -1 if ticket_type == 'SELL_RETURN' else 1
        tx_count += 1

        ttl += float(t.get('totalAmount', 0) or 0) * sign
        rnd += float(t.get('rounding',    0) or 0) * sign

        # Discount: sum discountTotalAmount from item-level discountDetails (C# algorithm)
        # NOTE: ticket.discount is a percentage field (e.g. 85, 100), NOT a money amount
        d = 0.0
        for item in (t.get('items') or []):
            for dd in (item.get('discountDetails') or []):
                amt = dd.get('discountTotalAmount') if dd.get('discountTotalAmount') is not None \
                      else dd.get('discountAmount')
                d += float(amt or 0)
        dis += d * sign

        # Tax: taxFee (C# field name), then fallbacks for v2 API variants
        t_tax = 0.0
        if t.get('taxFee') is not None:        t_tax = float(t['taxFee'] or 0)
        elif t.get('taxAmount') is not None:   t_tax = float(t['taxAmount'] or 0)
        elif t.get('taxList'):
            for tx in t['taxList']: t_tax += float(tx.get('taxAmount') or tx.get('amount') or 0)
        tax += t_tax * sign

        # Charges: serviceFee (C# field name), then fallbacks for v2 API variants
        t_chg = 0.0
        if t.get('serviceFee') is not None:      t_chg = float(t['serviceFee'] or 0)
        elif t.get('chargeAmount') is not None:  t_chg = float(t['chargeAmount'] or 0)
        elif t.get('serviceCharge') is not None: t_chg = float(t['serviceCharge'] or 0)
        elif t.get('chargeList'):
            for c in t['chargeList']: t_chg += float(c.get('amount') or 0)
        chg += t_chg * sign

    ttl=r2(ttl); rnd=r2(rnd); dis=r2(dis); tax=r2(tax); chg=r2(chg)

    # Formulas matching C# algorithm exactly:
    # net_excl  = thisAmountRaw + thisRounding - thisTax - thisCharges
    # grossSale = net_excl + thisDiscount
    # totalSale = thisAmountRaw
    # netTotal  = thisAmountRaw + thisRounding
    net_excl = r2(ttl + rnd - tax - chg)
    return {
        'date': bdate, 'txCount': tx_count,
        'crossSales':          r2(net_excl + dis),   # Gross Sales = net_excl + discount
        'discount':            dis,
        'rounding':            rnd,
        'netAmountExclusive':  net_excl,              # totalAmount + rounding - tax - charges
        'tax':                 tax,
        'charges':             chg,
        'totalSales':          ttl,                   # thisAmountRaw = sum(ticket.totalAmount)
        'crossSalesInclu':     ttl,                   # Gross Sales (Inclu.) = same as Total Sales
        'netSalesWithCharges': r2(ttl + rnd - tax),   # totalAmount + rounding - tax
        'netTotal':            r2(ttl + rnd),          # totalAmount + rounding
    }

def run_report(merchant, start, end):
    all_dates  = dates_between(start, end)
    start_hour = int(merchant.get('dayStartHour', 6))
    yesterday  = str(current_business_date(start_hour) - timedelta(days=1))
    rows_map   = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        # cache_only for dates older than yesterday — avoids burning quota on unsynced history
        futs = {ex.submit(collect_day_tickets, merchant, d, d < yesterday): d for d in all_dates}
        for fut in as_completed(futs):
            d = futs[fut]
            try:
                tickets = fut.result()
                rows_map[d] = aggregate(d, tickets)   # include zero-transaction days
            except Exception as ex2:
                print(f'  [report] {merchant.get("name","?")} {d}: {ex2}')
    rows  = [rows_map[d] for d in all_dates if d in rows_map]
    total = {
        'date': 'TOTAL', 'txCount': 0, 'crossSales': 0, 'discount': 0, 'rounding': 0,
        'netAmountExclusive': 0, 'tax': 0, 'charges': 0, 'totalSales': 0,
        'crossSalesInclu': 0, 'netSalesWithCharges': 0, 'netTotal': 0,
    }
    for row in rows:
        for k in total:
            if k != 'date': total[k] = r2(total[k] + row[k])
    return rows, total

def aggregate_payments(bdate, tickets):
    by_code  = {}
    tx_count = 0
    for t in tickets:
        if int(t.get('invalid', 0) or 0) != 0:
            continue
        ticket_type = (t.get('ticketType') or '').upper()
        sign = -1 if ticket_type == 'SELL_RETURN' else 1
        tx_count += 1
        for p in (t.get('payments') or []):
            code = p.get('code') or 'unknown'
            amt  = float(p.get('amount', 0) or 0) * sign
            by_code[code] = r2(by_code.get(code, 0) + amt)
    return {
        'date'   : bdate,
        'txCount': tx_count,
        'byCode' : by_code,
        'total'  : r2(sum(by_code.values())),
    }

def run_payment_report(merchant, start, end):
    all_dates  = dates_between(start, end)
    start_hour = int(merchant.get('dayStartHour', 6))
    yesterday  = str(current_business_date(start_hour) - timedelta(days=1))
    rows_map   = {}
    all_codes  = []   # ordered by first appearance
    with ThreadPoolExecutor(max_workers=5) as ex:
        # cache_only for dates older than yesterday — avoids burning quota on unsynced history
        futs = {ex.submit(collect_day_tickets, merchant, d, d < yesterday): d for d in all_dates}
        for fut in as_completed(futs):
            d = futs[fut]
            try:
                tickets = fut.result()
                row = aggregate_payments(d, tickets)   # include zero-transaction days
                rows_map[d] = row
                for code in row['byCode']:
                    if code not in all_codes:
                        all_codes.append(code)
            except Exception as ex2:
                print(f'  [payment] {merchant.get("name","?")} {d}: {ex2}')

    rows = [rows_map[d] for d in all_dates if d in rows_map]

    # Total row
    total_by_code = {}
    total_tx = 0
    for row in rows:
        total_tx += row['txCount']
        for code, amt in row['byCode'].items():
            total_by_code[code] = r2(total_by_code.get(code, 0) + amt)

    methods = fetch_pay_methods(merchant)
    # Sort: Cash (payCode_1) always first, others by code name
    all_codes.sort(key=lambda c: (0 if c == 'payCode_1' else 1, c))
    columns = [{'code': c, 'name': pay_name(c, methods)} for c in all_codes]

    return {
        'columns': columns,
        'rows'   : rows,
        'total'  : {
            'date'   : 'TOTAL',
            'txCount': total_tx,
            'byCode' : total_by_code,
            'total'  : r2(sum(total_by_code.values())),
        },
    }

def dates_between(start, end):
    cur = date.fromisoformat(start)
    fin = date.fromisoformat(end)
    out = []
    while cur <= fin:
        out.append(str(cur)); cur += timedelta(days=1)
    return out

# ── Auto-Sync ──────────────────────────────────────────────────────────────────
# Sync state is kept entirely in memory; a background thread flushes to disk every 30 s.
# This eliminates disk-I/O lock contention when 100 workers update state concurrently.
_sync_state_lock = threading.Lock()
_sync_state_mem  = {}          # in-memory store  {mid: {...}}
_sync_state_dirty = False      # True when memory differs from disk

def _load_sync_state_from_disk():
    if os.path.exists(SYNC_STATE_FILE):
        try:
            with open(SYNC_STATE_FILE, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _flush_sync_state():
    """Write in-memory state to disk (called by background flusher)."""
    global _sync_state_dirty
    with _sync_state_lock:
        if not _sync_state_dirty:
            return
        snapshot = dict(_sync_state_mem)
        _sync_state_dirty = False
    try:
        with open(SYNC_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f'  [sync] state flush error: {e}')

def _start_state_flusher():
    """Background thread: persist sync state to disk every 30 seconds."""
    def _loop():
        while True:
            time.sleep(30)
            _flush_sync_state()
    threading.Thread(target=_loop, daemon=True).start()

def get_sync_state(mid):
    with _sync_state_lock:
        return dict(_sync_state_mem.get(mid, {}))   # return a copy

def update_sync_state(mid, updates):
    global _sync_state_dirty
    with _sync_state_lock:
        _sync_state_mem.setdefault(mid, {}).update(updates)
        _sync_state_dirty = True

def _load_sync_state():
    """Legacy helper used by admin sync-status endpoint — returns full state."""
    with _sync_state_lock:
        return dict(_sync_state_mem)

def init_sync_state(mid):
    """Initialize sync state for a newly added merchant."""
    today     = str(date.today())
    yesterday = str(date.today() - timedelta(days=1))
    global _sync_state_dirty
    with _sync_state_lock:
        if mid not in _sync_state_mem:
            _sync_state_mem[mid] = {
                'last_daily_sync_date'    : None,
                'backfill_date'           : yesterday,
                'consecutive_no_data_days': 0,
                'api_calls_sync_today'    : 0,
                'api_calls_reset_date'    : today,
                'backfill_completed'      : False,
            }
            _sync_state_dirty = True

def sync_merchant(merchant):
    """
    One sync cycle for a single merchant.
    1. Always fetch yesterday first (daily sync).
    2. Use remaining quota to backfill older dates.
    3. Stop backfill after BACKFILL_STOP_DAYS consecutive empty days.
    """
    mid          = merchant['id']
    name         = merchant.get('name', mid)
    today        = str(date.today())              # calendar day — for quota/state reset
    biz_today    = str(current_business_date())   # current incomplete business day (always 6am boundary for sync)
    biz_yesterday= str(current_business_date() - timedelta(days=1))  # last complete biz day
    yesterday    = biz_yesterday                  # alias used below

    state = get_sync_state(mid)
    if not state:
        init_sync_state(mid)
        state = get_sync_state(mid)

    # Skip deactivated merchants entirely — no API calls wasted
    if state.get('deactivated'):
        return

    # Reset daily call counter if it's a new calendar day
    if state.get('api_calls_reset_date') != today:
        state['api_calls_sync_today']  = 0
        state['api_calls_total_today'] = 0
        state['api_calls_reset_date']  = today
        update_sync_state(mid, state)

    # Pre-flight: if total calls today already >= limit, skip until tomorrow
    total_today = state.get('api_calls_total_today', 0)
    if total_today >= SYNC_API_LIMIT:
        return   # quota already used up — other app needs the remainder

    calls_used = state.get('api_calls_sync_today', 0)

    def quota_ok():
        return calls_used < SYNC_API_LIMIT

    def fetch_one(bdate_str, force=False):
        """
        Fetch one business date.
        Returns (ticket_count, api_calls_made) on success, (None, 0) if quota is
        exhausted, or (None, -1) if the fetch itself failed — the caller uses that
        to tell the two apart when logging.
        Cached dates cost 0 quota; force=True re-fetches them anyway.
        """
        nonlocal calls_used
        if not force:
            on_disk = _from_disk(mid, bdate_str)
            if on_disk is not None:
                return len(on_disk), 0      # already cached — free
        if not quota_ok():
            return None, 0                  # quota gone, cannot fetch
        before = _api_calls.get(mid, 0)
        try:
            tickets = fetch_tickets(merchant, bdate_str, force=force)
        except Exception as ex:
            after = _api_calls.get(mid, 0)
            calls_used += max(0, after - before)
            print(f'  [sync] {name} {bdate_str} fetch failed: {ex}')
            return None, -1                 # existing cache, if any, is left untouched
        after = _api_calls.get(mid, 0)
        made   = max(0, after - before)
        calls_used += made
        return len(tickets), made

    # ── Step 1: daily sync — always re-fetch yesterday (force fresh, day is now complete) ─
    # Track by biz_yesterday (the date we're fetching), not the calendar date.
    # Keying on the calendar date let a restart shortly after the boundary mark the
    # sync as "done" for that day, so the scheduled run skipped it and the day was lost.
    if state.get('last_daily_sync_date') != yesterday:
        # force=True re-fetches even though the day may already be cached: an earlier
        # snapshot taken mid-day would be short, and the day is complete now.  The
        # cache is replaced only after the API call returns, so a timeout no longer
        # wipes the copy we already had (it used to be deleted up front).
        count, made = fetch_one(yesterday, force=True)
        if count is not None:
            with _c_lock:
                _mem.setdefault(mid, {}).pop(yesterday, None)
                _mem_ts.setdefault(mid, {}).pop(yesterday, None)
            state['last_daily_sync_date'] = yesterday
            print(f'  [sync] {name} daily {yesterday}: {count} tickets, {made} API calls')
        elif made == -1:
            print(f'  [sync] {name} daily {yesterday}: fetch failed, kept existing cache')
        else:
            print(f'  [sync] {name} daily {yesterday}: quota exhausted ({calls_used}/{SYNC_API_LIMIT})')

    # ── Step 1.2: also re-fetch day-before-yesterday once per sync day ──────────
    # Pospal API sometimes returns incomplete data at sync time (tickets settled late).
    # Re-fetching 2 days ago catches any tickets that appeared after yesterday's sync.
    day_before_yest = str(date.fromisoformat(yesterday) - timedelta(days=1))
    if state.get('last_daily_sync_date_2') != yesterday and quota_ok():
        count, made = fetch_one(day_before_yest, force=True)
        if count is not None:
            with _c_lock:
                _mem.setdefault(mid, {}).pop(day_before_yest, None)
                _mem_ts.setdefault(mid, {}).pop(day_before_yest, None)
            state['last_daily_sync_date_2'] = yesterday
            print(f'  [sync] {name} daily-2 {day_before_yest}: {count} tickets, {made} API calls')
        elif made == -1:
            print(f'  [sync] {name} daily-2 {day_before_yest}: fetch failed, kept existing cache')
        else:
            print(f'  [sync] {name} daily-2 {day_before_yest}: quota exhausted ({calls_used}/{SYNC_API_LIMIT})')

    # ── Step 1.5: recent gap fill — catch any days missed due to restarts/skips ────
    # Check the 3 business days before yesterday. If any are missing from disk cache,
    # fetch them now while quota allows. This acts as a safety net so a missed day is
    # recovered at the very next sync rather than staying empty permanently.
    RECENT_GAP_DAYS = 3
    if quota_ok():
        biz_yest_d = date.fromisoformat(yesterday)
        for i in range(1, RECENT_GAP_DAYS + 1):
            check_date = str(biz_yest_d - timedelta(days=i))
            if not os.path.exists(_cpath(mid, check_date)) and quota_ok():
                count, made = fetch_one(check_date)
                if count is not None:
                    print(f'  [sync] {name} gap-fill {check_date}: {count} tickets, {made} API calls')

    # ── Deactivation check: 90 consecutive recent empty days → stop syncing forever ─
    cache_dir = os.path.join(CACHE_DIR, mid)
    consec_recent = 0
    yest_d = date.today() - timedelta(days=1)
    for i in range(DEACTIVATE_DAYS):
        ds = str(yest_d - timedelta(days=i))
        p  = os.path.join(cache_dir, ds + '.json')
        if not os.path.exists(p): break
        try:
            with open(p, encoding='utf-8') as f: tickets = json.load(f)
        except Exception: break
        if any(int(t.get('invalid', 0) or 0) == 0 for t in tickets): break
        consec_recent += 1
    if consec_recent >= DEACTIVATE_DAYS:
        state['deactivated'] = True
        update_sync_state(mid, state)
        print(f'  [sync] {name} deactivated — {DEACTIVATE_DAYS} consecutive days no sales')
        return

    # ── Step 2: backfill older dates ────────────────────────────────────────────
    if not state.get('backfill_completed', False) and quota_ok():
        cur         = date.fromisoformat(state.get('backfill_date') or yesterday)
        consecutive = state.get('consecutive_no_data_days', 0)

        while quota_ok():
            bdate_str = str(cur)

            if bdate_str >= biz_today:      # never fetch current/future business day
                cur -= timedelta(days=1)
                continue

            count, made = fetch_one(bdate_str)

            if count is None:              # quota exhausted
                break

            if count == 0:
                consecutive += 1
                print(f'  [sync] {name} backfill {bdate_str}: empty '
                      f'({consecutive}/{BACKFILL_STOP_DAYS})')
                if consecutive >= BACKFILL_STOP_DAYS:
                    state['backfill_completed'] = True
                    print(f'  [sync] {name} backfill complete — '
                          f'{BACKFILL_STOP_DAYS} consecutive empty days')
                    break
            else:
                consecutive = 0
                if made > 0:
                    print(f'  [sync] {name} backfill {bdate_str}: '
                          f'{count} tickets, {made} API calls')

            cur -= timedelta(days=1)

        state['consecutive_no_data_days'] = consecutive
        if not state.get('backfill_completed'):
            state['backfill_date'] = str(cur)

    state['api_calls_sync_today'] = calls_used
    update_sync_state(mid, state)

SYNC_MERCHANT_TIMEOUT = 300   # max seconds per merchant per sync cycle (5 min)

def sync_all_merchants():
    """Sync every merchant in parallel. Called by the background scheduler."""
    ms = get_all_merchants()

    # ── Step 1: Refresh pay method names FIRST (while quota is still fresh) ──
    # 10 workers in parallel, once per calendar day per merchant.
    active = [m for m in ms if not m.get('deactivated')]
    print(f'  [pay_methods] refreshing {len(active)} merchants…')
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(refresh_pay_methods_daily, m): m for m in active}
        for fut in as_completed(futs):
            try:
                fut.result()
            except Exception as e:
                print(f'  [pay_methods] {futs[fut].get("name","?")} daily refresh error: {e}')
    print(f'  [pay_methods] refresh done')

    # ── Step 2: Sync tickets ──────────────────────────────────────────────────
    print(f'  [sync] starting {len(ms)} merchants with {SYNC_WORKERS} workers')
    with ThreadPoolExecutor(max_workers=SYNC_WORKERS) as ex:
        futs = {ex.submit(sync_merchant, m): m for m in ms}
        for fut in as_completed(futs):
            m = futs[fut]
            try:
                fut.result(timeout=SYNC_MERCHANT_TIMEOUT)
            except TimeoutError:
                print(f'  [sync] {m.get("name","?")} timed out after {SYNC_MERCHANT_TIMEOUT}s — will retry next cycle')
                fut.cancel()
            except Exception as e:
                print(f'  [sync] {m.get("name","?")} error: {e}')
            _flush_sync_state()
    print(f'  [sync] all merchants done')

def trigger_sync_for(merchant):
    """Spawn a one-shot background thread to sync a single merchant immediately."""
    t = threading.Thread(target=sync_merchant, args=(merchant,), daemon=True)
    t.start()

SYNC_HOUR = 6   # 06:00 MYT — the box runs on Asia/Kuala_Lumpur, so dt.now() below is
                # already local time.  This used to be 22 on the assumption that the
                # process ran on UTC; when the server timezone changed on 2026-06-12
                # the sync silently drifted to 22:00 MYT — 16 hours late every day.

def _secs_until_next_sync():
    """Seconds until the next SYNC_HOUR:00:00 (server local time = MYT)."""
    from datetime import datetime as dt
    now  = dt.now()
    nxt  = now.replace(hour=SYNC_HOUR, minute=0, second=0, microsecond=0)
    if now >= nxt:
        nxt += timedelta(days=1)
    return max(1, (nxt - now).total_seconds())

def start_sync_scheduler():
    """Background thread: sync all merchants once per day at SYNC_HOUR (6am MYT)."""
    def _loop():
        # Only run on startup if today's scheduled sync hasn't happened yet.
        # Prevents repeated quota consumption on multiple restarts/deploys.
        myt_now  = datetime.utcnow() + timedelta(hours=8)
        myt_date = str(myt_now.date())
        already_ran_today = all(
            (get_sync_state(m['id']) or {}).get('last_sync_run_date') == myt_date
            for m in get_all_merchants()[:5]   # sample 5 merchants as a proxy
        )
        if already_ran_today:
            secs_wait = _secs_until_next_sync()
            h, m_    = divmod(int(secs_wait) // 60, 60)
            print(f'  [sync] scheduler started — sync already ran today, next run in {h}h {m_}m ({SYNC_HOUR:02d}:00 MYT)')
        else:
            print(f'  [sync] scheduler started — running now (first sync today), then daily at {SYNC_HOUR:02d}:00 MYT')

        while True:
            myt_now = datetime.utcnow() + timedelta(hours=8)
            myt_str = myt_now.strftime('%Y-%m-%d %H:%M MYT')
            if already_ran_today:
                already_ran_today = False   # next iteration always runs
            else:
                t0 = time.time()
                tg_send(f'🔄 <b>Pospal Sync Started</b>\n{myt_str}')
                try:
                    sync_all_merchants()
                    # Mark today as synced on a sentinel merchant (first active)
                    ms_all = get_all_merchants()
                    active = [m for m in ms_all if not m.get('deactivated')]
                    for am in active[:5]:
                        st = get_sync_state(am['id']) or {}
                        st['last_sync_run_date'] = myt_str[:10]
                        update_sync_state(am['id'], st)
                    elapsed = int(time.time() - t0)
                    mins, secs = divmod(elapsed, 60)
                    tg_send(
                        f'✅ <b>Pospal Sync Done</b>\n'
                        f'{myt_str}\n'
                        f'Merchants: {len(active)} active\n'
                        f'Duration: {mins}m {secs}s'
                    )
                except Exception as ex:
                    print(f'  [sync] scheduler error: {ex}')
                    tg_send(f'❌ <b>Pospal Sync Error</b>\n{myt_str}\n{ex}')
            secs_wait = _secs_until_next_sync()
            h, m_ = divmod(int(secs_wait) // 60, 60)
            print(f'  [sync] next run in {h}h {m_}m (at {SYNC_HOUR:02d}:00 MYT)')
            time.sleep(secs_wait)
    threading.Thread(target=_loop, daemon=True).start()

# ── Transactions Export ────────────────────────────────────────────────────────
# The figures here must match the Transactions page cent-for-cent, so these three
# helpers mirror r2 / grossAmt / itemDiscount in public/orders.html exactly.
# Note math.floor(x*100+0.5) rather than round(): Python rounds half to even,
# JS Math.round rounds half up, and the two disagree on values like 0.125.
def _o_r2(n):
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        v = 0.0
    return math.floor(v * 100 + 0.5) / 100

def _o_is_ref(t):
    return str(t.get('ticketType') or '').upper() == 'SELL_RETURN'

def _o_gross(t):
    items = t.get('items') or []
    return _o_r2(sum(_o_r2(i.get('totalAmount')) for i in items)
                 + _o_r2(t.get('taxFee')) + _o_r2(t.get('serviceFee')))

def _o_discount(t):
    total = 0.0
    for i in t.get('items') or []:
        dd = i.get('discountDetails') or []
        if dd:
            total += _o_r2(sum(_o_r2(d.get('discountTotalAmount') or d.get('discountAmount') or 0)
                               for d in dd))
        else:
            # items without discountDetails: fall back to list price minus what was charged
            d = _o_r2(_o_r2(float(i.get('sellPrice') or 0) * float(i.get('quantity') or 0))
                      - _o_r2(i.get('totalAmount')))
            total += d if d > 0 else 0
    return _o_r2(total)


def build_orders_xlsx(merchant, tickets, pay_methods, detail=False, pay_cols=True):
    """
    Generate the Transactions .xlsx for an already-filtered list of tickets.

    The caller decides which tickets go in (the page's filters live in the
    browser); this only decides how they are laid out.  detail=True adds a
    second sheet with one row per line item, keyed by Receipt No.
    Returns bytes of the xlsx file.
    """
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise RuntimeError('openpyxl not installed — run: pip3 install openpyxl')

    hdr_fill = PatternFill('solid', fgColor='FF6600')
    hdr_font = Font(bold=True, color='FFFFFF', size=10)
    tot_fill = PatternFill('solid', fgColor='FFF7ED')
    tot_font = Font(bold=True, size=10)
    void_font = Font(italic=True, color='A1A1AA', size=10)
    void_tot_font = Font(bold=True, italic=True, color='A1A1AA', size=10)
    subtotal_rule = Border(top=Side(style='thin', color='FDBA74'))
    num_fmt   = '#,##0.00'
    date_fmt  = 'DD/MM/YYYY'
    center = Alignment(horizontal='center')
    right  = Alignment(horizontal='right')
    left   = Alignment(horizontal='left')

    def pay_text(t):
        return ', '.join(
            '%s %.2f' % (pay_methods.get(p.get('code'), p.get('code')), _o_r2(p.get('amount')))
            for p in (t.get('payments') or [])
        )

    def split_dt(t):
        dp, _, tp = str(t.get('datetime') or '').partition(' ')
        try:
            d = datetime.strptime(dp, '%Y-%m-%d').date()
        except ValueError:
            d = None
        return d, tp[:5]

    def write_header(ws, headers, widths, aligns):
        for ci, (h, w, a) in enumerate(zip(headers, widths, aligns), 1):
            c = ws.cell(row=1, column=ci, value=h)
            c.fill = hdr_fill; c.font = hdr_font; c.alignment = a
            ws.column_dimensions[get_column_letter(ci)].width = w
        ws.freeze_panes = 'A2'

    wb = openpyxl.Workbook()

    # ── Sheet 1 · Transactions (one row per ticket) ────────────────────────────
    ws = wb.active
    ws.title = 'Transactions'

    # Receipt numbers run 21 chars, so a fixed width truncates the tail — size the
    # column to the longest sn actually being exported (both sheets use this).
    sn_w = max(13, min(40, max((len(str(t.get('sn') or '')) for t in tickets), default=0) + 2))

    HEADERS = ['Receipt No.', 'Date', 'Time', 'Type', 'Cashier', 'Member', 'Qty',
               'Gross Amt', 'Net Collected', 'Excl. SST', 'SST', 'Discount']
    WIDTHS  = [sn_w, 12, 8, 9, 14, 18, 7, 13, 14, 13, 11, 11]
    ALIGNS  = [left, left, center, center, left, left, center,
               right, right, right, right, right]
    if pay_cols:
        HEADERS.append('Payment'); WIDTHS.append(28); ALIGNS.append(left)
    # The remark typed into Pospal on the ticket itself -- last, so the money
    # columns keep their positions for anyone with a saved template.
    HEADERS.append('Remark'); WIDTHS.append(30); ALIGNS.append(left)
    write_header(ws, HEADERS, WIDTHS, ALIGNS)

    NUM_FROM = 8   # column 8 onward is money, except the trailing Payment column
    row = 2
    for t in tickets:
        is_void = int(t.get('invalid') or 0) == 1
        ref     = _o_is_ref(t)
        d, tm   = split_dt(t)
        net     = _o_r2(t.get('totalAmount'))
        tax     = _o_r2(t.get('taxFee'))
        disc    = _o_discount(t)
        qty     = sum(float(i.get('quantity') or 0) for i in (t.get('items') or []))

        vals = [
            t.get('sn') or '', d, tm,
            'Void' if is_void else ('Refund' if ref else 'Sale'),
            (t.get('cashier') or {}).get('name') or '',
            t.get('customerName') or '',
            qty,
            _o_gross(t), net, _o_r2(net - tax), tax, disc,
        ]
        if pay_cols:
            vals.append(pay_text(t))
        vals.append((t.get('remark') or '').strip())

        for ci, v in enumerate(vals, 1):
            c = ws.cell(row=row, column=ci, value=v)
            if ci == 2:
                c.number_format = date_fmt; c.alignment = left
            elif ci in (3, 4, 7):
                c.alignment = center
            elif 8 <= ci <= 12:
                c.number_format = num_fmt; c.alignment = right
            else:
                c.alignment = left
            if is_void:
                c.font = void_font
        row += 1

    # ── Footer: Sales / Refunds / Net Total, mirroring renderFooter() ──────────
    # Deliberately counts void tickets, exactly like the on-screen tfoot does.
    def agg(rows):
        a = {'cnt': 0, 'g': 0.0, 'net': 0.0, 'net2': 0.0, 'tax': 0.0, 'disc': 0.0}
        for t in rows:
            n  = _o_r2(t.get('totalAmount'))
            tx = _o_r2(t.get('taxFee'))
            a['cnt']  += 1
            a['g']    += _o_gross(t)
            a['net']  += n
            a['net2'] += _o_r2(n - tx)
            a['tax']  += tx
            a['disc'] += _o_discount(t)
        return {k: (v if k == 'cnt' else _o_r2(v)) for k, v in a.items()}

    # Void tickets are cancelled, so their money must stay out of SALES and out of the
    # net — they get their own informational row instead.  Sale / Refund / Void here
    # split the same way the Type column does (void wins over refund), so the three
    # counts always add back up to the number of rows above.
    is_v     = lambda t: int(t.get('invalid') or 0) == 1
    voids    = agg([t for t in tickets if is_v(t)])
    refunds  = agg([t for t in tickets if not is_v(t) and     _o_is_ref(t)])
    sales    = agg([t for t in tickets if not is_v(t) and not _o_is_ref(t)])
    net_tot  = {k: sales[k] + refunds[k] if k == 'cnt' else _o_r2(sales[k] - refunds[k])
                for k in sales}

    # Reads top-down as an arithmetic: SALES minus REFUNDS rules off to NET TOTAL,
    # the money actually taken.  Refunds carry a real negative so the column can be
    # re-summed in Excel.  VOIDS sits below the rule — informational, never part of
    # the net — and only appears when voids were actually exported (the modal's
    # INCLUDE Void transactions box).
    lines = [('SALES', sales, False, 1, False), ('REFUNDS', refunds, False, -1, False),
             ('NET TOTAL', net_tot, False, 1, True)]
    if voids['cnt']:
        lines.append(('VOIDS', voids, True, 1, False))

    row += 1   # blank spacer line between the data and the totals
    for label, a, muted, sign, rule in lines:
        ws.cell(row=row, column=1, value='%s (%d orders)' % (label, a['cnt']))
        for ci, v in ((8, a['g']), (9, a['net']), (10, a['net2']), (11, a['tax']), (12, a['disc'])):
            c = ws.cell(row=row, column=ci, value=_o_r2(sign * v))
            c.number_format = num_fmt; c.alignment = right
        for ci in range(1, len(HEADERS) + 1):
            c = ws.cell(row=row, column=ci)
            c.fill = tot_fill; c.font = void_tot_font if muted else tot_font
            if rule:
                c.border = subtotal_rule
        row += 1

    # ── Sheet 2 · Line Items (one row per item, keyed by Receipt No.) ──────────
    if detail:
        ws2 = wb.create_sheet('Line Items')
        H2 = ['Receipt No.', 'Date', 'Type', 'Item', 'Barcode',
              'Qty', 'Unit Price', 'Total', 'Discount', 'Item Remark']
        W2 = [sn_w, 12, 9, 38, 16, 7, 12, 13, 11, 28]
        A2 = [left, left, center, left, left, center, right, right, right, left]
        write_header(ws2, H2, W2, A2)

        r2row = 2
        for t in tickets:
            items = t.get('items') or []
            if not items:
                continue
            is_void = int(t.get('invalid') or 0) == 1
            ref     = _o_is_ref(t)
            d, _    = split_dt(t)
            ttype   = 'Void' if is_void else ('Refund' if ref else 'Sale')
            sn      = t.get('sn') or ''
            if r2row > 2:
                r2row += 1   # blank line between receipts, so each block reads apart
            for i in items:
                q    = float(i.get('quantity') or 0)
                sell = float(i.get('sellPrice') or 0)
                unit = _o_r2(sell)
                amt  = _o_r2(i.get('totalAmount'))
                # multiply first, then round — buildDetail() does r2(sellPrice*qty),
                # and rounding the unit price first is off by a cent on 3dp prices
                dis  = _o_r2(_o_r2(sell * q) - amt)
                vals = [sn, d, ttype, i.get('name') or '',
                        i.get('productBarcode') or '', q, unit, amt, dis if dis > 0 else 0.0,
                        (i.get('remark') or '').strip()]
                for ci, v in enumerate(vals, 1):
                    c = ws2.cell(row=r2row, column=ci, value=v)
                    if ci == 2:
                        c.number_format = date_fmt; c.alignment = left
                    elif ci in (3, 6):
                        c.alignment = center
                    elif 7 <= ci <= 9:
                        c.number_format = num_fmt; c.alignment = right
                    else:
                        c.alignment = left
                    if is_void:
                        c.font = void_font
                r2row += 1

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── AR Invoice Export ──────────────────────────────────────────────────────────
def build_ar_invoice_autocount(merchant, start, end, debtor_code=None, acc_no=None, cod=None, inclusive_tax=None):
    """
    Generate AutoCount AR Invoice .xlsx for the given date range.
    debtor_code / acc_no / cod override the merchant defaults when provided.
    Returns bytes of the xlsx file.
    """
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        raise RuntimeError('openpyxl not installed — run: pip3 install openpyxl')

    DEBTOR_CODE  = debtor_code  or merchant.get('debtorCode', '300-0000')
    ACC_NO       = acc_no       or '500-1000'
    DISPLAY_TERM = cod          or 'C.O.D.'
    CURRENCY     = 'MYR'
    INCLUSIVE_TAX= inclusive_tax if inclusive_tax in ('T', 'F') else 'F'

    HEADERS = [
        'DocNo','DocDate','DebtorCode','JournalType','DisplayTerm','SalesAgent',
        'Description','CurrencyCode','CurrencyRate','RefNo2','Note','InclusiveTax',
        'AccNo','ToAccountRate','DetailDescription','ProjNo','DeptNo','TaxType',
        'TaxableAmt','TaxAdjustment','Amount',
    ]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'AR Invoice'

    hdr_font = Font(bold=True, color='FFFFFF')
    hdr_fill = PatternFill('solid', fgColor='1F4E79')
    for ci, h in enumerate(HEADERS, 1):
        cell = ws.cell(1, ci, h)
        cell.font = hdr_font
        cell.fill = hdr_fill
        cell.alignment = Alignment(horizontal='center')

    col_widths = [28,12,12,10,8,10,28,10,10,28,8,10,10,12,50,8,8,8,12,12,12]
    for ci, w in enumerate(col_widths, 1):
        ws.column_dimensions[ws.cell(1, ci).column_letter].width = w

    for bdate in dates_between(start, end):
        tickets = collect_day_tickets(merchant, bdate, cache_only=True)
        if not tickets:
            continue
        tickets = sorted(tickets, key=lambda t: t.get('sn', ''))
        for t in tickets:
            if int(t.get('invalid', 0) or 0) != 0:
                continue
            if (t.get('ticketType') or '').upper() == 'SELL_RETURN':
                continue
            sn       = t.get('sn', '')
            doc_no   = f'POS {sn}'
            raw_dt   = t.get('datetime', '')
            try:
                doc_date = _dt.strptime(raw_dt[:10], '%Y-%m-%d').strftime('%d/%m/%Y')
            except Exception:
                doc_date = bdate
            for item in (t.get('items') or []):
                amt = round(float(item.get('totalAmount', 0) or 0), 2)
                ws.append([
                    doc_no, doc_date, DEBTOR_CODE, 'SALES', DISPLAY_TERM, None,
                    doc_no, CURRENCY, 1, doc_no, None, INCLUSIVE_TAX,
                    ACC_NO, 1, item.get('name', ''), None, None, None,
                    amt, None, amt,
                ])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_journal_entry_autocount(merchant, start, end, cash_acc=None, bank_acc=None, sales_acc=None, payment_map=None):
    """
    Generate AutoCount Journal Entry .xlsx (daily cash/bank/sales summary).

    Simple mode (payment_map=None):
      Each day → up to 3 rows: Cash DR, Bank/e-wallet DR, Sales Revenue CR.

    Advanced mode (payment_map={code: acc_no, ...}):
      Each day → one DR row per payment code + Sales Revenue CR.
      Codes absent from payment_map fall back to bank_acc.
    """
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        raise RuntimeError('openpyxl not installed — run: pip3 install openpyxl')

    CASH_ACC  = cash_acc  or '320-0000'
    BANK_ACC  = bank_acc  or '310-1000'
    SALES_ACC = sales_acc or '500-0000'

    pay_names = {}
    if payment_map:
        with _pm_lock:
            pay_names = dict(_pay_methods.get(merchant['id'], {}))

    HEADERS = [
        'DocNo', 'DocDate', 'JournalType', 'Description',
        'CurrencyCode', 'AccNo', 'ProjNo', 'DetailDescription',
        'ToTaxCurrencyRate', 'DR', 'CR',
    ]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Journal Entry'

    hdr_font = Font(bold=True, color='FFFFFF')
    hdr_fill = PatternFill('solid', fgColor='1F4E79')
    for ci, h in enumerate(HEADERS, 1):
        cell = ws.cell(1, ci, h)
        cell.font = hdr_font
        cell.fill = hdr_fill
        cell.alignment = Alignment(horizontal='center')

    col_widths = [14, 12, 10, 42, 12, 12, 8, 26, 18, 12, 12]
    for ci, w in enumerate(col_widths, 1):
        ws.column_dimensions[ws.cell(1, ci).column_letter].width = w

    name = merchant.get('name', '')

    for bdate in dates_between(start, end):
        tickets = collect_day_tickets(merchant, bdate, cache_only=True)
        if not tickets:
            continue

        d        = date.fromisoformat(bdate)
        doc_date = d.strftime('%d/%m/%Y')
        doc_no   = f'JVPOSPAL{d.strftime("%y%m%d")}01'
        doc_desc = f'Daily Collection {doc_date} \u2014 {name}'

        def _row(acc, desc, dr, cr):
            return [doc_no, doc_date, 'GENERAL', doc_desc, 'MYR',
                    acc, None, desc, 1, dr, cr]

        if payment_map:
            # Advanced: one DR row per code
            by_code = {}
            for t in tickets:
                if int(t.get('invalid', 0) or 0) != 0: continue
                sign = -1 if (t.get('ticketType') or '').upper() == 'SELL_RETURN' else 1
                for p in (t.get('payments') or []):
                    code = p.get('code') or 'unknown'
                    amt  = round(float(p.get('amount', 0) or 0), 2) * sign
                    by_code[code] = round(by_code.get(code, 0.0) + amt, 2)
            total = round(sum(by_code.values()), 2)
            if total == 0: continue
            for code, amt in by_code.items():
                if amt == 0: continue
                acc      = payment_map.get(code) or BANK_ACC
                pay_name = pay_names.get(code, code).upper()
                ws.append(_row(acc, f'SALES ON {doc_date} {pay_name}', amt, 0))
            ws.append(_row(SALES_ACC, 'Sales Revenue', 0, total))
        else:
            # Simple: Cash vs Bank split
            cash_total = 0.0; bank_total = 0.0
            for t in tickets:
                if int(t.get('invalid', 0) or 0) != 0: continue
                sign = -1 if (t.get('ticketType') or '').upper() == 'SELL_RETURN' else 1
                for p in (t.get('payments') or []):
                    code = p.get('code') or ''
                    amt  = round(float(p.get('amount', 0) or 0), 2) * sign
                    if code == 'payCode_1': cash_total += amt
                    else: bank_total += amt
            cash_total = round(cash_total, 2); bank_total = round(bank_total, 2)
            total = round(cash_total + bank_total, 2)
            if total == 0: continue
            if cash_total > 0: ws.append(_row(CASH_ACC, f'SALES ON {doc_date} CASH', cash_total, 0))
            if bank_total > 0: ws.append(_row(BANK_ACC, f'SALES ON {doc_date} BANK', bank_total, 0))
            ws.append(_row(SALES_ACC, 'Sales Revenue', 0, total))

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_sales_invoice_autocount(merchant, start, end, debtor_code=None, debtor_name=None, cod=None):
    """
    Generate AutoCount Sales Invoice Listing .xlsx for the given date range.
    Columns: DocNo, DocDate, DebtorCode, DebtorName, DisplayTerm,
             ItemCode, DetailDescription, UOM, Qty, UnitPrice
    Skips voided (invalid!=0) and refund (SELL_RETURN) tickets.
    """
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        raise RuntimeError('openpyxl not installed — run: pip3 install openpyxl')

    DEBTOR_CODE  = debtor_code or merchant.get('debtorCode', '300-0000')
    DEBTOR_NAME  = debtor_name or 'POS SALES'
    DISPLAY_TERM = cod or 'C.O.D.'

    HEADERS = [
        'DocNo', 'DocDate', 'DebtorCode', 'DebtorName', 'DisplayTerm',
        'ItemCode', 'DetailDescription', 'UOM', 'Qty', 'UnitPrice',
    ]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Sales Invoice'

    hdr_font = Font(bold=True, color='FFFFFF')
    hdr_fill = PatternFill('solid', fgColor='1F4E79')
    for ci, h in enumerate(HEADERS, 1):
        cell = ws.cell(1, ci, h)
        cell.font = hdr_font
        cell.fill = hdr_fill
        cell.alignment = Alignment(horizontal='center')

    col_widths = [28, 12, 12, 32, 10, 20, 40, 8, 8, 12]
    for ci, w in enumerate(col_widths, 1):
        ws.column_dimensions[ws.cell(1, ci).column_letter].width = w

    for bdate in dates_between(start, end):
        tickets = collect_day_tickets(merchant, bdate, cache_only=True)
        if not tickets:
            continue
        tickets = sorted(tickets, key=lambda t: t.get('sn', ''))
        for t in tickets:
            if int(t.get('invalid', 0) or 0) != 0:
                continue
            if (t.get('ticketType') or '').upper() == 'SELL_RETURN':
                continue
            sn     = t.get('sn', '')
            doc_no = f'POS {sn}'
            raw_dt = t.get('datetime', '')
            try:
                doc_date = _dt.strptime(raw_dt[:10], '%Y-%m-%d').strftime('%d/%m/%Y')
            except Exception:
                doc_date = bdate
            for item in (t.get('items') or []):
                qty        = float(item.get('quantity', 1) or 1)
                unit_price = round(float(item.get('sellPrice', 0) or 0), 2)
                item_code  = item.get('productBarcode', '') or ''
                ws.append([
                    doc_no, doc_date, DEBTOR_CODE, DEBTOR_NAME, DISPLAY_TERM,
                    item_code, item.get('name', ''), 'PCS', qty, unit_price,
                ])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_customer_invoice_sql(merchant, start, end, debtor_code=None, acc_no=None, cod=None, inclusive_tax=None):
    """SQL Accounting — Customer Invoice import format."""
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        raise RuntimeError('openpyxl not installed')

    DEBTOR_CODE   = debtor_code or merchant.get('debtorCode', '300-0000')
    ACC_NO        = acc_no or '500-1000'
    TERMS         = cod or 'C.O.D.'
    INCLUSIVE_TAX = inclusive_tax if inclusive_tax in ('T', 'F') else 'F'

    HEADERS = [
        'DOCNO', 'DOCNOEX', 'CODE', 'DOCDATE', 'DESCRIPTION',
        'TERMS', 'CURRENCYRATE', 'CANCELLED',
        '_ACCOUNT', '_DESCRIPTION', '_TAX', '_TAXAMT', '_TAXINCLUSIVE', '_AMOUNT',
    ]

    wb = openpyxl.Workbook(); ws = wb.active; ws.title = 'ARAP Invoice'
    hf = Font(bold=True, color='FFFFFF')
    hfill = PatternFill('solid', fgColor='1F4E79')
    for ci, h in enumerate(HEADERS, 1):
        c = ws.cell(1, ci, h); c.font = hf; c.fill = hfill
        c.alignment = Alignment(horizontal='center')
    for ci, w in enumerate([28,14,12,12,28,10,12,10,12,36,8,10,12,12], 1):
        ws.column_dimensions[ws.cell(1,ci).column_letter].width = w

    for bdate in dates_between(start, end):
        tickets = collect_day_tickets(merchant, bdate, cache_only=True)
        if not tickets: continue
        for t in sorted(tickets, key=lambda t: t.get('sn','')):
            if int(t.get('invalid', 0) or 0) != 0: continue
            if (t.get('ticketType') or '').upper() == 'SELL_RETURN': continue
            sn = t.get('sn', '')
            doc_no = f'POS {sn}'
            raw_dt = t.get('datetime', '')
            try:    doc_date = _dt.strptime(raw_dt[:10], '%Y-%m-%d').strftime('%d/%m/%Y')
            except: doc_date = bdate
            for item in (t.get('items') or []):
                amt = round(float(item.get('totalAmount', 0) or 0), 2)
                ws.append([doc_no, None, DEBTOR_CODE, doc_date, doc_no,
                           TERMS, 1, 'F',
                           ACC_NO, item.get('name',''),
                           None, None, INCLUSIVE_TAX, amt])
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def build_journal_entry_sql(merchant, start, end, cash_acc=None, bank_acc=None, sales_acc=None, payment_map=None):
    """SQL Accounting — Journal Entry import format.

    Simple mode (payment_map=None): Cash DR + Bank/e-wallet DR + Sales CR.
    Advanced mode (payment_map={code: acc_no}): one DR row per payment code.
    """
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        raise RuntimeError('openpyxl not installed')

    CASH_ACC  = cash_acc  or '320-0000'
    BANK_ACC  = bank_acc  or '310-1000'
    SALES_ACC = sales_acc or '500-0000'

    pay_names = {}
    if payment_map:
        with _pm_lock:
            pay_names = dict(_pay_methods.get(merchant['id'], {}))

    HEADERS = [
        'DOCNO', 'DOCDATE', 'DESCRIPTION',
        '_CODE', '_DESCRIPTION',
        '_REF', '_TAX', '_TAXINCLUSIVE', '_DR', '_CR', '_LOCALDR', '_LOCALCR',
    ]

    wb = openpyxl.Workbook(); ws = wb.active; ws.title = 'Journal Entry'
    hf = Font(bold=True, color='FFFFFF')
    hfill = PatternFill('solid', fgColor='1F4E79')
    for ci, h in enumerate(HEADERS, 1):
        c = ws.cell(1, ci, h); c.font = hf; c.fill = hfill
        c.alignment = Alignment(horizontal='center')
    for ci, w in enumerate([18,12,42,12,28,12,8,12,12,12,12,12], 1):
        ws.column_dimensions[ws.cell(1,ci).column_letter].width = w

    name = merchant.get('name','')
    for bdate in dates_between(start, end):
        tickets = collect_day_tickets(merchant, bdate, cache_only=True)
        if not tickets: continue

        d        = date.fromisoformat(bdate)
        doc_date = d.strftime('%d/%m/%Y')
        doc_no   = f'JVPOSPAL{d.strftime("%y%m%d")}01'
        doc_desc = f'Daily Collection {doc_date} \u2014 {name}'

        def _row(code, desc, dr, cr):
            return [doc_no, doc_date, doc_desc,
                    code, desc,
                    None, None, 'F', dr, cr, dr, cr]

        if payment_map:
            by_code = {}
            for t in tickets:
                if int(t.get('invalid', 0) or 0) != 0: continue
                sign = -1 if (t.get('ticketType') or '').upper() == 'SELL_RETURN' else 1
                for p in (t.get('payments') or []):
                    code = p.get('code') or 'unknown'
                    amt  = round(float(p.get('amount', 0) or 0), 2) * sign
                    by_code[code] = round(by_code.get(code, 0.0) + amt, 2)
            total = round(sum(by_code.values()), 2)
            if total == 0: continue
            for code, amt in by_code.items():
                if amt == 0: continue
                acc      = payment_map.get(code) or BANK_ACC
                pay_name = pay_names.get(code, code).upper()
                ws.append(_row(acc, f'SALES ON {doc_date} {pay_name}', amt, 0))
            ws.append(_row(SALES_ACC, 'Sales Revenue', 0, total))
        else:
            cash_total = 0.0; bank_total = 0.0
            for t in tickets:
                if int(t.get('invalid', 0) or 0) != 0: continue
                sign = -1 if (t.get('ticketType') or '').upper() == 'SELL_RETURN' else 1
                for p in (t.get('payments') or []):
                    amt = round(float(p.get('amount', 0) or 0), 2) * sign
                    if (p.get('code') or '') == 'payCode_1': cash_total += amt
                    else: bank_total += amt
            cash_total = round(cash_total, 2); bank_total = round(bank_total, 2)
            total = round(cash_total + bank_total, 2)
            if total == 0: continue
            if cash_total > 0: ws.append(_row(CASH_ACC, f'SALES ON {doc_date} CASH', cash_total, 0))
            if bank_total > 0: ws.append(_row(BANK_ACC, f'SALES ON {doc_date} BANK', bank_total, 0))
            ws.append(_row(SALES_ACC, 'Sales Revenue', 0, total))

    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def build_sales_invoice_sql(merchant, start, end, debtor_code=None, debtor_name=None, cod=None):
    """SQL Accounting — Sales Invoice import format (SLPH_Invoice_Cash_Debit_Credit)."""
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        raise RuntimeError('openpyxl not installed')

    DEBTOR_CODE  = debtor_code or merchant.get('debtorCode', '300-0000')
    DEBTOR_NAME  = debtor_name or 'POS SALES'
    TERMS        = cod or 'C.O.D.'

    # 59-column header — matches SQL template exactly
    HEADERS = [
        'DOCNO','DOCNOEX','DOCDATE','CODE','EIV_UTC','IRBM_UUID','IRBM_LONGID','IRBM_STATUS',
        'COMPANYNAME','ADDRESS1','ADDRESS2','ADDRESS3','ADDRESS4','POSTCODE','CITY','STATE',
        'COUNTRY','PHONE1','AGENT','TERMS','DESCRIPTION','PROJECT','CC',
        'DOCREF1','DOCREF2','DOCREF3','DOCREF4','SALESTAXNO','SERVICETAXNO',
        'TIN','IDTYPE','IDNO','TOURISMNO','SIC','INCOTERMS','SUBMISSIONTYPE',
        '_ACCOUNT','_ITEMCODE','_DESCRIPTION','_DESCRIPTION2','_DESCRIPTION3',
        '_QTY','_UOM','_UNITPRICE','_DISC','_TAX','_TAXAMT','_TAXINCLUSIVE','_AMOUNT',
        '_IRBM_CLASSIFICATION','_TAXEXEMPTIONREASON','_LOCATION','_BATCH','_PROJECT',
        '_REMARK1','_REMARK2','_FROMDOCTYPE','_FROMDOCNO','_FROMSEQNO',
    ]

    wb = openpyxl.Workbook(); ws = wb.active; ws.title = 'SLPH_Invoice_Cash_Debit_Credit'
    hf = Font(bold=True, color='FFFFFF')
    hfill = PatternFill('solid', fgColor='1F4E79')
    for ci, h in enumerate(HEADERS, 1):
        c = ws.cell(1, ci, h); c.font = hf; c.fill = hfill
        c.alignment = Alignment(horizontal='center')
    ws.column_dimensions['A'].width = 28
    ws.column_dimensions['C'].width = 12
    ws.column_dimensions['D'].width = 12
    ws.column_dimensions['T'].width = 10
    ws.column_dimensions['U'].width = 28
    ws.column_dimensions['AK'].width = 36
    ws.column_dimensions['AM'].width = 8

    mid = merchant['id']
    for bdate in dates_between(start, end):
        tickets = _from_disk(mid, bdate)
        if tickets is None:
            with _c_lock: tickets = _mem.get(mid, {}).get(bdate)
        if not tickets: continue
        for t in sorted(tickets, key=lambda t: t.get('sn','')):
            if int(t.get('invalid', 0) or 0) != 0: continue
            if (t.get('ticketType') or '').upper() == 'SELL_RETURN': continue
            sn = t.get('sn', '')
            doc_no = f'POS {sn}'
            raw_dt = t.get('datetime', '')
            try:    doc_date = _dt.strptime(raw_dt[:10], '%Y-%m-%d').strftime('%d/%m/%Y')
            except: doc_date = bdate
            for item in (t.get('items') or []):
                qty        = float(item.get('quantity', 1) or 1)
                unit_price = round(float(item.get('sellPrice', 0) or 0), 2)
                amount     = round(float(item.get('totalAmount', 0) or 0), 2)
                item_code  = item.get('productBarcode', '') or ''
                # Build 59-column row; most fields None
                row = [None] * 59
                row[0]  = doc_no        # DOCNO
                row[2]  = doc_date      # DOCDATE
                row[3]  = DEBTOR_CODE   # CODE
                row[8]  = DEBTOR_NAME   # COMPANYNAME
                row[19] = TERMS         # TERMS
                row[20] = doc_no        # DESCRIPTION
                row[36] = None          # _ACCOUNT (SQL Sales Invoice uses item-level acc; leave blank)
                row[37] = item_code     # _ITEMCODE
                row[38] = item.get('name','')  # _DESCRIPTION
                row[41] = qty           # _QTY
                row[42] = 'PCS'         # _UOM
                row[43] = unit_price    # _UNITPRICE
                row[47] = 'F'           # _TAXINCLUSIVE
                row[48] = amount        # _AMOUNT
                ws.append(row)

    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


# ── HTTP Handler ───────────────────────────────────────────────────────────────
MIME = {'.html':'text/html','.css':'text/css','.js':'application/javascript',
        '.json':'application/json','.png':'image/png','.ico':'image/x-icon'}

class Handler(BaseHTTPRequestHandler):

    def _body(self):
        n = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(n)) if n else {}

    def _bearer(self):
        a = self.headers.get('Authorization', '')
        return a[7:] if a.startswith('Bearer ') else ''

    def _admin_auth(self):
        return check_admin_session(self._bearer())

    def _merch_auth(self):
        return check_merch_session(self._bearer())  # returns mid or None

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path):
        if not os.path.isfile(path):
            self.send_response(404); self.end_headers(); return
        ext = os.path.splitext(path)[1]
        ct  = MIME.get(ext, 'text/plain')
        with open(path, 'rb') as f: data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', ct + '; charset=utf-8')
        self.send_header('Content-Length', len(data))
        if ext == '.html':
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,PUT,DELETE,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        self.end_headers()

    # ── GET ────────────────────────────────────────────────────────────────────
    def do_GET(self):
        parsed = urlparse(self.path)
        qs     = parse_qs(parsed.query)
        pt     = parsed.path

        # Static pages
        if pt in ('/', '/index.html'):
            self._file(os.path.join(PUB_DIR, 'index.html')); return
        if pt in ('/report', '/report.html'):
            self._file(os.path.join(PUB_DIR, 'report.html')); return
        if pt in ('/payment', '/payment.html'):
            self._file(os.path.join(PUB_DIR, 'payment.html')); return
        if pt in ('/orders', '/orders.html'):
            self._file(os.path.join(PUB_DIR, 'orders.html')); return
        if pt in ('/admin', '/admin.html'):
            self._file(os.path.join(PUB_DIR, 'admin.html')); return

        if pt == '/api/version':
            self._json({'version': VERSION}); return

        if pt == '/api/changelog':
            # Admin-only: the file names merchants and describes internals.
            if not self._admin_auth():
                self._json({'ok': False, 'error': 'Unauthorized'}, 401); return
            path = os.path.join(BASE_DIR, 'CHANGELOG.md')
            try:
                with open(path, encoding='utf-8') as f:
                    text = f.read()
            except Exception:
                text = ''
            self._json({'ok': True, 'version': VERSION, 'changelog': text}); return

        # ── Merchant API ───────────────────────────────────────────────────────
        if pt == '/api/merchant/me':
            mid = self._merch_auth()
            if not mid:
                self._json({'ok': False, 'error': 'Not logged in'}, 401); return
            m = get_merchant(mid)
            if not m:
                self._json({'ok': False, 'error': 'Merchant not found'}, 404); return
            self._json({'ok': True, 'name': m['name'], 'account': m['account'],
                        'member_portal': bool(m.get('member_portal', False))})

        elif pt == '/api/merchant/categories':
            mid = self._merch_auth()
            if not mid:
                self._json({'ok': False, 'error': 'Not logged in'}, 401); return
            m = get_merchant(mid)
            if not m:
                self._json({'ok': False, 'error': 'Merchant not found'}, 404); return
            try:
                CAT_PATH = '/pospal-api2/openapi/v1/customerOpenApi/queryAllCustomerCategory'
                _count_call(mid)
                res = pospal_post(m['appId'], m['appKey'], CAT_PATH, {'appId': m['appId']}, host=m.get('host'))
                if res.get('status') != 'success':
                    self._json({'ok': False, 'message': 'POSPAL error'}); return
                cats = [{'name': c['name'], 'discount': c.get('discount')}
                        for c in (res.get('data') or []) if c.get('enable') == 1]
                self._json({'ok': True, 'categories': cats})
            except Exception as e:
                self._json({'ok': False, 'message': str(e)}, 503)

        elif pt == '/api/merchant/invoice-settings':
            mid = self._merch_auth()
            if not mid:
                self._json({'ok': False, 'error': 'Not logged in'}, 401); return
            self._json({'ok': True, 'settings': _load_inv_settings(mid)})

        elif pt == '/api/merchant/customer':
            mid = self._merch_auth()
            if not mid:
                self._json({'ok': False, 'error': 'Not logged in'}, 401); return
            # uid comes from customerUidStr, which /api/merchant/orders derived
            # server-side — the browser's own customerUid is precision-damaged.
            uid = qs.get('uid', [''])[0].strip()
            if not uid.isdigit():
                self._json({'ok': False, 'error': 'uid required'}, 400); return
            m = get_merchant(mid)
            if not m:
                self._json({'ok': False, 'error': 'Not found'}, 404); return
            try:
                # Short TTL: the invoice prints points/balance, which move.
                c = get_customers(m, [uid], CUST_FRESH_TTL).get(uid)
                if c and (c.get('name') or c.get('phone')):
                    self._json({'ok': True, 'customer': c})
                else:
                    self._json({'ok': False, 'error': 'Not found'})
            except Exception as ex:
                self._json({'ok': False, 'error': str(ex)}, 503)

        elif pt == '/api/merchant/report':
            mid = self._merch_auth()
            if not mid:
                self._json({'ok': False, 'error': 'Not logged in'}, 401); return
            merchant = get_merchant(mid)
            if not merchant:
                self._json({'ok': False, 'error': 'Merchant not found'}, 404); return
            start = qs.get('start', [''])[0]
            end   = qs.get('end',   [''])[0]
            if not start or not end:
                self._json({'ok': False, 'error': 'start and end required'}, 400); return
            try:
                rows, total = run_report(merchant, start, end)
                self._json({'ok': True, 'rows': rows, 'total': total})
            except Exception as ex:
                traceback.print_exc()
                self._json({'ok': False, 'error': str(ex)}, 500)

        elif pt == '/api/merchant/orders':
            mid = self._merch_auth()
            if not mid:
                self._json({'ok': False, 'error': 'Not logged in'}, 401); return
            merchant = get_merchant(mid)
            if not merchant:
                self._json({'ok': False, 'error': 'Merchant not found'}, 404); return
            start = qs.get('start', [''])[0]
            end   = qs.get('end',   [''])[0]
            if not start or not end:
                self._json({'ok': False, 'error': 'start and end required'}, 400); return
            try:
                # Same semantics as run_report: dates older than yesterday are
                # cache-only; today is fetched live (subject to the 30-min cooldown).
                start_hour = int(merchant.get('dayStartHour', 6))
                yesterday  = str(current_business_date(start_hour) - timedelta(days=1))
                calls_before = _api_calls.get(mid, 0)   # so the page can show what this load cost
                all_tickets = []
                for d in dates_between(start, end):
                    tickets = collect_day_tickets(merchant, d, cache_only=d < yesterday)
                    if tickets:
                        all_tickets.extend(tickets)
                all_tickets.sort(key=lambda t: t.get('datetime', ''), reverse=True)
                # uid and customerUid are int64s that lose their last digits in
                # JSON.parse, so send the exact values as strings too — the export
                # posts uidStr back to identify tickets.  Member names come from the
                # cache only; uncached ones are fetched by /api/merchant/customers
                # after render, to keep this request from waiting on dozens of lookups.
                enriched = []
                for t in all_tickets:
                    t = dict(t)          # copy: today's tickets are the live _mem objects
                    t['uidStr'] = str(t.get('uid') or '')
                    uid = t.get('customerUid')
                    if uid:
                        us = str(int(uid))
                        t['customerUidStr'] = us
                        c = cached_customer(mid, us, CUST_NAME_TTL)
                        if c is not None:
                            t['customerName'] = c.get('name') or ''
                    enriched.append(t)
                all_tickets = enriched
                pay_methods = dict(_pay_methods.get(mid, {}))
                pay_methods.update(merchant.get('payOverrides', {}))
                biz_today = str(current_business_date())
                with _c_lock:
                    today_ts = _mem_ts.get(mid, {}).get(biz_today)
                # Quota spent: this request only, plus today's running total.  The total
                # comes from sync state (the only counter that resets at midnight) and
                # covers this app alone.  The limit is whatever the last real Pospal
                # reading said, defaulting to 300 -- never query it here, since
                # queryDailyAccessTimesLog itself costs a call.
                calls_used = max(0, _api_calls.get(mid, 0) - calls_before)
                st         = get_sync_state(mid)
                calls_today = (st.get('api_calls_total_today', 0)
                               if st.get('api_calls_reset_date') == str(date.today()) else 0)
                quota = quota_snapshot(mid)   # None until a reading from today exists
                self._json({'ok': True, 'tickets': all_tickets, 'payMethods': pay_methods,
                            'bizToday': biz_today, 'todayFetchedAt': today_ts,
                            'cooldownSecs': TODAY_FETCH_CD_SECS, 'serverNow': time.time(),
                            'apiCallsUsed': calls_used, 'apiCallsToday': calls_today,
                            'apiCallsLimit': (quota or {}).get('limit', 300),
                            'quota': quota})
            except Exception as ex:
                traceback.print_exc()
                self._json({'ok': False, 'error': str(ex)}, 500)

        elif pt == '/api/merchant/report/export':
            mid = self._merch_auth()
            if not mid:
                self._json({'ok': False, 'error': 'Not logged in'}, 401); return
            merchant = get_merchant(mid)
            if not merchant:
                self._json({'ok': False, 'error': 'Merchant not found'}, 404); return
            start = qs.get('start', [''])[0]
            end   = qs.get('end',   [''])[0]
            if not start or not end:
                self._json({'ok': False, 'error': 'start and end required'}, 400); return
            try:
                import openpyxl
                from openpyxl.styles import Font, PatternFill, Alignment
                from openpyxl.utils import get_column_letter

                rows, total = run_report(merchant, start, end)

                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = 'Sales Report'

                hdr_fill = PatternFill('solid', fgColor='FF6600')
                hdr_font = Font(bold=True, color='FFFFFF', size=10)
                tot_fill = PatternFill('solid', fgColor='FFF7ED')
                tot_font = Font(bold=True, size=10)
                num_fmt  = '#,##0.00'
                center   = Alignment(horizontal='center')
                right    = Alignment(horizontal='right')
                left     = Alignment(horizontal='left')

                HEADERS = [
                    'Business Date', 'Tx', 'Gross Sales', 'Discount', 'Bill Rounding',
                    'Net Amt Excl.', 'Excl. Tax', 'Excl. Charges',
                    'Total Sales', 'Gross Sales (Inclu.)', 'Net Sales w/ Charges', 'Net Total'
                ]
                FIELDS = [
                    'date', 'txCount', 'crossSales', 'discount', 'rounding',
                    'netAmountExclusive', 'tax', 'charges',
                    'totalSales', 'crossSalesInclu', 'netSalesWithCharges', 'netTotal'
                ]
                WIDTHS = [14, 8, 16, 14, 14, 16, 14, 16, 14, 20, 22, 14]

                for ci, (h, w) in enumerate(zip(HEADERS, WIDTHS), 1):
                    cell = ws.cell(row=1, column=ci, value=h)
                    cell.fill = hdr_fill; cell.font = hdr_font
                    cell.alignment = left if ci == 1 else (center if ci == 2 else right)
                    ws.column_dimensions[get_column_letter(ci)].width = w

                for ri, row in enumerate(list(rows) + [total], 2):
                    is_tot = row['date'] == 'TOTAL'
                    for ci, field in enumerate(FIELDS, 1):
                        v = row.get(field, 0)
                        cell = ws.cell(row=ri, column=ci, value=v)
                        if is_tot:
                            cell.fill = tot_fill; cell.font = tot_font
                        if ci == 1:
                            cell.alignment = left
                        elif ci == 2:
                            cell.alignment = center
                        else:
                            cell.number_format = num_fmt; cell.alignment = right

                buf = io.BytesIO()
                wb.save(buf)
                xlsx = buf.getvalue()
                safe_name = ''.join(c for c in merchant.get('name','') if c.isascii() and c not in r'\/:"*?<>|').strip().replace(' ','_') or merchant.get('account','merchant')
                fname = f'Sales_{safe_name}_{start}_{end}.xlsx'
                self.send_response(200)
                self.send_header('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                self.send_header('Content-Disposition', f'attachment; filename="{fname}"')
                self.send_header('Content-Length', len(xlsx))
                self.end_headers()
                self.wfile.write(xlsx)
            except Exception as ex:
                traceback.print_exc()
                self._json({'ok': False, 'error': str(ex)}, 500)

        elif pt == '/api/merchant/payment-report':
            mid = self._merch_auth()
            if not mid:
                self._json({'ok': False, 'error': 'Not logged in'}, 401); return
            merchant = get_merchant(mid)
            if not merchant:
                self._json({'ok': False, 'error': 'Merchant not found'}, 404); return
            start = qs.get('start', [''])[0]
            end   = qs.get('end',   [''])[0]
            if not start or not end:
                self._json({'ok': False, 'error': 'start and end required'}, 400); return
            try:
                result = run_payment_report(merchant, start, end)
                self._json({'ok': True, **result})
            except Exception as ex:
                traceback.print_exc()
                self._json({'ok': False, 'error': str(ex)}, 500)

        elif pt == '/api/merchant/payment-report/export':
            mid = self._merch_auth()
            if not mid:
                self._json({'ok': False, 'error': 'Not logged in'}, 401); return
            merchant = get_merchant(mid)
            if not merchant:
                self._json({'ok': False, 'error': 'Merchant not found'}, 404); return
            start = qs.get('start', [''])[0]
            end   = qs.get('end',   [''])[0]
            if not start or not end:
                self._json({'ok': False, 'error': 'start and end required'}, 400); return
            try:
                import openpyxl
                from openpyxl.styles import Font, PatternFill, Alignment
                from openpyxl.utils import get_column_letter

                result  = run_payment_report(merchant, start, end)
                columns = result['columns']
                rows    = result['rows']
                total   = result['total']

                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = 'Payment Report'

                # Styles
                hdr_fill = PatternFill('solid', fgColor='FF6600')
                hdr_font = Font(bold=True, color='FFFFFF', size=10)
                tot_fill = PatternFill('solid', fgColor='FFF7ED')
                tot_font = Font(bold=True, size=10)
                num_fmt  = '#,##0.00'
                center   = Alignment(horizontal='center')
                right    = Alignment(horizontal='right')

                # Header
                headers = ['Business Date', 'Transactions'] + [c['name'] for c in columns] + ['Total']
                for ci, h in enumerate(headers, 1):
                    cell = ws.cell(row=1, column=ci, value=h)
                    cell.fill = hdr_fill
                    cell.font = hdr_font
                    cell.alignment = center if ci == 2 else (Alignment(horizontal='left') if ci == 1 else right)

                # Data rows
                for ri, row in enumerate(rows, 2):
                    ws.cell(row=ri, column=1, value=row['date'])
                    ws.cell(row=ri, column=2, value=row['txCount']).alignment = center
                    for ci, col in enumerate(columns, 3):
                        v = float(row['byCode'].get(col['code'], 0) or 0)
                        c = ws.cell(row=ri, column=ci, value=v if v else None)
                        c.number_format = num_fmt
                        c.alignment = right
                    tot_cell = ws.cell(row=ri, column=len(columns)+3, value=float(row['total'] or 0))
                    tot_cell.number_format = num_fmt
                    tot_cell.alignment = right

                # Total row
                tr = len(rows) + 2
                ws.cell(row=tr, column=1, value='TOTAL').font = tot_font
                ws.cell(row=tr, column=2, value=total['txCount']).font = tot_font
                ws.cell(row=tr, column=2).alignment = center
                for ci, col in enumerate(columns, 3):
                    v = float(total['byCode'].get(col['code'], 0) or 0)
                    c = ws.cell(row=tr, column=ci, value=v if v else None)
                    c.number_format = num_fmt; c.font = tot_font; c.alignment = right
                    c.fill = tot_fill
                gt = ws.cell(row=tr, column=len(columns)+3, value=float(total['total'] or 0))
                gt.number_format = num_fmt; gt.font = tot_font
                gt.alignment = right; gt.fill = tot_fill

                # Column widths
                ws.column_dimensions[get_column_letter(1)].width = 14
                ws.column_dimensions[get_column_letter(2)].width = 12
                for ci in range(3, len(columns)+4):
                    ws.column_dimensions[get_column_letter(ci)].width = 16

                buf = io.BytesIO()
                wb.save(buf)
                xlsx = buf.getvalue()
                safe_name = ''.join(c for c in merchant.get('name','') if c.isascii() and c not in r'\/:"*?<>|').strip().replace(' ','_') or merchant.get('account','merchant')
                fname = f'Payment_{safe_name}_{start}_{end}.xlsx'
                self.send_response(200)
                self.send_header('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                self.send_header('Content-Disposition', f'attachment; filename="{fname}"')
                self.send_header('Content-Length', len(xlsx))
                self.end_headers()
                self.wfile.write(xlsx)
            except Exception as ex:
                traceback.print_exc()
                self._json({'ok': False, 'error': str(ex)}, 500)

        elif pt == '/api/merchant/check-refunds':
            mid = self._merch_auth()
            if not mid:
                self._json({'ok': False, 'error': 'Not logged in'}, 401); return
            start = qs.get('start', [''])[0]
            end   = qs.get('end',   [''])[0]
            if not start or not end:
                self._json({'ok': False, 'error': 'start and end required'}, 400); return
            refunds = []
            for bdate in dates_between(start, end):
                tickets = _from_disk(mid, bdate)
                if tickets is None:
                    with _c_lock:
                        tickets = _mem.get(mid, {}).get(bdate)
                if not tickets:
                    continue
                for t in tickets:
                    if int(t.get('invalid', 0) or 0) != 0:
                        continue
                    if (t.get('ticketType') or '').upper() == 'SELL_RETURN':
                        raw_dt = t.get('datetime', '')
                        try:
                            doc_date = _dt.strptime(raw_dt[:10], '%Y-%m-%d').strftime('%d/%m/%Y')
                        except Exception:
                            doc_date = bdate
                        amt   = round(float(t.get('totalAmount', 0) or 0), 2)
                        items = [
                            {'name': i.get('name', ''), 'qty': float(i.get('quantity', 1) or 1)}
                            for i in (t.get('items') or [])
                        ]
                        refunds.append({'sn': t.get('sn', ''), 'date': doc_date, 'amount': amt, 'items': items})
            self._json({'ok': True, 'count': len(refunds), 'refunds': refunds})

        elif pt == '/api/merchant/journal-pay-codes':
            mid = self._merch_auth()
            if not mid:
                self._json({'ok': False, 'error': 'Not logged in'}, 401); return
            merchant = get_merchant(mid)
            if not merchant:
                self._json({'ok': False, 'error': 'Merchant not found'}, 404); return
            start = qs.get('start', [''])[0]
            end   = qs.get('end',   [''])[0]
            if not start or not end:
                self._json({'ok': False, 'error': 'start and end required'}, 400); return
            pm = fetch_pay_methods(merchant)   # {code: name}
            seen = []; seen_set = set()
            for bdate in dates_between(start, end):
                for t in (collect_day_tickets(merchant, bdate, cache_only=True) or []):
                    if int(t.get('invalid', 0) or 0) != 0: continue
                    for p in (t.get('payments') or []):
                        code = p.get('code') or 'unknown'
                        if code not in seen_set:
                            seen_set.add(code)
                            seen.append({'code': code, 'name': pm.get(code, code)})
            self._json({'ok': True, 'codes': seen})

        elif pt == '/api/merchant/export-ar':
            mid = self._merch_auth()
            if not mid:
                self._json({'ok': False, 'error': 'Not logged in'}, 401); return
            merchant = get_merchant(mid)
            if not merchant:
                self._json({'ok': False, 'error': 'Merchant not found'}, 404); return
            start       = qs.get('start',       [''])[0]
            end         = qs.get('end',         [''])[0]
            fmt         = qs.get('format',      ['autocount'])[0].lower()
            debtor_code  = qs.get('debtorCode',   [''])[0].strip() or None
            debtor_name  = qs.get('debtorName',   [''])[0].strip() or None
            acc_no       = qs.get('accNo',        [''])[0].strip() or None
            cod          = qs.get('cod',          [''])[0].strip() or None
            inclusive_tax= qs.get('inclusiveTax', [''])[0].strip() or None
            cash_acc     = qs.get('cashAcc',      [''])[0].strip() or None
            bank_acc     = qs.get('bankAcc',      [''])[0].strip() or None
            sales_acc    = qs.get('salesAcc',     [''])[0].strip() or None
            pm_str       = qs.get('paymentMap',   [''])[0].strip()
            payment_map  = json.loads(pm_str) if pm_str else None
            if not start or not end:
                self._json({'ok': False, 'error': 'start and end required'}, 400); return
            try:
                if fmt == 'autocount':
                    data = build_ar_invoice_autocount(merchant, start, end,
                                                      debtor_code=debtor_code,
                                                      acc_no=acc_no, cod=cod,
                                                      inclusive_tax=inclusive_tax)
                    fname = f'AR_Invoice_{start}_to_{end}.xlsx'
                elif fmt == 'journal':
                    data  = build_journal_entry_autocount(merchant, start, end,
                                                          cash_acc=cash_acc,
                                                          bank_acc=bank_acc,
                                                          sales_acc=sales_acc,
                                                          payment_map=payment_map)
                    fname = f'Journal_Entry_{start}_to_{end}.xlsx'
                elif fmt == 'sales':
                    data  = build_sales_invoice_autocount(merchant, start, end,
                                                          debtor_code=debtor_code,
                                                          debtor_name=debtor_name,
                                                          cod=cod)
                    fname = f'Sales_Invoice_{start}_to_{end}.xlsx'
                elif fmt == 'sql_customer':
                    data  = build_customer_invoice_sql(merchant, start, end,
                                                       debtor_code=debtor_code,
                                                       acc_no=acc_no, cod=cod,
                                                       inclusive_tax=inclusive_tax)
                    fname = f'SQL_Customer_Invoice_{start}_to_{end}.xlsx'
                elif fmt == 'sql_journal':
                    data  = build_journal_entry_sql(merchant, start, end,
                                                    cash_acc=cash_acc,
                                                    bank_acc=bank_acc,
                                                    sales_acc=sales_acc,
                                                    payment_map=payment_map)
                    fname = f'SQL_Journal_Entry_{start}_to_{end}.xlsx'
                elif fmt == 'sql_sales':
                    data  = build_sales_invoice_sql(merchant, start, end,
                                                    debtor_code=debtor_code,
                                                    debtor_name=debtor_name,
                                                    cod=cod)
                    fname = f'SQL_Sales_Invoice_{start}_to_{end}.xlsx'
                else:
                    self._json({'ok': False, 'error': f'Unknown format: {fmt}'}, 400); return
                self.send_response(200)
                self.send_header('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                self.send_header('Content-Disposition', f'attachment; filename="{fname}"')
                self.send_header('Content-Length', len(data))
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(data)
            except Exception as ex:
                traceback.print_exc()
                self._json({'ok': False, 'error': str(ex)}, 500)

        elif pt == '/api/merchant/usage':
            mid = self._merch_auth()
            if not mid:
                self._json({'ok': False, 'error': 'Not logged in'}, 401); return
            merchant = get_merchant(mid)

            # peek=1: answer from what is already in memory and never call Pospal.
            # The quota meter's first click uses this, so looking at the number can
            # never cost a call -- only an explicit second click reads it for real.
            if qs.get('peek', [''])[0] == '1':
                with _qc_lock:
                    c = _quota_cache.get(mid)
                    reading = dict(c) if c and c.get('date') == str(date.today()) else None
                snap = quota_snapshot(mid)
                age  = int(time.time() - reading['ts']) if reading and reading.get('ts') else None
                self._json({
                    'ok': True, 'peek': True,
                    'quota'        : snap,
                    'cachedDays'   : cached_count(mid),
                    'apiCallsToday': snap['estUsed'] if snap else _api_calls.get(mid, 0),
                    'apiCallsLimit': (reading or {}).get('limit', 300),
                    'apiCallsLeft' : snap['estLeft'] if snap else None,
                    'source'       : 'memory' if reading else 'none',
                    'cacheAgeSecs' : age,
                    'cooldownSecs' : max(0, 300 - age) if age is not None else 0,
                })
                return

            quota    = fetch_pospal_quota(merchant) if merchant else None
            if quota:
                # Age of the cached reading, so the page can tell the merchant
                # this is a cached number and when a real refresh is possible.
                age = max(0, int(time.time() - quota['ts']))
                self._json({
                    'ok': True,
                    'apiCallsToday': quota['used'],
                    'apiCallsLimit': quota['limit'],
                    'apiCallsLeft' : quota['left'],
                    'cachedDays'   : cached_count(mid),
                    'source'       : 'pospal',
                    'cacheAgeSecs' : age,
                    'cooldownSecs' : max(0, 300 - age),
                    # Same estimate the Transactions page shows, so the two agree
                    'quota'        : quota_snapshot(mid),
                })
            else:
                calls = _api_calls.get(mid, 0)
                self._json({
                    'ok': True,
                    'apiCallsToday': calls,
                    'apiCallsLimit': 300,
                    'apiCallsLeft' : max(0, 300 - calls),
                    'cachedDays'   : cached_count(mid),
                    'source'       : 'local',
                    'quota'        : quota_snapshot(mid),
                })

        # ── Admin API ──────────────────────────────────────────────────────────
        elif pt == '/api/admin/merchants':
            if not self._admin_auth():
                self._json({'ok': False, 'error': 'Unauthorized'}, 401); return
            ms = get_all_merchants()
            # Don't expose password hash or appKey, but include hasAppKey flag
            safe = [{'id': m['id'], 'name': m['name'], 'account': m.get('account',''),
                     'appId': m['appId'], 'debtorCode': m.get('debtorCode',''),
                     'dayStartHour': int(m.get('dayStartHour', 6)),
                     'hasAppKey': bool(m.get('appKey','')),
                     'member_portal': bool(m.get('member_portal', False)),
                     'join_member': bool(m.get('join_member', False))} for m in ms]
            self._json({'ok': True, 'merchants': safe})

        elif pt == '/api/admin/invoice-settings':
            if not self._admin_auth():
                self._json({'ok': False, 'error': 'Unauthorized'}, 401); return
            mid = qs.get('mid', [''])[0]
            if not get_merchant(mid):
                self._json({'ok': False, 'error': 'Merchant not found'}, 404); return
            self._json({'ok': True, 'settings': _load_inv_settings(mid)})

        elif pt == '/api/usage':
            # Admin overview — returns local counts only (fast, no Pospal calls)
            ms = get_all_merchants()
            self._json({'ok': True, 'merchants': [
                {'id': m['id'], 'name': m['name'],
                 'apiCallsToday': _api_calls.get(m['id'], 0),
                 'cachedDays': cached_count(m['id'])}
                for m in ms
            ]})

        elif pt == '/api/admin/sync-status':
            if not self._admin_auth():
                self._json({'ok': False, 'error': 'Unauthorized'}, 401); return
            all_state = _load_sync_state()
            ms        = get_all_merchants()
            result    = []
            for m in ms:
                s = all_state.get(m['id'], {})
                result.append({
                    'id'                    : m['id'],
                    'name'                  : m['name'],
                    'lastDailySyncDate'     : s.get('last_daily_sync_date'),
                    'backfillDate'          : s.get('backfill_date'),
                    'backfillCompleted'     : s.get('backfill_completed', False),
                    'consecutiveNoDataDays' : s.get('consecutive_no_data_days', 0),
                    'apiCallsSyncToday'     : s.get('api_calls_sync_today', 0),
                    'apiCallsSyncLimit'     : SYNC_API_LIMIT,
                    'cachedDays'            : cached_count(m['id']),
                })
            self._json({'ok': True, 'merchants': result})

        elif pt == '/api/admin/sync-trigger':
            if not self._admin_auth():
                self._json({'ok': False, 'error': 'Unauthorized'}, 401); return
            mid = parse_qs(parsed.query).get('merchantId', [''])[0]
            if mid:
                merchant = get_merchant(mid)
                if not merchant:
                    self._json({'ok': False, 'error': 'Merchant not found'}, 404); return
                trigger_sync_for(merchant)
                self._json({'ok': True, 'message': f'Sync triggered for {merchant["name"]}'})
            else:
                threading.Thread(target=sync_all_merchants, daemon=True).start()
                self._json({'ok': True, 'message': 'Sync triggered for all merchants'})

        elif pt == '/api/admin/refresh-pay-methods':
            if not self._admin_auth():
                self._json({'ok': False, 'error': 'Unauthorized'}, 401); return
            mid = parse_qs(parsed.query).get('merchantId', [''])[0]
            if mid:
                merchant = get_merchant(mid)
                if not merchant:
                    self._json({'ok': False, 'error': 'Merchant not found'}, 404); return
                result = fetch_pay_methods(merchant, force=True)
                self._json({'ok': True, 'merchant': merchant['name'], 'count': len(result), 'methods': result})
            else:
                results = {}
                for m in get_all_merchants():
                    try:
                        r = fetch_pay_methods(m, force=True)
                        results[m['name']] = len(r)
                    except Exception as ex:
                        results[m['name']] = f'error: {ex}'
                self._json({'ok': True, 'results': results})

        elif pt.startswith('/api/admin/quota/'):
            # Per-merchant real quota from Pospal (admin only, cached 5 min)
            if not self._admin_auth():
                self._json({'ok': False, 'error': 'Unauthorized'}, 401); return
            mid      = pt[len('/api/admin/quota/'):]
            merchant = get_merchant(mid)
            if not merchant:
                self._json({'ok': False, 'error': 'Merchant not found'}, 404); return
            quota = fetch_pospal_quota(merchant)
            if quota:
                self._json({'ok': True, 'used': quota['used'], 'limit': quota['limit'],
                            'left': quota['left'], 'source': 'pospal'})
            else:
                calls = _api_calls.get(mid, 0)
                self._json({'ok': True, 'used': calls, 'limit': 300,
                            'left': max(0, 300 - calls), 'source': 'local'})

        elif pt == '/api/admin/quotas':
            # Bulk quota for all merchants (concurrent, cached)
            if not self._admin_auth():
                self._json({'ok': False, 'error': 'Unauthorized'}, 401); return
            ms = get_all_merchants()
            quotas = {}
            with ThreadPoolExecutor(max_workers=5) as ex:
                futs = {ex.submit(fetch_pospal_quota, m): m for m in ms}
                for fut in as_completed(futs):
                    m = futs[fut]
                    try:
                        q = fut.result()
                        if q:
                            quotas[m['id']] = {'used': q['used'], 'limit': q['limit'],
                                               'left': q['left'], 'source': 'pospal'}
                        else:
                            raise ValueError('no data')
                    except Exception:
                        c = _api_calls.get(m['id'], 0)
                        quotas[m['id']] = {'used': c, 'limit': 300,
                                           'left': max(0, 300 - c), 'source': 'local'}
            self._json({'ok': True, 'quotas': quotas})

        elif pt.startswith('/api/admin/quota-log/'):
            # 7-day usage log for ONE merchant. Costs exactly 1 Pospal call and
            # is never cached — it only fires when an admin clicks Refresh in
            # the Edit Merchant modal.
            if not self._admin_auth():
                self._json({'ok': False, 'error': 'Unauthorized'}, 401); return
            mid      = pt[len('/api/admin/quota-log/'):]
            merchant = get_merchant(mid)
            if not merchant:
                self._json({'ok': False, 'error': 'Merchant not found'}, 404); return
            if not merchant.get('appKey'):
                self._json({'ok': False, 'error': 'No App Key set for this merchant'}, 400); return
            try:
                rows, qinfo = fetch_pospal_quota_log(merchant)
            except Exception as ex:
                self._json({'ok': False, 'error': str(ex)}, 502); return
            today_str = str(date.today())
            today_row = next((r for r in rows if r['date'] == today_str), None)
            if today_row:
                # We just paid for a fresh reading — seed the list-view cache
                # with it instead of letting the table spend another call.
                with _qc_lock:
                    _quota_cache[mid] = {
                        'used' : today_row['used'],
                        'limit': today_row['limit'],
                        'left' : max(0, today_row['limit'] - today_row['used']),
                        'ts'   : time.time(),
                    }
            self._json({'ok': True, 'rows': rows,
                        'appId': merchant.get('appId'),
                        'externalRows': qinfo['externalRows'],
                        'chainOutlets': qinfo['chainOutlets'],
                        'chainUsed'   : qinfo['chainUsed'],
                        'fetchedAt': int(time.time()),
                        'today': today_row or {'date': today_str, 'used': 0, 'limit': 300}})

        elif pt == '/api/admin/merchant-stats':
            # Activity status + current-month sales for all merchants (disk-cached 5 min)
            if not self._admin_auth():
                self._json({'ok': False, 'error': 'Unauthorized'}, 401); return
            ms    = get_all_merchants()
            stats = {}
            with ThreadPoolExecutor(max_workers=12) as ex:
                futs = {ex.submit(merchant_activity_stats, m): m for m in ms}
                for fut in as_completed(futs):
                    m = futs[fut]
                    try:
                        s = fut.result()
                        stats[s['mid']] = s
                    except Exception:
                        stats[m['id']] = {'mid': m['id'], 'consecutive_empty_days': 0,
                                          'status': 'active', 'month_sales': 0.0}
            self._json({'ok': True, 'stats': stats})

        elif pt == '/api/admin/pending-setup':
            if not self._admin_auth():
                self._json({'ok': False, 'error': 'Unauthorized'}, 401); return
            pending, found = fetch_workflow_pending()
            self._json({'ok': True, 'pending': pending, 'db_found': found})

        elif pt == '/api/download-png':
            token = qs.get('token', [''])[0]
            filename, png_bytes = _fetch_tmp_png(token)
            if png_bytes is None:
                self.send_response(404); self.end_headers(); return
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.send_header('Content-Length', len(png_bytes))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(png_bytes)

        elif pt == '/api/invoice':
            token = qs.get('token', [''])[0]
            html_content = _fetch_tmp_inv(token)
            if html_content is None:
                self.send_response(404)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(b'<!DOCTYPE html><html><body style="font-family:Arial;padding:40px;text-align:center"><h2>Invoice Not Found</h2><p>This invoice link has expired or is invalid.</p></body></html>')
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            encoded = html_content.encode('utf-8')
            self.send_header('Content-Length', len(encoded))
            self.end_headers()
            self.wfile.write(encoded)

        else:
            # Generic static file fallback (serves .js, .css, etc. from public/)
            sp = os.path.join(PUB_DIR, pt.lstrip('/').replace('/', os.sep))
            if os.path.isfile(sp) and os.path.abspath(sp).startswith(os.path.abspath(PUB_DIR)):
                self._file(sp)
            else:
                self.send_response(404); self.end_headers()

    # ── POST ───────────────────────────────────────────────────────────────────
    def do_POST(self):
        parsed = urlparse(self.path)
        qs     = parse_qs(parsed.query)
        pt     = parsed.path

        # ── Merchant login ─────────────────────────────────────────────────────
        if pt == '/api/merchant/login':
            body    = self._body()
            account = body.get('account', '').strip()
            pw      = body.get('password', '')
            m       = get_merchant_by_account(account)
            if not m or m.get('password') != hash_pw(pw):
                self._json({'ok': False, 'error': 'Wrong username or password'}, 401); return
            token = new_merch_session(m['id'])
            self._json({'ok': True, 'token': token, 'name': m['name']})

        # ── Admin: raw pay methods for a merchant ─────────────────────────────
        elif pt.startswith('/api/admin/pay-methods/'):
            if not self._admin_auth():
                self._json({'ok': False, 'error': 'Unauthorized'}, 401); return
            mid = pt[len('/api/admin/pay-methods/'):]
            m   = get_merchant_by_id(mid)
            if not m:
                self._json({'ok': False, 'error': 'Not found'}, 404); return
            try:
                _count_call(mid)
                res  = pospal_post(m['appId'], m['appKey'], PAY_METHOD_PATH,
                                   {'appId': m['appId']}, host=m.get('host'))
                raw  = res.get('data') or []
                self._json({'ok': True, 'raw': raw, 'resolved': fetch_pay_methods(m)})
            except Exception as ex:
                self._json({'ok': False, 'error': str(ex)})

        # ── Admin login ────────────────────────────────────────────────────────
        elif pt == '/api/admin/login':
            body = self._body()
            if body.get('password') == CONFIG.get('adminPassword'):
                self._json({'ok': True, 'token': new_admin_session()})
            else:
                self._json({'ok': False, 'error': 'Wrong password'}, 401)

        # ── Admin: dismiss workflow pending entry ──────────────────────────────
        elif pt == '/api/admin/pending-dismiss':
            if not self._admin_auth():
                self._json({'ok': False, 'error': 'Unauthorized'}, 401); return
            body    = self._body()
            wf_id   = body.get('wf_id', '').strip()
            account = body.get('account', '').strip()
            if wf_id:
                _pending_dismiss(wf_id, account or None)
            self._json({'ok': True})

        # ── Admin: add merchant ────────────────────────────────────────────────
        elif pt == '/api/merchants':
            if not self._admin_auth():
                self._json({'ok': False, 'error': 'Unauthorized'}, 401); return
            body    = self._body()
            name        = body.get('name',       '').strip()
            account     = body.get('account',    '').strip()
            aid         = body.get('appId',      '').strip()
            akey        = body.get('appKey',     '').strip()
            pw          = body.get('password', '123456').strip() or '123456'
            debtor_code = body.get('debtorCode', '').strip()
            day_start_hour = max(0, min(23, int(body.get('dayStartHour', 6) or 6)))
            if not name or not account or not aid or not akey:
                self._json({'ok': False, 'error': 'name, account, appId, appKey required'}, 400); return
            # Check duplicate account
            if get_merchant_by_account(account):
                self._json({'ok': False, 'error': f'Account "{account}" already exists'}, 400); return
            m = add_merchant(name, account, aid, akey, pw, debtor_code, day_start_hour)
            self._json({'ok': True, 'merchant': {'id': m['id'], 'name': m['name'], 'account': m['account']}})

        # ── Admin: reset merchant password ─────────────────────────────────────
        elif pt.startswith('/api/merchants/') and pt.endswith('/reset-password'):
            if not self._admin_auth():
                self._json({'ok': False, 'error': 'Unauthorized'}, 401); return
            mid = pt[len('/api/merchants/'):-len('/reset-password')]
            body = self._body()
            pw   = body.get('password', '123456') or '123456'
            ok   = reset_merchant_password(mid, pw)
            self._json({'ok': ok})

        # ── PNG download — step 1: POST stores PNG, returns one-time token ───────
        elif pt == '/api/download-png':
            try:
                body     = self._body()
                b64      = body.get('data', '')
                filename = body.get('filename', 'qr.png').replace('/', '_').replace('..', '_')
                if b64.startswith('data:'):
                    b64 = b64.split(',', 1)[1]
                png_bytes = _b64mod.b64decode(b64)
                token = _store_tmp_png(filename, png_bytes)
                self._json({'ok': True, 'token': token, 'filename': filename})
            except Exception as ex:
                self._json({'ok': False, 'error': str(ex)}, 400)

        # ── Merchant invoice settings (server-side persistence) ───────────────
        elif pt == '/api/merchant/invoice-settings':
            mid = self._merch_auth()
            if not mid:
                self._json({'ok': False, 'error': 'Not logged in'}, 401); return
            try:
                _save_inv_settings(mid, self._body())
                self._json({'ok': True})
            except Exception as ex:
                self._json({'ok': False, 'error': str(ex)}, 400)

        # ── Admin: edit any merchant's invoice template ────────────────────────
        elif pt == '/api/admin/invoice-settings':
            if not self._admin_auth():
                self._json({'ok': False, 'error': 'Unauthorized'}, 401); return
            try:
                body = self._body()
                mid  = body.get('mid', '')
                if not get_merchant(mid):
                    self._json({'ok': False, 'error': 'Merchant not found'}, 404); return
                settings = _save_inv_settings(mid, body.get('settings') or {})
                self._json({'ok': True, 'settings': settings})
            except Exception as ex:
                self._json({'ok': False, 'error': str(ex)}, 400)

        # ── Member names for the orders table (filled in after the rows render) ──
        elif pt == '/api/merchant/customers':
            mid = self._merch_auth()
            if not mid:
                self._json({'ok': False, 'error': 'Not logged in'}, 401); return
            m = get_merchant(mid)
            if not m:
                self._json({'ok': False, 'error': 'Merchant not found'}, 404); return
            try:
                uids = [str(u) for u in (self._body().get('uids') or []) if str(u).isdigit()]
                found = get_customers(m, uids[:CUST_MAX_FETCH], CUST_NAME_TTL)
                self._json({'ok': True, 'names': {u: (c.get('name') or '') for u, c in found.items()}})
            except Exception as ex:
                self._json({'ok': False, 'error': str(ex)}, 400)

        # ── Transactions export — POST because the page sends the filtered uid list
        elif pt == '/api/merchant/orders/export':
            mid = self._merch_auth()
            if not mid:
                self._json({'ok': False, 'error': 'Not logged in'}, 401); return
            merchant = get_merchant(mid)
            if not merchant:
                self._json({'ok': False, 'error': 'Merchant not found'}, 404); return
            try:
                body  = self._body()
                start = (body.get('start') or '').strip()
                end   = (body.get('end')   or '').strip()
                if not start or not end:
                    self._json({'ok': False, 'error': 'start and end required'}, 400); return
                uids = set(str(u) for u in (body.get('uids') or []))
                if not uids:
                    self._json({'ok': False, 'error': 'No transactions to export'}, 400); return

                # Re-read the same tickets the page is showing.  Cache-only for
                # everything before today, so an export never burns API quota.
                start_hour = int(merchant.get('dayStartHour', 6))
                yesterday  = str(current_business_date(start_hour) - timedelta(days=1))
                picked = []
                for d in dates_between(start, end):
                    for t in collect_day_tickets(merchant, d, cache_only=d < yesterday) or []:
                        if str(t.get('uid')) in uids:
                            picked.append(t)
                # Oldest first: a spreadsheet is read top-down like a ledger, so the
                # month runs 1/8 -> 31/8.  The page keeps newest-first (that route
                # sorts separately) because on screen you want today's rows on top.
                picked.sort(key=lambda t: t.get('datetime', ''))
                if not picked:
                    self._json({'ok': False, 'error': 'No transactions to export'}, 400); return

                # Member names come from the cache only — same as the orders route,
                # so the export never waits on dozens of member lookups.
                for i, t in enumerate(picked):
                    uid = t.get('customerUid')
                    if uid:
                        c = cached_customer(mid, str(int(uid)), CUST_NAME_TTL)
                        if c is not None:
                            t = dict(t); t['customerName'] = c.get('name') or ''
                            picked[i] = t

                pay_methods = dict(_pay_methods.get(mid, {}))
                pay_methods.update(merchant.get('payOverrides', {}))

                xlsx = build_orders_xlsx(
                    merchant, picked, pay_methods,
                    detail=bool(body.get('detail')),
                    pay_cols=body.get('payCols', True) is not False,
                )
                safe_name = ''.join(c for c in merchant.get('name', '')
                                    if c.isascii() and c not in r'\/:"*?<>|').strip().replace(' ', '_') \
                            or merchant.get('account', 'merchant')
                fname = f'Transactions_{safe_name}_{start}_{end}.xlsx'
                self.send_response(200)
                self.send_header('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                self.send_header('Content-Disposition', f'attachment; filename="{fname}"')
                self.send_header('Content-Length', len(xlsx))
                self.end_headers()
                self.wfile.write(xlsx)
            except Exception as ex:
                traceback.print_exc()
                self._json({'ok': False, 'error': str(ex)}, 500)

        # ── Invoice HTML store — POST saves HTML, GET /api/invoice?token= serves it
        elif pt == '/api/invoice-html':
            if not self._merch_auth():
                self._json({'ok': False, 'error': 'Unauthorized'}, 401); return
            try:
                body = self._body()
                html_content = body.get('html', '')
                if not html_content:
                    self._json({'ok': False, 'error': 'No HTML content'}, 400); return
                token = _store_tmp_inv(html_content)
                self._json({'ok': True, 'token': token})
            except Exception as ex:
                self._json({'ok': False, 'error': str(ex)}, 400)

        # ── Cache clear ────────────────────────────────────────────────────────
        elif pt == '/api/cache/clear':
            mid = qs.get('merchantId', [''])[0]
            # Allow merchant to clear their own cache
            if not mid:
                merch_mid = self._merch_auth()
                if merch_mid: mid = merch_mid
            removed = 0
            if mid:
                with _c_lock:
                    _mem.pop(mid, None)
                    _mem_ts.pop(mid, None)
                with _pm_lock: _pay_methods.pop(mid, None)  # re-fetch pay methods next load
                d = os.path.join(CACHE_DIR, mid)
                if os.path.exists(d):
                    for fname in os.listdir(d):
                        if fname.endswith('.json'):
                            os.remove(os.path.join(d, fname)); removed += 1
            else:
                with _c_lock:
                    _mem.clear()
                    _mem_ts.clear()
                with _pm_lock: _pay_methods.clear()
                for folder in os.listdir(CACHE_DIR):
                    fp = os.path.join(CACHE_DIR, folder)
                    if os.path.isdir(fp):
                        for fname in os.listdir(fp):
                            if fname.endswith('.json'):
                                os.remove(os.path.join(fp, fname)); removed += 1
            self._json({'ok': True, 'removed': removed})

        else:
            self.send_response(404); self.end_headers()

    # ── PUT ────────────────────────────────────────────────────────────────────
    def do_PUT(self):
        pt = urlparse(self.path).path
        if pt.startswith('/api/merchants/'):
            if not self._admin_auth():
                self._json({'ok': False, 'error': 'Unauthorized'}, 401); return
            mid  = pt[len('/api/merchants/'):]
            body = self._body()
            dsh  = body.get('dayStartHour')
            dsh  = max(0, min(23, int(dsh))) if dsh is not None else None
            mp   = body.get('member_portal')
            jm   = body.get('join_member')
            m    = update_merchant(mid,
                                   body.get('name',    ''),
                                   body.get('account', ''),
                                   body.get('appId',   ''),
                                   body.get('appKey',  ''),
                                   day_start_hour=dsh,
                                   member_portal=(bool(mp) if mp is not None else None),
                                   join_member=(bool(jm) if jm is not None else None))
            if m: self._json({'ok': True, 'merchant': {'id': m['id'], 'name': m['name'], 'account': m.get('account','')}})
            else: self._json({'ok': False, 'error': 'Merchant not found'}, 404)
        else:
            self.send_response(404); self.end_headers()

    # ── DELETE ─────────────────────────────────────────────────────────────────
    def do_DELETE(self):
        pt = urlparse(self.path).path
        if pt.startswith('/api/merchants/'):
            if not self._admin_auth():
                self._json({'ok': False, 'error': 'Unauthorized'}, 401); return
            mid = pt[len('/api/merchants/'):]
            self._json({'ok': delete_merchant(mid)})
        else:
            self.send_response(404); self.end_headers()

    def log_message(self, fmt, *args):
        print(f'  {args[0]}  {args[1]}')

# ── Start ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print(f'\n  3FS Technology — Pospal Multi-Merchant Report')
    print(f'  ───────────────────────────────────────────────')
    print(f'  Merchant → http://localhost:{PORT}')
    print(f'  Admin    → http://localhost:{PORT}/admin')
    print(f'  Stop     → Ctrl + C')
    # Never print the password: systemd captures stdout into the journal, which put
    # it in plain text where anyone with journalctl could read it.
    print(f'  Admin PW : (set in data/config.json)\n')

    # Flush state to disk on Ctrl+C / SIGTERM before exit
    def _shutdown(sig, frame):
        print('\n  [sync] flushing state before exit…')
        _flush_sync_state()
        raise SystemExit(0)
    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Load persisted sync state into memory (single disk read at startup)
    _sync_state_mem.update(_load_sync_state_from_disk())

    # Restore in-memory _api_calls counter from persisted total so quota display is accurate
    for _mid, _s in _sync_state_mem.items():
        if _s.get('api_calls_reset_date') == str(date.today()):
            _api_calls[_mid] = _s.get('api_calls_total_today', 0)

    # Load persisted pay methods from disk
    _pay_methods.update(_load_pay_methods_from_disk())
    print(f'  [pay_methods] loaded {len(_pay_methods)} merchants from disk')

    # Load persisted member names so they cost no API quota after a restart
    _customers.update(_load_customers_from_disk())
    print(f'  [customers] loaded {sum(len(c) for c in _customers.values())} members from disk')

    # Ensure all existing merchants have a sync state record
    for _m in get_all_merchants():
        init_sync_state(_m['id'])

    # Flush any newly added state records to disk, then start periodic flusher
    _flush_sync_state()
    _start_state_flusher()

    start_tg_bot()

    if os.environ.get('POSPAL_SYNC') == '1':
        start_sync_scheduler()
    else:
        print('  [sync] scheduler disabled (set POSPAL_SYNC=1 to enable)')

    # Prefetch pay methods for all merchants in background (non-blocking)
    def _prefetch_pay_methods():
        ms = get_all_merchants()
        print(f'  [pay_methods] prefetching {len(ms)} merchants in background…')
        with ThreadPoolExecutor(max_workers=20) as ex:
            for m in ms:
                ex.submit(fetch_pay_methods, m)
        print('  [pay_methods] prefetch complete')
    threading.Thread(target=_prefetch_pay_methods, daemon=True).start()

    class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True
    ThreadedHTTPServer(('', PORT), Handler).serve_forever()
