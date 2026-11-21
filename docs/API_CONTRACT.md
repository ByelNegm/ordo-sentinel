# BLACKBOX API Contract (v1, frozen for UI work)

Base URL: `http://localhost:8000` (the Vite dev server proxies `/api`). All money values are **integers in minor units** (fils, so 1 AED = 100). Field names ending in `_minor` are money. Timestamps are ISO-8601 UTC. Currency is always `AED`.

Changes to this file need lead sign-off. The UI may only depend on the fields listed here.

## Domain

| Object | Meaning |
|---|---|
| `Account` | Synthetic bank account. Balance is derived from ledger postings, never stored directly. |
| `PaymentInstruction` | What *should* happen. Unique `idempotency_key`; `expected_hash` = SHA-256 of canonical (id, debtor, creditor, amount_minor). Stored separately from settlement. |
| `SettlementEvent` | What the settlement service *says* happened. Emitted by service `settlement-svc`. |
| `JournalEntry` | Double-entry ledger posting (append-only). `kind` = `settlement` or `compensation`. |
| `Incident` | Integrity violation and its full investigation, containment and recovery lifecycle. |

## REST

### Read
- `GET /api/overview` → `Overview`
- `GET /api/payments?limit=50` → `PaymentInstruction[]` (newest first)
- `GET /api/settlements?limit=50` → `SettlementEvent[]` (newest first)
- `GET /api/ledger?limit=100` → `JournalEntry[]` (newest first)
- `GET /api/integrity` → `IntegrityReport`
- `GET /api/incidents` → `Incident[]` (newest first)
- `GET /api/incidents/{id}` → `Incident`
- `GET /api/audit?limit=100` → `AuditRecord[]` (newest first)

### Actions
- `POST /api/reset`: back to a healthy seeded bank (100 settled payments, balanced ledger, no incidents). Returns `Overview`.
- `POST /api/traffic/start` / `POST /api/traffic/stop`: live payment trickle (one payment roughly every 1.5s). Returns `{ "running": bool }`.
- `POST /api/faults/{kind}` with `kind` ∈ `duplicate | missing | tamper`: injects a real fault into `settlement-svc`. The next live payment is affected. Returns `{ "fault": kind, "service": "settlement-svc" }`. 409 if a fault is already active or the service is quarantined.
- `POST /api/incidents/{id}/approve` with body `{ "actor": "ops.lead@bank" }`: authorizes the validated recovery. 403 if the actor is not an authorized approver (authorized: `ops.lead@bank`, `treasury@bank`; the agent `blackbox-agent` can never approve). 404 for an unknown incident id (after the authorization check). 409 if the incident is not in `awaiting_approval`. Idempotent: a repeat returns the same incident unchanged.
- `POST /api/incidents/{id}/reject` with body `{ "actor": "..." }`: rejects the proposal (status `rejected`). 404 for an unknown incident id.
- `POST /api/services/settlement-svc/release`: lifts quarantine when no incident is open (including after rejection). Open statuses are `detected`, `investigating`, `contained`, `validating`, `awaiting_approval` and `correcting`. Held instructions are then processed. 409 if an incident is open or the service is not quarantined. Rejection acknowledges rather than repairs a violation; integrity can remain violated after release.

## Shapes

```ts
type Overview = {
  accounts: { id: string; name: string; type: "customer" | "internal"; balance_minor: number }[];
  totals: { debits_minor: number; credits_minor: number; ledger_entries: number };
  volume: { instructions: number; settled: number; pending: number; held: number };
  services: Service[];
  integrity: { status: "healthy" | "violated" | "recovering"; failing_checks: number };
  open_incidents: number;
  traffic_running: boolean;
};

type Service = {
  id: "settlement-svc";
  status: "running" | "quarantined";
  fault: null | "duplicate" | "missing" | "tamper";   // shown in the Attack Simulator only
  processed: number;
};

type PaymentInstruction = {
  id: string; idempotency_key: string;
  debtor: string; creditor: string; amount_minor: number; currency: "AED";
  created_at: string;
  status: "accepted" | "settled" | "held" | "missing" | "discrepancy";
  settlement_count: number;          // 1 is correct; 2 means a duplicate
  expected_hash: string;
};

type SettlementEvent = {
  id: string; instruction_id: string; seq: number; service: string;
  debtor: string; creditor: string; amount_minor: number;
  payload_hash: string; ts: string;
};

type JournalEntry = {
  id: string; kind: "settlement" | "compensation";
  instruction_id: string; event_id: string | null;
  corrects_entry_id: string | null;  // set on compensation entries
  lines: { account: string; side: "debit" | "credit"; amount_minor: number }[];
  ts: string; actor: string;         // "settlement-svc" or the approver
};

type Check = { name: string; pass: boolean; detail: string };
type IntegrityReport = { status: "healthy" | "violated" | "recovering"; checks: Check[]; ts: string };
// check names: ledger_balanced, unique_idempotency_keys, settlements_map_to_instructions,
//              single_financial_effect, ledger_matches_expected, no_missing_settlements, event_integrity

type TimelineItem = { ts: string; kind: "instruction" | "settlement" | "posting" | "detection" | "investigation" | "containment" | "proposal" | "sandbox" | "approval" | "correction" | "verification"; ref: string | null; detail: string };

type Incident = {
  id: string;
  type: "duplicate_settlement" | "missing_settlement" | "tampered_settlement";
  status: "detected" | "investigating" | "contained" | "validating" | "awaiting_approval" | "correcting" | "resolved" | "rejected" | "failed";
  detected_at: string;
  violations: Check[];
  affected_payments: string[];       // instruction ids
  affected_accounts: string[];
  impact_minor: number;              // money wrongly moved (or not moved)
  root_cause: { service: string; summary: string; confidence: "high" | "medium" | "low"; method: "deterministic" | "llm" };
  lineage: { instruction_id: string; event_ids: string[]; entry_ids: string[] }[];
  timeline: TimelineItem[];
  containment: { service: string; action: "quarantine"; at: string; held_instructions: number } | null;
  proposal: { id: string; description: string; entries: JournalEntry[] } | null;
  sandbox: {
    passed: boolean;
    checks_before: Check[]; checks_after: Check[];
    balances_before: Record<string, number>; balances_after: Record<string, number>;
    ts: string;
  } | null;
  approval: { actor: string; at: string } | null;
  corrections: string[];             // applied compensation entry ids
  verification: IntegrityReport | null;
};

type AuditRecord = { id: string; ts: string; actor: string; action: string; ref: string | null; detail: string };
```

## SSE `GET /api/stream`

Frames are `event: <type>` and `data: <json>`, with a heartbeat comment every 15s. Envelope: `{ "type": string, "ts": string, "data": object }`.

| type | data |
|---|---|
| `payment.accepted` | `PaymentInstruction` |
| `settlement.posted` | `{ event: SettlementEvent, entry: JournalEntry }` |
| `integrity.updated` | `IntegrityReport` |
| `incident.updated` | `Incident` (full object, sent at every status change) |
| `service.updated` | `Service` |
| `audit.appended` | `AuditRecord` |
| `reset` | `Overview` |

The UI should refetch `GET /api/overview` on `reset` and on reconnect.

## Duplicate-settlement demo lifecycle (P0)
1. `reset` → integrity `healthy`, 7/7 checks pass.
2. `traffic/start` → `payment.accepted` + `settlement.posted` every ~1.5s.
3. `faults/duplicate` → the next payment is settled twice (two events, two balanced entries). The ledger is still balanced, but `single_financial_effect` and `ledger_matches_expected` fail.
4. `incident.updated` moves automatically, about 1s per step: `detected` → `investigating` (lineage, timeline, root cause) → `contained` (`service.updated` quarantined; new payments are `held`) → `validating` → `awaiting_approval` (proposal + sandbox report, `passed: true`).
5. `approve` → `correcting` → `resolved`, with `corrections` and `verification` (all checks pass). The original entries are kept; the compensation entries link back via `corrects_entry_id`.
6. `services/settlement-svc/release` → held payments settle normally.
