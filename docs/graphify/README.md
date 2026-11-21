# BLACKBOX: local Graphify architecture map

Generated with **graphifyy 0.9.110**, Python 3.10, tree-sitter only.
No semantic extraction, LLM community naming, API key or model calls.
The report records **0 input / 0 output tokens**.

## Reproduce

```sh
uv tool install graphifyy
# Run from this repository; choose a new/empty corpus directory.
mkdir -p "$HOME/blackbox-evidence/graphify-input"
git archive d04ed0ca6021f2cf33f67c1f1302fc38e7829c15 backend frontend/src |
  tar -x -C "$HOME/blackbox-evidence/graphify-input"
graphify extract "$HOME/blackbox-evidence/graphify-input" \
  --code-only --no-cluster --max-workers 2 --out docs/graphify
graphify cluster-only docs/graphify --no-label
```

The fresh `docs/graphify` branch starts at backend **8c4589c**.
That revision has only `frontend/.gitkeep`; the corpus therefore uses console
revision **d04ed0c**. Its backend tree is byte-identical to 8c4589c:
`31a5933f95c112662178b3ba7e3d559c0e279209`. Neither code tree was modified.
The generated report's 8c4589c freshness stamp reflects the working directory,
not a separate frontend revision; use this explicit two-revision provenance.

Artifacts are in [graphify-out/](graphify-out/):
[graph.json](graphify-out/graph.json),
[GRAPH_REPORT.md](graphify-out/GRAPH_REPORT.md),
[graph.html](graphify-out/graph.html).
337 nodes, 1,147 clustered edges, 10 communities. Extraction initially emitted
1,245 edges; Graphify's build combines same-endpoint relationships.
24 code files scanned; `main.tsx` yielded no symbols. CSS, pytest.ini,
.gitkeep and requirements text are not indexed as code. Backend tests are included.
The HTML loads vis-network from unpkg; graph construction/querying is local.

## Four architecture queries

All output below is pasted from actual CLI runs. Commands use:
```sh
G=docs/graphify/graphify-out/graph.json
```

**Important:** an AST dependency graph is not a control-flow or points-to proof.
Graphify missed some dynamic receiver calls and can traverse containment
backwards even with `--directed`. INFERRED paths below are navigation aids,
not invented call chains. Source bridges/guards are called out separately.

### 1. Approval route to journal

```sh
graphify path backend_app_main_create_app_approve backend_app_ledger_ledger_append --graph "$G" --directed
```
```text
Shortest path (5 hops):
  approve() <--contains [EXTRACTED]-- create_app() --calls/uses [EXTRACTED/INFERRED 0.95]--> Runtime --uses [INFERRED 0.95]--> Bank --uses [INFERRED 0.95]--> Ledger --method [EXTRACTED]--> .append()
Path confidence: INFERRED (weakest hop 2: uses, score 0.95)
```

Source-verified dispatch: `backend/app/main.py:95–98` binds
`POST /api/incidents/{identifier}/approve` to
`runtime.coordinator.approve(identifier, body.actor)`.
`incident.py:418` calls the live `self.bank.ledger.append_batch(batch)`;
`ledger.py:73–76` first validates with `trial = deepcopy(self)` and
`trial.append(...)`, then publishes the validated batch to `self._entries`.
This exact dynamic call chain is **not fully resolved** by the graph above.

### 2. What triggers integrity checks?

```sh
graphify path backend_app_incident_incidentcoordinator_observe_post backend_app_integrity_inspect --graph "$G" --directed
```
```text
Shortest path (2 hops):
  .observe_post() --calls [EXTRACTED]--> .observe_integrity() --calls [EXTRACTED]--> inspect()
Path confidence: EXTRACTED (weakest hop 1: calls)
```

`backend/app/incident.py:56–68` dispatches post observation to the pure
`backend/app/integrity.py:148` inspector. Sandbox and approval also call
`inspect` before/after copied corrections and after real recovery, respectively.

### 3. Agent proposals cannot bypass the approval gate

```sh
graphify path backend_app_incident_incidentcoordinator_approve backend_app_ledger_ledger_append_batch --graph "$G" --directed
```
```text
Shortest path (3 hops):
  .approve() --calls [EXTRACTED]--> inspect() --references/uses [EXTRACTED/INFERRED 0.95]--> Ledger --method [EXTRACTED]--> .append_batch()
Path confidence: INFERRED (weakest hop 2: uses, score 0.95)
```

The graph locates the recovery boundary, but does **not** encode actor predicates.
Source verification supplies that missing fact: `incident.py:16–17` sets
`APPROVERS = {"ops.lead@bank", "treasury@bank"}` and
`AGENT = "blackbox-agent"`. At lines 395–397:

```python
if actor not in APPROVERS:
    await self.bus.publish(self.record(actor, "approval.denied", identifier, "Unauthorized approver"))
    raise ActionError(403, "Actor is not an authorized approver")
```

This executes before incident lookup, sandbox revalidation or the live append
at line 418. The route forwards `body.actor`; the agent is excluded from the
allowlist. This is the demo's actor gate, not production authentication.
Normal settlement writes are separate from agent recovery writes.

### 4. Sandbox appends target a copy

```sh
graphify path backend_app_incident_incidentcoordinator_sandbox backend_app_ledger_ledger_append --graph "$G" --directed
```
```text
Shortest path (3 hops):
  .sandbox() --calls [EXTRACTED]--> inspect() --references/uses [EXTRACTED/INFERRED 0.95]--> Ledger --method [EXTRACTED]--> .append()
Path confidence: INFERRED (weakest hop 2: uses, score 0.95)
```

Copy isolation is a source fact, not an alias guarantee from that path.
`backend/app/incident.py:227–257` starts with:
```python
ledger = deepcopy(self.bank.ledger)
instructions = deepcopy(self.bank.instructions)
events = deepcopy(self.bank.events)
before = inspect(ledger, instructions, events)
```
The candidate is checked against the canonical proposal, then
`ledger.append(entry, self.correction_key(incident, entry))` writes only this
local copy; `after = inspect(ledger, instructions, events)` inspects the same copy.
The agent pipeline calls this sandbox, not the live correction append.

Additional verification (unchanged backend, existing regression tests):
```sh
cd backend
pytest -q tests/test_incident.py::test_unauthorized_approval_never_posts \
  tests/test_incident.py::test_invalid_proposal_fails_sandbox_and_approval_without_touching_ledger
```
These cover denial with no live posting and byte-identical real ledger after
invalid sandbox/recovery attempts.
```text
8 passed, 1 warning in 2.18s
```
The warning is the existing Starlette/httpx TestClient deprecation.

## Viewer evidence

Serve locally with `python3 -m http.server 8766 --bind 127.0.0.1 --directory docs/graphify/graphify-out`
and open `http://127.0.0.1:8766/graph.html`.
Screenshot: `/home/ubuntu/blackbox-evidence/graphify.png`.
