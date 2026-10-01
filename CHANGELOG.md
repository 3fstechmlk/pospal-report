# Changelog — Pospal Report

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
