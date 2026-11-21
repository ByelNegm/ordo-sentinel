# BLACKBOX operations console

Live-only React + TypeScript + Vite + Tailwind console. No mock mode or prerecorded states.

## Run

Node 22.12+ (verified with 24.22.2); backend running on port 8000:

```sh
npm ci
npm run dev
```

Open http://localhost:5173. Vite proxies /api to the backend on 127.0.0.1:8000.

```sh
npm run build
npm run test:api
npm run test:acceptance
```

Acceptance uses Playwright attached to Chrome CDP at http://localhost:29229. Override CDP_URL, UI_URL or UI_EVIDENCE_DIR if needed. It drives real controls, so it resets the demo bank and leaves it healthy with traffic off. Screenshots and a request/error log go to /home/ubuntu/blackbox-evidence/ui by default.

## Implemented

- Five linked sections, persistent integrity/service/traffic status and live bank metrics.
- One named-event SSE connection, coalesced REST snapshots, refetch on reset/reconnect, visible connection failures.
- Payments, events, ledger, account balances, all seven checks, and all three real fault controls.
- Newest incident, deterministic root cause, containment, lineage and evidence timeline.
- Isolated proposal, balance simulation, before/after checks, agent 403 demonstration and human approval/rejection.
- Two real unsafe-correction challenges beside the safe proposal: rejected checks and ledger-preservation proof, followed by normal human approval. Acceptance also captures sandbox_rejected.png.
- Actual corrections with original-entry links, final verification, service release and audit.

Money is formatted from integer minor units. Action responses and backend errors are shown inline; response details can be expanded. All money movement and lifecycle decisions remain on the backend. Read limits use the backend's maximum of 500.

Only frontend/ was changed for this console. Root task/progress files are intentionally untouched to honor the frontend-only scope.
