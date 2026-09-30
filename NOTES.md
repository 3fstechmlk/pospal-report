# Pospal Report — Project Notes

## Server
- **IP**: `root@5.223.80.199`
- **Path**: `/opt/pospal-report`
- **Service**: `systemctl restart pospal`
- **Deploy**: `bash deploy.sh` (rsync + restart) — always run after any code change
- **Timezone**: UTC (MYT = UTC+8)

## Sync Schedule
- Runs **once per day at MYT 06:00** (UTC 22:00)
- Controlled by env var `POSPAL_SYNC=1` in `/etc/systemd/system/pospal.service`
- Local (`python3 run.py`) does NOT run sync — server only
- On service start: runs immediately ONLY if today's sync hasn't happened yet (prevents quota waste on redeploy)

## Sync Logic
- `SYNC_API_LIMIT = 250` calls per merchant per day
- **Pay methods refresh FIRST** (2 calls per merchant), then ticket sync — prevents quota exhaustion
- Pay methods refresh tracked in `sync_state` (`pm_refresh_date`) — survives restarts, no duplicate fetches
- Business date uses **MYT time** (UTC+8) — server is UTC so always add +8 before checking 06:00 cutoff
- Cached dates (on disk) cost 0 API calls
- Yesterday is always re-fetched fresh (disk cache deleted before sync)
- Backfill: goes backwards in history until 30 consecutive empty days (`BACKFILL_STOP_DAYS`)
- Report views: `cache_only=True` for dates older than yesterday — no API call if not yet synced

## Quota Management
- Pospal limit: 300 calls per merchant per day
- Our sync cap: 250 calls
- Pay methods: 2 extra calls per day (runs before sync)
- **DO NOT restart service repeatedly** — each restart that triggers sync burns 2 quota calls × all merchants
- If quota exhausted today, missing data will auto-recover at next 06:00 MYT sync
- **Checking the quota costs quota.** `queryDailyAccessTimesLog` consumes 1 call
  every time it runs — verified 2026-08-26 on 3fstech288: three calls in a row
  returned 13 → 14 → 15. Failed requests are charged too. This is why
  `fetch_pospal_quota` caches for 5 minutes; that cache is a cost guard, not a
  performance tweak — do not remove it to make the badge "live".
- Never auto-poll the quota. A frontend `setInterval` multiplies by the merchant
  count: a panel left open all day at one poll per 6 min would burn ~240
  calls/merchant/day against a 300 limit.
- Normal merchants use only ~4–11 calls/day, so 300 is roomy. The real risk has
  always been our own polling code, not merchant activity.

## Quota Log (Admin → Edit Merchant → API Quota)
- `fetch_pospal_quota_log()` + `GET /api/admin/quota-log/{mid}` — 1 call returns
  up to **7 days**; Pospal rejects `endDate - beginDate > 7` (and still charges).
- Manual only. Opening the Edit Merchant modal fires nothing; only the Refresh
  button spends a call.
- **Pospal returns one row per appId in the merchant's CHAIN, not just the appId
  you authenticated with.** A merchant still has exactly one appId — the extra
  rows are its sibling outlets. Verified 2026-08-27: querying one Butter & Olive
  outlet returned 56 rows (8 appIds × 7 days); all 7 foreign appIds resolved
  against `merchants.json` to our own merchants — BOCHERAS, BOAmpang, BOMegah,
  BOMalim, deescafesecondfloor, butterolivebatupahat and OliveHQ (the HQ).
  So that traffic was **our own sync doing the other outlets**, not third parties.
- Rows MUST still be filtered by our own `appId`, or the "used today" figure
  silently shows a sibling outlet's usage. Foreign appIds are resolved back to
  merchant names for the UI; one that does not resolve is flagged EXTERNAL and is
  genuinely another company's application.
- **Open question:** whether the 300/day limit is per-appId or shared across the
  chain. Every row reports `limitTimes: 300` and counts independently, which
  points to per-appId — but it is unconfirmed. If it turns out to be shared, the
  design is unsafe: `SYNC_API_LIMIT = 250` is applied *per merchant*, so an
  8-outlet chain could in theory issue 2000 calls against a single 300 pool. It
  has never bitten us because normal daily use across the whole chain is ~124.
- Results are cached per merchant in the browser's `localStorage`
  (`adm_quota_logs_v1`), so reopening a merchant shows the last fetch — with its
  timestamp — instead of paying for another call.

## Pospal API
- Server: `https://area9-win.pospal.cn`
- Signature: `MD5(appKey + compact_json).upper()`
- Header: `data-signature`, `time-stamp`
- Daily quota: 300 calls per merchant (Pospal limit)

## Pay Methods
- Priority: `KNOWN_PAY_CODES` → `queryAllPayMethod` → `queryMyPayMethod` showName → `payOverrides`
- `payOverrides` in `data/merchants.json` = highest priority, permanent override
- Use payOverrides for merchants with deactivated/historical codes that API no longer returns

## Admin Portal
- URL: `/admin` (password: see `data/config.json`)
- Merchants with no appKey show red **NO KEY** badge
- Edit modal warns when appKey is missing

## Telegram Bot
- Bot: `@ThreeFS_bot`
- Token + Chat ID in `data/config.json`
- Commands: `/status` (sync status, next run time), `/help`
- Auto-notifications: sync start, sync done (with duration + merchant count), sync error
- First sync after startup does NOT send notification (avoids noise on redeploy)

## Important Fixes Applied
| Date | Fix |
|---|---|
| 2026-08-27 | Quota log filters by our own `appId`, then resolves the rest against `merchants.json`. Pospal returns one row per appId **in the chain** — a Butter & Olive outlet came back with all 8 outlets (56 rows). Unfiltered, the "today" figure showed a sibling outlet's usage. Foreign ids that do not resolve are flagged EXTERNAL. |
| 2026-08-26 | `_save_ms` switched to atomic write (`.tmp` + `os.replace`), matching `pay_methods.json` / `customers.json`. Previously a kill/OOM mid-save could leave `merchants.json` permanently truncated (reproduced: 260581 → 129221 bytes, unparseable) — and the 22:00 `backup.sh` would then archive the broken file. |
| 2026-08-26 | Admin → Edit Merchant gained an API Quota section (manual refresh, 7-day log, 1 call); report page badge gained a cache-cooldown hint. Root-level duplicate HTML files moved to `legacy/` — `run.py` only ever served `public/`. |
| 2026-04-16 | Fixed `last_daily_sync_date` bug: now tracks `biz_yesterday` (the date fetched) instead of `today` (UTC calendar). Old logic caused restarts between MYT 06:00–08:00 to pre-mark the UTC day as synced, making the 22:00 UTC scheduled sync skip it. Result: every other day missed (Apr 12, Apr 14). |
| 2026-04-16 | Ran `recover_missing_dates.py` to backfill Apr 12 + Apr 14 for 762 merchants (1513 files fetched, 8 failed due to quota — auto-recover tomorrow) |
| 2026-04-16 | Added Step 1.5 gap-fill: each sync checks last 3 business days before yesterday; any missing cache files are fetched immediately. Safety net so a missed day is recovered at the next sync instead of staying empty permanently. |
|---|---|
| 2026-04-10 | pay_methods refresh moved BEFORE ticket sync |
| 2026-04-10 | payOverrides added for SEBUNGKUS (HHW FOODS) — payCode 9/107/110/111/123/130/131/136 |
| 2026-04-10 | payOverrides added for 有米气 GENTING (palaceyoumiqi) |
| 2026-04-10 | Recovered appKeys for 10 merchants with `**` prefix (matched by appId) |
| 2026-04-10 | Admin UI shows NO KEY badge + warning when merchant has no appKey |
| 2026-04-10 | Report views: cache_only=True for old dates — no API call if not yet synced |
| 2026-04-11 | Sync changed from every hour to once daily at MYT 06:00 |
| 2026-04-11 | Sync scheduler only runs on server (POSPAL_SYNC=1 env var) |
| 2026-04-11 | Business date fixed to use MYT time (was UTC, caused biz_yesterday to be wrong) |
| 2026-04-11 | Telegram bot added — /status command + sync notifications |
| 2026-04-11 | pay_methods refresh persisted in sync_state — no duplicate fetches after restart |
| 2026-04-11 | Startup sync skipped if today's sync already ran — prevents quota waste on redeploy |
