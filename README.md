# BLACKBOX — bank integrity recovery
**Team ordo_system · Duplicate, missing and tampered settlement recovery.** Ordo Sentinel is discontinued; its modules, tests and fixtures are preserved under [legacy/ordo_sentinel](legacy/ordo_sentinel/).

Track: **Protect the Big Guy — Code, Data & Infrastructure Rails**.

A ledger can balance and still be wrong. BLACKBOX compares independent payment intent with settlement events and append-only journal effects, identifies a faulty service, quarantines it and proposes a compensating entry. Recovery is tested on a deep copy and requires a human approver. The agent can never approve.

Source of truth: [frozen API contract](docs/API_CONTRACT.md). One FastAPI process; synthetic in-memory data; no real payments, persistence or production authentication.

Backend modules: models, ledger, bank, settlement, integrity, incident, traffic and main; reused EventBus in bus.py. The separate React/Vite/Tailwind operations console follows [the UI brief](docs/FRONTEND_BRIEF.md). Project control: [GOAL](GOAL.md) · [TASKS](TASKS.md) · [PROGRESS](PROGRESS.md).

## Run
Python 3.10+, from the repository root:
```sh
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```
Use one worker. API docs: http://localhost:8000/docs. CORS allows localhost:5173 and 127.0.0.1:5173; Vite proxies /api to :8000.

### Operations console
Use **Node.js 22.12+** (verified with **24.22.2**). The console is delivered in [PR #8](https://github.com/ByelNegm/ordo-sentinel/pull/8), branch `ui/blackbox-console`; these steps require a checkout containing that frontend.

Keep the backend running, then open a second terminal at the repository root:
```sh
cd frontend && npm install && npm run dev
```
Open **http://localhost:5173**. Vite forwards `/api` requests, including the SSE stream, from **:5173 → http://127.0.0.1:8000**. The console uses the real backend only; no mock mode is needed.

Tests (from backend/ with virtualenv active):
```sh
pytest -q
```
Only backend/tests is collected; archived Sentinel tests are not part of BLACKBOX.

## P0 curl demo
Subscribe in another terminal first:
```sh
curl -N http://localhost:8000/api/stream
```
Then:
```sh
curl -X POST http://localhost:8000/api/reset
curl -X POST http://localhost:8000/api/traffic/start
curl -X POST http://localhost:8000/api/faults/duplicate
curl http://localhost:8000/api/incidents
# Wait ~4 seconds for incident-0001 to reach awaiting_approval.
curl -X POST http://localhost:8000/api/incidents/incident-0001/approve \
  -H 'Content-Type: application/json' -d '{"actor":"ops.lead@bank"}'
curl -X POST http://localhost:8000/api/services/settlement-svc/release
curl http://localhost:8000/api/integrity
curl -X POST http://localhost:8000/api/traffic/stop
```
Every reset restores 12 account identities and 100 normally settled instructions. Live payments arrive about every 1.5s. A duplicate emits a fresh event and posts twice through a deliberately faulty retry path. Both entries balance, while single_financial_effect and ledger_matches_expected fail.

For P2, replace faults/duplicate with faults/missing or faults/tamper, resetting before each run. Missing acknowledges the instruction before losing its event and posting; a watchdog marks it missing after a 3s grace window, even if traffic stops. Allow roughly 7–9s for missing to reach awaiting_approval at default timings. Tamper increases the event amount by 100 fils and posts that altered effect. Its root cause names the differing amount_minor field. Both follow the same containment, sandbox, approval and release lifecycle.

## Demo reset checklist
- [ ] Backend :8000 and console :5173 are running; the console shows a live event stream, not a reconnect/error banner.
- [ ] In Attack Simulator, click **Reset baseline** and confirm the successful backend response. Reset discards demo history and cancels traffic, watchdogs and incident pipelines.
- [ ] Confirm **HEALTHY**, **7/7 checks**, **100 instructions settled**, **100 ledger entries**, **12 accounts**, **0 held / pending**, **0 open incidents**, service **running**, and traffic **OFF**.
- [ ] Start traffic, then inject exactly one fault. For duplicate, show that debits still equal credits while integrity becomes VIOLATED.
- [ ] Wait for **awaiting approval / SANDBOX PASSED**; demonstrate the agent's 403, approve as ops.lead@bank, verify **INTEGRITY RESTORED / 7/7**, then release settlement-svc and confirm the held queue drains.
- [ ] Stop traffic and reset before the next run or fault type. After rejection, reset is required before injecting another fault: unrecovered integrity violations return 409 even after service release.

## Financial / recovery invariants
- Money is strict integer fils everywhere; 100 fils = AED 1. Negative derived account balances are allowed in this synthetic accounting demo; this is not a credit/funds-availability engine.
- Account balances come only from journal lines (credits minus debits). Instruction intent is stored separately. Canonical hash input is UTF-8 id|debtor|creditor|amount_minor, SHA-256.
- The journal exposes append-only operations and detached snapshots. Compensation reverses a bad posting and links corrects_entry_id; originals remain unchanged. Missing effects and tamper replacements use compensation with corrects_entry_id null, linked by instruction_id. Original events remain as evidence; event_integrity recognizes a tampered event as reconciled only after its effect is reversed and a correct replacement is present.
- The pipeline investigates → contains → proposes → sandboxes → awaits approval. Default step delay is 1s; create_app(step_delay=0, traffic_interval=..., missing_grace=0) supports tests.
- Only ops.lead@bank or treasury@bank may approve; blackbox-agent is always forbidden. Actor strings are a demo authorization gate, not authenticated identities.
- Approval revalidates the sandbox under the runtime lock and appends an atomic correction batch keyed by incident + original entry. Repeat approval does not append again.
- Release requires no open incidents. Rejection permits release without repairing the acknowledged violation; fault injection requires healthy integrity, so reset before another fault after rejection. Reset cancels traffic, the missing-write watchdog and every pipeline under the same lock before constructing a new deterministic seed.
- Read limits must be between 1 and 500 (otherwise 422).
- SSE uses named event/data frames, 15s idle comment heartbeats and no buffering/cache. No durable replay: refetch overview on reconnect/reset.
