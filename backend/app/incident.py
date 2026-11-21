"""Evidence-led recovery coordinator. The agent proposes; only a human applies corrections."""
import asyncio
from copy import deepcopy

from .bank import Bank, money_text
from .bus import EventBus
from .daytona_runner import DaytonaValidator
from .integrity import (extra_postings, inspect, intent_lines, restored_instructions,
                        tampered_postings)
from .ledger import reversed_lines
from .models import (Approval, AuditAppended, AuditRecord, Containment, Incident,
                     IncidentUpdated, IntegrityUpdated, JournalEntry, Lineage, Proposal,
                     RejectionReason, RootCause, SandboxChallengeResponse, SandboxReport, ServiceUpdated, SettlementEvent,
                     SettlementPosted, PostedSettlement, TimelineItem, utcnow)
from .settlement import SettlementService

APPROVERS = {"ops.lead@bank", "treasury@bank"}
AGENT = "blackbox-agent"
OPEN_STATUSES = {"detected", "investigating", "contained", "validating",
                 "awaiting_approval", "correcting"}


class ActionError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status, self.detail = status, detail


class IncidentCoordinator:
    def __init__(self, bank: Bank, settlement: SettlementService, bus: EventBus,
                 lock: asyncio.Lock, step_delay: float = 1.0,
                 validator: DaytonaValidator | None = None) -> None:
        self.bank, self.settlement, self.bus = bank, settlement, bus
        self.lock, self.step_delay = lock, step_delay
        self.incidents: dict[str, Incident] = {}
        self.audit: list[AuditRecord] = []
        self.tasks: set[asyncio.Task] = set()
        self.validator = validator

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
        return [
            SettlementPosted(ts=event.ts, data=PostedSettlement(event=event, entry=entry)),
            self.record(event.service, "settlement.posted", entry.id,
                        f"Instruction {event.instruction_id}; event {event.id}"),
        ] + self.observe_integrity()

    def observe_integrity(self) -> list:
        report = inspect(self.bank.ledger, self.bank.instructions, self.bank.events)
        emitted = [IntegrityUpdated(ts=report.ts, data=report)]
        if report.status == "healthy":
            return emitted
        current = next((i for i in self.incidents.values() if i.status in OPEN_STATUSES), None)
        closed_payments = {identifier for incident in self.incidents.values()
                           if incident.status not in OPEN_STATUSES
                           for identifier in incident.affected_payments}
        extras = [e for e in extra_postings(self.bank.ledger) if e.instruction_id not in closed_payments]
        tampered = [e for e in tampered_postings(self.bank.ledger, self.bank.instructions, self.bank.events)
                    if e.instruction_id not in closed_payments]
        restored = restored_instructions(self.bank.ledger, self.bank.instructions)
        missing = [i for i in self.bank.instructions.values()
                   if i.status == "missing" and i.id not in restored and i.id not in closed_payments]
        if tampered:
            kind, postings = "tampered_settlement", tampered
            affected = {e.instruction_id for e in postings}
            impact = 0
            for identifier in affected:
                instruction = self.bank.instructions[identifier]
                delta = {}
                for line in [l.model_dump() for e in postings if e.instruction_id == identifier
                             for l in e.lines]:
                    delta[line["account"]] = delta.get(line["account"], 0) + (
                        line["amount_minor"] if line["side"] == "credit" else -line["amount_minor"])
                for line in intent_lines(instruction):
                    delta[line["account"]] = delta.get(line["account"], 0) - (
                        line["amount_minor"] if line["side"] == "credit" else -line["amount_minor"])
                impact += sum(abs(value) for value in delta.values()) // 2
        elif extras:
            kind, postings = "duplicate_settlement", extras
            affected = {e.instruction_id for e in postings}
            impact = sum(l.amount_minor for e in postings for l in e.lines if l.side == "debit")
        elif missing:
            kind, postings = "missing_settlement", []
            affected = {i.id for i in missing}
            impact = sum(i.amount_minor for i in missing)
        else:
            return emitted
        accounts = {l.account for e in postings for l in e.lines}
        accounts.update(account for identifier in affected
                        for account in (self.bank.instructions[identifier].debtor,
                                        self.bank.instructions[identifier].creditor))
        if current is None:
            now = utcnow()
            identifier = f"incident-{len(self.incidents) + 1:04}"
            current = Incident(
                id=identifier, type=kind, status="detected", detected_at=now,
                violations=[check for check in report.checks if not check.passed],
                affected_payments=sorted(affected), affected_accounts=sorted(accounts),
                impact_minor=impact,
                root_cause=RootCause(service=self.settlement.service.id, summary="Deterministic investigation pending",
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
            current.affected_payments = sorted(affected)
            current.affected_accounts = sorted(accounts)
            current.impact_minor = impact
            if current.status == "investigating":
                self._investigate(current)
        current.summary_text = self.summary_text(current)
        emitted.append(IncidentUpdated(ts=utcnow(), data=current.model_copy(deep=True)))
        return emitted

    def summary_text(self, incident: Incident) -> str:
        summaries = []
        for identifier in incident.affected_payments:
            instruction = self.bank.instructions[identifier]
            title = (f"Payment {instruction.reference} ({money_text(instruction.amount_minor)}, "
                     f"{instruction.purpose_label}) from {instruction.debtor_name} to {instruction.creditor_name}")
            if incident.type == "duplicate_settlement":
                summaries.append(f"{title} was settled twice; debits still equal credits, "
                                 f"but {instruction.debtor_name} was charged twice.")
            elif incident.type == "missing_settlement":
                summaries.append(f"{title} was acknowledged but never settled; "
                                 f"{instruction.creditor_name} has not received the expected credit.")
            else:
                event = next(e for e in self.bank.events if e.instruction_id == identifier)
                summaries.append(f"{title} was settled for {money_text(event.amount_minor)} instead of "
                                 f"{money_text(instruction.amount_minor)}; the posting differs from the approved instruction.")
        return " ".join(summaries)

    def _investigate(self, incident: Incident) -> None:
        lineage, timeline, summaries, services = [], [], [], set()
        entries = self.bank.ledger.entries
        for identifier in incident.affected_payments:
            instruction = self.bank.instructions[identifier]
            payment_label = (f"{instruction.reference} from {instruction.debtor_name} "
                             f"to {instruction.creditor_name}")
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
            if incident.type == "missing_settlement":
                services.add(self.settlement.service.id)
                summaries.append(f"{self.settlement.service.id} acknowledged instruction {payment_label} ({identifier}) "
                                 "but no event or posting exists after the grace window")
            elif incident.type == "tampered_settlement":
                for event in events:
                    differences = [
                        f"{field}: expected {getattr(instruction, field)}, observed {getattr(event, field)}"
                        for field in ("debtor", "creditor", "amount_minor")
                        if getattr(event, field) != getattr(instruction, field)
                    ]
                    if differences:
                        summaries.append(f"{event.service} altered payment {payment_label} (event {event.id}): " + "; ".join(differences))
            else:
                summaries.append(f"Events ({', '.join(e.id for e in events)}) share instruction {payment_label} ({identifier}) "
                                 f"and idempotency key ({instruction.idempotency_key}); retry bypassed deduplication")
        incident.lineage = lineage
        service = next(iter(services)) if len(services) == 1 else "settlement-svc"
        incident.root_cause = RootCause(
            service=service, summary="; ".join(summaries) + f"; responsible service {service}.",
            confidence="high" if len(services) == 1 else "medium", method="deterministic",
        )
        detection = next(t for t in incident.timeline if t.kind == "detection")
        incident.timeline = sorted(timeline + [detection], key=lambda t: t.ts)
        incident.timeline.append(TimelineItem(ts=utcnow(), kind="investigation", ref=incident.id,
                                              detail=incident.root_cause.summary))

    def propose(self, incident: Incident) -> Proposal:
        originals = (tampered_postings(self.bank.ledger, self.bank.instructions, self.bank.events)
                     if incident.type == "tampered_settlement" else extra_postings(self.bank.ledger)
                     if incident.type == "duplicate_settlement" else [])
        entries = [
            JournalEntry(id=f"correction-{incident.id}-{original.id}", kind="compensation",
                         instruction_id=original.instruction_id, event_id=None,
                         corrects_entry_id=original.id, lines=reversed_lines(original),
                         ts=utcnow(), actor=AGENT)
            for original in originals
            if original.instruction_id in incident.affected_payments
        ]
        if incident.type in {"missing_settlement", "tampered_settlement"}:
            entries.extend(
                JournalEntry(id=f"correction-{incident.id}-intent-{identifier}", kind="compensation",
                             instruction_id=identifier, event_id=None, corrects_entry_id=None,
                             lines=intent_lines(self.bank.instructions[identifier]), ts=utcnow(), actor=AGENT)
                for identifier in incident.affected_payments
            )
        return Proposal(id=f"proposal-{incident.id}",
                        description="Restore independent payment intent; preserve every original entry and event.",
                        entries=entries)

    @staticmethod
    def correction_key(incident: Incident, entry: JournalEntry) -> str:
        return f"{incident.id}:{entry.corrects_entry_id or 'intent:' + entry.instruction_id}"

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
            expected = self.propose(incident)
            def signature(entry):
                return entry.model_dump(exclude={"ts", "actor"})
            if not proposal.entries or [signature(e) for e in proposal.entries] != [
                signature(e) for e in expected.entries
            ]:
                raise ValueError("Proposal must exactly restore the affected instruction effects")
            for entry in proposal.entries:
                if entry.kind != "compensation":
                    raise ValueError("Proposal can only append compensation")
                ledger.append(entry, self.correction_key(incident, entry))
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

    async def challenge(self, identifier: str, variant: str) -> SandboxChallengeResponse:
        """Caller holds the runtime lock; only a detached incident is challenged."""
        incident = self.get(identifier)
        if incident.status != "awaiting_approval" or incident.proposal is None:
            raise ActionError(409, "Incident is not awaiting approval")
        if variant not in {"wrong_amount", "reverse_original"}:
            raise ActionError(422, "Unknown sandbox challenge variant")
        candidate = incident.model_copy(deep=True)
        candidate.proposal.id = f"challenge-{identifier}-{variant}"
        candidate.proposal.description = f"Unsafe correction challenge: {variant}"
        if variant == "wrong_amount":
            for entry in candidate.proposal.entries:
                for line in entry.lines:
                    line.amount_minor += 100
        elif incident.type == "duplicate_settlement":
            for entry in candidate.proposal.entries:
                original = next(e for e in self.bank.ledger.entries
                                if e.kind == "settlement" and e.instruction_id == entry.instruction_id)
                entry.corrects_entry_id = original.id
                entry.lines = JournalEntry.model_validate({
                    **entry.model_dump(), "lines": reversed_lines(original),
                }).lines
        else:
            for entry in candidate.proposal.entries:
                if entry.corrects_entry_id is None:
                    for line in entry.lines:
                        line.side = "credit" if line.side == "debit" else "debit"
        before = self.bank.ledger.serialize()
        ledger = deepcopy(self.bank.ledger)
        instructions, events = deepcopy(self.bank.instructions), deepcopy(self.bank.events)
        checks_before = inspect(ledger, instructions, events).checks
        balances_before = ledger.balances()
        reasons = []
        for proposed, expected in zip(candidate.proposal.entries, incident.proposal.entries):
            payment = self.bank.instructions[proposed.instruction_id]
            if proposed.corrects_entry_id != expected.corrects_entry_id:
                reasons.append(RejectionReason(
                    rule="lineage_guard",
                    detail=f"Reverses original entry JE{proposed.corrects_entry_id.rsplit('-', 1)[-1]} of "
                           f"{payment.reference} from {payment.debtor_name} to {payment.creditor_name}; "
                           f"only the duplicate effect JE{expected.corrects_entry_id.rsplit('-', 1)[-1]} may be reversed.",
                ))
            elif proposed.lines != expected.lines:
                reasons.append(RejectionReason(
                    rule="amount_guard" if variant == "wrong_amount" else "intent_guard",
                    detail=(f"{payment.reference} from {payment.debtor_name} to {payment.creditor_name}: "
                            f"correction lines differ from the approved {money_text(payment.amount_minor)} "
                            f"{payment.purpose_label.lower()} instruction; " +
                            ("each line is overstated by AED 1.00." if variant == "wrong_amount"
                             else "the replacement reverses the intended payment instead of restoring it.")),
                ))
        applied = False
        try:
            ledger.append_batch([(entry, self.correction_key(candidate, entry))
                                 for entry in candidate.proposal.entries])
            applied = True
        except (ValueError, TypeError, KeyError) as error:
            references = ", ".join(f"{instructions[p].reference} from {instructions[p].debtor_name} "
                                   f"to {instructions[p].creditor_name}" for p in incident.affected_payments)
            reasons.append(RejectionReason(rule="ledger_guard", detail=f"{references}: {error}"))
        after = inspect(ledger, instructions, events)
        if applied:
            for check in after.checks:
                if not check.passed:
                    detail = check.detail
                    for payment in instructions.values():
                        detail = detail.replace(payment.id, payment.reference or "Payment")
                    for account in self.bank.accounts.values():
                        detail = detail.replace(account.id, account.name)
                    references = ", ".join(f"{instructions[p].reference} ({instructions[p].debtor_name} "
                                           f"to {instructions[p].creditor_name})" for p in incident.affected_payments)
                    reasons.append(RejectionReason(rule="integrity_check", detail=f"{references}; {check.name}: {detail}"))
        report = SandboxReport(
            passed=not reasons and all(c.passed for c in after.checks),
            checks_before=checks_before, checks_after=after.checks,
            balances_before=balances_before, balances_after=ledger.balances(), ts=utcnow(),
        )
        result = SandboxChallengeResponse(
            variant=variant, proposal=candidate.proposal, sandbox=report,
            ledger_unchanged=before == self.bank.ledger.serialize(),
            applied=applied, rejection_reasons=reasons,
        )
        await self.bus.publish(self.record(
            AGENT, "sandbox.challenge.rejected", identifier,
            f"{variant}; applied to sandbox: {applied}; " + "; ".join(r.detail for r in reasons),
        ))
        return result

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
                payload = self.validation_payload(incident) if self.validator else None
            if self.validator:
                validated = await self.validator.validate(payload, incident.sandbox)
            else:
                validated = incident.sandbox
            async with self.lock:
                incident.sandbox = validated
                if validated.runner == "daytona":
                    detail = f"Validated in Daytona sandbox {validated.runner_id}"
                    incident.timeline.append(TimelineItem(
                        ts=utcnow(), kind="sandbox", ref=validated.runner_id, detail=detail))
                    await self.bus.publish(self.record(AGENT, "sandbox.daytona.validated",
                                                       identifier, detail))
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

    def validation_payload(self, incident: Incident) -> dict:
        return {
            "accounts": sorted(self.bank.ledger.accounts),
            "entries": [entry.model_dump(mode="json") for entry in self.bank.ledger.entries],
            "instructions": [item.model_dump(mode="json") for item in self.bank.instructions.values()],
            "events": [event.model_dump(mode="json") for event in self.bank.events],
            "proposal": incident.proposal.model_dump(mode="json"),
            "expected_proposal": self.propose(incident).model_dump(mode="json"),
        }

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
        confirmation = incident.sandbox
        incident.sandbox = self.sandbox(incident)
        if confirmation is not None and incident.sandbox.passed:
            for field in ("runner", "runner_id", "remote_match", "runner_note"):
                setattr(incident.sandbox, field, getattr(confirmation, field))
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
                  self.correction_key(incident, entry)) for entry in incident.proposal.entries]
        try:
            applied = self.bank.ledger.append_batch(batch)
        except Exception as error:
            incident.status = "failed"
            await self.bus.publish(self.record(actor, "recovery.failed", identifier, str(error)))
            await self.bus.publish(IncidentUpdated(ts=utcnow(), data=incident.model_copy(deep=True)))
            raise ActionError(409, "Correction batch failed; incident marked failed") from error
        incident.corrections = [entry.id for entry in applied]
        for entry in applied:
            incident.timeline.append(TimelineItem(ts=entry.ts, kind="correction", ref=entry.id,
                                                   detail=f"Compensates {entry.corrects_entry_id}"))
            await self.bus.publish(self.record(actor, "ledger.compensated", entry.id,
                                              entry.corrects_entry_id or f"Restores {entry.instruction_id}"))
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
