import pytest
from pydantic import TypeAdapter

from app.models import (AuditRecord, Incident, IntegrityReport, JournalEntry,
                        Overview, PaymentInstruction, SettlementEvent)
from conftest import awaiting_incident, duplicate_via_http, wait_for


def healthy(report):
    assert report["status"] == "healthy"
    assert len(report["checks"]) == 7 and all(c["pass"] for c in report["checks"])
    assert all(set(c) == {"name", "pass", "detail"} for c in report["checks"])


def test_read_endpoints_and_frozen_shapes(client):
    overview = Overview.model_validate(client.get("/api/overview").json())
    assert len(overview.accounts) == 12
    assert overview.volume.instructions == overview.volume.settled == 100
    assert overview.totals.ledger_entries == 100
    assert overview.totals.debits_minor == overview.totals.credits_minor
    assert overview.services[0].status == "running" and overview.services[0].fault is None
    assert overview.integrity.failing_checks == 0 and overview.open_incidents == 0
    assert client.get("/api/incidents").json() == []
    assert client.get("/api/incidents/unknown").status_code == 404
    for path, model in [("payments", PaymentInstruction), ("settlements", SettlementEvent),
                        ("ledger", JournalEntry), ("audit", AuditRecord)]:
        response = client.get("/api/" + path + "?limit=2")
        assert response.status_code == 200
        rows = TypeAdapter(list[model]).validate_python(response.json())
        assert 0 < len(rows) <= 2
        assert rows[0].id > rows[-1].id or len(rows) == 1
        assert client.get("/api/" + path + "?limit=0").status_code == 422
        assert client.get("/api/" + path + "?limit=500").status_code == 200
        assert client.get("/api/" + path + "?limit=501").status_code == 422
    healthy(client.get("/api/integrity").json())


@pytest.mark.parametrize("run", range(3))
def test_entire_p0_flow_three_times_from_clean_seed_via_http(client, run):
    seed = client.post("/api/reset").json()
    assert seed["volume"]["settled"] == 100 and seed["totals"]["ledger_entries"] == 100
    assert client.post("/api/traffic/start").json() == {"running": True}
    wait_for(lambda: client.get("/api/overview").json()["volume"]["instructions"] > 100)
    healthy(client.get("/api/integrity").json())
    assert client.post("/api/faults/duplicate").json() == {
        "fault": "duplicate", "service": "settlement-svc"}
    incident = awaiting_incident(client)
    wait_for(lambda: client.get("/api/overview").json()["volume"]["held"] > 0)
    assert client.post("/api/traffic/stop").json() == {"running": False}
    identifier = incident["id"]
    incident = client.get("/api/incidents/" + identifier).json()
    Incident.model_validate(incident)
    report = client.get("/api/integrity").json()
    assert {c["name"] for c in report["checks"] if not c["pass"]} == {
        "single_financial_effect", "ledger_matches_expected"}
    assert next(c for c in report["checks"] if c["name"] == "ledger_balanced")["pass"]
    assert incident["root_cause"]["service"] == "settlement-svc"
    assert incident["root_cause"]["method"] == "deterministic"
    assert len(incident["lineage"][0]["event_ids"]) == 2
    assert incident["sandbox"]["passed"]
    assert client.post("/api/services/settlement-svc/release").status_code == 409
    before = client.get("/api/ledger?limit=500").json()
    for actor in ("blackbox-agent", "unauthorized@bank"):
        assert client.post("/api/incidents/" + identifier + "/approve",
                           json={"actor": actor}).status_code == 403
    assert client.get("/api/ledger?limit=500").json() == before
    response = client.post("/api/incidents/" + identifier + "/approve",
                           json={"actor": "ops.lead@bank"})
    assert response.status_code == 200, response.text
    resolved = response.json()
    assert resolved["status"] == "resolved"
    assert resolved["approval"]["actor"] == "ops.lead@bank"
    assert len(resolved["corrections"]) == 1
    healthy(resolved["verification"])
    after = client.get("/api/ledger?limit=500").json()
    assert len(after) == len(before) + 1
    assert after[1:] == before
    assert after[0]["corrects_entry_id"] in {e["id"] for e in before}
    assert after[0]["actor"] == "ops.lead@bank"
    again = client.post("/api/incidents/" + identifier + "/approve",
                        json={"actor": "treasury@bank"})
    assert again.json() == resolved
    assert client.get("/api/ledger?limit=500").json() == after
    assert client.post("/api/incidents/" + identifier + "/approve",
                       json={"actor": "blackbox-agent"}).status_code == 403
    assert client.post("/api/services/settlement-svc/release").json()["status"] == "running"
    assert client.get("/api/overview").json()["volume"]["held"] == 0
    healthy(client.get("/api/integrity").json())
    payments = client.get("/api/payments?limit=500").json()
    assert all(p["status"] == "settled" for p in payments)
    audit = client.get("/api/audit?limit=500").json()
    actions = {record["action"] for record in audit}
    assert {"fault.injected", "incident.detected", "service.quarantined", "recovery.proposed",
            "sandbox.completed", "approval.denied", "recovery.approved", "ledger.compensated",
            "recovery.verified", "service.released"} <= actions
    reset = client.post("/api/reset").json()
    assert reset == seed
    assert client.get("/api/incidents").json() == []
    healthy(client.get("/api/integrity").json())


@pytest.mark.parametrize("kind", ["duplicate", "missing", "tamper"])
def test_fault_modes_and_conflicts(client, kind):
    assert client.post("/api/faults/unknown").status_code == 422
    assert client.post("/api/faults/" + kind).status_code == 200
    assert client.post("/api/faults/" + kind).status_code == 409
    client.post("/api/reset")
    duplicate_via_http(client)
    assert client.post("/api/faults/" + kind).status_code == 409


def test_reject_cannot_approve_but_can_release_held_payments(client):
    incident = duplicate_via_http(client)
    identifier = incident["id"]
    before = client.get("/api/ledger?limit=500").json()
    response = client.post("/api/incidents/" + identifier + "/reject",
                           json={"actor": "ops.lead@bank"})
    assert response.status_code == 200 and response.json()["status"] == "rejected"
    assert client.post("/api/incidents/" + identifier + "/approve",
                       json={"actor": "ops.lead@bank"}).status_code == 409
    assert client.get("/api/ledger?limit=500").json() == before
    held = client.get("/api/overview").json()["volume"]["held"]
    assert client.post("/api/services/settlement-svc/release").status_code == 200
    assert client.get("/api/ledger?limit=500").json()[held:] == before
    assert client.get("/api/overview").json()["services"][0]["status"] == "running"
    assert client.get("/api/overview").json()["open_incidents"] == 0


def test_approval_state_and_body_validation(client):
    runtime = client.app.state.runtime
    runtime.coordinator.step_delay = 10
    client.post("/api/faults/duplicate")
    client.post("/api/traffic/start")
    incident = wait_for(lambda: (client.get("/api/incidents").json() or [None])[0])
    client.post("/api/traffic/stop")
    assert incident["status"] == "detected"
    path = "/api/incidents/" + incident["id"]
    assert client.post(path + "/approve", json={"actor": "ops.lead@bank"}).status_code == 409
    assert client.post(path + "/reject", json={"actor": "ops.lead@bank"}).status_code == 409
    assert client.post(path + "/approve", json={}).status_code == 422
    assert client.post("/api/incidents/missing/approve",
                       json={"actor": "ops.lead@bank"}).status_code == 404
    assert client.post("/api/incidents/missing/approve",
                       json={"actor": "blackbox-agent"}).status_code == 403
    assert client.post("/api/incidents/missing/reject",
                       json={"actor": "ops.lead@bank"}).status_code == 404


def test_invalid_proposal_rejected_through_http_with_byte_identical_ledger(client):
    incident = duplicate_via_http(client)
    runtime = client.app.state.runtime
    runtime.coordinator.get(incident["id"]).proposal.entries = []
    before = runtime.bank.ledger.serialize()
    response = client.post("/api/incidents/" + incident["id"] + "/approve",
                           json={"actor": "ops.lead@bank"})
    assert response.status_code == 409
    assert runtime.bank.ledger.serialize() == before
    assert client.get("/api/incidents/" + incident["id"]).json()["status"] == "failed"


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:5173"])
def test_cors(client, origin):
    response = client.options("/api/reset", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST"})
    assert response.headers["access-control-allow-origin"] == origin
