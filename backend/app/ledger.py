"""Append-only double-entry store. Balances are always recomputed, never assigned."""
from collections import Counter
from copy import deepcopy
import json
from typing import Iterable

from .models import JournalEntry


def reversed_lines(entry: JournalEntry) -> list[dict]:
    return [{"account": line.account, "side": "credit" if line.side == "debit" else "debit",
             "amount_minor": line.amount_minor} for line in entry.lines]


def line_signature(entry: JournalEntry) -> Counter:
    return Counter((line.account, line.side, line.amount_minor) for line in entry.lines)


class Ledger:
    def __init__(self, accounts: Iterable[str]) -> None:
        self.accounts = frozenset(accounts)
        self._entries: tuple[JournalEntry, ...] = ()
        self._correction_keys: dict[str, str] = {}

    @property
    def entries(self) -> tuple[JournalEntry, ...]:
        """Detached snapshots cannot mutate the journal."""
        return deepcopy(self._entries)

    def append(self, entry: JournalEntry, correction_key: str | None = None) -> JournalEntry:
        if correction_key and correction_key in self._correction_keys:
            existing = next(e for e in self._entries if e.id == self._correction_keys[correction_key])
            if (existing.corrects_entry_id != entry.corrects_entry_id
                    or existing.instruction_id != entry.instruction_id
                    or line_signature(existing) != line_signature(entry)):
                raise ValueError("Correction key conflicts with an existing correction")
            return existing.model_copy(deep=True)
        entry = JournalEntry.model_validate(entry.model_dump())
        if any(e.id == entry.id for e in self._entries):
            raise ValueError("Journal entry id already exists")
        if len(entry.lines) < 2 or any(line.account not in self.accounts for line in entry.lines):
            raise ValueError("Posting needs at least two lines on known accounts")
        debit = sum(line.amount_minor for line in entry.lines if line.side == "debit")
        credit = sum(line.amount_minor for line in entry.lines if line.side == "credit")
        if debit != credit:
            raise ValueError("Journal entry must balance")
        if entry.kind == "settlement":
            if entry.event_id is None or entry.corrects_entry_id is not None:
                raise ValueError("Settlement must reference an event, not a correction")
        else:
            original = next((e for e in self._entries if e.id == entry.corrects_entry_id), None)
            if (original is None or original.kind != "settlement"
                    or entry.instruction_id != original.instruction_id or entry.event_id is not None):
                raise ValueError("Compensation must reference an original settlement")
            if any(e.corrects_entry_id == original.id for e in self._entries):
                raise ValueError("Original entry already compensated")
            reverse = Counter((l["account"], l["side"], l["amount_minor"]) for l in reversed_lines(original))
            if line_signature(entry) != reverse:
                raise ValueError("Compensation must exactly reverse original lines")
        self._entries += (entry.model_copy(deep=True),)
        if correction_key:
            self._correction_keys[correction_key] = entry.id
        return entry.model_copy(deep=True)

    def append_batch(self, entries: list[tuple[JournalEntry, str]]) -> list[JournalEntry]:
        """Validate a whole correction batch before any real append."""
        trial = deepcopy(self)
        posted = [trial.append(entry, key) for entry, key in entries]
        self._entries += trial._entries[len(self._entries):]
        self._correction_keys.update(trial._correction_keys)
        return posted

    def balances(self) -> dict[str, int]:
        balances = {account: 0 for account in sorted(self.accounts)}
        for entry in self._entries:
            for line in entry.lines:
                balances[line.account] += line.amount_minor * (1 if line.side == "credit" else -1)
        return balances

    def serialize(self) -> bytes:
        return json.dumps([e.model_dump(mode="json") for e in self._entries],
                          sort_keys=True, separators=(",", ":")).encode()
