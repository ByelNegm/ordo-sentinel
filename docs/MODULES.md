# Backend module boundaries — Phase 0
Run one FastAPI worker. Models and these interfaces are the frozen builder handoff; HTTP/SSE payloads follow [API_CONTRACT.md](API_CONTRACT.md).

**Only edit your own module(s) + their tests; models.py changes need lead approval.** Builder A/B/C add tests in tests/test_risk_policy.py, tests/test_bank_scenario.py and tests/test_explainer.py respectively. Lead owns tests/test_contract.py, dependencies, routing and shared docs/config; coordinate interface changes before editing another owner's files.

## app/models.py — Lead
Pydantic v2 Account, State, Txn, Counterparty, Risk, Factor, Alert, CustomerMessage, Explanation, DecisionRequest, AlertResolved, AccountUpdated, ScenarioStatus; five typed events and EventEnvelope. EVENT_ADAPTER.validate_json(line) validates the discriminated Event union. No extra payload fields. Use model_dump(mode="json") for JSON primitives.

## app/main.py — Lead
create_app() -> FastAPI; app = create_app(). Routes all contracted endpoints; /fixtures is a development-only static fixture mount. app.state.bank/bus/runner are the shared instances. CORS permits http://localhost:5173. Shutdown/reset await runner.stop(). REST handlers mutate on the event loop, not worker threads.

## app/bus.py — Lead
EventBus(); async publish(event: Event) -> None; async with subscribe() as queue yields asyncio.Queue[Event]. Process-local fanout; 256-event queues drop oldest when full. No durable replay: reconnect must reload snapshots. SSE sends 15s idle heartbeats, no-cache and X-Accel-Buffering: no.

## app/risk.py — Builder A
score(txn: Txn, ctx: RiskContext) -> Risk. RiskContext(balance: float, cumulative_drain: float = 0, recent_transactions: list[Txn] = []). Stub returns the fixture risk unchanged. Replace with deterministic rules/customer statistics and reason factors; no trained ML or LLM decision-making.

## app/policy.py — Builder A
decide(risk: Risk, ctx: PolicyContext) -> Decision. PolicyContext(balance: float, cumulative_drain: float, client_frozen: bool = False); cumulative_drain includes the candidate once. Implements <40 allow, 40–75 hold, >75 or >30% cumulative drain freeze; frozen client always freezes.

## app/bank.py — Builder B
Bank(); snapshot() -> State; reset() -> State; account_update() -> AccountUpdated; post(txn: Txn), hold(txn: Txn), block(txn: Txn), freeze(client_id: str) -> None; unfreeze(client_id: str) -> AccountUpdated; upsert_alert(alert: Alert) -> None; resolve(alert_id: str, decision: str) -> AlertResolved. BankError(status: int, detail: str) maps to HTTP errors.

Public state: state: State; transactions: dict[str, Txn]; alerts: dict[str, Alert]; resolutions: dict[str, AlertResolved]; catalog: list[Txn]. Synchronous methods must not await, so each mutation stays atomic. Seed uses fixture account plus empty live records, not every fixture loaded as live state. Basic post/hold/block/deny/confirm/idempotency work; baseline expansion and timeout handling remain Builder B work. Frozen/blocked transfers cannot confirm; unfreeze does not retry.

## app/scenario.py — Builder B
ScenarioRunner(bank: Bank, bus: EventBus, pace: float = 1.0); running: bool; start(name: str) -> ScenarioStatus; async stop() -> None. start schedules one task; caller rejects overlap. stop cancels and joins before reset. Normal stub posts three known-payee debits totaling AED 85 (25/30/30), preserving the fixture checkpoint balance. Drain replays fixture instructions/alerts/status at relative timings, calls score/decide, applies bank mutations and publishes calculated account updates.

Drain stops before scripted fixture denials; customer must tap Deny. Direct drain from reset uses AED 520000; normal → drain uses AED 519915. Mock UI should still use the documented fixture checkpoint. Scenario names persist after completion until reset. Future async explanation enrichment must not delay enforcement or resurrect state after reset.

## app/explainer.py — Builder C
async explain(alert: Alert) -> Explanation, containing customer_message: CustomerMessage (en/ar) and analyst_explanation: str. Stub immediately returns fixture/template text. Add async cached LLM with timeout/fallback; never decide money movement. Keep enforcement independent of LLM latency. Current runner awaits this immediate stub; coordinate nonblocking enrichment with Builder B.

## Phase 0 limits / next integration
No live LLM, 90-day statistical seed, automatic alert expiry or real frontend proxy verification yet. Risk is fixture-backed, not a validated detector. Builder B must implement expiry against simulated time (fixture timestamps are not wall clock). Snapshot reconciliation remains required after decisions/reconnect/reset; there is no transaction-resolved event. Main serves all contract endpoints today; this is not a claim of complete production behavior.
