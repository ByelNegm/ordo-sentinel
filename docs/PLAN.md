# MVP execution plan
## Success criterion
Five-minute live demo, no Q&A: normal daytime activity → deterministic 2 AM API burst → offshore AED 450,000 wire blocked in <1 second of submission → clear phone explanation → Deny → **AED 450,000 protected**. This is a target to measure during implementation, not a latency claim already tested.

## Build only
- One FastAPI process; in-memory bank with one customer (~AED 520k), reset, seeded 90-day baseline, known payees/devices/API clients.
- asyncio runner: normal daytime trickle and repeatable drain sequence. Fixed simulated timestamps; wall-clock sleeps only pace presentation.
- Risk score 0–100: amount z-score, hour histogram, velocity window, new payee/device/API client, demo offshore list, percentage of balance targeted.
- Policy: <40 allow; 40–75 hold + out-of-band step-up; >75 **or cumulative drain >30%** freeze API client/consent token. Count posted, held and attempted amounts once in the drain window, including the candidate; do not wait for funds to leave.
- Hybrid detection: deterministic rules/statistics decide; no trained ML. Async cached LLM EN/AR customer message + analyst narrative; immediate template fallback. Never block enforcement on LLM.
- SSE event bus with 15s comment heartbeat and X-Accel-Buffering: no; REST actions.
- One React/Vite/Tailwind app: /phone guardian and /analyst dashboard. Vite /api → :8000.
- Fixture baseline: AED 520,000; normal grocery debit AED 85; hold AED 1,200 + AED 1,800; block AED 450,000. Denying wire displays exactly AED 450,000 protected; denying remaining burst later increases it to AED 453,000.

## Cuts / hard stop
No auth, real DB, real SMS/push, ML training, multi-customer, native mobile, real payments or production-security claims. Guardian UI simulates the independent channel; compromised API credentials cannot submit real customer approvals in a production design. No app code in this planning commit.

## Today (local event time; starting ~11:45; deadline 16:00)
| Time | Deliverable |
|---|---|
| 12:15 | Contract + fixtures frozen; UI skeleton |
| 13:45 | End-to-end integration (both screens + SSE + decisions) |
| 14:45 | Feature freeze; only demo-breaking fixes |
| 15:00 | Record five-minute video with Cap |
| 15:30 | Submit GitHub repository + video link |
| 15:30–16:00 | Buffer / rehearsal |

## Ownership / coordination
- Backend owner + Devin: bank mock, runner, risk, policy, explainer, SSE; api/* branches.
- Frontend colleague + separate Devin: all UI; ui/* branches; work against fixtures immediately, never wait on backend.
- PRs target main; freeze shared API at 12:15, coordinate any breaking change with both owners. No remote/push until repository exists.
- Devin: parallel sessions, show in video. Cap: recording. Daytona: optional hosting only if ≤20 minutes; otherwise local demo. Graphify/Collabute: skip unless immediate quick win.

## Five-minute demo script
| Elapsed | Action / narration |
|---|---|
| 0:00–0:40 | Show normal daytime activity and customer baseline. “Authentication is not intent.” |
| 0:40–1:20 | Trigger 2 AM drain; show API burst, new payees, risk chips and holds. |
| 1:20–2:10 | AED 450,000 offshore wire arrives; show blocked status and frozen API token in <1s target. |
| 2:10–3:10 | Switch to phone: plain-language EN/AR warning; tap Deny on wire. |
| 3:10–3:50 | Show AED 450,000 protected, unchanged posted balance and audit resolution; no LLM money decisions. |
| 3:50–4:30 | Explain rules/stats + async explanations; show parallel Devin workflow briefly. |
| 4:30–5:00 | Reset; show repeatability. Close with customer protection, not another login check. |

## Acceptance / rehearsal checks (future implementation)
Normal posts once; medium risk holds; boundary scores 39/40/75/76 behave correctly; >30% overrides score. Duplicate deny does not double-count; stale confirm cannot bypass a freeze; timeout never releases funds. SSE disconnect recovers via REST snapshots; reset cancels old runner; LLM failure leaves templates usable. Measure freeze latency; rehearse twice and record before submission.
