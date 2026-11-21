# API contract v1 — freeze at 12:15
Planning contract; no endpoints implemented yet. Base path /api. JSON over HTTP; no auth in this synthetic demo. All timestamps ISO 8601 with offset; demo clock is UAE (+04:00). IDs are opaque strings. Monetary values are nonnegative AED numbers (max 2 decimals); direction determines sign (render outgoing wire as −AED 450,000).

## Shared types / semantics
- State: {account:{id,name,balance,available,held,currency:"AED"}, frozen_clients:string[], protected_amount:number, scenario:"idle"|"normal"|"drain"}.
- Txn: exact txn.scored data shape below. Fields required; counterparty includes name, iban, country (ISO alpha-2), is_new, offshore. IBANs are synthetic placeholders, not validation samples.
- Risk: score integer 0–100, level low (<40), medium (40–59), high (60–75), critical (>75); factors array of {code,label,weight}. Weights are illustrative contributions; clamp aggregate score at 100.
- Alert: exact alert.created data shape below. severity uses same levels. customer_message is {en:string,ar:string}; all fields present even during LLM failure (template fallback).
- balance = posted funds; available = balance − held. Blocked transactions do not debit or reserve funds. Freeze targets the client/consent token, not the whole account.
- Policy <40 allow/posted; 40–75 hold/held; >75 or cumulative targeted drain >30% freeze/blocked. A low score can therefore still freeze. Existing holds stay held when a client freezes.
- proposed MVP decisions: confirm posts held funds only if client is not frozen; deny cancels holds without debiting; blocked money never posts through a confirm. Denied/expired holds become blocked in transaction snapshots. Frozen client must be explicitly unfrozen separately; never auto-retry a blocked transfer.
- protected_amount counts each denied, prevented transaction once, not every freeze attempt. Wire deny raises it to 450000; denying burst later raises it to 453000. Repeated same decision is idempotent; conflicting resolution is 409.
- Alert timeout: auto/expired; held funds released without posting, client remains frozen if already frozen. Timeout is not a customer-confirmed protection count.
- GET alerts returns active/unresolved alerts only. Resolved IDs disappear; retain history from alert.resolved in UI. Repeated alert.created ID is an upsert (burst grouping or explanation enrichment), not another alert. Reconcile snapshots after actions, reset or reconnect.
- These response/error/lifecycle details fill gaps for fixture-first development; coordinate changes before contract freeze.

## HTTP endpoints and examples
Success is 200 application/json throughout (including start/reset). No body on POST unless specified.

### GET /api/state
Response:
```json
{"account":{"id":"acct_001","name":"Aisha Al Mansoori","balance":520000,"available":520000,"held":0,"currency":"AED"},"frozen_clients":[],"protected_amount":0,"scenario":"idle"}
```

### GET /api/transactions?limit=50
Default 50, positive integer up to 200; newest first. Empty response: []. Txn schema and full mixed normal/drain list: fixtures/transactions.json (fixture is chronological for readability; sort descending for REST mock). Example response:
```json
[{"id":"txn_normal","ts":"2025-11-21T13:00:00+04:00","amount":85,"currency":"AED","direction":"out","counterparty":{"name":"Neighborhood Grocer","iban":"AE000000000000000000001","country":"AE","is_new":false,"offshore":false},"channel":"card","client_id":"card_001","device_id":"device_known","risk":{"score":8,"level":"low","factors":[]},"decision":"allow","status":"posted"}]
```

### GET /api/alerts
Response example below; [] when none. fixtures/alerts.json is the two active alerts just after wire block, before any customer decision.
```json
[{"id":"alert_wire","txn_ids":["txn_wire"],"severity":"critical","title":"AED 450,000 offshore wire blocked","analyst_explanation":"Unfamiliar API client, overnight burst and offshore destination. Token frozen before posting.","customer_message":{"en":"We blocked an unusual AED 450,000 overseas payment. Was this you?","ar":"حظرنا دفعة خارجية غير معتادة بقيمة ٤٥٠٬٠٠٠ درهم. هل أجريتها؟"},"actions":["confirm","deny"],"expires_at":"2025-11-22T02:05:02+04:00"}]
```

### POST /api/scenario/{normal|drain}/start
No body. Request examples: POST /api/scenario/normal/start and POST /api/scenario/drain/start.
Responses respectively:
```json
{"name":"normal","step":0,"total":3}
```
```json
{"name":"drain","step":0,"total":3}
```
normal is a three-transaction daytime trickle; drain submits three instructions at one-second intervals. Use normal first for the demo; drain starts after normal finishes. Reject overlapping runs with 409. State scenario remains last chosen name after completion until reset; step=total signals completion.

### POST /api/reset
No body. Cancel runner, invalidate pending explanation tasks/cache updates, clear alerts/transactions/freezes/protection and restore deterministic seed. Response is the same initial State as GET /api/state above. Emit account.updated and scenario.status {name:"idle",step:0,total:0}; UI clears lists and re-fetches all snapshots after reset. Reset must not permit a stale task/event to repopulate old state.

### POST /api/alerts/{id}/decision
Requests (either choice):
```json
{"decision":"deny"}
```
```json
{"decision":"confirm"}
```
Example POST /api/alerts/alert_wire/decision deny response:
```json
{"id":"alert_wire","resolution":"denied","by":"customer"}
```
Confirm on an eligible held transaction:
```json
{"id":"alert_burst","resolution":"confirmed","by":"customer"}
```
Emit alert.resolved then account.updated. Both UIs use this customer-attributed demo endpoint; analyst/auto are reserved event producers. Confirm for frozen client returns 409, does not move funds. Deny wire does not implicitly resolve burst.

### POST /api/clients/{client_id}/unfreeze
No body. Example POST /api/clients/api_partner_7/unfreeze response:
```json
{"balance":519915,"available":516915,"held":3000,"frozen_clients":[],"protected_amount":450000}
```
Returns account.updated data and emits it; no posting/retry implied. Known already-unfrozen client is idempotent; unknown client 404.

### GET /api/stream
Response headers: Content-Type: text/event-stream; Cache-Control: no-cache; X-Accel-Buffering: no. Each application frame is data: followed by a JSON envelope and two newlines; envelope type drives dispatch. Example wire bytes:
```text
data: {"type":"scenario.status","ts":"2025-11-22T02:00:00+04:00","data":{"name":"drain","step":0,"total":3}}

: heartbeat

```
Heartbeat comment every 15s; not a JSON event. Browser EventSource reconnects, then reload snapshots; no durable replay/Last-Event-ID guarantee in this MVP. fixtures/events.ndjson contains envelopes only, one per line: wrap each in data: … followed by a blank line for an SSE server, or dispatch directly in the frontend timer.

## Event envelope
All events: {type:string,ts:ISO8601,data:object}. No extra top-level fields.
### txn.scored
Upsert transaction by id. channel api|app|card, direction out|in; decision allow|hold|freeze; status posted|held|blocked.
```json
{"type":"txn.scored","ts":"2025-11-22T02:00:02+04:00","data":{"id":"txn_wire","ts":"2025-11-22T02:00:02+04:00","amount":450000,"currency":"AED","direction":"out","counterparty":{"name":"Pelagic Holdings","iban":"SC000000000000000000004","country":"SC","is_new":true,"offshore":true},"channel":"api","client_id":"api_partner_7","device_id":"device_api_new","risk":{"score":99,"level":"critical","factors":[{"code":"BALANCE_DRAIN","label":"Over 30% of balance targeted","weight":14}]},"decision":"freeze","status":"blocked"}}
```
All eight wire factors are shown in fixtures/transactions.json; this is a shortened valid payload.

### alert.created
```json
{"type":"alert.created","ts":"2025-11-22T02:00:02+04:00","data":{"id":"alert_wire","txn_ids":["txn_wire"],"severity":"critical","title":"AED 450,000 offshore wire blocked","analyst_explanation":"Deterministic policy froze the API client before posting.","customer_message":{"en":"We blocked an unusual AED 450,000 overseas payment. Was this you?","ar":"حظرنا دفعة خارجية غير معتادة بقيمة ٤٥٠٬٠٠٠ درهم. هل أجريتها؟"},"actions":["confirm","deny"],"expires_at":"2025-11-22T02:05:02+04:00"}}
```

### alert.resolved
resolution confirmed|denied|expired; by customer|analyst|auto.
```json
{"type":"alert.resolved","ts":"2025-11-22T02:00:08+04:00","data":{"id":"alert_wire","resolution":"denied","by":"customer"}}
```

### account.updated
Merge into State account money fields + top-level frozen_clients/protected_amount.
```json
{"type":"account.updated","ts":"2025-11-22T02:00:08+04:00","data":{"balance":519915,"available":516915,"held":3000,"frozen_clients":["api_partner_7"],"protected_amount":450000}}
```

### scenario.status
name idle|normal|drain; step/total nonnegative integers.
```json
{"type":"scenario.status","ts":"2025-11-22T02:00:02+04:00","data":{"name":"drain","step":3,"total":3}}
```

## Errors / empty cases
FastAPI-style error body; preserve state on errors. 404 unknown alert/client, 409 conflicting run/resolution or frozen-client confirm; 422 invalid body, scenario name or limit. Examples:
```json
{"detail":"Alert not found"}
```
```json
{"detail":"Client is frozen; confirmation cannot post funds"}
```
```json
{"detail":[{"loc":["body","decision"],"msg":"Input should be 'confirm' or 'deny'","type":"literal_error"}]}
```
UI shows a non-destructive error and re-fetches snapshots. Empty alerts/transactions are [], never null.

## Fixture checkpoints
state.json is the reset snapshot (no transactions); transactions.json is a scenario catalog, NOT transactions to deduct from the reset balance on load. alerts.json is an active-alert checkpoint before denial, NOT alerts to show immediately after reset.
Replay events.ndjson after simulating normal grocery txn_normal once (balance 519915). It includes grouped burst upserts, wire freeze, wire deny at +8s (protected 450000), optional burst deny at +9s (protected 453000). Stop at +8s for the headline demo. Timed decisions in the replay are scripted customer actions; interactive mock mode pauses these until the user taps. Each checkpoint is intentional; do not blindly load all fixtures as one initial snapshot.
