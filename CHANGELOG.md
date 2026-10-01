# Changelog — Pospal Report

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
