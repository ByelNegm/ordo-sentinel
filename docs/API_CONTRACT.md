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
- `POST /api/faults/{kind}` with `kind` ∈ `duplicate | missing | tamper`: injects a real fault into `settlement-svc`. The next live payment is affected. Returns `{ "fault": kind, "service": "settlement-svc" }`. 409 if a fault is already active or the service is quarantined. While integrity is not healthy, returns 409 with detail `"Integrity violated by an unrecovered incident; reset required"`.
- `POST /api/incidents/{id}/approve` with body `{ "actor": "ops.lead@bank" }`: authorizes the validated recovery. 403 if the actor is not an authorized approver (authorized: `ops.lead@bank`, `treasury@bank`; the agent `blackbox-agent` can never approve). 404 for an unknown incident id (after the authorization check). 409 if the incident is not in `awaiting_approval`. Idempotent: a repeat returns the same incident unchanged.
- `POST /api/incidents/{id}/reject` with body `{ "actor": "..." }`: rejects the proposal (status `rejected`). 404 for an unknown incident id.
- `POST /api/incidents/{id}/sandbox/challenge` with body `{ "variant": "wrong_amount" | "reverse_original" }`: tests an unsafe candidate without changing the real ledger, proposal or incident status. Returns `{ variant, proposal: Proposal, sandbox: Incident["sandbox"], ledger_unchanged: bool, applied: bool, rejection_reasons: {rule: string, detail: string}[] }` with a non-null sandbox report. 404 for an unknown incident; 409 unless awaiting_approval; 422 for an unknown variant. wrong_amount adds 100 minor to each line; reverse_original targets the legitimate posting instead of the duplicate (missing/tamper reverse the intended replacement). First records canonical/lineage rule violations, then attempts an atomic append on a copy. A refused append records ledger_guard and applied=false, with unchanged checks/balances. An accepted append sets applied=true and reports genuine post-apply checks/balances, recording integrity_check reasons for failures. Duplicate reverse_original has 7/7 post-apply checks but is still rejected by lineage_guard: only the extra effect may be reversed. Reasons use payment references/names. Appends sandbox.challenge.rejected and publishes audit.appended; real approval remains separately canonical-validated.
- `POST /api/services/settlement-svc/release`: lifts quarantine when no incident is open (including after rejection). Open statuses are `detected`, `investigating`, `contained`, `validating`, `awaiting_approval` and `correcting`. Held instructions are then processed. 409 if an incident is open or the service is not quarantined. Rejection acknowledges rather than repairs a violation; integrity can remain violated after release.

## Shapes

Display metadata is additive and optional for older consumers. Seeded accounts carry synthetic UAE IBANs (AE + mod-97 digits + bank code 033 + 16 account digits); these identify no real accounts. Payment references use FT + seed year/day + five deterministic alphanumerics. Purpose codes: SAL Salary (AED 8,000–45,000), SUP Supplier payment (2,500–25,000), RNT Rent (3,000–18,000), UTL Utilities (300–2,500), INV Invoice settlement (1,500–35,000), FND Opening balance transfer (200,000–450,000). Generated amounts include nonzero fils. Existing identifiers and canonical hash inputs remain unchanged; names, IBANs, references and purposes are not hash inputs.

```ts
type Overview = {
  accounts: { id: string; name: string; type: "customer" | "internal"; balance_minor: number; iban?: string | null }[];
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
  reference?: string | null; purpose?: string | null; purpose_label?: string | null;
  debtor_name?: string | null; creditor_name?: string | null;
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
  summary_text?: string | null;
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
    runner?: "daytona" | "local";
    runner_id?: string | null;
    remote_match?: boolean | null;
    runner_note?: string | null;
  } | null;
  approval: { actor: string; at: string } | null;
  corrections: string[];             // applied compensation entry ids
  verification: IntegrityReport | null;
};

type AuditRecord = { id: string; ts: string; actor: string; action: string; ref: string | null; detail: string };
```

### Optional Daytona confirmation

When DAYTONA_API_KEY is set and BLACKBOX_DAYTONA is not "0", startup pre-warms
one private sandbox using Daytona Python SDK 2.x's v0 namespace (v0-sdk extra).
Only detached synthetic evidence, the proposal/canonical expected proposal and
the pure checker modules are sent; no credentials or live ledger handles are uploaded.
Validation waits at most 8 seconds, outside the runtime lock. Not-ready, error,
timeout, invalid JSON and disagreement all retain the authoritative local report
and explain the fallback in runner_note. remote_match=false means disagreement;
null means no remote comparison completed. A matching result records runner=daytona,
runner_id and remote_match=true, plus sandbox.daytona.validated / audit.appended
and a sandbox timeline item "Validated in Daytona sandbox <id>".
Reset reuses the pre-warmed sandbox; shutdown deletes it. Idle/TTL deletion also
limits resources after an ungraceful exit. Challenges remain local. Human approval
always repeats local validation; Daytona never authorizes or applies a live correction.

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
