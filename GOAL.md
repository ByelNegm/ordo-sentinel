# GOAL — BLACKBOX

**North star:** prove, live, that BLACKBOX autonomously reconstructs and recovers a banking-infrastructure integrity failure without hiding history and without letting AI move money.

**The one demo (P0):** healthy bank → duplicate settlement fault → integrity violation (ledger still balanced, but wrong) → autonomous investigation → service containment → recovery proposal → sandbox validation → human approval → compensating correction → verified reconciliation. Repeatable from Reset.

**Track:** Protect the Big Guy — Code, Data & Infrastructure Rails. Deadline 16:00 Dubai (submit 15:30).

## In scope
- Synthetic bank: accounts, 100+ seeded payments, instructions / settlement events / ledger kept separate, integer minor units.
- Double-entry, append-only ledger. Independent reconciliation from instructions.
- Real fault injection in `settlement-svc`: duplicate (P0), missing and tampered (P2).
- 7 deterministic integrity checks, the incident pipeline, quarantine, the sandbox, an approval gate, idempotent compensating entries, the audit log.
- A dark command-center UI with 5 views, all wired to the real backend.

## Rules
- Deterministic code decides and corrects. An LLM (optional) may only explain, must be schema-validated, and is labeled. The fallback is labeled "Deterministic".
- No history rewrite: corrections are new entries linked to the originals.
- Synthetic data only, no real bank connections, no paid infra, no secrets in the repo.
- Out of scope: auth, persistence beyond process, deployment, real ML. New ideas go to the Parking Lot in TASKS.md.
