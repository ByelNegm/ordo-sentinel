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
PURPOSES = {
    "SAL": ("Salary", 800_000, 4_500_000),
    "SUP": ("Supplier payment", 250_000, 2_500_000),
    "RNT": ("Rent", 300_000, 1_800_000),
    "UTL": ("Utilities", 30_000, 250_000),
    "INV": ("Invoice settlement", 150_000, 3_500_000),
    "FND": ("Opening balance transfer", 20_000_000, 45_000_000),
}


def uae_iban(account_number: int) -> str:
    bban = f"033{account_number:016d}"
    return f"AE{98 - int(bban + '101400') % 97:02d}{bban}"


def payment_reference(sequence: int) -> str:
    value, suffix = 42_000_000 + sequence, ""
    while value:
        value, digit = divmod(value, 36)
        suffix = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"[digit] + suffix
    return f"FT{SEED_TIME:%y%j}{suffix.zfill(5)}"


def money_text(amount_minor: int) -> str:
    return f"AED {amount_minor // 100:,}.{amount_minor % 100:02d}"


def canonical_hash(instruction_id: str, debtor: str, creditor: str, amount_minor: int) -> str:
    """Canonical UTF-8 id|debtor|creditor|amount_minor; no whitespace or float conversion."""
    return hashlib.sha256(f"{instruction_id}|{debtor}|{creditor}|{amount_minor}".encode()).hexdigest()


@dataclass(frozen=True)
class AccountIdentity:
    id: str
    name: str
    type: str
    iban: str


class Bank:
    def __init__(self) -> None:
        names = ("Al Noor Trading LLC", "Gulf Horizon Logistics FZE", "Fatima Al Mansoori",
                 "Rashid Medical Centre", "Mariam Al Mazrouei", "Emirates Precision Industries LLC",
                 "Khalid Al Nuaimi", "Al Waha Utilities Services LLC", "Layla Al Suwaidi",
                 "Palm Grove Properties LLC")
        base = random.Random(42).randrange(10**15, 10**16 - 12)
        self.accounts = {
            f"customer-{i:02}": AccountIdentity(f"customer-{i:02}", name, "customer", uae_iban(base + i))
            for i, name in enumerate(names, 1)
        }
        self.accounts["clearing"] = AccountIdentity("clearing", "UAEFTS Settlement Clearing", "internal", uae_iban(base + 11))
        self.accounts["treasury"] = AccountIdentity("treasury", "Central Treasury – Liquidity Pool", "internal", uae_iban(base + 12))
        self.ledger = Ledger(self.accounts)
        self.instructions: dict[str, PaymentInstruction] = {}
        self.events: list[SettlementEvent] = []
        self._keys: dict[str, str] = {}
        self._rng = random.Random(42)

    def create_instruction(self, debtor: str, creditor: str, amount_minor: int,
                           idempotency_key: str | None = None,
                           created_at: datetime | None = None, purpose: str = "INV") -> PaymentInstruction:
        if debtor not in self.accounts or creditor not in self.accounts or debtor == creditor:
            raise ValueError("Payment must name two distinct known accounts")
        if type(amount_minor) is not int or amount_minor <= 0:
            raise ValueError("Money must be a positive integer in minor units")
        if purpose not in PURPOSES:
            raise ValueError("Unknown payment purpose")
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
            reference=payment_reference(len(self.instructions) + 1), purpose=purpose,
            purpose_label=PURPOSES[purpose][0], debtor_name=self.accounts[debtor].name,
            creditor_name=self.accounts[creditor].name,
        )
        self.instructions[identifier] = instruction
        self._keys[key] = identifier
        return instruction

    def next_payment(self, created_at: datetime | None = None) -> PaymentInstruction:
        purpose = self._rng.choice(["SAL", "SUP", "RNT", "UTL", "INV"])
        corporates = ["customer-01", "customer-02", "customer-04", "customer-06", "customer-10"]
        debtor = self._rng.choice(corporates)
        creditors = (["customer-03", "customer-05", "customer-07", "customer-09"] if purpose == "SAL"
                     else ["customer-08"] if purpose == "UTL" else ["customer-10"] if purpose == "RNT"
                     else corporates)
        creditor = self._rng.choice([a for a in creditors if a != debtor] or ["customer-01"])
        _, low, high = PURPOSES[purpose]
        amount = self._rng.randint(low // 100, high // 100 - 1) * 100 + self._rng.randint(1, 99)
        return self.create_instruction(debtor, creditor, amount, created_at=created_at, purpose=purpose)

    def seed(self, settlement: "SettlementService") -> None:
        """Exactly 100 instructions, each processed through the ordinary settlement path."""
        for i, account in enumerate(list(self.accounts)[:10]):
            amount = self._rng.randint(250_000, 449_999) * 100 + self._rng.randint(1, 99)
            payment = self.create_instruction("clearing", account, amount,
                                              created_at=SEED_TIME + timedelta(seconds=i), purpose="FND")
            settlement.enqueue(payment)
            settlement.process_queue(posted_at=payment.created_at)
        for i in range(10, 100):
            payment = self.next_payment(SEED_TIME + timedelta(seconds=i))
            settlement.enqueue(payment)
            settlement.process_queue(posted_at=payment.created_at)

    def account_snapshots(self) -> list[Account]:
        balances = self.ledger.balances()
        return [Account(id=a.id, name=a.name, type=a.type, balance_minor=balances[a.id], iban=a.iban)
                for a in self.accounts.values()]
