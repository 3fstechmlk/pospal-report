# Sales Orders Optimization — Implementation Plan
Date: 2026-05-03
Spec: docs/superpowers/specs/2026-05-03-orders-optimization-design.md

## Overview

All changes are in `public/orders.html` only — no backend changes needed. The work replaces the current dark-themed page with a light-theme version that matches `report.html`/`payment.html`, adds two new table columns (实收不含税, 消费税), replaces the single-row footer with a three-row sales/refunds/net summary, and adds an Expand All toggle.

## Prerequisites
- [ ] Server running: `python3 run.py` on port 8080
- [ ] Logged in as youmiqi to verify UI changes live

---

## Tasks

### Task 1: Replace CSS — dark theme → light theme
**What:** Delete the entire current `<style>` block in `orders.html` and replace with the light-theme CSS system from `report.html`. Copy across: CSS variables (`--or`, `--dk`, `--gy`, `--bd`, `--bg`, `--wh`, `--re`), body font stack (system fonts, no Google Fonts import), `.topbar`, `.brand`, `.nav-link`, `.nav-link.active`, `.btn-logout`, `.fbar`, `.btn`, `.btn-p`, `.btn-g`, `.stats`/`.sc` card system, `.tc` table container, `thead th`, `tbody tr/td` styles, loading spinner, error bar, pagination. Add new classes needed only for orders: `.footer-summary` (three-row footer container), `.fs-row` (one summary row), `.fs-sale`/`.fs-refund`/`.fs-net` row variants, `.expand-all-btn`.
**Files:** `public/orders.html`
**Depends on:** None
**Done when:** Page loads at `http://localhost:8080/orders` with white background, orange brand, dark topbar — visually matching `report.html`. No console errors.

---

### Task 2: Update HTML shell — topbar, filter bar, stats strip
**What:** Rewrite the body HTML (not JS) to match the report.html structure:
- Topbar: use `.topbar`/`.brand`/`.nav-link` classes; Orders link gets `.active`
- Filter bar: wrap in `.fbar` white card; labels use `.fbar label` style; Load button uses `.btn.btn-p`; payment select and SN input styled as plain bordered inputs matching report.html
- Stats strip: change from 6 `.sc` dark cards to 6 `.sc` white cards in a `.stats` flex row; update `id` attributes to match Task 3 (`id="sOrd"`, `id="sAR"`, `id="sNet"`, `id="sTax"`, `id="sSvc"`, `id="sProfit"`); key values get `.val.or` class
- Table container: wrap table in `.tc` white card
**Files:** `public/orders.html`
**Depends on:** Task 1
**Done when:** Topbar, filter bar, stats cards, and table container all render with the correct light-theme styles. Stats strip is hidden until data loads (controlled by JS toggle).

---

### Task 3: Update stats calculation — 总应收 = totalAmount − taxFee
**What:** Rewrite `calcStats(s, e)` in the JS section:
- `总应收 (sAR)` = `sum(totalAmount − taxFee)` across all valid (non-invalid) tickets
- `实收含税 (sNet)` = `sum(totalAmount)`
- `总税费 (sTax)` = `sum(taxFee)`
- `总服务费 (sSvc)` = `sum(serviceFee)`
- `总利润 (sProfit)` = `sum(totalProfit)`
- `Total Orders (sOrd)` = count of non-invalid tickets
- All values prefixed with `RM ` and formatted to 2 decimal places
- Stats strip becomes visible (add CSS class or toggle display) after calculation
**Files:** `public/orders.html`
**Depends on:** Task 2
**Done when:** Loading youmiqi April data shows 6 stat cards with correct values; 总应收 equals 实收含税 − 总税费 (verify by mental arithmetic on one day).

---

### Task 4: Update table structure — add 2 new columns
**What:** In the `<colgroup>` and `<thead>`, insert two new columns between "Net Received" and "Discount":
1. `实收(不含税)` — right-aligned
2. `消费税` — right-aligned

Update `colspan` on any full-width cells (e.g., "no results" message, detail rows) from 11 → 13.
**Files:** `public/orders.html`
**Depends on:** Task 2
**Done when:** Table header shows 13 columns with correct labels; detail row spans all 13 columns without visual breakage.

---

### Task 5: Update renderRows() — new cells + SELL_RETURN positive values
**What:** In `renderRows()`, for each ticket `<tr>`:
- After the existing "Net Received" `<td>`, insert two new `<td>` cells:
  - `实收(不含税)` = `r2(t.totalAmount − t.taxFee)`, formatted as number (no RM prefix), right-aligned mono
  - `消费税` = `r2(t.taxFee)`, show `—` when 0, right-aligned mono
- SELL_RETURN rows: display all monetary values as **positive numbers** (remove the existing sign-flip for display; sign-flip is only used in footer totals)
**Files:** `public/orders.html`
**Depends on:** Task 4
**Done when:** Every row shows correct values in the two new columns; a SELL_RETURN row shows its refund amount as a positive value in all monetary columns.

---

### Task 6: Replace footer with three-row summary
**What:** Replace the current single-row `renderFooter()` function with a new implementation that renders three `<tr>` rows inside a `<tfoot>` (or equivalent `<tbody>` rows styled as footer) at the bottom of the table:

**Row 1 — 销售单** (SELL only):
- Aggregate: count, 总应收, 实收含税, 实收不含税, 税费, 服务费, 折让 (`gross(t) - totalAmount`), 利润
- Style: label "销售单" in orange, subtle top border

**Row 2 — 退货单** (SELL_RETURN only):
- Same columns, values shown as positive raw amounts
- Style: label "退货单" in red (`--re`), light red row background

**Row 3 — 净合计** (Sales − Refunds):
- Each monetary field = sales_value − refund_value
- Style: label "净合计" bold, slightly darker background `#f4f4f5`, bold font weight

All three rows cover the **entire filtered set** (not just the current page). The Qty, Gross Amt, and Expand columns in footer rows show `—` or are left blank.
**Files:** `public/orders.html`
**Depends on:** Task 5
**Done when:** Footer shows 3 rows after loading data; Row 3 净合计 monetary values equal Row 1 minus Row 2 for every column; if there are no SELL_RETURN tickets, Row 2 shows all zeros (not hidden).

---

### Task 7: Add Expand All / Collapse All button
**What:** Add a button in the table header bar (right side, next to the order count):
- Label: "Expand All" (default) / "Collapse All" (when expanded)
- Style: `.btn.btn-g` (secondary gray button, matching report.html style)
- `expandAll()`: iterate all visible ticket rows on the current page, call the expand logic for each that isn't already open; set button to "Collapse All"
- `collapseAll()`: remove all `.drow` detail rows, reset all `.xbtn` chevrons; set button to "Expand All"
- On page change or filter change: reset button label to "Expand All" (existing rows are cleared on re-render anyway)
**Files:** `public/orders.html`
**Depends on:** Task 5
**Done when:** Clicking "Expand All" opens detail rows for all tickets on the current page simultaneously; clicking "Collapse All" closes all of them; individual chevrons still work independently after using Expand All.
