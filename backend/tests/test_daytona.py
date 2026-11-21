import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.daytona_runner import DaytonaValidator, financial_result
from app.models import SandboxReport
from app.remote_check import validate
from app.traffic import Runtime


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.delenv("DAYTONA_API_KEY", raising=False)
    monkeypatch.delenv("BLACKBOX_DAYTONA", raising=False)


async def scenario(kind="duplicate"):
    runtime = Runtime(step_delay=0, missing_grace=0)
    await runtime.inject(kind)
    await runtime.submit_payment()
    await asyncio.gather(*tuple(runtime.coordinator.tasks))
    incident = next(iter(runtime.coordinator.incidents.values()))
    assert incident.status == "awaiting_approval"
    return runtime, incident


@pytest.mark.parametrize("kind", ["duplicate", "missing", "tamper"])
def test_remote_checker_matches_local_and_never_changes_live_ledger(kind):
    async def run():
        runtime, incident = await scenario(kind)
        before = runtime.bank.ledger.serialize()
        payload = runtime.coordinator.validation_payload(incident)
        original = deepcopy(payload)
        remote = SandboxReport.model_validate(validate(payload))
        assert remote.passed and len(remote.checks_after) == 7
        assert financial_result(remote) == financial_result(incident.sandbox)
        assert payload == original
        assert runtime.bank.ledger.serialize() == before
        for malformed in (None, {**payload["proposal"], "entries": []}):
            unsafe = deepcopy(payload)
            unsafe["proposal"] = malformed
            assert validate(unsafe)["passed"] is False
        assert runtime.bank.ledger.serialize() == before
        await runtime.stop()
    asyncio.run(run())


@pytest.mark.parametrize("disabled", [False, True])
def test_no_key_or_explicit_disable_reaches_approval_locally(monkeypatch, disabled):
    if disabled:
        monkeypatch.setenv("DAYTONA_API_KEY", "unused-test-key")
        monkeypatch.setenv("BLACKBOX_DAYTONA", "0")

    async def run():
        runtime, incident = await scenario()
        runtime.validator.start()
        assert runtime.validator.task is None
        assert incident.sandbox.runner == "local"
        assert incident.sandbox.remote_match is None
        assert incident.sandbox.runner_note
        await runtime.coordinator.approve(incident.id, "ops.lead@bank")
        assert all(check.passed for check in incident.verification.checks)
        await runtime.stop()
    asyncio.run(run())


def test_absent_sdk_falls_back_without_blocking(monkeypatch):
    import sys
    monkeypatch.setenv("DAYTONA_API_KEY", "unused-test-key")
    monkeypatch.setitem(sys.modules, "daytona", None)

    async def run():
        runtime, incident = await scenario()
        runtime.validator.start()
        await runtime.validator.task
        result = await runtime.validator.validate({}, incident.sandbox)
        assert result.passed and result.runner == "local"
        assert "ModuleNotFoundError" in result.runner_note
        assert incident.status == "awaiting_approval"
        await runtime.stop()
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["match", "mismatch", "empty", "error", "timeout"])
def test_confirmation_and_fallback_modes(monkeypatch, mode):
    async def run():
        runtime, incident = await scenario()
        validator = DaytonaValidator(timeout=0.02)
        validator.ready = True
        validator.sandbox = SimpleNamespace(id="real-looking-test-id")
        original = incident.sandbox.model_dump()
        response = incident.sandbox.model_dump(mode="json", by_alias=True)

        async def remote(payload):
            if mode == "timeout":
                await asyncio.sleep(60)
            if mode == "error":
                raise RuntimeError("service unavailable")
            if mode == "empty":
                return {}
            if mode == "mismatch":
                response["balances_after"]["customer-01"] += 1
            return response

        monkeypatch.setattr(validator, "_serialized_run", remote)
        result = await validator.validate({}, incident.sandbox)
        assert financial_result(result) == financial_result(incident.sandbox)
        assert incident.sandbox.model_dump() == original
        assert result.runner == ("daytona" if mode == "match" else "local")
        assert result.remote_match == (True if mode == "match" else False if mode == "mismatch" else None)
        assert result.runner_id == ("real-looking-test-id" if mode == "match" else None)
        assert result.runner_note
        if mode == "timeout":
            assert "timed out" in result.runner_note
        await runtime.stop()
    asyncio.run(run())


def test_warming_up_falls_back_and_reset_cancels_remote_wait(monkeypatch):
    async def run():
        runtime = Runtime(step_delay=0)
        runtime.validator.note = "warming up"
        started = asyncio.Event()

        async def remote(payload):
            started.set()
            await asyncio.sleep(60)

        runtime.validator.ready = True
        monkeypatch.setattr(runtime.validator, "_serialized_run", remote)
        await runtime.inject("duplicate")
        await runtime.submit_payment()
        await asyncio.wait_for(started.wait(), timeout=1)
        assert not runtime.lock.locked()
        await asyncio.wait_for(runtime.reset(), timeout=1)
        assert not runtime.coordinator.incidents
        runtime.validator.ready = False
        await runtime.inject("duplicate")
        await runtime.submit_payment()
        await asyncio.gather(*tuple(runtime.coordinator.tasks))
        incident = next(iter(runtime.coordinator.incidents.values()))
        assert incident.status == "awaiting_approval"
        assert incident.sandbox.runner_note == "warming up"
        await runtime.stop()
    asyncio.run(run())


def test_success_is_audited_and_approval_keeps_confirmation(monkeypatch):
    async def run():
        runtime = Runtime(step_delay=0)
        runtime.validator.ready = True
        runtime.validator.sandbox = SimpleNamespace(id="test-sandbox")
        runtime.validator.client = SimpleNamespace(v0=SimpleNamespace(delete=AsyncMock()), close=AsyncMock())

        async def remote(payload):
            return validate(payload)

        monkeypatch.setattr(runtime.validator, "_serialized_run", remote)
        await runtime.inject("duplicate")
        await runtime.submit_payment()
        await asyncio.gather(*tuple(runtime.coordinator.tasks))
        incident = next(iter(runtime.coordinator.incidents.values()))
        assert incident.sandbox.runner == "daytona"
        assert incident.sandbox.remote_match is True
        assert any(item.detail == "Validated in Daytona sandbox test-sandbox" for item in incident.timeline)
        assert any(item.action == "sandbox.daytona.validated" for item in runtime.coordinator.audit)
        before = runtime.bank.ledger.serialize()
        with pytest.raises(Exception) as denied:
            await runtime.coordinator.approve(incident.id, "blackbox-agent")
        assert denied.value.status == 403
        assert runtime.bank.ledger.serialize() == before
        await runtime.coordinator.approve(incident.id, "ops.lead@bank")
        assert incident.sandbox.runner == "daytona" and incident.sandbox.remote_match is True
        assert all(check.passed for check in incident.verification.checks)
        client = runtime.validator.client
        sandbox = runtime.validator.sandbox
        await runtime.stop()
        client.v0.delete.assert_awaited_once_with(sandbox, timeout=10)
        client.close.assert_awaited_once()
    asyncio.run(run())
