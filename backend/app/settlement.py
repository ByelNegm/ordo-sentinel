"""settlement-svc: a real duplicate retry bug, not a prebuilt incident fixture."""
from collections import deque
from collections.abc import Callable
from datetime import datetime

from .bank import Bank, canonical_hash
from .models import (JournalEntry, PaymentInstruction, PostingLine, Service,
                     SettlementEvent, utcnow)

PostingHook = Callable[[SettlementEvent, JournalEntry], None]


class SettlementService:
    def __init__(self, bank: Bank) -> None:
        self.bank = bank
        self.service = Service()
        self.queue: deque[str] = deque()
        self._processed_keys: set[str] = set()

    def enqueue(self, instruction: PaymentInstruction) -> None:
        if instruction.idempotency_key in self._processed_keys or instruction.id in self.queue:
            return
        if self.service.status == "quarantined":
            instruction.status = "held"
        self.queue.append(instruction.id)

    def inject(self, kind: str) -> None:
        if self.service.status == "quarantined" or self.service.fault is not None:
            raise ValueError("Fault already active or service quarantined")
        if kind in {"missing", "tamper"}:
            raise NotImplementedError(f"{kind} fault is P2")
        if kind != "duplicate":
            raise ValueError("Unknown fault")
        self.service.fault = kind

    def _post(self, instruction: PaymentInstruction, hook: PostingHook | None,
              posted_at: datetime | None = None) -> None:
        sequence = len(self.bank.events) + 1
        now = posted_at or utcnow()
        event = SettlementEvent(
            id=f"event-{sequence:06}", instruction_id=instruction.id, seq=sequence,
            service=self.service.id, debtor=instruction.debtor, creditor=instruction.creditor,
            amount_minor=instruction.amount_minor,
            payload_hash=canonical_hash(instruction.id, instruction.debtor,
                                        instruction.creditor, instruction.amount_minor), ts=now,
        )
        entry = JournalEntry(
            id=f"entry-{len(self.bank.ledger.entries) + 1:06}", kind="settlement",
            instruction_id=instruction.id, event_id=event.id, corrects_entry_id=None,
            lines=[PostingLine(account=event.debtor, side="debit", amount_minor=event.amount_minor),
                   PostingLine(account=event.creditor, side="credit", amount_minor=event.amount_minor)],
            ts=now, actor=self.service.id,
        )
        self.bank.ledger.append(entry)
        self.bank.events.append(event)
        instruction.settlement_count += 1
        instruction.status = "settled" if instruction.settlement_count == 1 else "discrepancy"
        self.service.processed += 1
        if hook:
            hook(event, entry)

    def process_queue(self, hook: PostingHook | None = None,
                      posted_at: datetime | None = None) -> None:
        while self.queue and self.service.status == "running":
            instruction = self.bank.instructions[self.queue.popleft()]
            if instruction.idempotency_key in self._processed_keys:
                continue
            fault = self.service.fault
            self.service.fault = None
            self._post(instruction, hook, posted_at)
            self._processed_keys.add(instruction.idempotency_key)
            if fault == "duplicate":
                # Retry bug: bypass the processed-key guard and emit a fresh event.
                self._post(instruction, hook, posted_at)
            elif fault in {"missing", "tamper"}:
                raise NotImplementedError("P2 fault hook")

    def quarantine(self) -> None:
        self.service.status = "quarantined"
        for identifier in self.queue:
            self.bank.instructions[identifier].status = "held"
