# Inventory Monthly Snapshot — Design Spec
Date: 2026-04-12

## Background

POSPAL (`queryProductList`) only returns live/current stock. There is no historical inventory API. To support financial reporting (e.g. 31/12 year-end stock value), the system must take its own snapshots and store them locally.

## Requirements

- Monthly snapshot per merchant, automatically triggered
- No manual trigger
- Accessible via existing Portal (Admin + Merchant side)
- Export as Excel (.xlsx)
- Must not blow the POSPAL 300 API calls/day limit

## Trigger Logic

Inside the existing hourly sync loop in `run.py`, add a call to `run_inventory_snapshot()` with the following guard:

```
current_hour == 6
AND today is the 1st of the month
AND data/inventory_snapshots/{merchant_uid}/{YYYY-MM}.json does not exist
```

- Snapshot is labeled as the **previous month** (e.g. triggered on 2025-02-01 → stored as `2025-01`)
- 6am chosen because bars/restaurants operating past midnight will have finished trading by then
- If a merchant's API call fails at 6am, no file is created → the loop retries automatically at 7am, 8am, etc. (still the 1st of the month, file still absent)
- After the 1st passes, retries stop naturally (2nd of month condition fails)
- Merchants that already have the file are skipped instantly (idempotent)

### API Call Budget (monthly, per merchant)

| Merchant Type | Approx SKUs | API Calls/Month |
|---------------|-------------|-----------------|
| A — F&B small | < 200       | 1–2             |
| B — Retail    | ≤ 1,000     | up to 10        |
| C — Supermarket | ≤ 5,000   | up to 50        |
| D — Large     | > 5,000     | up to 100       |

All well within the 300/month limit. (Sales sync uses up to 250/day but inventory snapshot is monthly, not daily.)

## Storage

```
data/inventory_snapshots/
  {merchant_uid}/
    2024-12.json
    2025-01.json
    2025-02.json
```

### JSON Schema

```json
{
  "snapshot_month": "2025-01",
  "snapshot_taken_at": "2025-02-01T06:03:21",
  "merchant_uid": "xxx",
  "merchant_name": "ABC Restaurant",
  "is_quarter_end": false,
  "is_year_end": false,
  "products": [
    {
      "category": "Beverages",
      "name": "100Plus 325ml",
      "barcode": "9556789012345",
      "stock_qty": 48,
      "cost_price": 1.20,
      "retail_price": 2.50,
      "stock_value": 57.60
    }
  ],
  "summary": {
    "total_skus": 85,
    "total_stock_value": 4320.50
  }
}
```

- `stock_value` = `cost_price × stock_qty`, computed at snapshot time
- `is_quarter_end` = true when snapshot_month ends in `-03`, `-06`, `-09`, `-12`
- `is_year_end` = true when snapshot_month ends in `-12`
- File presence = snapshot success; absence = not yet taken or failed

## Portal UI

### Admin Portal — Inventory Report page
- Dropdown: select merchant
- Table of available snapshot months:
  - Columns: Month | Total SKUs | Total Stock Value (RM) | Quarter End | Year End | Download
- Click Download → generates and returns Excel for that month

### Merchant Portal — Inventory Report page
- Same table, pre-filtered to their own merchant (no merchant selector needed)

## Excel Export Format

Filename: `{MerchantName}_Inventory_{YYYY-MM}.xlsx`

| Category | Product Name | Barcode | Stock Qty | Cost Price (RM) | Retail Price (RM) | Stock Value (RM) |
|----------|-------------|---------|-----------|-----------------|-------------------|-----------------|
| Beverages | 100Plus 325ml | 955... | 48 | 1.20 | 2.50 | 57.60 |
| ... | | | | | | |
| **TOTAL** | | | **285** | | | **4,320.50** |

- Last row: bold TOTAL with sum of Stock Qty and Stock Value
- Sorted by Category then Product Name
- Uses `openpyxl` (already available in project or add as dependency)

## Implementation Touch Points

| File | Change |
|------|--------|
| `pospal-report/run.py` | Add `run_inventory_snapshot()` function; hook into hourly sync loop |
| `pospal-report/run.py` | Add `/api/inventory-snapshots` GET endpoint (list months) |
| `pospal-report/run.py` | Add `/api/inventory-snapshots/download` GET endpoint (Excel) |
| `pospal-report/public/` | Add Inventory Report page (HTML + JS) for Admin + Merchant portals |

## Out of Scope

- Manual/on-demand snapshot trigger
- Daily snapshots
- Stock movement history (in/out transactions)
- Push notifications when snapshot completes
