# Sales Orders Page — Implementation Plan
Date: 2026-05-02
Spec: docs/superpowers/specs/2026-05-02-sales-orders-design.md

## Overview

Build a Sales Orders page (`public/orders.html`) for the merchant portal that replicates the Pospal 销售单据 view. A new `GET /api/merchant/orders` route in `run.py` reads exclusively from disk cache (no API calls). All filtering and pagination run client-side in JS. Validated against the youmiqi有米气 merchant.

## Prerequisites
- [ ] Server running: `python3 run.py` on port 8080
- [ ] youmiqi有米气 cache populated (files exist under `cache/07720b38-33ff-11f1-b0e8-02502e7664be/`)

---

## Tasks

### Task 1: Add `/orders` page route to `run.py`
**What:** Register the new static page so the server serves it. Add two lines in `do_GET` alongside the existing `/report` and `/payment` routes.
**Files:** `run.py`
**Depends on:** None
**Done when:** `GET /orders` returns HTTP 200 (file-not-found is OK at this point; just the route exists).

---

### Task 2: Add `GET /api/merchant/orders` endpoint to `run.py`
**What:** New route in `do_GET`. Auth via `_merch_auth()`. Accepts `start` and `end` query params (YYYY-MM-DD). For each date in range, call `collect_day_tickets(merchant, date, cache_only=True)` — this respects any merchant `dayStartHour` offset. Merge all tickets into one flat list. Build `payMethods` dict from `_pay_methods.get(merchant['id'], {})`, merged with merchant `payOverrides` if present. Return `{ ok: true, tickets: [...], payMethods: {...} }`.
**Files:** `run.py`
**Depends on:** Task 1 (same edit block)
**Done when:** `curl "http://localhost:8080/api/merchant/orders?start=2026-04-10&end=2026-04-11"` (with valid session cookie) returns a JSON object with `ok: true`, a `tickets` array, and a `payMethods` dict.

---

### Task 3: Create `public/orders.html` — shell, CSS, topbar, filter bar
**What:** Create the file. Copy the full CSS variable block and topbar structure from `report.html`. Topbar nav: `Sales Report | Payment Report | Orders (active)`. Filter bar contains: date range inputs (same `id="s"` / `id="e"` pattern), a `<select id="payFilter">` dropdown (initially just "All Payment Methods"), a text input `id="snSearch"` with placeholder "Receipt No.", and a Load button `id="bLoad"`. Include `<script src="/datepicker.js?v=5">` and wire up `new DateRangePicker('s', 'e', () => {})`. Add empty `<div id="content">` placeholder where table will go.
**Files:** `public/orders.html` (create)
**Depends on:** None
**Done when:** `http://localhost:8080/orders` loads without JS errors; topbar shows correct nav; date pickers work; filter bar renders correctly.

---

### Task 4: Implement JS fetch + payment method dropdown population
**What:** Add JS in `orders.html`. On Load button click: read `s`/`e` dates, call `GET /api/merchant/orders?start=...&end=...`, show a loading spinner inside `#content` during fetch, handle errors with an inline error message. On success, store tickets in a module-level variable `allTickets`. Build the payment method dropdown from the union of pay codes present in the returned tickets, using `payMethods` for display names; prepend "All Payment Methods" option. Call a `render()` function (stub for now).
**Files:** `public/orders.html`
**Depends on:** Task 2, Task 3
**Done when:** Loading a date range populates the pay method dropdown with the correct options from that merchant's data; console shows ticket count.

---

### Task 5: Implement summary table rendering
**What:** Add `render()` function. Applies current filter state (pay method + SN search) to `allTickets` to produce `filteredTickets`. Renders a `<table>` inside `#content` with columns: `Actions | Receipt No. | Date & Time | Type | Cashier | Member | Qty | Gross Amt | Net Received | Discount | Profit`. Each data row is a `<tr data-uid="...">`. Compute per-row values per the spec data mapping:
- Gross Amt = `sum(item.totalAmount) + taxFee + serviceFee`
- Discount = Gross Amt − `totalAmount`
- Type: `SELL_RETURN` → "Refund", else "Sale"
- Member: `customerUid != 0` → UID string, else `—`

Apply row styling: light red background for Refund rows; muted/strikethrough for `invalid = 1`.  Actions column has a `▶` button per row (click handler registered but expand logic added in Task 6).
**Files:** `public/orders.html`
**Depends on:** Task 4
**Done when:** Loading a date range shows a table with correct row counts and correct values in all columns (verify one row manually against the cache JSON).

---

### Task 6: Implement expand/collapse detail rows
**What:** Wire up the `▶` / `▼` toggle. On expand, insert a detail block immediately after the ticket row as a `<tr class="detail-row">` containing a nested table with:
1. One row per `ticket.items[]`: name + `(barcode)`, qty, unit price (`item.sellPrice`), total (`item.totalAmount`), discount amount (`item.sellPrice × qty − item.totalAmount`), profit (`item.totalProfit`)
2. Rounding row: label "Rounding", value = `ticket.rounding` (signed)
3. Service Tax row: label "Service Tax", value = `ticket.taxFee` (only shown if `taxFee > 0`)
4. Service Charge row: label "Service Charge", value = `ticket.serviceFee` (only shown if `serviceFee > 0`)
5. Info line (full-width cell): table card (`ticketOnTable.tableCardNo` if present) · rounding note if `rounding != 0` · payment method name + amount from `ticket.payments[]`

On collapse, remove the detail row. Toggle button label flips between `▶` and `▼`.
**Files:** `public/orders.html`
**Depends on:** Task 5
**Done when:** Clicking `▶` on any row expands to show correct item rows and adjustment rows; clicking `▼` collapses; info line shows table number and payment method correctly.

---

### Task 7: Client-side filtering, footer totals, and pagination
**What:** Three pieces wired together in `render()`:

**Filtering:** Before rendering, filter `allTickets`:
- Payment method: keep tickets where any `ticket.payments[].code` matches selected pay code (or "all")
- SN search: case-insensitive substring match on `ticket.sn`

**Footer totals:** Below the table, render a summary bar showing totals across the entire `filteredTickets` array (all pages): `Total Orders: N | Gross: X.XX | Net Received: X.XX | Discount: X.XX | Profit: X.XX`. For Refund tickets, negate `totalAmount` and `totalProfit` in totals.

**Pagination:** Slice `filteredTickets` into pages of 50. Render only the current page's rows. Below the footer, render: `« First ‹ Prev  Page X of Y  Next › Last »` as clickable controls (disabled when at boundary). Page resets to 1 when filters change.
**Files:** `public/orders.html`
**Depends on:** Task 6
**Done when:** Selecting a payment method filter correctly narrows rows and updates footer totals; SN search filters to matching receipts; pagination controls work correctly across page boundaries; footer totals always reflect the full filtered set not just the visible page.

---

### Task 8: Update topbar nav in `report.html` and `payment.html`
**What:** In both files, add an `<a href="/orders" class="nav-link">Orders</a>` link to the topbar nav, between "Payment Report" and the version badge.
**Files:** `public/report.html`, `public/payment.html`
**Depends on:** Task 3
**Done when:** The Orders link appears in the topbar on both pages; clicking it navigates to `/orders`; the active styling is correct on each respective page.
