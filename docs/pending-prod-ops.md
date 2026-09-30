# Pending production operations

Things that must be run **on the server**, by hand, at the next deploy.
Each entry stays here until it has been run, then gets struck out with the date.

---

## 1. Delete the future-date cache files left by the `fetch_tickets` bug

**Status:** pending
**Recorded:** 2026-09-30
**Fixed in code by:** the `if bdate > today: return []` guard in `fetch_tickets`
(`run.py`) — the guard stops *new* bad files, it does **not** clean up the
existing ones.

### What is wrong

Before the guard, querying a date that had not arrived yet made `fetch_tickets`
take the historical branch (`bdate != today`) and cache Pospal's empty answer as
`[]`. On the day itself `_from_disk` then served that `[]` — an empty list is not
`None`, so the function returned before reaching the live fetch, and the whole day
read as zero sales until the next 06:00 sync force-refetched it as "yesterday".

### Files found on 2026-09-30 (server 5.223.80.199, `/opt/pospal-report/cache/`)

| Merchant | Account | File | Size | Written |
|---|---|---|---|---|
| 3FS 288 | `3fstech288` | `0772f4c6-33ff-11f1-b0e8-02502e7664be/2026-09-30.json` | 2 B (`[]`) | 2026-09-01 17:52 |
| WANNA BE TRADING (MY) | `uju555my` | `0772d0bd-33ff-11f1-b0e8-02502e7664be/2026-09-30.json` | 2 B (`[]`) | 2026-09-22 14:12 |

**Not affected — do not touch:** `94038d77-989d-4f6b-9683-db2a5a32d111`
(3FS Demo Cafe / `3fsdemo`) has dated files from 2026-09-30 through 2026-12-31,
60–150 KB each, all written 2026-04-15 16:20. The tickets inside carry datetimes
matching their own filenames, so that is deliberately generated demo data, not
bug output.

### Note before running

Both files are dated 2026-09-30. Once the 06:00 sync of 2026-10-01 has run, that
day becomes "yesterday" and gets force-refetched, so these two files repair
themselves and there is nothing left to delete. The script below therefore finds
the files by rule rather than by name, and is safe to run on any date.

### The rule the script uses

Delete a cache file only when **both** hold:

- its filename date is `>= the current business day` (a file for today can only
  have been written ahead of time — the live path keeps today in `_mem`, never on
  disk — and a file for a later date cannot legitimately exist at all), **and**
- its content is an empty array (`size <= 2`) — this is what makes it bug output
  and is what keeps 3FS Demo Cafe's populated future files out of the way.

### Step 1 — dry run (prints only, deletes nothing)

```bash
ssh -i "/c/Users/JONA TAI/.ssh/id_ed25519" -o StrictHostKeyChecking=no root@5.223.80.199 "python3 -c \"
import os, json, datetime
CACHE='/opt/pospal-report/cache'
now=datetime.datetime.now()
biz=(now.date() if now.hour>=6 else now.date()-datetime.timedelta(days=1))
print('current business day:', biz)
hits=[]
for mid in sorted(os.listdir(CACHE)):
    d=os.path.join(CACHE,mid)
    if not os.path.isdir(d): continue
    for f in sorted(os.listdir(d)):
        if not f.endswith('.json'): continue
        if f[:-5] < str(biz): continue
        p=os.path.join(d,f); sz=os.path.getsize(p)
        mark='DELETE' if sz<=2 else 'keep (has content)'
        print('  %-18s %s %s  %d bytes  mtime %s' % (mark, mid, f, sz, datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime('%Y-%m-%d %H:%M')))
        if sz<=2: hits.append(p)
print('to delete:', len(hits))
\""
```

### Step 2 — delete (run only after reading step 1's output)

```bash
ssh -i "/c/Users/JONA TAI/.ssh/id_ed25519" -o StrictHostKeyChecking=no root@5.223.80.199 "python3 -c \"
import os, datetime
CACHE='/opt/pospal-report/cache'
now=datetime.datetime.now()
biz=(now.date() if now.hour>=6 else now.date()-datetime.timedelta(days=1))
n=0
for mid in sorted(os.listdir(CACHE)):
    d=os.path.join(CACHE,mid)
    if not os.path.isdir(d): continue
    for f in sorted(os.listdir(d)):
        if not f.endswith('.json') or f[:-5] < str(biz): continue
        p=os.path.join(d,f)
        if os.path.getsize(p)<=2:
            os.remove(p); n+=1; print('removed', mid, f)
print('removed', n, 'files')
\""
```

### After deleting

Those merchants' next Transactions/Report load for today goes live to Pospal
(1 API call per day in the range) and shows the real figures. No service restart
needed — the files are read from disk on demand.

---

## 2. Nothing else — the rest of this round is plain code, deployed by the normal tar/scp

Recorded 2026-09-30, for context when reading entry 1 at deploy time. These went
out with the code and need no manual step on the server:

- `fetch_tickets` future-date guard (`run.py`) — stops new bad files
- `datepicker.js` / `.css` — future days no longer selectable; `?v=` bumped on
  `orders.html` and `report.html`
- `_count_call` added to the 5 Pospal calls that were never counted
  (`fetch_pospal_quota`, `fetch_pay_methods` ×2, member categories, admin pay
  methods) — after this the local counter finally reflects what this app spends
- `quota_snapshot()` + `_invalidate_quota_cache` keeping the reading as a baseline
  — Transactions and Sales Report now show the same estimated quota figure
- `PORT` reads the `PORT` env var (defaults to 8080, so the server is unaffected)
- central 401 handling on the four protected pages (a stale token no longer leaves
  a page looking logged in); `payment.html` gained the `if (!TOKEN)` check the other
  merchant pages already had
- `public/quota-meter.js` (new file) — the shared quota badge, two-stage refresh:
  1st click reads memory (`/api/merchant/usage?peek=1`, free), 2nd click spends one
  call.  Mounted on Sales Report, Payment Report and Transactions; Sales Report's
  private copy of that logic and its 8 now-orphaned CSS rules were removed
- `/api/merchant/usage?peek=1` (new, `run.py`) — answers from memory, never calls Pospal
- `payment.html` no longer reads the live quota just to show "Cached: N days" on
  entry; it uses `peek=1`, so opening that page costs nothing
- `admin.html` error messages now use `display:'block'` (6 places) — `.msg` carries
  `display:none`, so `''` had been leaving every message invisible
- `payment.html` was still on `datepicker.js?v=5` / `css?v=4` and so had missed the
  future-date fix; all three pages are on `js?v=6` / `css?v=5` now
- quota meter kept to one line by shortening the hint text; the hint hides under
  1450px (its text stays in the tooltip).  The meter sits far right on all three
  pages via `margin-left:auto`, matching Sales Report and Payment Report
- the meter peeks once on mount (free), so the badge and the 5-minute countdown
  survive a page reload instead of resetting to blank; the mount peek deliberately
  does not arm the button, so spending a call still takes a deliberate click
- Pospal's two remark fields are now surfaced: `items[].remark` (Product Remark)
  under each line in the expanded detail, `remark` (Transaction Remark) as a pill,
  and both as new last columns in the export ('Remark' on Transactions, 'Item
  Remark' on Line Items)
- the printed invoice shows both too (`public/invoice-template.js`): a per-line
  remark under the item description and a 'Transaction Remark' panel above the
  invoice note.  Each has a Layout toggle (`item_remark`, `pos_remark`) and there
  is a new `{ticket_remark}` placeholder for Text blocks; the editor's sample
  ticket carries both so the preview shows them
- the invoice panel for the note the user types on the Transactions page is
  labelled 'Additional Remark' (was plain 'Remark', which read as a twin of the
  Pospal one).  Same wording on the input's label and on the WhatsApp line
