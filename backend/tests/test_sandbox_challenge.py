import asyncio

import pytest

from app.incident import ActionError
from app.traffic import Runtime
from conftest import awaiting_incident


@pytest.mark.parametrize("kind", ["duplicate", "missing", "tamper"])
@pytest.mark.parametrize("variant", ["wrong_amount", "reverse_original"])
def test_challenge_isolated_rejected_audited_and_real_recovery_succeeds(client, kind, variant):
    assert client.post("/api/faults/" + kind).status_code == 200
    assert client.post("/api/traffic/start").status_code == 200
    incident = awaiting_incident(client)
    client.post("/api/traffic/stop")
    path = "/api/incidents/" + incident["id"]
    original = client.get(path).json()
    ledger = client.get("/api/ledger?limit=500").content
    response = client.post(path + "/sandbox/challenge", json={"variant": variant})
    assert response.status_code == 200
    result = response.json()
    assert result["variant"] == variant
    assert result["ledger_unchanged"] is True
    assert result["sandbox"]["passed"] is False
    applied = variant == "reverse_original" or kind == "missing"
    assert result["applied"] is applied
    assert result["rejection_reasons"]
    assert all(r["detail"] for r in result["rejection_reasons"])
    rules = {r["rule"] for r in result["rejection_reasons"]}
    if kind == "duplicate" and variant == "reverse_original":
        assert rules == {"lineage_guard"}
        assert all(c["pass"] for c in result["sandbox"]["checks_after"])
    elif applied:
        assert "integrity_check" in rules
        assert any(not c["pass"] for c in result["sandbox"]["checks_after"])
    else:
        assert "ledger_guard" in rules
        assert result["sandbox"]["checks_after"] == result["sandbox"]["checks_before"]
    assert next(c for c in result["sandbox"]["checks_after"] if c["name"] == "ledger_balanced")["pass"]
    assert (result["sandbox"]["balances_before"] != result["sandbox"]["balances_after"]) is applied
    assert client.get("/api/ledger?limit=500").content == ledger
    assert client.get(path).json() == original
    assert original["status"] == "awaiting_approval"
    for actual, proposed in zip(result["proposal"]["entries"], original["proposal"]["entries"]):
        assert sum(l["amount_minor"] for l in actual["lines"] if l["side"] == "debit") == sum(
            l["amount_minor"] for l in actual["lines"] if l["side"] == "credit")
        if variant == "wrong_amount":
            assert [l["amount_minor"] for l in actual["lines"]] == [
                l["amount_minor"] + 100 for l in proposed["lines"]]
    if variant == "reverse_original" and kind == "duplicate":
        target = result["proposal"]["entries"][0]["corrects_entry_id"]
        assert target == original["lineage"][0]["entry_ids"][0]
        assert target != original["proposal"]["entries"][0]["corrects_entry_id"]
    audit = client.get("/api/audit").json()[0]
    assert audit["action"] == "sandbox.challenge.rejected" and variant in audit["detail"]
    resolved = client.post(path + "/approve", json={"actor": "ops.lead@bank"}).json()
    assert resolved["status"] == "resolved"
    assert all(c["pass"] for c in resolved["verification"]["checks"])
    assert len(resolved["verification"]["checks"]) == 7
    assert client.post(path + "/sandbox/challenge", json={"variant": variant}).status_code == 409


def test_challenge_unknown_id_invalid_variant_and_empty_bank(client):
    audit = client.get("/api/audit").json()
    body = {"variant": "wrong_amount"}
    assert client.post("/api/incidents/unknown/sandbox/challenge", json=body).status_code == 404
    assert client.post("/api/incidents/unknown/sandbox/challenge", json={"variant": "unknown"}).status_code == 422
    assert client.get("/api/incidents").json() == []
    assert len(client.get("/api/ledger?limit=500").json()) == 100
    assert client.get("/api/audit").json() == audit


def test_challenge_publishes_audit_event_and_rejects_early_status():
    async def run():
        runtime = Runtime(step_delay=0, missing_grace=0)
        try:
            await runtime.inject("duplicate")
            await runtime.submit_payment()
            await asyncio.gather(*tuple(runtime.coordinator.tasks))
            incident = next(iter(runtime.coordinator.incidents.values()))
            async with runtime.bus.subscribe() as queue:
                async with runtime.lock:
                    await runtime.coordinator.challenge(incident.id, "wrong_amount")
                event = await asyncio.wait_for(queue.get(), timeout=1)
                assert event.type == "audit.appended"
                assert event.data.action == "sandbox.challenge.rejected"
            incident.status = "investigating"
            with pytest.raises(ActionError) as exc:
                await runtime.coordinator.challenge(incident.id, "wrong_amount")
            assert exc.value.status == 409
        finally:
            await runtime.stop()
    asyncio.run(run())
