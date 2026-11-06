# Changelog — Pospal Report

---

## v1.7.0 — 2026-11-06

### New
- **Activate button for deactivated merchants.** In the merchant list, a
  merchant marked Deactivated now has an **Activate** button. Pressing it turns
  the merchant back on, syncs it straight away and fetches the days it missed
  while deactivated. It will not be deactivated again automatically for the
  next 30 days.

### Fixed
- **Deactivated merchants that start selling again are picked up
  automatically.** A merchant with no sales for 90 days used to stop syncing
  for good, so if it opened later, a day only showed up in its report when
  someone happened to open the report the next morning; other days stayed
  empty. Deactivated merchants are now checked every morning (one API call from
  that merchant's own quota). As soon as a sale shows up, the merchant becomes
  Active again and the days it missed are fetched.

---

## v1.6.0 — 2026-11-05

### New
- **Full-screen landscape report on phones.** Sales Report and Payment Report
  now have an orange rotate button at the top right of the report table. Tap it
  and only the report fills the screen, turned sideways (to the left first, then
  it follows how you hold the phone). The column headers stay on top and the
  date column stays on the left while you scroll. Tap **Exit** to go back.
  On iPhone the page cannot hide Safari's address bar or turn the screen by
  itself, so the table is shown sideways; turn the phone left to read it.

### Improved
- **Report pages fit phone screens.** Sales Report, Payment Report and
  Transactions no longer run off the side of the screen:
  - the top bar uses two rows (name and Log Out on top, the three report tabs below);
  - From / To fill one row and the buttons sit below them;
  - stat cards show two per row;
  - wide tables keep the date column in view while you scroll sideways;
  - pop-up windows never get wider than the screen;
  - the date picker opens from the bottom of the screen with larger dates to tap.
- **Transactions on phones.** An expanded transaction's items, remark and
  Print / WhatsApp buttons stay on screen instead of scrolling sideways with the
  table, and the expand button is no longer cut off.
- **Admin on phones.** Each merchant shows as a card with Edit / PW / Del
  buttons. Pending Setup shows each entry on two lines (company name and stage,
  then account and buttons). Edit Report is hidden on phones because the
  invoice template editor needs a bigger screen.
- **Login pages fit phone screens**, and text boxes no longer make iPhone zoom
  in when you tap them.

---

## v1.5.1 — 2026-11-04

### Fixed
- **Member highlight no longer leaves a stray line.** The orange bar on the
  Member field used to travel to the far left of the Info Fields block when
  Member was ordered first, looking like a misplaced divider. The member row is
  now highlighted by its orange label alone.

---

## v1.5.0 — 2026-11-04

### New
- **Reorder invoice fields right on the preview.** In Edit Report, hover any
  field in the live preview and drag its orange handle to reorder the fields
  inside that section (e.g. put Table before Cashier, or move a totals row).
  Hovering the handle outlines the exact field it will move. The drop line sits
  in one place instead of flickering between two.
- **＋ Add field on every section.** Each card — Header, Info Fields, Items
  Table, Totals, Payment Method, Footer — can now add fields:
  - a **transaction value** (e.g. Time, Member Phone, Total Paid, Barcode), or
  - a **custom field** with your own label and text (supports variables like
    `{total}`, `{member_name}`).
  Added fields show a dashed chip with a × to remove them. The Items table adds
  these as a column (e.g. Barcode).
- **Text Box section.** Add a Text Box, give it a title in Admin, and the
  merchant fills in the content on the Report page. The transaction detail lists
  each Text Box with a checkbox — tick it to include it on that invoice (and
  type the content); leave it unticked to keep it off. A saved default can be
  set per Text Box and edited per invoice.
- **Cleaner centered header.** The "Centered — classic receipt look" layout was
  restyled: a prominent company name, tidy details, a divider, and a spaced
  TAX INVOICE title with a muted No · Date line.

### Fixed
- Hiding a field or resizing a box in the template now survives Save — these
  were previously lost when the template was saved.

---

## v1.4.1 — 2026-10-29

### New

- **Tick-off box in Pending Setup.** Each account in the Pending Setup list now
  has a checkbox next to its Setup button. Click it to tick the account (green
  with a white tick), click again to untick. Ticks are saved on the server, so
  they stay after a page reload and every admin sees the same ticks.

---

## v1.4.0 — 2026-10-29

### New

- **Member portal home-page ads.** In the Client Portal you can now upload up to
  5 promotion images for your member portal home page, add an optional link to
  each, change their order and delete them. Customers see them as a swipeable
  carousel below the welcome card, changing every 5 seconds.

---

## v1.3.5 — 2026-10-22

### New

- **Add Merchant reads Pospal's new credential format.** Pospal now issues
  credentials as two lines, `appId=...` and `appKey=...`. Paste them into the
  template box and the App ID and App Key fields fill in by themselves. The older
  template is still accepted. The field hints now describe the new format: a
  16-character App ID and a 32-character App Key.

### Fixed

- The "✓ Credentials parsed successfully" line never appeared after pasting a
  template. It now shows once the credentials are read.

---

## v1.3.4 — 2026-10-20

### New

- **You can now view a merchant's App Key from Edit Merchant.** The App Key
  field has an eye icon on its right. Click it to show the current key, click it
  again to hide it. The key is only fetched from the server when you click, and
  it is cleared again when you hide it, close the window, or open another
  merchant. Leaving the field blank still keeps the existing key, and merchants
  without a key show no eye icon.

### Security

- The merchant list still never carries App Keys. Showing a key goes through its
  own admin-only request that the browser is told not to cache, and the server
  log records which merchant's key was viewed (never the key itself).

---

## v1.3.3 — 2026-10-01

### New

- **The admin console now shows where a merchant's API quota went.** Opening a
  day in the 7-day quota log splits it by what spent it — Daily Sync, Report
  Pages, Quota Checks, Payment Methods, Member Lookup — instead of just a total.
  Anything Pospal counted that this app cannot account for (the member portal
  shares the same App ID) shows as **Unattributed**, kept separate from the
  existing per-App-ID list so the two kinds of "someone else" do not get mixed up.
- **Every API call is now logged individually.** Clicking a feature, or "View
  all calls with timestamps", opens the exact calls behind that number: the time
  each went out and what came back — the page and ticket count for a ticket
  query, the reading for a quota check, the member's name for a lookup. Failed
  calls are listed in red with the reason. Covers calls this app made, kept for
  8 days; reading any of it costs no API call.

### Fixed

- **The WhatsApp invoice link was unreadable on a phone.** The shared page
  declared no viewport, so phones laid it out for a desktop and shrank the whole
  invoice into a thumbnail at the top of the screen. It now fits the screen it is
  opened on, while Print and Download PDF still produce the A4 layout.
- `sync_state.json` was written in place, which truncates it to zero before
  writing. It now carries the per-feature usage history as well, so an
  interrupted write would have taken every merchant's sync position with it.
  Written atomically now, the same way `merchants.json` already was.

---

## v1.3.2 — 2026-10-01

### Fixed

- **The remarks never showed on a printed invoice.** v1.3.0 added Pospal's product
  and transaction remarks to the invoice, but the pages still asked for
  `invoice-template.js?v=9` while the file itself had changed — so browsers kept
  serving the cached copy without them. The expanded detail and the Excel export
  were unaffected (one is inline in the page, the other is built server-side);
  only Print / PDF was missing them. Bumped to `?v=10`.

---

## v1.3.1 — 2026-10-01

### Fixed

- **Version badge was barely legible.** All four pages drew it as `#52525b` text on
  a `#27272a` chip — 1.93:1, well under the 4.5:1 AA floor. In the admin console it
  was worse than dim: that dark chip sat in the light toolbar between two outlined
  buttons, looking out of place. The admin badge now follows the outlined-button
  style (grey on white, 4.83:1, orange on hover at 4.93:1); on Sales Report,
  Transactions and Payment Report the chip stays dark to match the topbar and only
  the text was lifted to `#a1a1aa` (5.81:1).

---

## v1.3.0 — 2026-10-01

### Fixed

- **A future date could freeze a whole day's sales at zero.** Querying a date that
  had not arrived yet cached Pospal's empty answer to disk. On the day itself that
  empty file was served instead of the live data, so the Transactions, Sales Report
  and Payment pages all read zero — and no API call was made, so nothing corrected
  it until the next 06:00 sync. `fetch_tickets` now refuses future dates outright,
  and the date picker no longer lets one be selected.
- **A stale session left pages looking signed in.** Sessions live in the server's
  memory, so a restart invalidated every token while the browser kept the string.
  Only the Sales Report noticed; Transactions and Payment Report sat there until
  something failed with "Not logged in". All four protected pages now handle a 401
  centrally and return to the sign-in screen.
- **Admin error messages never appeared.** The stylesheet hides `.msg` by default
  and the code cleared the inline style instead of setting it, so a wrong password
  looked like nothing happened. Six places fixed.
- Payment Report read the live Pospal quota on every page load just to show the
  cached-days count, spending API calls for a number held locally. Opening that
  page is free now.

### New

- **API quota meter on all three merchant pages.** The ↻ button is two-stage: the
  first click shows what is already known and costs nothing, a second click reads
  the exact figure from Pospal (that read costs one call). The badge and the
  5-minute countdown survive a page reload.
- **Both Pospal remark fields are now visible.** A product remark shows under its
  line in the expanded detail and on the printed invoice; a transaction remark
  shows as its own panel. Both are in the Excel export as new columns, and the
  invoice template gained toggles for each plus a `{ticket_remark}` placeholder.
- The Transactions page reports what each load cost in API calls, alongside an
  estimate of the day's total usage.

### Security

- The admin password is no longer printed at startup. systemd captured that line
  into the journal, leaving it readable in plain text to anyone with `journalctl`.

---

## v1.2.1 — 2026-08

- Journal export: advanced pay-code mapping
- SALES ON date in descending format

---

## v1.2 — 2026-08

- Per-merchant `dayStartHour`, so shops that close after midnight get their takings
  counted against the right day
- Every export routed through `collect_day_tickets`, so exported figures match the
  on-screen ones exactly

---

## v1.1 — 2026-07

- Sales and Payment export
- Version badge on all pages
- AutoCount / SQL button marks

---

## v1.0 — 2026-06

- Initial release: multi-merchant Pospal sales reporting
- Daily sync with per-merchant API quota budgeting
- Disk-backed ticket cache with backfill and gap-fill
