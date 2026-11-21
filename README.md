# BLACKBOX — Autonomous Banking Incident Reconstruction & Recovery

Track: **Protect the Big Guy — Code, Data & Infrastructure Rails**.

A settlement service has a retry bug and posts a payment twice. Each posting balances, so a "debits = credits" dashboard stays green, but the bank is wrong. BLACKBOX reconciles the ledger against the payment instructions independently and catches the error. It then reconstructs the lineage and timeline, quarantines the faulty service, proposes compensating entries, proves them in an isolated sandbox, and waits for a human approver. It applies the correction without rewriting history and verifies that integrity is restored.

**Deterministic code decides and moves money. AI never does.**

## Architecture
- `backend/`: Python FastAPI, in-memory, SSE (`/api/stream`). Modules: `ledger`, `bank`, `settlement`, `integrity`, `incident`, `traffic`, `main`.
- `frontend/`: React + Vite + Tailwind operations console (Bank Operations, Attack Simulator, Incident Investigation, Recovery Sandbox, Recovery Verification).
- Contract: [docs/API_CONTRACT.md](docs/API_CONTRACT.md). UI brief: [docs/FRONTEND_BRIEF.md](docs/FRONTEND_BRIEF.md).
- Discontinued Ordo Sentinel code: `legacy/ordo_sentinel/` and git history.

## Run
```bash
cd backend && pip install -r requirements.txt && uvicorn app.main:app --port 8000
cd frontend && npm install && npm run dev   # http://localhost:5173
cd backend && pytest -q
```

## Demo (5 min)
Reset → start traffic → inject duplicate → VIOLATED (ledger still balanced) → autonomous investigation + quarantine → sandbox PASSED → agent approval refused (403) → ops lead approves → correction → INTEGRITY RESTORED, 7/7 → release service.

Project control: [GOAL.md](GOAL.md) · [TASKS.md](TASKS.md) · [PROGRESS.md](PROGRESS.md)
