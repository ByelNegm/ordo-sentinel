import asyncio

import pytest

from app.incident import ActionError
from app.integrity import inspect
from app.ledger import reversed_lines
from app.models import PostingLine, Proposal
from app.traffic import Runtime


async def ready(runtime):
    await runtime.inject("duplicate")
    await runtime.submit_payment()
    tasks = tuple(runtime.coordinator.tasks)
    await asyncio.gather(*tasks)
    incident = next(iter(runtime.coordinator.incidents.values()))
    assert incident.status == "awaiting_approval"
    return incident


def test_lineage_root_cause_quarantine_sandbox_approval_and_release():
    async def run():
        runtime = Runtime(step_delay=0)
        try:
            incident = await ready(runtime)
            payment_id = incident.affected_payments[0]
            payment = runtime.bank.instructions[payment_id]
            assert incident.root_cause.service == "settlement-svc"
            assert incident.root_cause.method == "deterministic"
            assert payment.idempotency_key in incident.root_cause.summary
            assert payment.id in incident.root_cause.summary
            assert "share instruction" in incident.root_cause.summary
            assert len(incident.lineage) == 1
            assert len(incident.lineage[0].event_ids) == len(incident.lineage[0].entry_ids) == 2
            assert set(incident.affected_accounts) == {payment.debtor, payment.creditor}
            assert incident.impact_minor == payment.amount_minor
            assert {"instruction", "settlement", "posting", "detection", "investigation",
                    "containment", "proposal", "sandbox"} <= {item.kind for item in incident.timeline}
            assert incident.sandbox.passed
            assert sum(not c.passed for c in incident.sandbox.checks_before) == 2
            assert all(c.passed for c in incident.sandbox.checks_after)
            assert incident.sandbox.balances_before != incident.sandbox.balances_after
            before = runtime.bank.ledger.serialize()
            originals = runtime.bank.ledger.entries
            await runtime.submit_payment()
            await runtime.submit_payment()
            assert runtime.bank.ledger.serialize() == before
            assert len(runtime.settlement.queue) == 2
            assert runtime.overview().volume.held == 2
            assert incident.containment.held_instructions == 2
            assert all(runtime.bank.instructions[i].status == "held" for i in runtime.settlement.queue)
            with pytest.raises(ActionError) as error:
                await runtime.release()
            assert error.value.status == 409
            async with runtime.lock:
                resolved = await runtime.coordinator.approve(incident.id, "ops.lead@bank")
            assert resolved.status == "resolved"
            assert all(c.passed for c in resolved.verification.checks)
            assert len(resolved.corrections) == 1
            correction = runtime.bank.ledger.entries[-1]
            original = next(e for e in originals if e.id == correction.corrects_entry_id)
            assert correction.kind == "compensation"
            assert correction.actor == "ops.lead@bank"
            assert correction.event_id is None
            assert [line.model_dump() for line in correction.lines] == reversed_lines(original)
            assert runtime.bank.ledger.entries[:len(originals)] == originals
            before_repeat = runtime.bank.ledger.serialize()
            incident_json = resolved.model_dump_json(by_alias=True)
            async with runtime.lock:
                again = await runtime.coordinator.approve(incident.id, "treasury@bank")
            assert again.model_dump_json(by_alias=True) == incident_json
            assert runtime.bank.ledger.serialize() == before_repeat
            released = await runtime.release()
            assert released.status == "running" and not runtime.settlement.queue
            assert len(runtime.bank.ledger.entries) == len(originals) + 3
            assert runtime.overview().volume.held == 0
            assert inspect(runtime.bank.ledger, runtime.bank.instructions, runtime.bank.events).status == "healthy"
        finally:
            await runtime.stop()
    asyncio.run(run())


@pytest.mark.parametrize("actor", ["blackbox-agent", "intruder@bank", ""])
def test_unauthorized_approval_never_posts(actor):
    async def run():
        runtime = Runtime(step_delay=0)
        try:
            incident = await ready(runtime)
            before = runtime.bank.ledger.serialize()
            with pytest.raises(ActionError) as error:
                async with runtime.lock:
                    await runtime.coordinator.approve(incident.id, actor)
            assert error.value.status == 403
            assert runtime.bank.ledger.serialize() == before
            assert incident.approval is None
        finally:
            await runtime.stop()
    asyncio.run(run())


@pytest.mark.parametrize("corruption", ["empty", "wrong_amount", "original_not_extra", "duplicate_reference", "non_compensation"])
def test_invalid_proposal_fails_sandbox_and_approval_without_touching_ledger(corruption):
    async def run():
        runtime = Runtime(step_delay=0)
        try:
            incident = await ready(runtime)
            before = runtime.bank.ledger.serialize()
            proposal = incident.proposal
            correction = proposal.entries[0]
            if corruption == "empty":
                proposal.entries = []
            elif corruption == "wrong_amount":
                proposal.entries = [correction.model_copy(update={"lines": [
                    PostingLine(account=line.account, side=line.side, amount_minor=line.amount_minor + 1)
                    for line in correction.lines]})]
            elif corruption == "original_not_extra":
                proposal.entries = [correction.model_copy(update={
                    "corrects_entry_id": incident.lineage[0].entry_ids[0]})]
            elif corruption == "duplicate_reference":
                proposal.entries = [correction, correction.model_copy(update={"id": "second"})]
            else:
                proposal.entries = [correction.model_copy(update={"kind": "settlement"})]
            sandbox = runtime.coordinator.sandbox(incident)
            assert not sandbox.passed
            assert runtime.bank.ledger.serialize() == before
            with pytest.raises(ActionError) as error:
                async with runtime.lock:
                    await runtime.coordinator.approve(incident.id, "ops.lead@bank")
            assert error.value.status == 409
            assert runtime.bank.ledger.serialize() == before
            assert incident.status == "failed" and incident.approval is None
        finally:
            await runtime.stop()
    asyncio.run(run())


def test_automatic_sandbox_failure_never_applies_proposal():
    async def run():
        runtime = Runtime(step_delay=0)
        runtime.coordinator.propose = lambda incident: Proposal(id="invalid", description="No reversal", entries=[])
        try:
            await runtime.inject("duplicate")
            await runtime.submit_payment()
            before = runtime.bank.ledger.serialize()
            await asyncio.gather(*tuple(runtime.coordinator.tasks))
            incident = next(iter(runtime.coordinator.incidents.values()))
            assert incident.status == "failed" and not incident.sandbox.passed
            assert runtime.bank.ledger.serialize() == before
            assert not incident.corrections
        finally:
            await runtime.stop()
    asyncio.run(run())


def test_reset_cancels_traffic_and_all_incident_tasks_without_stale_events():
    async def run():
        runtime = Runtime(traffic_interval=10, step_delay=10)
        async with runtime.bus.subscribe() as queue:
            await runtime.inject("duplicate")
            await runtime.set_traffic(True)
            deadline = asyncio.get_running_loop().time() + 2
            while not runtime.coordinator.tasks:
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.01)
            old_tasks = set(runtime.coordinator.tasks) | {runtime.traffic.task}
            reset = await asyncio.wait_for(runtime.reset(), timeout=2)
            assert all(task.done() for task in old_tasks)
            assert not runtime.coordinator.tasks and not runtime.traffic.running
            assert reset.volume.instructions == reset.totals.ledger_entries == 100
            assert reset.integrity.status == "healthy"
            observed = []
            while not queue.empty():
                observed.append(queue.get_nowait())
            assert observed[-1].type == "reset"
            await asyncio.sleep(0.02)
            assert queue.empty()
            assert not runtime.coordinator.incidents
        await runtime.stop()
    asyncio.run(run())
