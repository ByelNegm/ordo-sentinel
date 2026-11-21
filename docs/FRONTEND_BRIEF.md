# Frontend Devin handoff — Ordo Sentinel
You own **all UI only**, for team **ordo_system**, CIS Hack “Protect the little guy: human & transaction.” Deadline 16:00 today; MVP only. Implement one React + Vite + Tailwind app in frontend/. Backend owner + another Devin session build FastAPI separately. Start from fixtures now; never wait for backend.

## Product / story
At 2 AM, customer Aisha is asleep. FaceID/video KYC/auth already passed, but API transfers target her account. Bank-side rules/statistics flag small new-payee transfers and freeze a **−AED 450,000 offshore wire** before posting. LLM only explains; it never approves money movement. Customer taps Deny; show **AED 450,000 protected**. No trained ML or real banking.

## Screens
- **/analyst**: dark bank-grade dashboard; balances (posted/available/held), large protected counter, live transaction table, timestamp/amount/payee/channel/status, score and risk-factor chips, alert narrative/detail panel, frozen client badge + explicit unfreeze action. Buttons: normal scenario, drain scenario, reset. Show scenario step, connection/mock badge and meaningful empty/error states.
- **/phone**: mobile-frame guardian view; customer/balance summary, alert card with plain-language EN/AR message (Arabic RTL), amount, unfamiliar service/payee, Confirm / Deny, clear pending/error/success state. Prioritize wire alert so Deny yields exactly AED 450,000 protected. Explain that blocked funds have not left. Disable confirm when frozen and explain why.
- Consistent emerald protection, amber hold, red block; color plus labels/icons, legible type, restrained motion, touch-sized actions. Analyst desktop + responsive mobile frame, no native app. Visible demo-only label; never imply real push or production auth.

## Contract / integration
Read docs/API_CONTRACT.md as source of truth. Vite proxies /api to http://localhost:8000.
GET /api/state, /api/transactions?limit=50, /api/alerts; POST /api/scenario/{normal|drain}/start, /api/reset, /api/alerts/{id}/decision with {decision:"confirm"|"deny"}, /api/clients/{client_id}/unfreeze; EventSource /api/stream.
Envelope {type,ts,data}: txn.scored (upsert transaction), alert.created (upsert alert, including later explanation), alert.resolved (remove active + retain resolution), account.updated (merge money fields and frozen_clients/protected_amount), scenario.status. 15s SSE comment heartbeats need no UI dispatch. Fetch snapshots on load, reset, action completion and reconnect; render connection state. No silent retry of money actions; backend handles idempotency. Avoid duplicate rows/counters from repeated events.

## Mock without backend
- VITE_USE_MOCK=true selects a mock adapter; false uses REST/SSE. No automatic fallback that hides integration failures.
- Load root fixtures via Vite raw imports (e.g. ../../fixtures/state.json from frontend/src/) and events.ndjson with ?raw; parse each nonempty line with JSON.parse. Keep the same adapter API/reducer for both modes.
- Reset loads state.json plus empty transactions/alerts. transactions.json is a catalog: normal mode posts txn_normal once (AED 85), leaving 519915. alerts.json is the pre-decision drain checkpoint, not reset content.
- Drain replay uses the NDJSON envelope timestamps on a timer (0,1,2 seconds; preserve order for ties). No real SSE framing parsing required in mock mode. Starts from normal-completed balance. Repeated alert_burst IDs update one card.
- Replay has scripted wire deny at +8s then burst deny at +9s. For interactive mode PAUSE before these and generate matching resolution/account updates on actual taps; for unattended replay dispatch them on schedule. Never do both or increment protection twice.
- Deny wire: protected 450000, held 3000, posted 519915, available 516915; frozen API stays frozen. Deny burst later: protected 453000, held 0, available 519915. Confirm on frozen client is 409; show reason, do not post. Reset cancels every timer and restores fixture seed.
- Empty/error/LLM-fallback states must stay usable. Display backend customer text as plain text, not HTML.

## Suggested file layout
frontend/
  package.json
  index.html
  vite.config.ts
  src/
    main.tsx
    App.tsx
    styles.css
    pages/Phone.tsx
    pages/Analyst.tsx
    components/ProtectedCounter.tsx
    components/AlertCard.tsx
    components/TransactionTable.tsx
    components/RiskChips.tsx
    lib/api.ts
    lib/mock.ts
    lib/store.ts
    types.ts

You may create frontend-local config/dependencies as needed during implementation; none exist yet. Do not edit backend/. Do not alter shared docs/fixtures/contract without coordinating with backend owner. No auth, DB, real SMS/push, ML, multiple customers or native mobile. Do not deploy publicly.

## Schedule / collaboration
- 12:15: UI skeleton and contract frozen.
- 13:45: integrate both routes with backend.
- 14:45: feature freeze.
- 15:00: Cap five-minute recording; 15:30 GitHub + video submission; 16:00 deadline.
Use ui/* branches; backend uses api/*; PRs target main. Remote does not exist yet: local work only until owner creates it. Show parallel Devin sessions in video. Optional Daytona only if ≤20 minutes; skip Graphify/Collabute unless instant win.

## UI acceptance
Normal → drain → wire frozen → phone Deny → AED 450,000 protected → reset, repeat. Verify visual state on both routes, empty data, action errors, Arabic RTL, reconnect and reset cancellation. No unsupported “<1s verified” claim; backend measures enforcement latency separately.
