"""Async live traffic and a lock-serialized demo runtime/reset boundary."""
import asyncio
from collections.abc import Awaitable, Callable

from .bank import Bank
from .bus import EventBus
from .incident import ActionError, IncidentCoordinator, OPEN_STATUSES
from .models import (FaultResponse, IncidentUpdated, IntegritySummary, Overview,
                     PaymentAccepted, Reset, ServiceUpdated, Totals, Volume, utcnow)
from .settlement import SettlementService


class Traffic:
    def __init__(self, submit: Callable[[], Awaitable[None]], interval: float = 1.5) -> None:
        self.submit, self.interval = submit, interval
        self.task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def start(self) -> None:
        if not self.running:
            self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while True:
            await self.submit()
            await asyncio.sleep(self.interval)

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None


class Runtime:
    def __init__(self, traffic_interval: float = 1.5, step_delay: float = 1.0,
                 missing_grace: float = 3.0) -> None:
        if missing_grace < 0:
            raise ValueError("Missing-settlement grace cannot be negative")
        self.lock = asyncio.Lock()
        self.bus = EventBus()
        self.step_delay = step_delay
        self.missing_grace = missing_grace
        self.missing_task: asyncio.Task | None = None
        self.traffic = Traffic(self.submit_payment, traffic_interval)
        self._seed()

    def _seed(self) -> None:
        self.bank = Bank()
        self.settlement = SettlementService(self.bank, self.missing_grace)
        self.bank.seed(self.settlement)
        self.coordinator = IncidentCoordinator(self.bank, self.settlement, self.bus,
                                               self.lock, self.step_delay)
        self.coordinator.record("system", "bank.seeded", None, "100 payments settled through normal processing")

    def overview(self) -> Overview:
        entries = self.bank.ledger.entries
        report = self.coordinator.report()
        payments = list(self.bank.instructions.values())
        return Overview(
            accounts=self.bank.account_snapshots(),
            totals=Totals(
                debits_minor=sum(l.amount_minor for e in entries for l in e.lines if l.side == "debit"),
                credits_minor=sum(l.amount_minor for e in entries for l in e.lines if l.side == "credit"),
                ledger_entries=len(entries),
            ),
            volume=Volume(
                instructions=len(payments),
                settled=sum(i.status in {"settled", "discrepancy"} for i in payments),
                pending=sum(i.status in {"accepted", "missing"} for i in payments),
                held=sum(i.status == "held" for i in payments),
            ),
            services=[self.settlement.service.model_copy()],
            integrity=IntegritySummary(status=report.status,
                                       failing_checks=sum(not c.passed for c in report.checks)),
            open_incidents=sum(i.status in OPEN_STATUSES for i in self.coordinator.incidents.values()),
            traffic_running=self.traffic.running,
        )

    async def submit_payment(self) -> None:
        async with self.lock:
            instruction = self.bank.next_payment()
            self.settlement.enqueue(instruction)
            await self.bus.publish(PaymentAccepted(ts=utcnow(), data=instruction.model_copy(deep=True)))
            await self.bus.publish(self.coordinator.record("traffic", "payment.accepted", instruction.id,
                                                          instruction.status))
            emitted = []
            self.settlement.process_queue(lambda event, entry: emitted.extend(
                self.coordinator.observe_post(event, entry)))
            if instruction.id in self.settlement.pending_missing:
                emitted.append(self.coordinator.record(
                    "settlement-svc", "settlement.acknowledged", instruction.id,
                    "Deduplication acknowledged before a lost event/journal write"))
            emitted.extend(self._expire_missing())
            if self.settlement.pending_missing and (
                self.missing_task is None or self.missing_task.done()
            ):
                self.missing_task = asyncio.create_task(self._watch_missing())
            for event in emitted:
                await self.bus.publish(event)
            if instruction.status == "held":
                for incident in self.coordinator.incidents.values():
                    if incident.containment is not None and incident.status != "resolved":
                        incident.containment.held_instructions = sum(
                            i.status == "held" for i in self.bank.instructions.values())
                        await self.bus.publish(IncidentUpdated(ts=utcnow(), data=incident.model_copy(deep=True)))
            await self.bus.publish(ServiceUpdated(ts=utcnow(), data=self.settlement.service.model_copy()))

    def _expire_missing(self) -> list:
        expired = self.settlement.expire_missing()
        if not expired:
            return []
        return [self.coordinator.record("blackbox-agent", "settlement.missing", identifier,
                                        "Grace window elapsed without an event or posting")
                for identifier in expired] + self.coordinator.observe_integrity()

    async def _watch_missing(self) -> None:
        while self.settlement.pending_missing:
            due_in = min(self.missing_grace - (
                utcnow() - self.bank.instructions[identifier].created_at).total_seconds()
                for identifier in self.settlement.pending_missing)
            await asyncio.sleep(max(0, due_in))
            async with self.lock:
                for event in self._expire_missing():
                    await self.bus.publish(event)

    async def _stop_missing(self) -> None:
        if self.missing_task is not None:
            self.missing_task.cancel()
            await asyncio.gather(self.missing_task, return_exceptions=True)
            self.missing_task = None

    async def set_traffic(self, running: bool) -> dict:
        async with self.lock:
            if running:
                self.traffic.start()
            else:
                await self.traffic.stop()
            await self.bus.publish(self.coordinator.record(
                "operator", "traffic.started" if running else "traffic.stopped", None, str(running)))
            return {"running": self.traffic.running}

    async def inject(self, kind: str) -> FaultResponse:
        async with self.lock:
            try:
                self.settlement.inject(kind)
            except ValueError as error:
                await self.bus.publish(self.coordinator.record("operator", "fault.conflict", kind, str(error)))
                raise ActionError(409, str(error)) from error
            await self.bus.publish(self.coordinator.record("operator", "fault.injected", kind, "settlement-svc"))
            await self.bus.publish(ServiceUpdated(ts=utcnow(), data=self.settlement.service.model_copy()))
            return FaultResponse(fault=kind)

    async def reset(self) -> Overview:
        async with self.lock:
            await self.traffic.stop()
            await self._stop_missing()
            await self.coordinator.stop()
            self._seed()
            await self.bus.publish(self.coordinator.record("operator", "bank.reset", None, "Healthy seed restored"))
            result = self.overview()
            await self.bus.publish(Reset(ts=utcnow(), data=result))
            return result

    async def release(self):
        async with self.lock:
            incidents = list(self.coordinator.incidents.values())
            if (any(i.status in OPEN_STATUSES for i in incidents)
                    or self.settlement.service.status != "quarantined"):
                await self.bus.publish(self.coordinator.record("operator", "release.denied",
                                                              "settlement-svc", "Open incident or service not quarantined"))
                raise ActionError(409, "Release requires no open incidents and a quarantined service")
            self.settlement.service.status = "running"
            await self.bus.publish(self.coordinator.record("operator", "service.released",
                                                          "settlement-svc", "Processing held queue"))
            await self.bus.publish(ServiceUpdated(ts=utcnow(), data=self.settlement.service.model_copy()))
            emitted = []
            self.settlement.process_queue(lambda event, entry: emitted.extend(
                self.coordinator.observe_post(event, entry)))
            for event in emitted:
                await self.bus.publish(event)
            result = self.settlement.service.model_copy()
            await self.bus.publish(ServiceUpdated(ts=utcnow(), data=result))
            return result

    async def stop(self) -> None:
        async with self.lock:
            await self.traffic.stop()
            await self._stop_missing()
            await self.coordinator.stop()
