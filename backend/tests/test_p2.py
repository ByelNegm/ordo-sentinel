import asyncio
from datetime import timedelta

import pytest

from app.bank import Bank
from app.incident import ActionError
from app.integrity import event_integrity, inspect
from app.models import PostingLine, utcnow
from app.settlement import SettlementService
from app.traffic import Runtime
from conftest import awaiting_incident, duplicate_via_http, wait_for


async def ready(runtime, kind):
    await runtime.inject(kind)
    await runtime.submit_payment()
    await asyncio.gather(*tuple(runtime.coordinator.tasks))
    incident = next(iter(runtime.coordinator.incidents.values()))
    assert incident.status == "awaiting_approval"
    return incident


def test_missing_grace_boundary_drops_real_event_and_posting():
    bank = Bank()
    service = SettlementService(bank, missing_grace=3)
    bank.seed(service)
    now = utcnow()
    payment = bank.next_payment(now)
    before = bank.ledger.serialize()
    service.inject("missing")
    service.enqueue(payment)
    service.process_queue()
    assert len(bank.events) == 100 and bank.ledger.serialize() == before
    assert payment.status == "accepted" and payment.settlement_count == 0
    assert service.expire_missing(now + timedelta(seconds=2.999)) == []
    assert inspect(bank.ledger, bank.instructions, bank.events).status == "healthy"
    assert service.expire_missing(now + timedelta(seconds=3)) == [payment.id]
    assert payment.status == "missing"
    assert {c.name for c in inspect(bank.ledger, bank.instructions, bank.events).checks
            if not c.passed} == {"no_missing_settlements", "ledger_matches_expected"}
    service.enqueue(payment)
    service.process_queue()
    assert bank.ledger.serialize() == before and len(bank.events) == 100


@pytest.mark.parametrize("kind", ["missing", "tamper"])
def test_p2_lineage_sandbox_recovery_idempotency_and_release(kind):
    async def run():
        runtime = Runtime(step_delay=0, missing_grace=0)
        try:
            incident = await ready(runtime, kind)
            payment = runtime.bank.instructions[incident.affected_payments[0]]
            assert incident.type == {"missing": "missing_settlement", "tamper": "tampered_settlement"}[kind]
            assert incident.root_cause.service == "settlement-svc"
            assert incident.root_cause.method == "deterministic"
            assert incident.root_cause.confidence == "high"
            assert incident.sandbox.passed
            assert all(c.passed for c in incident.sandbox.checks_after)
            assert incident.sandbox.balances_before != incident.sandbox.balances_after
            assert set(incident.affected_accounts) == {payment.debtor, payment.creditor}
            if kind == "missing":
                assert payment.status == "missing" and payment.settlement_count == 0
                assert incident.lineage[0].event_ids == incident.lineage[0].entry_ids == []
                assert "no event or posting" in incident.root_cause.summary
                assert incident.impact_minor == payment.amount_minor
                assert len(incident.proposal.entries) == 1
                assert incident.proposal.entries[0].corrects_entry_id is None
            else:
                assert payment.status == "discrepancy" and payment.settlement_count == 1
                assert len(incident.lineage[0].event_ids) == len(incident.lineage[0].entry_ids) == 1
                event = runtime.bank.events[-1]
                assert event.amount_minor == payment.amount_minor + 100
                assert event.payload_hash != payment.expected_hash
                assert "amount_minor" in incident.root_cause.summary
                assert str(event.amount_minor) in incident.root_cause.summary
                assert incident.impact_minor == 100
                assert len(incident.proposal.entries) == 2
                assert incident.proposal.entries[0].corrects_entry_id == runtime.bank.ledger.entries[-1].id
                assert incident.proposal.entries[1].corrects_entry_id is None
            originals = runtime.bank.ledger.entries
            events = [e.model_dump_json() for e in runtime.bank.events]
            before = runtime.bank.ledger.serialize()
            assert runtime.coordinator.sandbox(incident).passed
            assert runtime.bank.ledger.serialize() == before
            await runtime.submit_payment()
            assert runtime.overview().volume.held == 1
            assert runtime.bank.ledger.serialize() == before
            async with runtime.lock:
                resolved = await runtime.coordinator.approve(incident.id, "ops.lead@bank")
            assert resolved.status == "resolved" and payment.status == "settled"
            assert len(resolved.verification.checks) == 7
            assert all(c.passed for c in resolved.verification.checks)
            assert runtime.bank.ledger.entries[:len(originals)] == originals
            assert [e.model_dump_json() for e in runtime.bank.events] == events
            assert all(e.actor == "ops.lead@bank" for e in runtime.bank.ledger.entries[len(originals):])
            after = runtime.bank.ledger.serialize()
            snapshot = resolved.model_dump_json()
            async with runtime.lock:
                repeated = await runtime.coordinator.approve(incident.id, "treasury@bank")
            assert repeated.model_dump_json() == snapshot
            assert runtime.bank.ledger.serialize() == after
            await runtime.release()
            assert runtime.overview().volume.held == 0
            assert all(c.passed for c in runtime.coordinator.report().checks)
        finally:
            await runtime.stop()
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["missing", "tamper"])
def test_p2_invalid_proposal_cannot_change_real_ledger(kind):
    async def run():
        runtime = Runtime(step_delay=0, missing_grace=0)
        try:
            incident = await ready(runtime, kind)
            incident.proposal.entries.pop()
            before = runtime.bank.ledger.serialize()
            assert not runtime.coordinator.sandbox(incident).passed
            with pytest.raises(ActionError) as error:
                async with runtime.lock:
                    await runtime.coordinator.approve(incident.id, "ops.lead@bank")
            assert error.value.status == 409 and incident.status == "failed"
            assert runtime.bank.ledger.serialize() == before
        finally:
            await runtime.stop()
    asyncio.run(run())


def test_tampered_event_not_excused_by_reversal_alone_or_wrong_replacement():
    async def run():
        runtime = Runtime(step_delay=0, missing_grace=0)
        try:
            incident = await ready(runtime, "tamper")
            reversal, replacement = incident.proposal.entries
            runtime.bank.ledger.append(reversal)
            assert not event_integrity(runtime.bank.instructions, runtime.bank.events, runtime.bank.ledger).passed
            replacement.lines = [
                PostingLine(account=l.account, side=l.side, amount_minor=l.amount_minor + 1)
                for l in replacement.lines]
            runtime.bank.ledger.append(replacement)
            assert not event_integrity(runtime.bank.instructions, runtime.bank.events, runtime.bank.ledger).passed
            assert runtime.coordinator.report().status != "healthy"
        finally:
            await runtime.stop()
    asyncio.run(run())


def test_missing_watchdog_detects_without_traffic_and_reset_cancels_it():
    async def run():
        runtime = Runtime(step_delay=0, missing_grace=0.05)
        try:
            await runtime.inject("missing")
            await runtime.submit_payment()
            assert not runtime.coordinator.incidents and not runtime.traffic.running
            assert runtime.coordinator.report().status == "healthy"
            deadline = asyncio.get_running_loop().time() + 2
            while not runtime.coordinator.incidents:
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.005)
            await asyncio.gather(*tuple(runtime.coordinator.tasks))
            assert next(iter(runtime.coordinator.incidents.values())).status == "awaiting_approval"
            await runtime.reset()
            runtime.settlement.missing_grace = 10
            runtime.missing_grace = 10
            await runtime.inject("missing")
            await runtime.submit_payment()
            task = runtime.missing_task
            assert task is not None and not task.done()
            reset = await runtime.reset()
            assert task.done() and runtime.missing_task is None
            assert not runtime.coordinator.tasks and not runtime.coordinator.incidents
            assert reset.integrity.status == "healthy"
        finally:
            await runtime.stop()
    asyncio.run(run())


def test_reject_release_requires_reset_before_a_new_fault():
    async def run():
        runtime = Runtime(step_delay=0, missing_grace=0)
        try:
            first = await ready(runtime, "duplicate")
            await runtime.submit_payment()
            async with runtime.lock:
                await runtime.coordinator.reject(first.id, "ops.lead@bank")
            assert runtime.overview().open_incidents == 0
            await runtime.release()
            assert runtime.settlement.service.status == "running"
            assert runtime.overview().volume.held == runtime.overview().open_incidents == 0
            with pytest.raises(ActionError) as error:
                await runtime.inject("duplicate")
            assert error.value.status == 409
            await runtime.reset()
            runtime.coordinator.step_delay = 10
            await runtime.inject("duplicate")
            await runtime.submit_payment()
            second = runtime.coordinator.incidents["incident-0001"]
            assert second.status == "detected" and first.status == "rejected"
            assert second is not first
        finally:
            await runtime.stop()
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["duplicate", "missing", "tamper"])
def test_http_rejected_unrecovered_incident_blocks_new_fault_until_reset(client, kind):
    incident = duplicate_via_http(client)
    path = "/api/incidents/" + incident["id"]
    assert client.post(path + "/reject", json={"actor": "ops.lead@bank"}).status_code == 200
    assert client.post("/api/services/settlement-svc/release").status_code == 200
    assert client.get("/api/integrity").json()["status"] == "violated"
    before = client.get("/api/ledger?limit=500").json()
    response = client.post("/api/faults/" + kind)
    assert response.status_code == 409
    assert response.json() == {"detail": "Integrity violated by an unrecovered incident; reset required"}
    assert client.get("/api/overview").json()["services"][0]["fault"] is None
    assert client.get("/api/ledger?limit=500").json() == before
    assert len(client.get("/api/incidents").json()) == 1
    assert client.get("/api/audit?limit=1").json()[0]["action"] == "fault.conflict"
    assert client.post("/api/reset").status_code == 200
    assert client.post("/api/faults/" + kind).status_code == 200


def test_gate_blocks_tamper_before_duplicate_quarantine():
    async def run():
        runtime = Runtime(step_delay=0, missing_grace=0)
        try:
            await runtime.inject("duplicate")
            await runtime.submit_payment()
            incident = next(iter(runtime.coordinator.incidents.values()))
            affected = incident.affected_payments[:]
            assert incident.status == "detected"
            assert runtime.settlement.service.status == "running"
            with pytest.raises(ActionError) as error:
                await runtime.inject("tamper")
            assert error.value.status == 409
            assert error.value.detail == "Integrity violated by an unrecovered incident; reset required"
            assert runtime.settlement.service.fault is None
            await asyncio.gather(*tuple(runtime.coordinator.tasks))
            assert incident.affected_payments == affected
            assert incident.type == "duplicate_settlement"
            assert incident.status == "awaiting_approval" and incident.sandbox.passed
        finally:
            await runtime.stop()
    asyncio.run(run())


def test_gate_blocks_missing_before_quarantine_and_release_settles_held():
    async def run():
        runtime = Runtime(step_delay=0, missing_grace=10)
        try:
            await runtime.inject("duplicate")
            await runtime.submit_payment()
            assert runtime.settlement.service.status == "running"
            with pytest.raises(ActionError) as error:
                await runtime.inject("missing")
            assert error.value.status == 409
            assert runtime.settlement.service.fault is None
            await asyncio.gather(*tuple(runtime.coordinator.tasks))
            incident = next(iter(runtime.coordinator.incidents.values()))
            await runtime.submit_payment()
            held_id = runtime.settlement.queue[0]
            async with runtime.lock:
                await runtime.coordinator.approve(incident.id, "ops.lead@bank")
            await runtime.release()
            held = runtime.bank.instructions[held_id]
            assert held.status == "settled" and held.settlement_count == 1
            assert not runtime.settlement.pending_missing and runtime.missing_task is None
            assert runtime.coordinator.report().status == "healthy"
        finally:
            await runtime.stop()
    asyncio.run(run())


def test_append_batch_failure_marks_failed_and_is_audited(monkeypatch):
    async def run():
        runtime = Runtime(step_delay=0)
        try:
            incident = await ready(runtime, "duplicate")
            before = runtime.bank.ledger.serialize()
            def fail(batch):
                raise ValueError("simulated append failure")
            monkeypatch.setattr(runtime.bank.ledger, "append_batch", fail)
            with pytest.raises(ActionError) as error:
                async with runtime.lock:
                    await runtime.coordinator.approve(incident.id, "ops.lead@bank")
            assert error.value.status == 409 and incident.status == "failed"
            assert runtime.bank.ledger.serialize() == before
            assert runtime.coordinator.audit[-1].action == "recovery.failed"
            assert runtime.coordinator.audit[-1].detail == "simulated append failure"
        finally:
            await runtime.stop()
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["missing", "tamper"])
def test_full_p2_http_flow(client, kind):
    assert client.post("/api/reset").json()["volume"]["settled"] == 100
    assert client.post("/api/faults/" + kind).json()["fault"] == kind
    assert client.post("/api/traffic/start").status_code == 200
    incident = awaiting_incident(client)
    wait_for(lambda: client.get("/api/overview").json()["volume"]["held"] > 0)
    client.post("/api/traffic/stop")
    path = "/api/incidents/" + incident["id"]
    assert incident["sandbox"]["passed"]
    assert incident["type"] == {"missing": "missing_settlement", "tamper": "tampered_settlement"}[kind]
    failures = {c["name"] for c in client.get("/api/integrity").json()["checks"] if not c["pass"]}
    assert failures == ({"no_missing_settlements", "ledger_matches_expected"} if kind == "missing"
                        else {"event_integrity", "ledger_matches_expected"})
    before = client.get("/api/ledger?limit=500").json()
    assert client.post(path + "/approve", json={"actor": "blackbox-agent"}).status_code == 403
    resolved = client.post(path + "/approve", json={"actor": "ops.lead@bank"}).json()
    assert resolved["status"] == "resolved"
    assert len(resolved["verification"]["checks"]) == 7
    assert all(c["pass"] for c in resolved["verification"]["checks"])
    after = client.get("/api/ledger?limit=500").json()
    added = 1 if kind == "missing" else 2
    assert len(after) == len(before) + added and after[added:] == before
    assert client.post(path + "/approve", json={"actor": "ops.lead@bank"}).json() == resolved
    assert client.get("/api/ledger?limit=500").json() == after
    assert client.post("/api/services/settlement-svc/release").status_code == 200
    assert client.get("/api/overview").json()["volume"]["held"] == 0
    assert all(c["pass"] for c in client.get("/api/integrity").json()["checks"])
