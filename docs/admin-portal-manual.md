# Admin Portal — Staff Operations Manual

**System:** 3FS Technology Sales Report Portal  
**Portal URL:** `http://5.223.80.199/admin`  
**Last updated:** 2026-04-14

---

## Table of Contents

1. [Logging In](#1-logging-in)
2. [Dashboard Overview](#2-dashboard-overview)
3. [Understanding Merchant Status](#3-understanding-merchant-status)
4. [Adding a New Merchant](#4-adding-a-new-merchant)
5. [Editing a Merchant](#5-editing-a-merchant)
6. [Resetting a Merchant Password](#6-resetting-a-merchant-password)
7. [Checking API Quota](#7-checking-api-quota)
8. [Deleting a Merchant](#8-deleting-a-merchant)
9. [Day Start Hour Setting](#9-day-start-hour-setting)
10. [Common Scenarios & FAQ](#10-common-scenarios--faq)

---

## 1. Logging In

1. Navigate to `/admin` in your browser.
2. Enter the **admin password** and click **Login**.
3. If you enter the wrong password, an error message will appear — check with your team lead for the correct password.
4. The session is stored in your browser tab. Closing the tab will require you to log in again.
5. Click **Log Out** (top-right) when done to clear the session.

> **Note:** The admin login is a **separate** password from merchant accounts. Do not confuse the two.

---

## 2. Dashboard Overview

After logging in you will see the **Merchant Management** table.

### Toolbar

| Element | Purpose |
|---|---|
| Search box | Filter merchants by company name, username, or App ID |
| **All / Active / Inactive 10d / Inactive 30d / Deactivated** pills | Filter merchants by activity status |
| **+ Add Merchant** | Open form to register a new merchant |
| Version badge (e.g. `v1.2.1`) | Current running version of the backend |
| **Log Out** | End your admin session |

### Table Columns

| Column | Description |
|---|---|
| **#** | Row number (sorted by status then monthly sales) |
| **Company Name** | Merchant's business name. A red `NO KEY` badge means the App Key is missing — the merchant **cannot sync** until fixed |
| **Username** | The login account the merchant uses (e.g. `lcc11888`) |
| **Status** | Activity status badge (see Section 3) |
| **This Month (RM)** | Total sales for the current calendar month pulled from cache |
| **Cached** | Number of days of ticket data stored locally on the server |
| **Quota Today** | Pospal API calls used vs. daily limit (e.g. `45/1500 (1455 left)`). Colour: green = healthy, amber = getting low, red = almost exhausted |
| **Actions** | Quota / Edit / PW / Del buttons |

---

## 3. Understanding Merchant Status

| Badge | Meaning |
|---|---|
| **Active** (green) | Merchant has had sales recently |
| **Inactive 10d** (yellow) | No sales for 10+ consecutive days |
| **Inactive 30d** (red) | No sales for 30+ consecutive days |
| **Deactivated** (grey) | No sales for 90+ consecutive days — **auto-sync has stopped** |

> **What to do with Deactivated merchants:**  
> If the merchant is still a customer (e.g. seasonal business, temporary closure), they are fine — their data stays on disk. If they have genuinely stopped using the service, you may delete them to keep the list clean.

---

## 4. Adding a New Merchant

Click **+ Add Merchant** in the toolbar.

### Step 1 — Paste Credentials Template (Recommended)

If you received a Pospal credentials block from the system (formatted like below), paste it into the **Paste Pospal Credentials Template** textarea:

```
====appId appKey====
account : lcc11888
company : LAO CIN CHAO SDN BHD
appID   : abcdef1234567890abcdef1234567890
appKey  : 9876543210
```

The form will **auto-fill** all fields. A green ✓ confirmation will appear when parsing succeeds.

### Step 2 — Fill / Verify Fields

| Field | Required? | Notes |
|---|---|---|
| **Company Name** | Yes | Full legal or trading name, e.g. `LAO CIN CHAO SDN BHD` |
| **Username (account)** | Yes | Pospal account ID, e.g. `lcc11888`. This is also the merchant's login username |
| **Pospal App ID** | Yes | 32-character hex string from Pospal |
| **Pospal App Key** | Yes (Add) | Numeric key from Pospal. Required when adding. Optional when editing (leave blank = keep existing) |
| **Default Password** | Yes (Add) | Initial login password for the merchant. Default: `123456`. You should inform the merchant of this password after setup |
| **Day Start Hour** | Optional | See Section 9. Leave as `6` unless the merchant is 24-hour (use `0`) |

### Step 3 — Save

Click **Save**. A toast notification will confirm success and show: `Merchant added. Login: lcc11888 / 123456`.

**Important:** Tell the merchant their login credentials right away. They log in at the main portal URL (not `/admin`).

---

## 5. Editing a Merchant

Click **Edit** on the relevant row.

- You can update Company Name, Username, App ID, and Day Start Hour.
- **App Key:** Leave blank to keep the existing key. Only fill in if you are updating or adding a missing key.
- **Password is not shown here** — use the **PW** button to reset it separately.
- If you see a yellow warning ("⚠ This merchant has no App Key"), enter the App Key immediately so API sync can work.

Click **Save** when done.

---

## 6. Resetting a Merchant Password

Click **PW** on the relevant row.

1. The current merchant name is shown for confirmation.
2. Enter the new password (default pre-filled: `123456`).
3. Click **Reset**.
4. Inform the merchant of their new password.

> Use this when a merchant forgets their password or requests a change.

---

## 7. Checking API Quota

Each merchant has a **Pospal API daily quota** (typically 1,500 calls/day). The system auto-fetches quota every 2 minutes.

To manually refresh a single merchant's quota:
1. Click the **Quota** button on the relevant row.
2. The cell updates immediately with the latest figure from Pospal.

**Colour guide:**
- Green — plenty of quota remaining
- Amber — under 100 calls left (monitor closely)
- Red — under 50 calls left (API sync may fail for that day)

> If a merchant runs out of quota, their report will show cached data only until the next day when quota resets.

---

## 8. Deleting a Merchant

Click **Del** on the relevant row.

A confirmation dialog will appear. Click **Delete** to confirm.

> **What gets deleted:** The merchant's credentials and login are removed.  
> **What stays:** All cached report data on disk is kept (it does not affect anything since the merchant can no longer log in).

**Only delete merchants who are no longer customers.** There is no undo — you would need to re-add them manually.

---

## 9. Day Start Hour Setting

This setting controls when a **business day** starts for report aggregation.

| Value | Meaning | Use case |
|---|---|---|
| `6` (default) | Business day = 6:00 AM to 5:59 AM next day | Standard merchants |
| `0` | Business day = midnight to midnight (calendar day) | 24-hour outlets (e.g. babaroncafe) |

**How to set:**
- In the Add / Edit modal, find **Day Start Hour (0–23, MYT)**.
- Enter `0` for midnight-to-midnight businesses.
- Enter `6` (or leave default) for all others.

> This setting affects the report, payment summary, and all Excel exports. It does **not** change how the Pospal API is queried — only how data is grouped when displayed.

---

## 10. Common Scenarios & FAQ

### "I need to onboard a new merchant"

1. Get their Pospal credentials (account, appID, appKey) and company name from sales/ops.
2. Click **+ Add Merchant**, paste the credential block or fill manually.
3. Set Day Start Hour to `0` if they are 24-hour; otherwise leave as `6`.
4. Save, then send the merchant their login URL and credentials.

### "A merchant says they can't log in"

1. Search for the merchant in the admin table.
2. Confirm the **Username** field matches what the merchant is typing.
3. Click **PW**, set a new password, save, and share it with the merchant.

### "A merchant's report is empty / not updating"

Check these in order:
1. Does the row show a red `NO KEY` badge? → Click Edit and enter the missing App Key.
2. Is **Quota Today** red or near zero? → Quota exhausted for today; will auto-recover tomorrow.
3. Is the **Cached** column showing 0 days? → The merchant may be newly added; data will appear after the first overnight sync.
4. Is status **Deactivated**? → Sync has stopped. If the merchant is active again, their sync will resume automatically once sales come in.

### "I accidentally set the wrong Day Start Hour"

Click **Edit**, correct the value, and save. The change takes effect immediately for new report views and exports.

### "The Quota column shows `(est)` next to the number"

This means the quota was estimated from usage data, not fetched directly from Pospal. Click the **Quota** button for that merchant to get the real figure.

### "What is the admin password?"

The admin password is set in the server configuration. Check with your team lead or the person who manages the server. It is different from any merchant password.

---

*For technical issues, contact the system administrator.*
