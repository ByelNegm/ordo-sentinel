# TASKS — BLACKBOX
Owners: **Devin** = backend/lead, **UI** = colleague's Devin session. Times are Dubai.

## M0 — Pivot (13:15–13:30)
- [x] Branch `pivot/blackbox` from main; stop Ordo builders (Devin)
- [x] API contract v1 + frontend brief (Devin)
- [x] GOAL / TASKS / PROGRESS / README rewritten (Devin)

## M1 — Backend P0, duplicate settlement (→14:30, Devin)
- [x] Models, ledger, bank seed (100 payments), settlement-svc with all three fault modes
- [x] 7 integrity checks + reconciliation
- [x] Incident pipeline: investigate → contain → propose → sandbox → awaiting_approval
- [x] Approval gate (403/409), idempotent compensation, verification, release
- [x] Traffic trickle, reset, SSE, audit log
- [x] pytest suite green (64 tests); P0 HTTP flow 3× + each P2 HTTP flow; live curl flow for all three kinds from reset
- [x] Independent P0 review gate pass (6e21285, reviewer verdict PASS)
- [x] Review follow-ups: closed-incident handling/release, append failure audit, limit ≤500, unknown-id contract clarification
- [x] Devin Review gate fixes (f13b2e4): healthy-integrity fault gate; post-rejection and pre-quarantine overlap regressions

## M2 — UI (→14:45, UI)
Console delivered in PR #8 (ui/blackbox-console); merge pending. Live-only by design; no mock mode.
- [x] Shell, status bar, SSE hook against the real backend
- [x] Bank Operations · Attack Simulator
- [x] Incident Investigation · Recovery Sandbox · Recovery Verification
- [x] Acceptance flow 3× against the live backend without page reload; full missing and tamper UI recovery also passed

## M3 — P2 scenarios (14:30–15:00, Devin)
- [x] Missing settlement · Tampered settlement (detection + recovery)
- [x] Unsafe sandbox challenge endpoint: wrong_amount / reverse_original, isolated rejection, audit and real recovery regressions
- [x] Credible UAE names/IBANs, deterministic payment references/purposes and real-data incident summaries
- [x] Truthful sandbox challenge diagnostics: applied flag, policy/ledger reasons and actual post-apply checks

## M4 — Ship (15:00–16:00, Team)
- [x] README console run steps and demo reset checklist
- [ ] Feature freeze 15:00; e2e demo runs ×3
- [ ] 5-min script + video (incl. Devin engineering evidence)
- [ ] Submit by 15:30; rehearse

## Parking Lot
- LLM-written incident narrative (schema-validated, labeled)
