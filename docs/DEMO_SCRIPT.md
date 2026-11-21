# BLACKBOX — 5-Minute Demo Script

Track: **Protect the Big Guy — Code, Data & Infrastructure Rails**. Field names come from [API_CONTRACT.md](API_CONTRACT.md) and UI controls from [FRONTEND_BRIEF.md](FRONTEND_BRIEF.md). Placeholders `<like this>` must be filled with real observed values before going on stage. Don't invent numbers.

## Pre-flight (T-5 min)
- Backend: `cd backend && uvicorn app.main:app --port 8000`. Frontend: `cd frontend && npm run dev`, open `http://localhost:5173`. Confirm that mock mode is **off**.
- Attack Simulator → **Reset to healthy baseline**. The status bar must read **HEALTHY · 7/7 · settlement-svc running · 0 open incidents · traffic off**.
- Have a second terminal open with the [backup curl commands](#backup-plan-ui-fails) ready. Set the browser zoom so the status bar is readable from the back of the room.

## 60-second pitch opener (spoken before the clock starts, or as 0:00–0:30 when time is tight)
> "Every bank has a dashboard that says debits equal credits. That dashboard can be green while the bank is wrong. A settlement service retries, posts the same payment twice, and each posting balances perfectly. Nobody notices until a customer or a regulator does.
> BLACKBOX is an autonomous incident responder for the rails underneath the bank: code, data and infrastructure. It reconciles the ledger against what *should* have happened, reconstructs exactly what went wrong, quarantines the faulty service, proves a fix in a sandbox, and waits for a human. It never rewrites history, and AI never moves money. Deterministic code decides; people approve. Let me break a bank for you."

---

## 0:00–0:30 · Healthy bank
- **Click:** left rail → **Bank Operations**. Attack Simulator → **Start traffic** (then return to Bank Operations).
- **Screen:** status bar **HEALTHY**, 7/7 checks. The live payments table is filling (`id`, `debtor → creditor`, `amount_minor`, `status: settled`, `settlement_count` = 1). Ledger totals `debits_minor` = `credits_minor`. `volume.instructions` and `volume.settled` are counting up from the 100 seeded payments. All 7 integrity chips are green.
- **Say:** "This is a synthetic bank: `<N accounts>` accounts and 100 seeded payments, with live traffic arriving every second and a half. Instructions, settlement events and the ledger are kept separately, and the ledger is double-entry and append-only. Seven independent integrity checks are all green."

## 0:30–1:15 · Inject duplicate settlement
- **Click:** left rail → **Attack Simulator** → **Inject Duplicate Settlement**.
- **Screen:** an inline response `{ "fault": "duplicate", "service": "settlement-svc" }`. Service `fault: "duplicate"` is shown here only. Back in **Bank Operations**, the next live payment shows a red **×2** badge (`settlement_count: 2`), and two settlement events with the same `instruction_id` appear in the event feed.
- **Say:** "This isn't a fake alert. I'm injecting a real retry bug into the settlement service, and the next payment will be settled twice. There it is: one instruction, two settlement events, two ledger postings. Watch the totals."

## 1:15–2:00 · Detected discrepancy (the key insight)
- **Click:** stay on **Bank Operations**, and point at the ledger totals and then the integrity chips.
- **Screen:** `debits_minor` **still equals** `credits_minor`, yet the status bar flips to **VIOLATED**. `ledger_balanced` stays **green**; `single_financial_effect` and `ledger_matches_expected` turn **red** (`<x>/7` checks passing).
- **Say:** "Debits still equal credits. A traditional control says this bank is fine. It isn't: a customer has been charged twice. BLACKBOX doesn't trust the ledger to check itself. It independently replays every payment instruction, derives what the ledger *should* contain, and compares. Balanced is not the same as correct, and that's the gap this product closes."

## 2:00–2:45 · Autonomous investigation + quarantine
- **Click:** left rail → **Incident Investigation**. No clicks are needed: it auto-focuses the newest incident and the stepper advances by itself.
- **Screen:** the stepper goes `detected → investigating → contained`. The root cause card shows `service: settlement-svc`, `summary`, `confidence`, and a method badge reading **Deterministic**. `impact_minor` is shown large (`<AED amount>`), with `affected_payments`, `affected_accounts`, and the lineage tree (instruction → 2 event_ids → 2 entry_ids). The evidence `timeline` and the containment card (`action: quarantine`, `held_instructions: <N>`) appear. The status bar shows **settlement-svc quarantined**, and new payments arrive as `held`.
- **Say:** "Nobody touched anything. Within seconds BLACKBOX traced the lineage from instruction to events to postings, built a timeline, and pinned the root cause on settlement-svc. Note the badge: this was found by deterministic analysis, not an LLM guess. Then it contained the blast radius: the service is quarantined, and new payments are safely held instead of being double-charged."

## 2:45–3:45 · Recovery proposal, sandbox, 403, human approval
- **Click:** left rail → **Recovery Sandbox**. Approver select → **blackbox-agent** → **Approve**. Then approver select → **ops.lead@bank** → **Approve**.
- **Screen:** the incident is in `awaiting_approval`. It shows the `proposal.description` and a compensating `entries` table, `balances_before` vs `balances_after` with only the changed accounts highlighted, and `checks_before` (red) vs `checks_after` (7/7 green) side by side, under a **Sandbox PASSED** banner (`sandbox.passed: true`). Approving as `blackbox-agent` shows a visible **403** inline. Approving as `ops.lead@bank` moves the stepper to `correcting`.
- **Say:** "BLACKBOX proposes a fix: compensating entries, not deletions. Before anyone sees it, the fix is applied to an isolated copy of the bank, and all seven checks pass there. Now, can the AI approve its own fix? (click) 403. No. The agent is structurally barred from moving money. Only an authorized human can do it. The ops lead approves."

## 3:45–4:30 · Compensating correction, 7/7, INTEGRITY RESTORED
- **Click:** left rail → **Recovery Verification**. Then **Release settlement-svc**.
- **Screen:** applied corrections (`kind: compensation`, each with `corrects_entry_id` → the original entry) and the note that the original is preserved. The final `verification` checks are all green, and **INTEGRITY RESTORED** appears big (incident `resolved`). The status bar shows **HEALTHY · 7/7**. The audit history (`/api/audit`) lists every step with its `actor`, including the refused agent approval. After Release, the held payments settle normally.
- **Say:** "The correction is a new, linked entry. The original double posting is still there, because auditors and regulators need to see what happened, not a cleaned-up story. Seven of seven checks pass and integrity is restored. Every step is in the audit log, including the AI's refused approval. Releasing the service, the held payments now settle."

## 4:30–5:00 · Built with Devin
- **Click:** switch to the repo / [DEVIN_USAGE.md](DEVIN_USAGE.md) and the PR list (https://github.com/ByelNegm/ordo-sentinel/pulls).
- **Screen:** the PR list, review comments, and test output `<N tests passed>`.
- **Say:** "We built this with Devin as an engineering team: a lead session orchestrating parallel builder sessions per module, an independent review gate that never wrote the code it reviewed, and a frozen API contract that let a colleague's Devin build this UI in parallel. We even pivoted products mid-hackathon without rewriting git history. `<N tests passed>`, and the full flow runs from Reset `<N>` times in a row. BLACKBOX: balanced isn't correct, and AI never moves the money."

---

## Backup plan (UI fails)
Narrate the same beats from a terminal, keeping the numbers large (`jq` is required). Base URL `http://localhost:8000`.

```bash
B=http://localhost:8000
curl -s -X POST $B/api/reset | jq '{integrity, totals, volume}'           # HEALTHY, 7/7
curl -s -X POST $B/api/traffic/start                                      # {"running":true}
curl -s -X POST $B/api/faults/duplicate                                   # {"fault":"duplicate","service":"settlement-svc"}
sleep 3
curl -s $B/api/overview | jq '{totals, integrity}'                        # debits == credits, status "violated"
curl -s $B/api/integrity | jq '.checks[] | {name, pass}'                  # ledger_balanced true; 2 checks false
curl -s "$B/api/payments?limit=10" | jq '.[] | select(.settlement_count>1)'  # the ×2 payment
sleep 5
ID=$(curl -s $B/api/incidents | jq -r '.[0].id')
curl -s $B/api/incidents/$ID | jq '{status, root_cause, impact_minor, containment, lineage}'
curl -s $B/api/incidents/$ID | jq '{proposal: .proposal.description, sandbox_passed: .sandbox.passed}'
curl -s -w '\nHTTP %{http_code}\n' -X POST $B/api/incidents/$ID/approve \
  -H 'Content-Type: application/json' -d '{"actor":"blackbox-agent"}'    # HTTP 403
curl -s -X POST $B/api/incidents/$ID/approve \
  -H 'Content-Type: application/json' -d '{"actor":"ops.lead@bank"}' | jq .status
sleep 3
curl -s $B/api/incidents/$ID | jq '{status, corrections, verification: [.verification.checks[] | {name, pass}]}'
curl -s "$B/api/ledger?limit=5" | jq '.[] | select(.kind=="compensation") | {id, corrects_entry_id, actor}'
curl -s -X POST $B/api/services/settlement-svc/release
curl -s "$B/api/audit?limit=20" | jq '.[] | {actor, action, detail}'
curl -s -X POST $B/api/traffic/stop
```

The SSE view, optionally in a split pane: `curl -N $B/api/stream`.

If the backend itself fails, play the pre-recorded run video (`<video link>`) and narrate over it using the same lines.

## Stage checklist
- Run Reset between rehearsals. Rehearse the full flow `<N>` times in a row without reloading the page.
- If an incident gets stuck before `awaiting_approval`, check `GET /api/incidents/{id}` → `status`. Fall back to curl and keep talking.
- Don't say "AI detected": the detection is deterministic. AI (if shown) only explains, and is labeled.
