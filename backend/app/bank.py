"""Synthetic instructions and account identities, independent of settlement evidence."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import random
from typing import TYPE_CHECKING

from .ledger import Ledger
from .models import Account, PaymentInstruction, SettlementEvent, utcnow

if TYPE_CHECKING:
    from .settlement import SettlementService

SEED_TIME = datetime(2026, 11, 21, 8, tzinfo=timezone.utc)


def canonical_hash(instruction_id: str, debtor: str, creditor: str, amount_minor: int) -> str:
    """Canonical UTF-8 id|debtor|creditor|amount_minor; no whitespace or float conversion."""
    return hashlib.sha256(f"{instruction_id}|{debtor}|{creditor}|{amount_minor}".encode()).hexdigest()


@dataclass(frozen=True)
class AccountIdentity:
    id: str
    name: str
    type: str


class Bank:
    def __init__(self) -> None:
        names = ("Aisha", "Omar", "Mariam", "Khalid", "Noor", "Yousef",
                 "Fatima", "Hassan", "Layla", "Saeed")
        self.accounts = {
            f"customer-{i:02}": AccountIdentity(f"customer-{i:02}", name, "customer")
            for i, name in enumerate(names, 1)
        }
        self.accounts["clearing"] = AccountIdentity("clearing", "Settlement clearing", "internal")
        self.accounts["treasury"] = AccountIdentity("treasury", "Treasury control", "internal")
        self.ledger = Ledger(self.accounts)
        self.instructions: dict[str, PaymentInstruction] = {}
        self.events: list[SettlementEvent] = []
        self._keys: dict[str, str] = {}
        self._rng = random.Random(42)

    def create_instruction(self, debtor: str, creditor: str, amount_minor: int,
                           idempotency_key: str | None = None,
                           created_at: datetime | None = None) -> PaymentInstruction:
        if debtor not in self.accounts or creditor not in self.accounts or debtor == creditor:
            raise ValueError("Payment must name two distinct known accounts")
        if type(amount_minor) is not int or amount_minor <= 0:
            raise ValueError("Money must be a positive integer in minor units")
        if idempotency_key in self._keys:
            existing = self.instructions[self._keys[idempotency_key]]
            if (existing.debtor, existing.creditor, existing.amount_minor) != (debtor, creditor, amount_minor):
                raise ValueError("Idempotency key conflicts with instruction")
            return existing
        identifier = f"payment-{len(self.instructions) + 1:06}"
        key = idempotency_key or f"idem-{identifier}"
        if key in self._keys:
            raise ValueError("Idempotency key already exists")
        instruction = PaymentInstruction(
            id=identifier, idempotency_key=key, debtor=debtor, creditor=creditor,
            amount_minor=amount_minor, created_at=created_at or utcnow(),
            expected_hash=canonical_hash(identifier, debtor, creditor, amount_minor),
        )
        self.instructions[identifier] = instruction
        self._keys[key] = identifier
        return instruction

    def next_payment(self, created_at: datetime | None = None) -> PaymentInstruction:
        debtor, creditor = self._rng.sample(
            [account.id for account in self.accounts.values() if account.type == "customer"], 2)
        return self.create_instruction(debtor, creditor, self._rng.randint(10000, 250000),
                                       created_at=created_at)

    def seed(self, settlement: "SettlementService") -> None:
        """Exactly 100 instructions, each processed through the ordinary settlement path."""
        for i, account in enumerate(list(self.accounts)[:10]):
            payment = self.create_instruction("clearing", account, 5_000_000,
                                              created_at=SEED_TIME + timedelta(seconds=i))
            settlement.enqueue(payment)
            settlement.process_queue(posted_at=payment.created_at)
        for i in range(10, 100):
            payment = self.next_payment(SEED_TIME + timedelta(seconds=i))
            settlement.enqueue(payment)
            settlement.process_queue(posted_at=payment.created_at)

    def account_snapshots(self) -> list[Account]:
        balances = self.ledger.balances()
        return [Account(id=a.id, name=a.name, type=a.type, balance_minor=balances[a.id])
                for a in self.accounts.values()]
