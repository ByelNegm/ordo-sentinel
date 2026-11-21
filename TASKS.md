# TASKS — BLACKBOX
Owners: **Devin** = backend/lead, **UI** = colleague's Devin session. Times are Dubai.

## M0 — Pivot (13:15–13:30)
- [x] Branch `pivot/blackbox` from main; stop Ordo builders (Devin)
- [x] API contract v1 + frontend brief (Devin)
- [x] GOAL / TASKS / PROGRESS / README rewritten (Devin)

## M1 — Backend P0, duplicate settlement (→14:30, Devin)
- [x] Models, ledger, bank seed (100 payments), settlement-svc duplicate fault + P2 hooks (501)
- [x] 7 integrity checks + reconciliation
- [x] Incident pipeline: investigate → contain → propose → sandbox → awaiting_approval
- [x] Approval gate (403/409), idempotent compensation, verification, release
- [x] Traffic trickle, reset, SSE, audit log
- [x] pytest suite green (33 tests); full HTTP flow 3× from clean seeds + live curl flow 1×
- [ ] Independent review gate pass

## M2 — UI (→14:45, UI)
- [ ] Shell, status bar, SSE hook, mock mode
- [ ] Bank Operations · Attack Simulator
- [ ] Incident Investigation · Recovery Sandbox · Recovery Verification
- [ ] Acceptance flow 3× against the live backend

## M3 — P2 scenarios (14:30–15:00, Devin)
- [ ] Missing settlement · Tampered settlement (detection + recovery)

## M4 — Ship (15:00–16:00, Team)
- [ ] Feature freeze 15:00; e2e demo runs ×3
- [ ] 5-min script + video (incl. Devin engineering evidence)
- [ ] Submit by 15:30; rehearse

## Parking Lot
- LLM-written incident narrative (schema-validated, labeled)
