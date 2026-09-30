"""
migrate_biz_day.py
------------------
One-time migration: convert existing cache files from calendar-day (00:00–23:59)
to business-day (06:00–next day 05:59) format.

For each business date D:
  new D.json = tickets from old D.json where time >= 06:00
             + tickets from old D+1.json where time < 06:00

Safe to run multiple times (idempotent — skips already-migrated files).
"""

import json, os, sys
from datetime import date, timedelta, datetime

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cache')
MIGRATED_MARKER = '__biz_day_migrated__'

def ticket_time(t):
    """Return time portion of ticket datetime as HH:MM:SS string."""
    dt = t.get('datetime', '')
    if len(dt) >= 19:
        return dt[11:19]
    return '00:00:00'

def migrate_merchant(mid_dir):
    files = sorted(f for f in os.listdir(mid_dir) if f.endswith('.json'))
    dates = [f[:-5] for f in files]  # strip .json

    if not dates:
        return 0

    # Check if already migrated
    marker = os.path.join(mid_dir, MIGRATED_MARKER)
    if os.path.exists(marker):
        return 0

    modified = 0
    for i, d in enumerate(dates):
        path_d = os.path.join(mid_dir, d + '.json')
        try:
            with open(path_d, encoding='utf-8') as f:
                tickets_d = json.load(f)
        except Exception:
            continue

        # tickets from D where time >= 06:00
        from_d = [t for t in tickets_d if ticket_time(t) >= '06:00:00']

        # tickets from D+1 where time < 06:00 (early morning of next calendar day)
        from_next = []
        if i + 1 < len(dates):
            next_d = str(date.fromisoformat(d) + timedelta(days=1))
            if dates[i + 1] == next_d:
                path_next = os.path.join(mid_dir, next_d + '.json')
                try:
                    with open(path_next, encoding='utf-8') as f:
                        tickets_next = json.load(f)
                    from_next = [t for t in tickets_next if ticket_time(t) < '06:00:00']
                except Exception:
                    pass

        new_tickets = from_d + from_next

        # Only rewrite if something changed
        if len(new_tickets) != len(tickets_d) or from_next:
            with open(path_d, 'w', encoding='utf-8') as f:
                json.dump(new_tickets, f, ensure_ascii=False, separators=(',', ':'))
            modified += 1

    # Write migration marker
    with open(marker, 'w') as f:
        f.write(datetime.now().isoformat())

    return modified

def main():
    if not os.path.isdir(CACHE_DIR):
        print('No cache directory found. Nothing to migrate.')
        return

    merchants = [d for d in os.listdir(CACHE_DIR)
                 if os.path.isdir(os.path.join(CACHE_DIR, d))]
    print(f'Migrating {len(merchants)} merchants…')

    total_modified = 0
    skipped = 0
    for m in sorted(merchants):
        mid_dir = os.path.join(CACHE_DIR, m)
        marker  = os.path.join(mid_dir, MIGRATED_MARKER)
        if os.path.exists(marker):
            skipped += 1
            continue
        mod = migrate_merchant(mid_dir)
        total_modified += mod
        if mod:
            print(f'  {m}: {mod} files updated')

    print(f'\nDone. {total_modified} files updated, {skipped} merchants already migrated.')

if __name__ == '__main__':
    main()
