# BLACKBOX Frontend Brief (paste into the UI Devin session)

**Project pivot:** Ordo Sentinel (customer fraud) is discontinued. We now build **BLACKBOX: Autonomous Banking Incident Reconstruction & Recovery** for the track "Protect the Big Guy — Code, Data & Infrastructure Rails". The hard deadline is **16:00 Dubai** and the UI must be integrated by **14:45**.

Read first: `GOAL.md`, `docs/API_CONTRACT.md` (the only source of field names), `TASKS.md` (tick the UI items) and `PROGRESS.md` (add a dated entry for each PR).

## Rules
- Work only in `frontend/`. Branch from `pivot/blackbox` as `ui/*` and open PRs into `pivot/blackbox`. Do not edit `backend/` or the contract; ask the lead.
- The old `/phone` and `/analyst` guardian UI is retired. Don't continue it.
- **Every control calls the real backend.** No fake buttons, prerecorded success states or hardcoded recovery animations. Everything on screen comes from the REST/SSE data.
- Money is integer minor units. Format with `(amount_minor / 100).toLocaleString('en-AE', { style: 'currency', currency: 'AED' })`.

## Stack
React + Vite + TypeScript + Tailwind. `vite.config.ts` proxies `/api` to `http://localhost:8000`. Use one `EventSource('/api/stream')` hook that keeps state: overview, latest 50 payments, settlements, ledger, incidents by id, audit. On `reset`/reconnect, refetch with GET. Optional: `recharts` for volume, `framer-motion` for subtle transitions.

## Look and feel
A premium dark fintech command center: near-black background (`#0a0d12`), slate panels, a single cyan accent for live data, amber for detecting/investigating, red for violated/quarantined, green for verified. Inter/Geist typography, tabular numbers for money, restrained motion (fade/slide of about 150ms, a pulse on live rows). It must be readable from the back of a room: large status headline, high contrast.

## Layout
A single page (`/`) with a left rail of 5 sections and a persistent top status bar showing **integrity status** (HEALTHY / VIOLATED / RECOVERING), checks passed x/7, `settlement-svc` status, open incidents and traffic on/off.

1. **Bank Operations**
   - A live payments table (id, debtor → creditor, amount, status, `settlement_count` badge; a red "×2" when it's 2).
   - A settlement event feed.
   - Ledger totals: debits vs credits, both shown, which visibly stay equal during the duplicate fault. This is the key insight: "balanced ≠ correct".
   - The 7 integrity checks as pass/fail chips.
   - Transaction volume counter or sparkline. Account balances table.
2. **Attack Simulator**
   - Buttons: Start/Stop traffic, Inject Duplicate Settlement, Inject Missing Settlement, Inject Tampered Settlement, Reset to healthy baseline.
   - Each button shows the backend response or a 409 error inline.
   - Missing and tampered may return 409/501 until the backend ships them (P2). Show "coming soon" only when the backend returns 501.
3. **Incident Investigation** (shown when an incident exists; it auto-focuses on the newest)
   - A status stepper: detected → investigating → contained → validating → awaiting_approval → correcting → resolved.
   - Root cause card: service, summary, confidence, and a method badge. A badge reading "Deterministic" must say exactly that; never label it AI.
   - Affected payments, financial impact (`impact_minor`, large), and lineage (instruction → events → entries as a small tree).
   - An evidence timeline as a vertical list of `timeline` items. Containment card: quarantined service and held instructions count.
4. **Recovery Sandbox**
   - The proposal description and compensating entries table.
   - Balances before/after from `sandbox.balances_before/after`, with only changed accounts highlighted.
   - `checks_before` vs `checks_after`, side by side.
   - Sandbox PASSED/FAILED banner.
   - Approval controls: an approver select (`ops.lead@bank`, `treasury@bank`, plus `blackbox-agent` to show the 403 rejection on stage), and Approve / Reject buttons. They are enabled only in `awaiting_approval`.
5. **Recovery Verification**
   - Applied corrections: the compensation entries with `corrects_entry_id` linking to the original, and a note that the original is preserved.
   - Final `verification` checks (all green) and a big "INTEGRITY RESTORED" when the incident is `resolved`.
   - A "Release settlement-svc" button.
   - The audit history table (`/api/audit`).

## Mock mode
Until the backend is live, `VITE_USE_MOCK=true` reads `frontend/src/mock/*.json` that you create from the contract shapes and plays a scripted SSE sequence. Remove mock mode from the demo build; the demo uses the live backend only.

## Acceptance (run from the live backend)
Reset → Start traffic → Inject Duplicate → the status bar turns VIOLATED and the "×2" payment appears → the incident steps run on their own up to awaiting_approval → the sandbox shows PASSED → approving as `blackbox-agent` gives a visible 403 → approving as `ops.lead@bank` → RESOLVED, INTEGRITY RESTORED, 7/7 checks → Release → held payments settle → Reset. Do it 3 times in a row without a page reload.
