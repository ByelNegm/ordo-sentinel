# Graph Report - graphify  (2026-11-21)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 337 nodes · 1147 edges · 10 communities (8 shown, 2 thin omitted)
- Extraction: 81% EXTRACTED · 19% INFERRED · 0% AMBIGUOUS · INFERRED: 219 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `8c4589cc`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8

## God Nodes (most connected - your core abstractions)
1. `Runtime` - 60 edges
2. `IncidentCoordinator` - 43 edges
3. `create_app()` - 38 edges
4. `Model` - 37 edges
5. `utcnow()` - 30 edges
6. `SettlementService` - 29 edges
7. `Bank` - 28 edges
8. `inspect()` - 27 edges
9. `Ledger` - 26 edges
10. `ActionError` - 25 edges

## Surprising Connections (you probably didn't know these)
- `create_app()` --uses--> `ActionError`  [INFERRED]
  backend/app/main.py → backend/app/incident.py
- `test_invalid_proposal_fails_sandbox_and_approval_without_touching_ledger()` --uses--> `ActionError`  [INFERRED]
  backend/tests/test_incident.py → backend/app/incident.py
- `test_lineage_root_cause_quarantine_sandbox_approval_and_release()` --uses--> `ActionError`  [INFERRED]
  backend/tests/test_incident.py → backend/app/incident.py
- `test_unauthorized_approval_never_posts()` --uses--> `ActionError`  [INFERRED]
  backend/tests/test_incident.py → backend/app/incident.py
- `create_app()` --uses--> `FaultResponse`  [INFERRED]
  backend/app/main.py → backend/app/models.py

## Import Cycles
- None detected.

## Communities (10 total, 2 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.09
Nodes (34): ActionError, FaultResponse, IntegritySummary, Overview, PaymentAccepted, Reset, ServiceUpdated, Totals (+26 more)

### Community 1 - "Community 1"
Cohesion: 0.13
Nodes (24): money_text(), IncidentCoordinator, intent_lines(), ActorRequest, Approval, AuditAppended, AuditRecord, Containment (+16 more)

### Community 2 - "Community 2"
Cohesion: 0.08
Nodes (40): AccountView(), App(), act(), attemptUnsafe(), Badge(), Checks(), clock(), DisplayContext (+32 more)

### Community 3 - "Community 3"
Cohesion: 0.11
Nodes (16): AccountIdentity, Bank, canonical_hash(), payment_reference(), uae_iban(), Account, PaymentInstruction, Service (+8 more)

### Community 4 - "Community 4"
Cohesion: 0.11
Nodes (16): awaiting_incident(), duplicate_via_http(), wait_for(), healthy(), test_approval_state_and_body_validation(), test_cors(), test_entire_p0_flow_three_times_from_clean_seed_via_http(), test_fault_modes_and_conflicts() (+8 more)

### Community 5 - "Community 5"
Cohesion: 0.25
Nodes (19): _check(), event_integrity(), expected_balances(), extra_postings(), inspect(), invalid_event(), ledger_balanced(), ledger_matches_expected() (+11 more)

### Community 6 - "Community 6"
Cohesion: 0.15
Nodes (14): line_signature(), reversed_lines(), JournalEntry, PostingLine, ready(), test_automatic_sandbox_failure_never_applies_proposal(), test_invalid_proposal_fails_sandbox_and_approval_without_touching_ledger(), run() (+6 more)

### Community 7 - "Community 7"
Cohesion: 0.09
Nodes (3): create_app(), stream(), client()

## Knowledge Gaps
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Runtime` connect `Community 0` to `Community 1`, `Community 3`, `Community 6`, `Community 7`, `Community 8`?**
  _High betweenness centrality (0.123) - this node is a cross-community bridge._
- **Are the 14 inferred relationships involving `Runtime` (e.g. with `Bank` and `EventBus`) actually correct?**
  _`Runtime` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.09114183307731695 - nodes in this community are weakly interconnected._
- **Why does `create_app()` connect `Community 7` to `Community 0`, `Community 1`, `Community 3`, `Community 4`, `Community 5`, `Community 6`?**
  _High betweenness centrality (0.112) - this node is a cross-community bridge._
- **Are the 23 inferred relationships involving `IncidentCoordinator` (e.g. with `Bank` and `EventBus`) actually correct?**
  _`IncidentCoordinator` has 23 INFERRED edges - model-reasoned connections that need verification._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.1259259259259259 - nodes in this community are weakly interconnected._
- **Why does `IncidentCoordinator` connect `Community 1` to `Community 0`, `Community 3`, `Community 5`, `Community 6`, `Community 8`?**
  _High betweenness centrality (0.043) - this node is a cross-community bridge._