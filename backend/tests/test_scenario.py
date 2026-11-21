import asyncio
from datetime import timedelta

import httpx
import pytest

from app import scenario
from app.bank import Bank, BankError
from app.bus import EventBus
from app.main import create_app
from app.models import EVENT_ADAPTER, Explanation
from app.scenario import ScenarioRunner


def queued_events(queue):
    events = []
    while not queue.empty():
        event = queue.get_nowait()
        events.append(EVENT_ADAPTER.validate_json(event.model_dump_json()))
    return events


def test_generated_scenarios_follow_demo_clock_and_policy(monkeypatch):
    contexts = []
    scorer = scenario.score

    def record_context(txn, context):
        contexts.append(context)
        return scorer(txn, context)

    monkeypatch.setattr(scenario, "score", record_context)

    async def run():
        bank, bus = Bank(), EventBus()
        runner = ScenarioRunner(bank, bus, pace=0)
        async with bus.subscribe() as queue:
            try:
                assert runner.start("normal").total == 3
                await runner.task
                assert bank.state.account.balance == 519_915
                runner.start("drain")
                await runner.task
                events = queued_events(queue)
                txns = [event.data for event in events if event.type == "txn.scored"]
                assert [txn.amount for txn in txns] == [25, 30, 30, 1200, 1800, 450_000]
                assert [txn.ts.hour for txn in txns] == [13, 13, 13, 2, 2, 2]
                assert [txn.ts.second for txn in txns] == [0, 1, 2, 0, 1, 2]
                assert all(txn.ts.utcoffset() == timedelta(hours=4) for txn in txns)
                assert [txn.status for txn in txns] == ["posted"] * 3 + ["held", "held", "blocked"]
                assert [event.data.step for event in events if event.type == "scenario.status"] == [
                    0, 1, 2, 3, 0, 1, 2, 3,
                ]
                assert [context.cumulative_drain for context in contexts] == [25, 55, 85, 1200, 3000, 453_000]
                assert len(contexts[-1].recent_transactions) == 2
                assert contexts[-1].baseline.hour_histogram == bank.baseline.hour_histogram
                assert bank.resolve("alert_wire", "deny").resolution == "denied"
                assert bank.state.protected_amount == 450_000
                assert bank.state.scenario == "drain"
            finally:
                await runner.stop()

    asyncio.run(run())


def test_wire_explanation_uses_live_balance_after_normal_then_drain(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def run():
        bank, bus = Bank(), EventBus()
        runner = ScenarioRunner(bank, bus, pace=0)
        async with bus.subscribe() as queue:
            try:
                runner.start("normal")
                await runner.task
                runner.start("drain")
                await runner.task

                [wire_alert] = [event.data for event in queued_events(queue)
                                if event.type == "alert.created" and event.data.id == "alert_wire"]
                assert "86.55% of the AED 519,915 balance" in wire_alert.analyst_explanation
                assert wire_alert == bank.alerts["alert_wire"]
            finally:
                await runner.stop()

    asyncio.run(run())


def test_frozen_service_retries_are_blocked_while_card_payments_post(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def run():
        app = create_app()
        runner, bus = app.state.runner, app.state.bus
        runner.pace = 0
        frozen_client = "api_partner_7"
        freeze_reason = "CLIENT_ALREADY_FROZEN"

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            async def start(name):
                assert (await client.post(f"/api/scenario/{name}/start")).status_code == 200
                await runner.task

            try:
                await start("normal")
                await start("drain")
                state = (await client.get("/api/state")).json()
                assert state["account"]["balance"] == 519_915
                assert state["frozen_clients"] == [frozen_client]
                assert state["protected_amount"] == 0
                response = await client.post("/api/alerts/alert_wire/decision", json={"decision": "deny"})
                assert response.status_code == 200

                async with bus.subscribe() as queue:
                    await start("drain")
                    retries = [e.data for e in queued_events(queue) if e.type == "txn.scored"]
                    assert len(retries) == 3
                    assert all(txn.client_id == frozen_client and txn.status == "blocked" for txn in retries)
                    assert all(any(f.code == freeze_reason for f in txn.risk.factors) for txn in retries)
                    assert retries[0].risk.score <= 75
                    state = (await client.get("/api/state")).json()
                    assert state["account"]["balance"] == 519_915

                    await start("normal")
                    purchases = [e.data for e in queued_events(queue) if e.type == "txn.scored"]
                    assert sum(txn.amount for txn in purchases) == 85
                    assert all(txn.channel == "card" and txn.status == "posted" for txn in purchases)
                    assert all(not any(f.code == freeze_reason for f in txn.risk.factors) for txn in purchases)
                    state = (await client.get("/api/state")).json()
                    assert state["account"]["balance"] == 519_830
                    assert state["frozen_clients"] == [frozen_client]
                    assert state["protected_amount"] == 450_000
            finally:
                await runner.stop()

    asyncio.run(run())


@pytest.mark.parametrize("choice", ["confirm", "deny"])
def test_early_burst_decision_leaves_second_hold_actionable(monkeypatch, choice):
    async def run():
        bank, bus = Bank(), EventBus()
        runner = ScenarioRunner(bank, bus, pace=0)
        paused, resume = asyncio.Event(), asyncio.Event()
        publish_status = runner._publish_status

        async def pause_after_first(name, step, total, ts):
            await publish_status(name, step, total, ts)
            if step == 1:
                paused.set()
                await resume.wait()

        monkeypatch.setattr(runner, "_publish_status", pause_after_first)
        try:
            runner.start("drain")
            await asyncio.wait_for(paused.wait(), 1)
            bank.resolve("alert_burst", choice)
            assert bank.state.account.held == 0
            resume.set()
            await runner.task
            assert bank.state.account.held == 1800
            [second_alert] = [alert for alert in bank.alerts.values()
                              if alert.txn_ids == ["txn_drain_002"]]
            assert second_alert.id != "alert_burst"
            bank.resolve(second_alert.id, "deny")
            assert bank.state.account.held == 0
            assert bank.transactions["txn_drain_002"].status == "blocked"
        finally:
            await runner.stop()

    asyncio.run(run())


def test_start_cannot_replace_task_while_reset_joins_cancellation(monkeypatch):
    async def run():
        app = create_app()
        runner = app.state.runner
        entered, cancelled, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def slow_cancellation(*args):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()
                await finish.wait()

        monkeypatch.setattr(runner, "_run", slow_cancellation)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.post("/api/scenario/drain/start")).status_code == 200
            await asyncio.wait_for(entered.wait(), 1)
            first_task = runner.task
            outcome = []

            def restart_as_task_finishes(task):
                assert task.done()
                try:
                    runner.start("normal")
                except BankError as exc:
                    outcome.append(exc.status)

            # This callback runs after the task becomes done, before reset's join completes.
            first_task.add_done_callback(restart_as_task_finishes)
            reset = asyncio.create_task(client.post("/api/reset"))
            await asyncio.wait_for(cancelled.wait(), 1)
            assert (await client.post("/api/scenario/normal/start")).status_code == 409
            finish.set()
            response = await asyncio.wait_for(reset, 1)
            assert outcome == [409]
            assert response.status_code == 200
            assert response.json()["scenario"] == "idle"
            assert runner.task is None and not runner.running
            assert not app.state.bank.transactions

    asyncio.run(run())


def test_http_reset_recovers_after_runner_crash(monkeypatch, caplog):
    async def run():
        app = create_app()
        runner = app.state.runner

        async def crash(*args):
            raise BankError(409, "test runner crash")

        monkeypatch.setattr(runner, "_run", crash)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.post("/api/scenario/drain/start")).status_code == 200
            with pytest.raises(BankError, match="test runner crash"):
                await runner.task
            response = await client.post("/api/reset")
            assert response.status_code == 200
            assert response.json()["scenario"] == "idle"
            assert runner.task is None

    asyncio.run(run())
    assert "test runner crash" in caplog.text


def test_alerts_auto_expire_and_emit_events_after_the_run():
    async def run():
        bank, bus = Bank(), EventBus()
        runner = ScenarioRunner(bank, bus, pace=0.0002)
        async with bus.subscribe() as queue:
            try:
                runner.start("drain")
                await runner.task
                assert not runner.running
                assert set(bank.alerts) == {"alert_burst", "alert_wire"}
                expiries = []
                while len(expiries) < 2:
                    event = await asyncio.wait_for(queue.get(), 1)
                    if event.type == "alert.resolved":
                        expiries.append(event.data)
                        updated = await asyncio.wait_for(queue.get(), 1)
                        assert updated.type == "account.updated"
                        assert updated.data.held == 0
                assert [(expiry.id, expiry.resolution, expiry.by) for expiry in expiries] == [
                    ("alert_burst", "expired", "auto"), ("alert_wire", "expired", "auto"),
                ]
                assert bank.state.frozen_clients == ["api_partner_7"]
                assert bank.state.protected_amount == 0
                assert not bank.alerts
            finally:
                await runner.stop()

    asyncio.run(run())


def test_enrichment_is_nonblocking_upserts_live_text_and_cancels_on_reset(monkeypatch):
    async def run():
        app = create_app()
        bank, bus, runner = app.state.bank, app.state.bus, app.state.runner
        runner.pace = 0
        enrich_wire, wire_finished, released = asyncio.Event(), asyncio.Event(), asyncio.Event()
        started, cancelled = [], []

        def template(alert, *, txns, balance):
            assert [txn.id for txn in txns] == alert.txn_ids
            assert balance == 519_915
            return Explanation(customer_message=alert.customer_message, analyst_explanation="Immediate template")

        async def enrich(alert, *, txns, balance):
            assert [txn.id for txn in txns] == alert.txn_ids
            assert balance == 519_915
            started.append(alert.id)
            if alert.id == "alert_wire":
                await enrich_wire.wait()
                wire_finished.set()
                return Explanation(customer_message=alert.customer_message, analyst_explanation="Enriched wire")
            try:
                await released.wait()
            except asyncio.CancelledError:
                cancelled.append(alert.id)
                raise

        monkeypatch.setattr(scenario.explainer, "explain", template)
        monkeypatch.setattr(scenario.explainer, "enrich", enrich)
        runner.start("normal")
        await runner.task
        async with bus.subscribe() as queue:
            runner.start("drain")
            await runner.task
            assert started.count("alert_burst") == 2 and "alert_wire" in started
            assert bank.transactions["txn_wire"].status == "blocked"
            assert bank.alerts["alert_wire"].analyst_explanation == "Immediate template"
            assert any(event.type == "alert.created" and event.data.id == "alert_wire"
                       for event in queued_events(queue))
            enrich_wire.set()
            await asyncio.wait_for(wire_finished.wait(), 1)
            [update] = queued_events(queue)
            assert update.type == "alert.created"
            assert update.data.id == "alert_wire" and update.data.analyst_explanation == "Enriched wire"

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                assert (await client.post("/api/reset")).status_code == 200
            assert cancelled == ["alert_burst", "alert_burst"]
            assert not bank.alerts and not bank.transactions
            assert [event.type for event in queued_events(queue)] == ["account.updated", "scenario.status"]

    asyncio.run(run())
