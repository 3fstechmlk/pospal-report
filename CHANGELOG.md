# Changelog — 3FS Workflow

---

## v1.2 — 2026-04-15

### New Features
- **Keivi Workflow** — dedicated board for Keivi FA clients, separate from Pospal
  - Stages: Financial Assessment → Pending Onboard → Onboarding → Activation → Key into Google Sheet → Onboarded → Completed / Failed / Refund/CN
  - Auto-derived status badge: Trial (Onboarding/Activation), ✓ Live (Key into Google Sheet/Onboarded/Completed), Fail (Failed/Refund/CN) — no manual selection needed
  - Delete client button (🗑) in modal footer with confirmation
- **Unified Payments Page** — `/payments` now shows both Pospal and Keivi clients
  - Source filter tabs: All Sources / Pospal / Keivi
  - Source badge column in table
  - Single modal handles both sources
- **Payment History Tracking** — every payment update is recorded
  - History stored in `payment_history` table (old/new status, old/new balance, note, timestamp, operator)
  - History tab in payment modal with visual timeline (color-coded status badges)
- **FA Panel improvements**
  - FA panel is now editable in **all Keivi stages**, not just Pending Onboard
  - **Save Changes** saves FA fields (payment status, balance, service ticks) — no separate Update FA button needed
  - Ticking/unticking a service (E-invoice, Payment Gateway, etc.) auto-creates or **deletes** the linked task
  - "View in Payments →" link in FA panel

### UI / Branding
- **"Account Setup" renamed to "Pospal"** across all sidebar nav labels and board headers
- **Pospal icon** (pospal-icon.png) replaces 📋 emoji in all sidebars
- **Keivi icon** (keivi-icon.png / mark-color.png) replaces 🟠 emoji in all sidebars
- **LHDN logo** (einvoice-icon.png) replaces 🧾 emoji for E-invoice sidebar link
- **Revenue Monster logo** (paymentgw-icon.png) replaces 💳 emoji for Payment GW sidebar link
- **Pospal Form (`/form`)** — full redesign: card-based UI, mobile-responsive, Pospal branding, 30-min time picker
- **Keivi Form (`/keivi-form`)** — same redesign: split date + time selects, 30-min intervals (08:00–20:00)
- Google OAuth credentials pre-filled on Team page (client secret no longer disappears)

### Bug Fixes
- FA E-invoice untick now correctly **deletes** the linked task (previously only created, never deleted)
- Save Changes now saves FA fields — previously read from wrong DOM element
- Google team page "Not set up" — `clientSecret` now returned by `/api/google-status`
- Deploy path corrected to `/opt/pospal-report/` (previously syncing to wrong `/root/pospal-report/`)

### Infrastructure
- Git repo initialized; v1.0 and v1.2 tagged
- DB backed up before each major deploy
- `CLAUDE.md` added — "上线去console" auto-deploy command documented
- `static/` folder added for icon assets

---

## v1.0 — 2026-04-14

- Initial release: Pospal (Account Setup) kanban board
- Asana data migration (416 records)
- FA review workflow with Google Calendar sync
- Linked tasks (E-invoice, Payment Gateway, Mall, QR Printing)
- Archive page, QR Printing, Mall Integration boards
- Team management, login/logout
