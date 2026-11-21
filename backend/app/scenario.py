"""Builder B: cancellable fixture-paced runners. No scripted customer decisions."""
import asyncio
from datetime import datetime, timezone

from .bank import Bank, FIXTURES
from .bus import EventBus
from .explainer import explain
from .models import (EVENT_ADAPTER, AccountUpdatedEvent, AlertCreatedEvent,
                     Alert, ScenarioStatus, ScenarioStatusEvent, Txn, TxnScoredEvent)
from .policy import PolicyContext, decide
from .risk import RiskContext, score


class ScenarioRunner:
    def __init__(self, bank: Bank, bus: EventBus, pace: float = 1.0) -> None:
        self.bank, self.bus, self.pace = bank, bus, pace
        self.task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def start(self, name: str) -> ScenarioStatus:
        """Caller rejects overlap; runs begin after 100ms so immediate SSE can attach."""
        self.bank.state.scenario = name
        self.task = asyncio.create_task(self._run(name))
        return ScenarioStatus(name=name, step=0, total=3)

    async def stop(self) -> None:
        """Cancel and join before resetting bank or accepting another run."""
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    async def _status(self, name: str, step: int) -> None:
        await self.bus.publish(ScenarioStatusEvent(ts=datetime.now(timezone.utc),
                               data=ScenarioStatus(name=name, step=step, total=3)))

    async def _submit(self, txn: Txn, cumulative: float) -> None:
        txn = txn.model_copy(deep=True)
        txn.risk = score(txn, RiskContext(self.bank.state.account.balance, cumulative,
                                          list(self.bank.transactions.values())))
        decision = decide(txn.risk, PolicyContext(self.bank.state.account.balance, cumulative,
                          txn.client_id in self.bank.state.frozen_clients))
        {"allow": self.bank.post, "hold": self.bank.hold, "freeze": self.bank.block}[decision](txn)
        await self.bus.publish(TxnScoredEvent(ts=txn.ts, data=self.bank.transactions[txn.id]))
        await self.bus.publish(AccountUpdatedEvent(ts=txn.ts, data=self.bank.account_update()))

    async def _run(self, name: str) -> None:
        await asyncio.sleep(0.1 * self.pace)
        await self._status(name, 0)
        if name == "normal":
            base = self.bank.catalog[0]
            for i, amount in enumerate((25, 30, 30), 1):
                txn = base.model_copy(update={"id": f"txn_normal_{i}", "amount": amount}, deep=True)
                await self._submit(txn, 0)
                await self._status(name, i)
                if i < 3:
                    await asyncio.sleep(self.pace)
            return
        previous = None
        cumulative = 0.0
        for line in (FIXTURES / "events.ndjson").read_text().splitlines():
            event = EVENT_ADAPTER.validate_json(line)
            if event.type == "alert.resolved":
                break
            if previous is not None:
                await asyncio.sleep(max(0, (event.ts - previous).total_seconds()) * self.pace)
            previous = event.ts
            if event.type == "txn.scored":
                cumulative += event.data.amount
                await self._submit(event.data, cumulative)
            elif event.type == "alert.created":
                explanation = await explain(event.data)
                alert = Alert.model_validate({**event.data.model_dump(), **explanation.model_dump()})
                self.bank.upsert_alert(alert)
                await self.bus.publish(AlertCreatedEvent(ts=event.ts, data=alert))
            elif event.type == "scenario.status":
                await self.bus.publish(event)
