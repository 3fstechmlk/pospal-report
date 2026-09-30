# Sales Orders Page — Optimization Design Spec
**Date:** 2026-05-03
**Status:** Approved
**Builds on:** `docs/superpowers/specs/2026-05-02-sales-orders-design.md`

---

## Overview

Three focused improvements to `public/orders.html`:
1. Unify color/typography with `report.html` and `payment.html` (light theme, orange accent)
2. Add two new table columns (实收不含税, 消费税) and a three-row summary footer
3. One-click expand/collapse all transactions

---

## 1. UI Unification

### Color system — match report.html exactly
```css
--or: #f60;
--dk: #18181b;
--gy: #71717a;
--bd: #e4e4e7;
--bg: #fafafa;
--wh: #fff;
--re: #dc2626;
```

### Typography
- Font: `-apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif` (no Google Fonts)
- Remove `Outfit` and `JetBrains Mono` imports

### Layout components (match report.html patterns exactly)
| Component | Style |
|---|---|
| Topbar | `background: #18181b`, orange brand, same nav-link classes |
| Filter bar | White card `.fbar` with border + shadow, same as report.html |
| Stats cards | White `.sc` cards, orange `.val.or` for key figures, same row layout |
| Table container | White `.tc` card with border + shadow |
| Table header | `background: #f4f4f5`, same `thead th` style |
| Buttons | `.btn .btn-p` (orange) for Load, `.btn .btn-g` for secondary |

### Stats strip (6 cards, shown after load)
| Card | Value | Color |
|---|---|---|
| Total Orders | count of valid tickets | default |
| 总应收 | sum(totalAmount − taxFee) | orange |
| 实收（含税）| sum(totalAmount) | orange |
| 总税费 SST | sum(taxFee) | default |
| 总服务费 | sum(serviceFee) | default |
| 总利润 | sum(totalProfit) | orange |

---

## 2. New Table Columns

### Column order (13 columns total)
```
Expand | Receipt No. | Date & Time | Type | Cashier | Member | Qty |
Gross Amt | 实收(含税) | 实收(不含税) | 消费税 | Discount | Profit
```

### New column calculations (per ticket row)
- **实收（不含税）** = `totalAmount − taxFee`
- **消费税** = `taxFee` (shown as `—` when 0)

### 总应收 definition
`总应收 = totalAmount − taxFee`
Rationale: SST is collected on behalf of the government (pass-through), not merchant revenue. When discount/rounding = 0, this equals 实收（不含税）— consistent with Pospal's bottom bar.

---

## 3. Three-Row Summary Footer

Displayed at the bottom of the table, below the last data row. Three rows:

### Row 1 — Sales (SELL only, orange label)
```
销售单  |  N单  |  总应收 RM X  |  实收(含税) RM X  |  实收(不含税) RM X  |  税 RM X  |  服务费 RM X  |  折让 RM X  |  利润 RM X
```

### Row 2 — Refunds (SELL_RETURN only, red label)
```
退货单  |  N单  |  总应收 RM X  |  实收(含税) RM X  |  实收(不含税) RM X  |  税 RM X  |  服务费 RM X  |  折让 RM X  |  利润 RM X
```
- All values displayed as positive numbers (not negated) so the operator sees the raw refund amount
- Row styled with red text / subtle red background

### Row 3 — Net (Sales − Refunds, bold)
```
净合计  |  N单  |  总应收 RM X  |  实收(含税) RM X  |  实收(不含税) RM X  |  税 RM X  |  服务费 RM X  |  折让 RM X  |  利润 RM X
```
- Totals = Sales − Refunds for all monetary fields
- Bold weight, slightly darker background

### Footer covers filtered set (all pages, not just current page)

---

## 4. Expand All / Collapse All

- Button in the table header bar, right side: **"Expand All"** / **"Collapse All"** (toggle)
- On "Expand All": insert detail rows for every visible ticket on the current page
- On "Collapse All": remove all detail rows and reset all chevrons
- Individual row chevrons continue to work independently
- Button resets to "Expand All" when page changes or filters change

---

## 5. SELL_RETURN Display in Table

- SELL_RETURN rows remain visible in the table with red-tinted background and "Refund" badge (unchanged from current)
- Their monetary values displayed as **positive numbers** in the table row (same as Pospal — shows the actual refund amount, not negated)
- Expand detail works the same as SELL rows

---

## Out of Scope

- Exporting the orders table
- Cashier / member filters
- Column sorting
- Date quick-presets
- Table number filter
