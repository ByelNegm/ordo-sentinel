# Ordo Sentinel — north star
Protect the customer when authentication succeeds but intent is absent: show bank-side autonomous transaction defense stopping an asleep customer's 2 AM API drain, paired with a clear customer guardian UI. Build only a credible, repeatable hackathon MVP: deterministic rules/statistics control money movement; the LLM explains in EN/AR and never decides. Team **ordo_system** ships the smallest working proof, not a production bank.

## Single demo success criterion
**Normal → 2 AM drain → AED 450,000 offshore wire frozen → phone Deny → “AED 450,000 protected” → reset; repeatable.** Five minutes, no Q&A. Target wire enforcement <1 second; measure before claiming it. Freeze the API client/consent token and block the wire, not the entire account. Deny the wire before the smaller burst to preserve the headline counter.

## Judging criteria
- **Innovation:** defend transaction intent after successful authentication.
- **Technical:** working rules/stats, deterministic policy, SSE and safe action handling; LLM fallback.
- **Practicality:** bank-side intervention with an understandable, independent-channel guardian simulation.
- **Demo Quality:** coherent five-minute story, legible screens, repeatable reset and measured claims.
- **Devin Use Case:** show parallel backend/frontend Devin sessions and their integration in the video.

## Scope guardrails
**In scope:** single-process Python FastAPI; seeded in-memory one-customer bank with 90-day baseline; normal/drain asyncio runner; 0–100 risk + reasons; allow/hold/freeze policy; decision/unfreeze/reset REST endpoints; SSE with 15s heartbeat; async cached EN/AR LLM explanations + templates; React/Vite/Tailwind /phone and /analyst; fixtures/mock replay; tests and demo recording.

**Out of scope:** authentication, real DB, real payments, real SMS/push, ML training, multiple customers, native mobile and production-security claims. Daytona hosting only if ≤20 minutes; Graphify/Collabute skipped unless an immediate quick win.

## Deadline / drift check
**2026-11-21, Asia/Dubai: submit GitHub + video by 15:30; hard deadline 16:00.** Contract 12:15; integration 13:45; feature freeze 14:45; Cap recording 15:00.

Before starting new work, name the demo-arc step or judging criterion it serves. If neither, put it in **Parking Lot**, not the active checklist. After feature freeze, only demo-breaking fixes. Coordinate contract changes with both owners; see [plan](docs/PLAN.md), [contract](docs/API_CONTRACT.md), [tasks](TASKS.md) and [progress](PROGRESS.md).

## Parking Lot
- Post-hackathon ideas only; no active commitments. Record proposed work here with its rationale before expanding scope.
