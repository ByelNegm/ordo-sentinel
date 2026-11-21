# BLACKBOX — bank integrity recovery
**Team ordo_system · P0: duplicate settlement.** Ordo Sentinel is discontinued; its modules, tests and fixtures are preserved under [legacy/ordo_sentinel](legacy/ordo_sentinel/).

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
Every reset restores 12 account identities and 100 normally settled instructions. Live payments arrive about every 1.5s. A duplicate emits a fresh event and posts twice through a deliberately faulty retry path. Both entries balance, while single_financial_effect and ledger_matches_expected fail. Missing/tamper fault injection returns 501 (P2).

## Financial / recovery invariants
- Money is strict integer fils everywhere; 100 fils = AED 1. Negative derived account balances are allowed in this synthetic accounting demo; this is not a credit/funds-availability engine.
- Account balances come only from journal lines (credits minus debits). Instruction intent is stored separately. Canonical hash input is UTF-8 id|debtor|creditor|amount_minor, SHA-256.
- The journal exposes append-only operations and detached snapshots. Compensation reverses an extra posting and links corrects_entry_id; originals remain unchanged.
- The pipeline investigates → contains → proposes → sandboxes → awaits approval. Default step delay is 1s; create_app(step_delay=0, traffic_interval=...) supports tests.
- Only ops.lead@bank or treasury@bank may approve; blackbox-agent is always forbidden. Actor strings are a demo authorization gate, not authenticated identities.
- Approval revalidates the sandbox under the runtime lock and appends an atomic correction batch keyed by incident + original entry. Repeat approval does not append again.
- Release requires resolved incidents. Reset cancels traffic and every pipeline under the same lock before constructing a new deterministic seed.
- SSE uses named event/data frames, 15s idle comment heartbeats and no buffering/cache. No durable replay: refetch overview on reconnect/reset.
