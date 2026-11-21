# How We Used Devin

BLACKBOX was built in a single hackathon day by a small team using Devin as an engineering organization rather than an autocomplete. Placeholders `<like this>` are filled with the final numbers at freeze.

## 1. A lead session orchestrating parallel builders
- One **lead Devin session** owned the plan, the API contract, integration and merges.
- It split the backend into modules with explicit ownership boundaries and started **one builder Devin session per module**, all running in parallel on their own `api/*` branches:

| PR | Builder | Module |
|---|---|---|
| [#1](https://github.com/ByelNegm/ordo-sentinel/pull/1) | Lead | Skeleton: frozen contract models, all endpoints, SSE, module boundaries |
| [#2](https://github.com/ByelNegm/ordo-sentinel/pull/2) | Builder A | Risk scoring + policy |
| [#3](https://github.com/ByelNegm/ordo-sentinel/pull/3) | Builder C | Explainer (templates EN/AR + optional, capped LLM rewrite) |
| [#4](https://github.com/ByelNegm/ordo-sentinel/pull/4) | Builder B | Seeded bank + scenario runner |

- The lead merged the builder branches into the skeleton and verified the integrated system end to end (pytest + live curl/SSE runs) before recording the results in PROGRESS.md.
- The BLACKBOX backend (`ledger`, `bank`, `settlement`, `integrity`, `incident`, `traffic`) follows the same pattern: `<BLACKBOX backend PR links>`.

## 2. An independent review gate
- A separate **review-gate Devin session**, which never wrote any of the code, reviewed each deliverable against GOAL.md and the contract before merge. It checked the code for contract drift, invented metrics, hidden fake states, and claims not backed by test output.
- **Devin Review** ran on the PRs as an additional automated reviewer; its comments were fixed or answered on the PR.
- The rule: a builder can't mark its own work done; only the gate and the lead's integration run can.

## 3. Anti-drift files
Every session, human or Devin, reads the same three files before taking work:
- [GOAL.md](../GOAL.md): north star, scope, hard rules (deterministic code decides; AI never moves money; no history rewrite).
- [TASKS.md](../TASKS.md): milestones with owners, plus a Parking Lot for new ideas, so scope creep is written down instead of built.
- [PROGRESS.md](../PROGRESS.md): a dated, timed log appended in the same PR as the work, with exact test counts and caveats.

This kept `<N>` concurrent sessions aligned without a human relaying context between them.

## 4. A frozen API contract enabling a parallel UI
- [API_CONTRACT.md](API_CONTRACT.md) was frozen (v1) before any implementation. Changes need lead sign-off.
- [FRONTEND_BRIEF.md](FRONTEND_BRIEF.md) was pasted into a **colleague's separate Devin session**, which built the React operations console against the contract, first in mock mode and then against the live backend. Backend and UI were built simultaneously by different people's Devins, with the contract as the only interface.
- The brief forbids fake buttons and prerecorded success states: every control calls the real backend.

## 5. A mid-hackathon pivot without rewriting history
- At 13:14 the team pivoted from **Ordo Sentinel** (customer-fraud defense) to **BLACKBOX**. The lead Devin:
  - stopped the in-flight Ordo builders (PR [#5](https://github.com/ByelNegm/ordo-sentinel/pull/5) left unmerged),
  - branched `pivot/blackbox` from `main`, keeping PRs #1–#4 merged and intact,
  - froze a new contract and frontend brief, and rewrote GOAL/TASKS/PROGRESS/README, with the Ordo log archived in PROGRESS.md,
  - kept the discontinued code in `legacy/ordo_sentinel/` and in git history. No force-push or history rewrite.
- Contract and brief were ready about 6 minutes after the pivot decision (PROGRESS.md 13:14 → 13:20), and the UI session started immediately.

## 6. Test and verification evidence
| Item | Result |
|---|---|
| Backend pytest (`cd backend && pytest -q`) | `<N tests passed>` |
| Full duplicate-settlement curl flow from Reset | `<N/N runs passed>` |
| UI acceptance flow without reloading the page | `<N/N runs passed>` |
| Review-gate verdict | `<pass / findings fixed>` |
| Devin Review comments addressed | `<N>` |

## What Devin did vs. what humans did
- **Humans:** chose the track and the pivot, made the product decisions, approved merges, ran the demo.
- **Devin:** planning, contract design, parallel module implementation, integration, tests, independent review, docs, and this demo script.
