"""Evidence-led recovery coordinator. The agent proposes; only a human applies corrections."""
import asyncio
from copy import deepcopy

from .bank import Bank
from .bus import EventBus
from .integrity import extra_postings, inspect
from .ledger import reversed_lines
from .models import (Approval, AuditAppended, AuditRecord, Containment, Incident,
                     IncidentUpdated, IntegrityUpdated, JournalEntry, Lineage, Proposal,
                     RootCause, SandboxReport, ServiceUpdated, SettlementEvent,
                     SettlementPosted, PostedSettlement, TimelineItem, utcnow)
from .settlement import SettlementService

APPROVERS = {"ops.lead@bank", "treasury@bank"}
AGENT = "blackbox-agent"


class ActionError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status, self.detail = status, detail


class IncidentCoordinator:
    def __init__(self, bank: Bank, settlement: SettlementService, bus: EventBus,
                 lock: asyncio.Lock, step_delay: float = 1.0) -> None:
        self.bank, self.settlement, self.bus = bank, settlement, bus
        self.lock, self.step_delay = lock, step_delay
        self.incidents: dict[str, Incident] = {}
        self.audit: list[AuditRecord] = []
        self.tasks: set[asyncio.Task] = set()

    def record(self, actor: str, action: str, ref: str | None, detail: str) -> AuditAppended:
        record = AuditRecord(id=f"audit-{len(self.audit) + 1:06}", ts=utcnow(),
                             actor=actor, action=action, ref=ref, detail=detail)
        self.audit.append(record)
        return AuditAppended(ts=record.ts, data=record)

    def get(self, identifier: str) -> Incident:
        if identifier not in self.incidents:
            raise ActionError(404, "Incident not found")
        return self.incidents[identifier]

    def report(self):
        report = inspect(self.bank.ledger, self.bank.instructions, self.bank.events)
        if report.status == "violated" and any(
            i.status in {"contained", "validating", "awaiting_approval", "correcting"}
            for i in self.incidents.values()
        ):
            report.status = "recovering"
        return report

    def observe_post(self, event: SettlementEvent, entry: JournalEntry) -> list:
        """Called synchronously after EVERY append, including the faulty retry."""
        report = inspect(self.bank.ledger, self.bank.instructions, self.bank.events)
        emitted = [
            SettlementPosted(ts=event.ts, data=PostedSettlement(event=event, entry=entry)),
            self.record(event.service, "settlement.posted", entry.id,
                        f"Instruction {event.instruction_id}; event {event.id}"),
            IntegrityUpdated(ts=report.ts, data=report),
        ]
        if report.status == "healthy":
            return emitted
        current = next((i for i in self.incidents.values() if i.status != "resolved"), None)
        extras = extra_postings(self.bank.ledger)
        if current is None:
            now = utcnow()
            identifier = f"incident-{len(self.incidents) + 1:04}"
            current = Incident(
                id=identifier, type="duplicate_settlement", status="detected", detected_at=now,
                violations=[check for check in report.checks if not check.passed],
                affected_payments=sorted({e.instruction_id for e in extras}),
                affected_accounts=sorted({line.account for e in extras for line in e.lines}),
                impact_minor=sum(sum(l.amount_minor for l in e.lines if l.side == "debit") for e in extras),
                root_cause=RootCause(service=event.service, summary="Deterministic investigation pending",
                                     confidence="low", method="deterministic"),
                lineage=[], timeline=[TimelineItem(ts=now, kind="detection", ref=identifier,
                                                  detail="Independent intent and ledger effects disagree")],
            )
            self.incidents[identifier] = current
            task = asyncio.create_task(self._pipeline(identifier))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
            emitted.append(self.record(AGENT, "incident.detected", identifier,
                                       ", ".join(c.name for c in current.violations)))
        else:
            current.affected_payments = sorted({e.instruction_id for e in extras})
            current.affected_accounts = sorted({line.account for e in extras for line in e.lines})
            current.impact_minor = sum(
                sum(l.amount_minor for l in e.lines if l.side == "debit") for e in extras)
            if current.status == "investigating":
                self._investigate(current)
        emitted.append(IncidentUpdated(ts=utcnow(), data=current.model_copy(deep=True)))
        return emitted

    def _investigate(self, incident: Incident) -> None:
        lineage, timeline, summaries, services = [], [], [], set()
        entries = self.bank.ledger.entries
        for identifier in incident.affected_payments:
            instruction = self.bank.instructions[identifier]
            events = [e for e in self.bank.events if e.instruction_id == identifier]
            postings = [e for e in entries if e.instruction_id == identifier]
            lineage.append(Lineage(instruction_id=identifier, event_ids=[e.id for e in events],
                                   entry_ids=[e.id for e in postings]))
            timeline.append(TimelineItem(ts=instruction.created_at, kind="instruction", ref=identifier,
                                         detail=f"Intent stored with key {instruction.idempotency_key}"))
            timeline.extend(TimelineItem(ts=e.ts, kind="settlement", ref=e.id,
                                         detail=f"{e.service} emitted event seq {e.seq}") for e in events)
            timeline.extend(TimelineItem(ts=e.ts, kind="posting", ref=e.id,
                                         detail="Balanced ledger effect") for e in postings)
            services.update(e.service for e in events)
            summaries.append(f"Events {', '.join(e.id for e in events)} share instruction {identifier} "
                             f"and idempotency key {instruction.idempotency_key}")
        incident.lineage = lineage
        service = next(iter(services)) if len(services) == 1 else "settlement-svc"
        incident.root_cause = RootCause(
            service=service, summary="; ".join(summaries) + f"; emitted by {service} (retry bypassed deduplication).",
            confidence="high" if len(services) == 1 else "medium", method="deterministic",
        )
        detection = next(t for t in incident.timeline if t.kind == "detection")
        incident.timeline = sorted(timeline + [detection], key=lambda t: t.ts)
        incident.timeline.append(TimelineItem(ts=utcnow(), kind="investigation", ref=incident.id,
                                              detail=incident.root_cause.summary))

    def propose(self, incident: Incident) -> Proposal:
        entries = [
            JournalEntry(id=f"correction-{incident.id}-{original.id}", kind="compensation",
                         instruction_id=original.instruction_id, event_id=None,
                         corrects_entry_id=original.id, lines=reversed_lines(original),
                         ts=utcnow(), actor=AGENT)
            for original in extra_postings(self.bank.ledger)
            if original.instruction_id in incident.affected_payments
        ]
        return Proposal(id=f"proposal-{incident.id}",
                        description="Reverse each extra posting; preserve every original entry.", entries=entries)

    def sandbox(self, incident: Incident) -> SandboxReport:
        """Deep-copy all financial evidence. Invalid proposals never touch the real ledger."""
        ledger = deepcopy(self.bank.ledger)
        instructions = deepcopy(self.bank.instructions)
        events = deepcopy(self.bank.events)
        before = inspect(ledger, instructions, events)
        balances_before = ledger.balances()
        valid = True
        try:
            if incident.proposal is None:
                raise ValueError("Proposal missing")
            proposal = Proposal.model_validate(incident.proposal.model_dump())
            extras = {e.id for e in extra_postings(ledger)
                      if e.instruction_id in incident.affected_payments}
            references = [e.corrects_entry_id for e in proposal.entries]
            if not extras or len(references) != len(set(references)) or set(references) != extras:
                raise ValueError("Proposal must reverse every extra posting exactly once")
            for entry in proposal.entries:
                if entry.kind != "compensation":
                    raise ValueError("Proposal can only append compensation")
                ledger.append(entry, f"{incident.id}:{entry.corrects_entry_id}")
        except (ValueError, TypeError, KeyError):
            valid = False
        after = inspect(ledger, instructions, events)
        return SandboxReport(
            passed=valid and all(check.passed for check in after.checks),
            checks_before=before.checks, checks_after=after.checks,
            balances_before=balances_before, balances_after=ledger.balances(), ts=utcnow(),
        )

    async def _change(self, incident: Incident, status: str, action: str, detail: str) -> None:
        incident.status = status
        await self.bus.publish(self.record(AGENT, action, incident.id, detail))
        await self.bus.publish(IncidentUpdated(ts=utcnow(), data=incident.model_copy(deep=True)))

    async def _pipeline(self, identifier: str) -> None:
        try:
            await asyncio.sleep(self.step_delay)
            async with self.lock:
                incident = self.get(identifier)
                self._investigate(incident)
                await self._change(incident, "investigating", "incident.investigated",
                                   incident.root_cause.summary)
            await asyncio.sleep(self.step_delay)
            async with self.lock:
                self.settlement.quarantine()
                now = utcnow()
                incident.containment = Containment(
                    service=self.settlement.service.id, action="quarantine", at=now,
                    held_instructions=sum(i.status == "held" for i in self.bank.instructions.values()),
                )
                incident.timeline.append(TimelineItem(ts=now, kind="containment",
                                                       ref=self.settlement.service.id,
                                                       detail="Settlement service quarantined"))
                await self.bus.publish(ServiceUpdated(ts=now, data=self.settlement.service.model_copy()))
                await self._change(incident, "contained", "service.quarantined", "New payments will be held")
            await asyncio.sleep(self.step_delay)
            async with self.lock:
                incident.proposal = self.propose(incident)
                incident.timeline.append(TimelineItem(ts=utcnow(), kind="proposal", ref=incident.proposal.id,
                                                       detail=incident.proposal.description))
                await self._change(incident, "validating", "recovery.proposed", incident.proposal.description)
            await asyncio.sleep(self.step_delay)
            async with self.lock:
                incident.sandbox = self.sandbox(incident)
                incident.timeline.append(TimelineItem(ts=utcnow(), kind="sandbox", ref=incident.proposal.id,
                                                       detail=f"Sandbox passed: {incident.sandbox.passed}"))
                await self._change(incident, "awaiting_approval" if incident.sandbox.passed else "failed",
                                   "sandbox.completed", f"Sandbox passed: {incident.sandbox.passed}")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            async with self.lock:
                incident = self.get(identifier)
                await self._change(incident, "failed", "incident.failed", str(error))

    async def approve(self, identifier: str, actor: str) -> Incident:
        """Caller holds the runtime lock across validation and the atomic append batch."""
        if actor not in APPROVERS:
            await self.bus.publish(self.record(actor, "approval.denied", identifier, "Unauthorized approver"))
            raise ActionError(403, "Actor is not an authorized approver")
        incident = self.get(identifier)
        if incident.status == "resolved" and incident.approval is not None:
            await self.bus.publish(self.record(actor, "approval.repeated", identifier, "Already applied; no new correction"))
            return incident
        if incident.status != "awaiting_approval":
            await self.bus.publish(self.record(actor, "approval.conflict", identifier, incident.status))
            raise ActionError(409, "Incident is not awaiting approval")
        incident.sandbox = self.sandbox(incident)
        if not incident.sandbox.passed:
            await self._change(incident, "failed", "approval.invalid", "Proposal failed sandbox revalidation")
            raise ActionError(409, "Proposal failed sandbox revalidation")
        now = utcnow()
        incident.approval = Approval(actor=actor, at=now)
        incident.timeline.append(TimelineItem(ts=now, kind="approval", ref=identifier, detail=f"Approved by {actor}"))
        incident.status = "correcting"
        await self.bus.publish(self.record(actor, "recovery.approved", identifier, "Sandbox revalidated"))
        await self.bus.publish(IncidentUpdated(ts=now, data=incident.model_copy(deep=True)))
        batch = [(entry.model_copy(update={"actor": actor, "ts": utcnow()}, deep=True),
                  f"{identifier}:{entry.corrects_entry_id}") for entry in incident.proposal.entries]
        applied = self.bank.ledger.append_batch(batch)
        incident.corrections = [entry.id for entry in applied]
        for entry in applied:
            incident.timeline.append(TimelineItem(ts=entry.ts, kind="correction", ref=entry.id,
                                                   detail=f"Compensates {entry.corrects_entry_id}"))
            await self.bus.publish(self.record(actor, "ledger.compensated", entry.id, entry.corrects_entry_id))
        for payment_id in incident.affected_payments:
            self.bank.instructions[payment_id].status = "settled"
        for lineage in incident.lineage:
            lineage.entry_ids.extend(e.id for e in applied if e.instruction_id == lineage.instruction_id)
        incident.verification = inspect(self.bank.ledger, self.bank.instructions, self.bank.events)
        incident.timeline.append(TimelineItem(ts=utcnow(), kind="verification", ref=identifier,
                                               detail="All seven checks re-run against the real ledger"))
        incident.status = "resolved" if all(c.passed for c in incident.verification.checks) else "failed"
        await self.bus.publish(self.record(actor, "recovery.verified", identifier, incident.verification.status))
        await self.bus.publish(IntegrityUpdated(ts=utcnow(), data=incident.verification))
        await self.bus.publish(IncidentUpdated(ts=utcnow(), data=incident.model_copy(deep=True)))
        return incident

    async def reject(self, identifier: str, actor: str) -> Incident:
        incident = self.get(identifier)
        if incident.status != "awaiting_approval":
            await self.bus.publish(self.record(actor, "rejection.conflict", identifier, incident.status))
            raise ActionError(409, "Incident is not awaiting approval")
        incident.status = "rejected"
        await self.bus.publish(self.record(actor, "recovery.rejected", identifier, "Service remains quarantined"))
        await self.bus.publish(IncidentUpdated(ts=utcnow(), data=incident.model_copy(deep=True)))
        return incident

    async def stop(self) -> None:
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
