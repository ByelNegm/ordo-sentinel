# MVP task checklist
All target times: **2026-11-21, Asia/Dubai**. Check only when complete; append evidence/decisions to [PROGRESS.md](PROGRESS.md). Follow [GOAL.md](GOAL.md); new scope must pass its drift check. Backend branches api/*; frontend ui/*; PRs into main.

## Backend — ByelNegm + Devin
- [ ] [ByelNegm + Devin] FastAPI skeleton, /api/state and fixtures served for development — **12:15**.
- [ ] [ByelNegm + Devin] Mock bank + deterministic one-customer seed/baseline — **12:30**.
- [ ] [ByelNegm + Devin] SSE stream, 15s heartbeat, X-Accel-Buffering: no — **12:45**.
- [ ] [ByelNegm + Devin] asyncio normal/drain scenario runner — **13:00**.
- [ ] [ByelNegm + Devin] Risk engine, customer stats and reason codes — **13:00**.
- [ ] [ByelNegm + Devin] Policy: <40 allow, 40–75 hold, >75 or cumulative drain >30% freeze client — **13:15**.
- [ ] [ByelNegm + Devin] Decision/unfreeze/reset endpoints; idempotency and runner cancellation — **13:30**.
- [ ] [ByelNegm + Devin] Async cached LLM explainer + immediate EN/AR template fallback — **13:30**.
- [ ] [ByelNegm + Devin] CORS/proxy check with frontend; Vite /api → :8000 — **13:45**.
- [ ] [ByelNegm + Devin] pytest drain scenario, policy boundaries, duplicate deny, reset and LLM failure; measure freeze latency — **14:30**.

## Frontend — colleague + her Devin
- [ ] [Frontend colleague + Devin] React/Vite/Tailwind skeleton, /phone and /analyst routes — **12:15**.
- [ ] [Frontend colleague + Devin] VITE_USE_MOCK adapter + timed fixtures/events.ndjson replay; interactive deny, reset cancellation — **12:45**.
- [ ] [Frontend colleague + Devin] Analyst dashboard: balances, transactions, risks, alerts, frozen client and scenario/reset controls — **13:15**.
- [ ] [Frontend colleague + Devin] Phone guardian: message, Confirm/Deny, protected counter and action states — **13:15**.
- [ ] [Frontend colleague + Devin] Arabic RTL and readable bilingual messages — **13:30**.
- [ ] [Frontend colleague + Devin] Integrate live REST/SSE; reconnect, empty/error states and both-route visual check — **13:45**.

## Shared / Demo
- [x] [ByelNegm + Devin] Repo initialized and docs pushed — **11:50**.
- [x] [ByelNegm + Devin] Plan/API contract/fixtures/frontend brief drafted and fixtures validated — **11:50**.
- [x] [ByelNegm + Devin] GOAL/TASKS/PROGRESS anti-drift docs and handoff links — **12:00**.
- [ ] [ByelNegm] Resolve frontend collaborator invite — **12:00**.
- [ ] [Both owners + Devin sessions] Contract + fixtures freeze — **12:15**.
- [ ] [Both owners + Devin sessions] End-to-end integration of full demo arc — **13:45**.
- [ ] [Both owners] README run instructions for backend, frontend and mock mode — **14:30**.
- [ ] [Both owners] Feature freeze; only demo-breaking fixes afterward — **14:45**.
- [ ] [Both owners] Rehearsal ×3: normal → drain → wire Deny → protected counter → reset — **15:00**.
- [ ] [ByelNegm + frontend colleague] Record five-minute Cap video, showing parallel Devin use — **15:00**.
- [ ] [ByelNegm] Submit GitHub repository + video link — **15:30** (hard deadline **16:00**).

## Parking Lot
- [ ] [Both owners] Optional Daytona hosting only if ≤20 minutes and demo-safe — **deferred; no commitment before 15:30 submission**.
- [ ] [Both owners] Other scope proposals: log rationale against GOAL.md before scheduling — **post-hackathon**.
