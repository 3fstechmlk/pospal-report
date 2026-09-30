# Sales Orders Page — Design Spec
**Date:** 2026-05-02  
**Status:** Approved

## Overview

A new Sales Orders page (`orders.html`) in the merchant portal that replicates the Pospal 销售单据 view. Reads exclusively from the local disk cache — no Pospal API calls. Validated using the **youmiqi有米气** merchant (`07720b38-33ff-11f1-b0e8-02502e7664be`).

---

## Architecture

### New file: `public/orders.html`
- Follows the exact same design system as `report.html` (topbar, brand, CSS variables, datepicker)
- Topbar nav includes: Report | Payment | **Orders** (active) | logout
- Topbar nav on `report.html` and `payment.html` updated to include the Orders link

### New backend route: `GET /api/merchant/orders` in `run.py`
- Auth: `_merch_auth()` cookie check — same as all other merchant routes
- Query params: `start` (YYYY-MM-DD), `end` (YYYY-MM-DD)
- Reads from `cache/{merchantId}/YYYY-MM-DD.json` — no Pospal API calls ever made
- Response: `{ ok: true, tickets: [...], payMethods: { "payCode_101": "Cash", ... } }`
  - `payMethods` built from `data/pay_methods.json` for this merchant; falls back to raw code
- Returns all tickets across the date range; includes invalid tickets flagged but not filtered out server-side

### Client-side only
- Payment method filter, SN search, and pagination all run in JS on the returned array
- No round-trips to server after initial load

---

## Data Mapping

### Summary row (one per ticket)

| Label | Source |
|---|---|
| Receipt No. | `ticket.sn` |
| Date & Time | `ticket.datetime` |
| Type | `ticket.ticketType` → "Sale" / "Refund" |
| Cashier | `ticket.cashier.name` |
| Member | `ticket.customerUid != 0` → UID string, else `—` |
| Qty | `sum(item.quantity)` across all items |
| Gross Amt | `sum(item.totalAmount) + ticket.taxFee + ticket.serviceFee` |
| Net Received | `ticket.totalAmount` |
| Discount | Gross Amt − Net Received (= rounding ± item discounts) |
| Profit | `ticket.totalProfit` |

### Expanded detail (inserted inline below each ticket row)

**Item rows** (one per `ticket.items[]`):
- Name + barcode (e.g. `酱油皇炒面 WOK FRIED SHUNDE NOODLES (2407271815247)`)
- Qty | Unit Price (`item.sellPrice`) | Total (`item.totalAmount`) | Discount amt | Profit (`item.totalProfit`)

**Adjustment rows:**
- `Rounding` — shows `ticket.rounding` as a signed value (negative = round down)
- `Service Tax` — `ticket.taxFee` (Malaysia Service Tax Act 2018; no % displayed)
- `Service Charge` — `ticket.serviceFee` (no % displayed)

**Info line** (full-width, below adjustment rows):
- Table: `ticket.ticketOnTable.tableCardNo` (if present)
- Discount note: e.g. `Rounding (Savings: 0.04, 1x)` — only shown when rounding != 0
- Payment: pay method display name + amount, e.g. `Payment: Debit Card 109.70`

---

## UI Layout

### Filter bar
Left to right:
1. Date range picker — start/end dates, same `datepicker.js` component as `report.html`
2. Payment method dropdown — "All Payment Methods" + one option per distinct pay code in results
3. SN search text input (placeholder: "Receipt No.")
4. **Load** button — fetches from `/api/merchant/orders`; filtering/search apply client-side on results

### Table

**Columns:**  
`Actions | Receipt No. | Date & Time | Type | Cashier | Member | Qty | Gross Amt | Net Received | Discount | Profit`

- **Actions** column: `▶` / `▼` toggle button to expand/collapse inline detail
- Refund rows highlighted with a distinct background (light red tint)
- Invalid tickets (if any) shown with a strikethrough / muted style

### Footer (below table, above pagination)
Shows totals for the **current filtered set** (all pages, not just visible page):  
`Total Orders: N | Gross: X.XX | Net Received: X.XX | Discount: X.XX | Profit: X.XX`

### Pagination
`« First | ‹ Prev | Page X of Y | Next › | Last »`  
50 rows per page, same style as Pospal native UI.

---

## Compliance Notes

- **Service Tax** row label (no percentage): aligns with Malaysia Service Tax Act 2018 display requirements
- **Service Charge** row label (no percentage): restaurant-level charge, distinct from government tax
- Ticket type "SELL_RETURN" displayed as "Refund" and handled as sign-reversed in totals
- `invalid = 1` tickets visible but visually flagged — operators can identify voided transactions

---

## Out of Scope (this version)

- Cashier filter and Member filter (deferred)
- Export to Excel / CSV
- Printing individual receipts
- Live auto-refresh
