"""Member-portal home-page ads (002): validation + per-merchant storage.

pospal-report is the only writer of data/member_ads/<merchant id>/ (ads.json +
image files); pospal-member only reads them. Standard library only.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import secrets
import struct
import threading
import traceback
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlparse

MAX_ADS   = 5
MAX_BYTES = 1048576
MAX_LINK  = 500
DECLARED_TYPES = {'image/jpeg', 'image/png', 'image/webp'}
EXT_BY_TYPE    = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp'}
TYPE_BY_EXT    = {v: k for k, v in EXT_BY_TYPE.items()}
MID_RE         = re.compile(r'^[A-Za-z0-9-]{1,64}$')   # merchant id -> directory name
ID_RE          = re.compile(r'^[a-f0-9]{16}$')

LINK_MSG = ('Invalid link（链接无效）. It must start with http:// or https:// '
            'and have a valid domain (max 500 characters).')

# Host rules (review R2): pospal-member reads links with the WHATWG URL parser and drops any
# it cannot parse, so a link is accepted here only if that parser accepts its host as well.
# These rules may be stricter than WHATWG, never looser.
_LABEL_RE   = re.compile(r'^[a-z0-9_-]+$')               # one DNS label after IDNA, lowercased
_NUMERIC_RE = re.compile(r'^([0-9]+|0x[0-9a-f]*)$')      # WHATWG "ends in a number" -> IPv4 parsing
_IPV4_RE    = re.compile(r'^(0|[1-9][0-9]{0,2})$')

# English messages the merchant page can show as-is (design 8.3.5)
MESSAGES = {
    'not_logged_in':        'Not logged in',
    'merchant_not_found':   'Merchant not found',
    'merchant_unsupported': 'This merchant cannot store ads',
    'length_required':      'Content-Length required',
    'bad_length':           'Invalid Content-Length',
    'empty':                'Image is empty',
    'too_large':            'Image is larger than 1 MB',
    'unsupported_type':     'Only JPG, PNG or WebP images are allowed',
    'bad_image':            'The file is not a valid JPG, PNG or WebP image',
    'limit_reached':        'You can upload up to 5 ads',
    'incomplete_body':      'Upload was interrupted',
    'bad_json':             'Invalid request body',
    'bad_link':             LINK_MSG,
    'bad_order':            'Invalid order',
    'ad_not_found':         'Ad not found',
    'ads_unreadable':       'Ad settings could not be read',
    'write_failed':         'Could not save the ad, please try again',
}


class AdsError(Exception):
    def __init__(self, status, code, message=None):
        self.status  = status
        self.code    = code
        self.message = message or MESSAGES.get(code, code)
        super().__init__(f'{status} {code}: {self.message}')


def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# ── Validation ────────────────────────────────────────────────────────────────
def detect_image_type(data: bytes) -> str | None:
    if data[:3] == b'\xFF\xD8\xFF':
        return 'image/jpeg'
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png'
    if len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


# ── Image size from the file header (首页按图片比例自动适配) ───────────────────
# Every reader below works on a bytes object with explicit bounds checks and returns
# None on anything unexpected: never raises, never reads past the end, and every loop
# either advances by at least one byte or stops.
_JPEG_SOF = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}   # C4 = DHT, C8 = JPG, CC = DAC are not frame headers
_JPEG_STANDALONE = frozenset([0x01]) | frozenset(range(0xD0, 0xD8))   # TEM, RST0-7: no length field


def _u16be(b, i):
    return (b[i] << 8) | b[i + 1]


def _exif_orientation(p) -> int:
    """Orientation (1-8) from an APP1 payload, or 0 when absent / unreadable."""
    if len(p) < 14 or p[:6] != b'Exif\x00\x00':
        return 0
    t = p[6:]
    if t[:2] == b'II':
        e = '<'
    elif t[:2] == b'MM':
        e = '>'
    else:
        return 0
    if struct.unpack_from(e + 'H', t, 2)[0] != 42:
        return 0
    off = struct.unpack_from(e + 'I', t, 4)[0]
    if off < 8 or off + 2 > len(t):
        return 0
    count = struct.unpack_from(e + 'H', t, off)[0]
    pos = off + 2
    for _ in range(count):                     # at most 65535 rounds, each bounds-checked
        if pos + 12 > len(t):
            return 0
        tag, typ = struct.unpack_from(e + 'HH', t, pos)
        if tag == 0x0112:
            v = struct.unpack_from(e + 'H', t, pos + 8)[0] if typ == 3 else 0
            return v if 1 <= v <= 8 else 0
        pos += 12
    return 0


def _jpeg_size(b):
    n = len(b)
    if n < 4 or b[0] != 0xFF or b[1] != 0xD8:
        return None
    i, orient = 2, 0
    while i < n:
        if b[i] != 0xFF:                       # every segment must start with a marker
            return None
        while i < n and b[i] == 0xFF:          # fill bytes
            i += 1
        if i >= n:
            return None
        m = b[i]
        if m in _JPEG_STANDALONE:
            i += 1
            continue
        if m == 0x00 or m in (0xD8, 0xD9, 0xDA):   # stuffed byte, second SOI, EOI or scan before any frame header
            return None
        if i + 3 > n:
            return None
        seg = _u16be(b, i + 1)                 # includes the 2 length bytes
        if seg < 2 or i + 1 + seg > n:         # 0 / 1 would never advance; past the end = truncated
            return None
        if m in _JPEG_SOF:
            if seg < 7:
                return None
            h, w = _u16be(b, i + 4), _u16be(b, i + 6)
            if not (w and h):
                return None
            return (h, w) if orient >= 5 else (w, h)      # 5-8: rotated 90°, swap
        if m == 0xE1 and not orient:
            orient = _exif_orientation(b[i + 3:i + 1 + seg])
        i += 1 + seg                           # seg >= 2, so i grows by >= 3
    return None


def _png_size(b):
    if len(b) < 24 or b[:8] != b'\x89PNG\r\n\x1a\n' or b[12:16] != b'IHDR':
        return None
    w, h = struct.unpack_from('>II', b, 16)
    return (w, h) if 0 < w < 2 ** 31 and 0 < h < 2 ** 31 else None


def _webp_size(b):
    if len(b) < 30 or b[:4] != b'RIFF' or b[8:12] != b'WEBP':
        return None
    kind = b[12:16]
    if kind == b'VP8 ':
        if b[23:26] != b'\x9d\x01\x2a':
            return None
        w, h = struct.unpack_from('<HH', b, 26)
        w, h = w & 0x3FFF, h & 0x3FFF
    elif kind == b'VP8L':
        if b[20] != 0x2F:
            return None
        bits = struct.unpack_from('<I', b, 21)[0]
        w, h = (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    elif kind == b'VP8X':
        w = int.from_bytes(b[24:27], 'little') + 1
        h = int.from_bytes(b[27:30], 'little') + 1
    else:
        return None
    return (w, h) if w and h else None


_SIZE_READERS = {'image/jpeg': _jpeg_size, 'image/png': _png_size, 'image/webp': _webp_size}


def image_size(data) -> tuple[int, int] | None:
    """(width, height) as displayed (JPEG EXIF Orientation 5-8 swaps them), or None."""
    if not isinstance(data, (bytes, bytearray)):
        return None
    reader = _SIZE_READERS.get(detect_image_type(data))
    if reader is None:
        return None
    try:
        return reader(bytes(data))
    except (IndexError, struct.error):         # defensive only: the readers bound-check before reading
        return None


def _dim(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 < v < 2 ** 31 else None


def normalize_link(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AdsError(400, 'bad_link', LINK_MSG)
    v = value.strip()                      # trims every Unicode space at the ends (NBSP, U+3000 ...)
    if v == '':
        return None
    if len(v) > MAX_LINK:
        raise AdsError(400, 'bad_link', LINK_MSG)
    # No space or control char (C0, DEL, C1) inside; no format char (zero-width, BOM, bidi) anywhere
    if any(c.isspace() or unicodedata.category(c) in ('Cc', 'Cf') for c in v):
        raise AdsError(400, 'bad_link', LINK_MSG)
    try:
        p = urlparse(v)
        host = p.hostname
        p.port                             # out-of-range / non-numeric port only raises here
    except ValueError:
        raise AdsError(400, 'bad_link', LINK_MSG)
    if p.scheme.lower() not in ('http', 'https') or not host or not _host_ok(p.netloc):
        raise AdsError(400, 'bad_link', LINK_MSG)
    return v


def _host_ok(netloc: str) -> bool:
    if '\\' in netloc:                      # browsers end the host at '\', Python does not
        return False
    hostport = netloc.rpartition('@')[2]
    if hostport.startswith('['):            # IPv6 literal: plain address only (no zone id, no IPvFuture)
        inner, sep, rest = hostport[1:].partition(']')
        if not sep or '%' in inner or (rest and not _port_ok(rest)):
            return False
        try:
            ipaddress.IPv6Address(inner)
        except ValueError:
            return False
        return True
    host, sep, port = hostport.partition(':')
    if sep and not _port_ok(':' + port):
        return False
    if not host.isascii():
        try:
            host = host.encode('idna').decode('ascii')
        except UnicodeError:
            return False
    labels = host.lower().split('.')
    if len(labels) > 1 and labels[-1] == '':
        labels.pop()                        # one trailing dot is fine
    for label in labels:
        if not _LABEL_RE.match(label):      # also rejects empty labels and < > ^ | % * ! ...
            return False
        if label.startswith('xn--') and not _ace_ok(label):
            return False
    if _NUMERIC_RE.match(labels[-1]):       # treated as an IPv4 address: plain dotted quad only
        return len(labels) == 4 and all(_IPV4_RE.match(x) and int(x) <= 255 for x in labels)
    return True


def _port_ok(s: str) -> bool:
    # ':' then nothing or ASCII digits; urlparse has already rejected ports above 65535
    return s.startswith(':') and (s == ':' or (s[1:].isascii() and s[1:].isdigit()))


def _ace_ok(label: str) -> bool:
    # 'xn--' label: must be valid punycode that round-trips through IDNA
    try:
        u = label[4:].encode('ascii').decode('punycode')
        return bool(u) and not u.isascii() and u.encode('idna').decode('ascii') == label
    except UnicodeError:
        return False


def parse_content_length(v) -> int | None:
    if v is None:
        return None
    v = v.strip()
    if not re.fullmatch(r'[0-9]{1,10}', v):     # '-1', '', '1e3', full-width digits all fail
        raise AdsError(400, 'bad_length', 'Invalid Content-Length')
    return int(v)


def _real(p):
    # Windows realpath can return a '\\?\' path when the target is being created by
    # another thread at that moment; drop the prefix so the prefix check stays stable.
    r = os.path.realpath(p)
    if r.startswith('\\\\?\\UNC\\'):
        r = '\\\\' + r[8:]
    elif r.startswith('\\\\?\\'):
        r = r[4:]
    return r


def merchant_dir(root, mid) -> str:
    if not isinstance(mid, str) or not MID_RE.fullmatch(mid):
        raise AdsError(409, 'merchant_unsupported')
    d = os.path.join(root, mid)
    if not _real(d).startswith(_real(root) + os.sep):
        raise AdsError(409, 'merchant_unsupported')
    return d


def _file_path(dir_, entry) -> str:
    # Always rebuilt from the validated id + ext -- never from the stored 'file' value
    p = os.path.join(dir_, f"{entry['id']}.{entry['ext']}")
    if not _real(p).startswith(_real(dir_) + os.sep):
        raise AdsError(500, 'ads_unreadable')
    return p


# ── Per-merchant lock (single process, ThreadingMixIn) ────────────────────────
_locks = {}
_locks_guard = threading.Lock()


def _lock_for(mid):
    with _locks_guard:
        lk = _locks.get(mid)
        if lk is None:
            lk = _locks[mid] = threading.Lock()
        return lk


# ── ads.json ──────────────────────────────────────────────────────────────────
def _load_unlocked(dir_) -> list[dict]:
    """Caller must hold the merchant lock. Missing file -> []. Anything invalid
    -> ads_unreadable (never treated as empty, never silently dropped).
    A legacy top-level 'layout' is ignored (and dropped on the next write); an entry's
    w / h is a display hint only: missing or invalid values are kept as None."""
    try:
        with open(os.path.join(dir_, 'ads.json'), encoding='utf-8') as f:
            doc = json.loads(f.read())
    except FileNotFoundError:
        return []
    except ValueError:                     # bad JSON or bad UTF-8
        raise AdsError(500, 'ads_unreadable')
    except OSError:
        traceback.print_exc()
        raise AdsError(500, 'ads_unreadable')
    if not isinstance(doc, dict):
        raise AdsError(500, 'ads_unreadable')
    raw = doc.get('ads')
    if not isinstance(raw, list) or len(raw) > MAX_ADS:
        raise AdsError(500, 'ads_unreadable')
    out, seen = [], set()
    for e in raw:
        if not isinstance(e, dict):
            raise AdsError(500, 'ads_unreadable')
        ad_id = e.get('id')
        if not isinstance(ad_id, str) or not ID_RE.fullmatch(ad_id) or ad_id in seen:
            raise AdsError(500, 'ads_unreadable')
        fname = e.get('file')
        ext = fname.rpartition('.')[2] if isinstance(fname, str) else ''
        if ext not in TYPE_BY_EXT or fname != f'{ad_id}.{ext}':
            raise AdsError(500, 'ads_unreadable')
        link = e.get('link')
        if link is not None and not isinstance(link, str):
            raise AdsError(500, 'ads_unreadable')
        seen.add(ad_id)
        w, h = _dim(e.get('w')), _dim(e.get('h'))
        if w is None or h is None:
            w = h = None
        out.append({'id': ad_id, 'ext': ext, 'link': link, 'created_at': e.get('created_at'), 'w': w, 'h': h})
    return out


def _entry_doc(a):
    d = {'id': a['id'], 'file': f"{a['id']}.{a['ext']}", 'link': a['link'], 'created_at': a['created_at']}
    if a.get('w') and a.get('h'):              # legacy entries without a size stay without one
        d['w'], d['h'] = a['w'], a['h']
    return d


def _save(dir_, ads):
    tmp = os.path.join(dir_, 'ads.json.tmp')
    doc = {'version': 1, 'updated_at': _now(), 'ads': [_entry_doc(a) for a in ads]}
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, separators=(',', ':'))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, os.path.join(dir_, 'ads.json'))
    except BaseException:
        try:
            os.remove(tmp)                # never leave ads.json.tmp behind
        except OSError:
            pass
        raise


def _save_or_fail(dir_, ads):
    try:
        _save(dir_, ads)
    except OSError:
        traceback.print_exc()
        raise AdsError(500, 'write_failed')


def _pub(a):
    # w / h：后台判断「横竖混放」用；_load_unlocked 已把缺失 / 非法的尺寸归一成 None
    return {'id': a['id'], 'link': a['link'], 'created_at': a['created_at'], 'w': a.get('w'), 'h': a.get('h')}


def public_view(ads) -> list[dict]:
    return [_pub(a) for a in ads]


def _find(ads, ad_id):
    for a in ads:
        if a['id'] == ad_id:
            return a
    raise AdsError(404, 'ad_not_found')


# ── Public operations ─────────────────────────────────────────────────────────
def load(root, mid) -> list[dict]:
    d = merchant_dir(root, mid)
    with _lock_for(mid):
        return _load_unlocked(d)


def add(root, mid, data: bytes) -> tuple[dict, list]:
    if len(data) == 0:
        raise AdsError(400, 'empty')
    if len(data) > MAX_BYTES:
        raise AdsError(413, 'too_large')
    ctype = detect_image_type(data)
    size = image_size(data) if ctype else None
    if size is None:                           # unknown type, or a header we cannot read
        raise AdsError(415, 'bad_image')
    ext = EXT_BY_TYPE[ctype]
    d = merchant_dir(root, mid)
    with _lock_for(mid):
        ads = _load_unlocked(d)
        if len(ads) >= MAX_ADS:
            raise AdsError(409, 'limit_reached')
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            traceback.print_exc()
            raise AdsError(500, 'write_failed')
        while True:
            entry = {'id': secrets.token_hex(8), 'ext': ext, 'link': None, 'created_at': _now(),
                     'w': size[0], 'h': size[1]}
            if any(a['id'] == entry['id'] for a in ads):
                continue
            path = _file_path(d, entry)
            try:
                f = open(path, 'xb')
            except FileExistsError:
                continue
            except OSError:
                traceback.print_exc()
                raise AdsError(500, 'write_failed')
            break
        new = ads + [entry]
        try:
            with f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            _save(d, new)
        except OSError:
            traceback.print_exc()
            try:
                os.remove(path)           # roll back the new image
            except OSError:
                pass
            raise AdsError(500, 'write_failed')
    return _pub(entry), public_view(new)


def set_link(root, mid, ad_id, link) -> tuple[dict, list]:
    link = normalize_link(link)
    d = merchant_dir(root, mid)
    with _lock_for(mid):
        ads = _load_unlocked(d)
        entry = _find(ads, ad_id)
        entry['link'] = link
        _save_or_fail(d, ads)
    return _pub(entry), public_view(ads)


def reorder(root, mid, ids) -> list:
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise AdsError(400, 'bad_order')
    d = merchant_dir(root, mid)
    with _lock_for(mid):
        ads = _load_unlocked(d)
        current = [a['id'] for a in ads]
        if len(ids) != len(set(ids)) or len(ids) != len(current) or set(ids) != set(current):
            raise AdsError(400, 'bad_order')
        by_id = {a['id']: a for a in ads}
        new = [by_id[i] for i in ids]
        _save_or_fail(d, new)
    return public_view(new)


def delete(root, mid, ad_id) -> list:
    d = merchant_dir(root, mid)
    with _lock_for(mid):
        ads = _load_unlocked(d)
        entry = _find(ads, ad_id)
        path = _file_path(d, entry)
        new = [a for a in ads if a['id'] != entry['id']]
        _save_or_fail(d, new)             # ads.json first ...
        try:
            os.remove(path)               # ... then the file; a leftover orphan is harmless
        except FileNotFoundError:
            pass
        except OSError:
            traceback.print_exc()
    return public_view(new)


def image_bytes(root, mid, ad_id) -> tuple[bytes, str]:
    d = merchant_dir(root, mid)
    with _lock_for(mid):
        entry = _find(_load_unlocked(d), ad_id)
        path = _file_path(d, entry)
        try:
            with open(path, 'rb') as f:
                data = f.read()
        except FileNotFoundError:
            raise AdsError(404, 'ad_not_found')
        except OSError:
            traceback.print_exc()
            raise AdsError(500, 'ads_unreadable')
    return data, TYPE_BY_EXT[entry['ext']]
