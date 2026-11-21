export type Check = { name: string; pass: boolean; detail: string }
export type Integrity = { status: 'healthy' | 'violated' | 'recovering'; checks: Check[]; ts: string }
export type Service = { id: string; status: 'running' | 'quarantined'; fault: string | null; processed: number }
export type Overview = {
  accounts: { id: string; name: string; type: string; balance_minor: number }[]
  totals: { debits_minor: number; credits_minor: number; ledger_entries: number }
  volume: { instructions: number; settled: number; pending: number; held: number }
  services: Service[]
  integrity: { status: Integrity['status']; failing_checks: number }
  open_incidents: number
  traffic_running: boolean
}
export type Payment = {
  id: string; idempotency_key: string; debtor: string; creditor: string; amount_minor: number
  currency: string; created_at: string; status: string; settlement_count: number; expected_hash: string
}
export type Settlement = {
  id: string; instruction_id: string; seq: number; service: string; debtor: string; creditor: string
  amount_minor: number; payload_hash: string; ts: string
}
export type Entry = {
  id: string; kind: string; instruction_id: string; event_id: string | null
  corrects_entry_id: string | null; ts: string; actor: string
  lines: { account: string; side: string; amount_minor: number }[]
}
export type Incident = {
  id: string; type: string; status: string; detected_at: string; violations: Check[]
  affected_payments: string[]; affected_accounts: string[]; impact_minor: number
  root_cause: { service: string; summary: string; confidence: string; method: string }
  lineage: { instruction_id: string; event_ids: string[]; entry_ids: string[] }[]
  timeline: { ts: string; kind: string; ref: string | null; detail: string }[]
  containment: { service: string; action: string; at: string; held_instructions: number } | null
  proposal: { id: string; description: string; entries: Entry[] } | null
  sandbox: {
    passed: boolean; checks_before: Check[]; checks_after: Check[]
    balances_before: Record<string, number>; balances_after: Record<string, number>; ts: string
  } | null
  approval: { actor: string; at: string } | null
  corrections: string[]; verification: Integrity | null
}
export type Audit = { id: string; ts: string; actor: string; action: string; ref: string | null; detail: string }
export type Snapshot = {
  overview: Overview | null; integrity: Integrity | null; payments: Payment[]
  settlements: Settlement[]; ledger: Entry[]; incidents: Incident[]; audit: Audit[]
}
