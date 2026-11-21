"""Seven pure evidence checks. A balanced ledger is not proof of a correct ledger."""
from collections import Counter
from collections.abc import Mapping, Sequence

from .bank import canonical_hash
from .ledger import Ledger
from .models import Check, IntegrityReport, PaymentInstruction, SettlementEvent, utcnow

Instructions = Mapping[str, PaymentInstruction]


def _check(name: str, passed: bool, detail: str) -> Check:
    return Check(name=name, **{"pass": passed}, detail=detail)


def ledger_balanced(ledger: Ledger) -> Check:
    entries = ledger.entries
    passed = all(sum(l.amount_minor for l in e.lines if l.side == "debit") ==
                 sum(l.amount_minor for l in e.lines if l.side == "credit") for e in entries)
    return _check("ledger_balanced", passed, f"{len(entries)} entries checked for equal debits/credits")


def unique_idempotency_keys(instructions: Instructions) -> Check:
    keys = [i.idempotency_key for i in instructions.values()]
    return _check("unique_idempotency_keys", len(keys) == len(set(keys)),
                  f"{len(keys)} independently stored instruction keys")


def settlements_map_to_instructions(ledger: Ledger, instructions: Instructions,
                                   events: Sequence[SettlementEvent]) -> Check:
    event_map = {e.id: e for e in events}
    passed = len(event_map) == len(events) and all(e.instruction_id in instructions for e in events)
    passed = passed and all(
        e.instruction_id in instructions and
        (e.kind == "compensation" or
         (e.event_id in event_map and event_map[e.event_id].instruction_id == e.instruction_id))
        for e in ledger.entries
    )
    return _check("settlements_map_to_instructions", passed,
                  f"{len(events)} events mapped to independent instructions and postings")


def extra_postings(ledger: Ledger) -> list:
    """Uncorrected settlement effects after the first, grouped by instruction."""
    entries = ledger.entries
    corrected = {e.corrects_entry_id for e in entries if e.kind == "compensation"}
    seen = Counter()
    extras = []
    for entry in entries:
        if entry.kind == "settlement" and entry.id not in corrected:
            seen[entry.instruction_id] += 1
            if seen[entry.instruction_id] > 1:
                extras.append(entry)
    return extras


def single_financial_effect(ledger: Ledger, instructions: Instructions) -> Check:
    entries = ledger.entries
    corrected = {e.corrects_entry_id for e in entries if e.kind == "compensation"}
    counts = Counter(e.instruction_id for e in entries
                     if e.kind == "settlement" and e.id not in corrected)
    wrong = [i.id for i in instructions.values()
             if counts[i.id] != (0 if i.status in {"accepted", "held"} else 1)]
    passed = not wrong and not (set(counts) - set(instructions))
    return _check("single_financial_effect", passed,
                  "Exactly one net ledger effect per settled instruction" if passed else
                  "Wrong net effect count: " + ", ".join(wrong))


def expected_balances(ledger: Ledger, instructions: Instructions) -> dict[str, int]:
    balances = {account: 0 for account in sorted(ledger.accounts)}
    for instruction in instructions.values():
        if instruction.status not in {"accepted", "held"}:
            balances[instruction.debtor] -= instruction.amount_minor
            balances[instruction.creditor] += instruction.amount_minor
    return balances


def ledger_matches_expected(ledger: Ledger, instructions: Instructions) -> Check:
    actual, expected = ledger.balances(), expected_balances(ledger, instructions)
    wrong = [account for account in expected if actual[account] != expected[account]]
    return _check("ledger_matches_expected", not wrong,
                  "Balances match independent instructions" if not wrong else
                  "Balance mismatch: " + ", ".join(wrong))


def no_missing_settlements(instructions: Instructions, events: Sequence[SettlementEvent]) -> Check:
    settled = {e.instruction_id for e in events}
    missing = [i.id for i in instructions.values()
               if i.status not in {"accepted", "held"} and i.id not in settled]
    return _check("no_missing_settlements", not missing,
                  "No due instructions lack settlement evidence" if not missing else ", ".join(missing))


def event_integrity(instructions: Instructions, events: Sequence[SettlementEvent]) -> Check:
    invalid = []
    for event in events:
        instruction = instructions.get(event.instruction_id)
        if (instruction is None or event.payload_hash != instruction.expected_hash
                or event.payload_hash != canonical_hash(event.instruction_id, event.debtor,
                                                         event.creditor, event.amount_minor)
                or instruction.expected_hash != canonical_hash(instruction.id, instruction.debtor,
                                                               instruction.creditor, instruction.amount_minor)):
            invalid.append(event.id)
    return _check("event_integrity", not invalid,
                  "Event payload hashes match independent intent" if not invalid else ", ".join(invalid))


def inspect(ledger: Ledger, instructions: Instructions,
            events: Sequence[SettlementEvent]) -> IntegrityReport:
    checks = [
        ledger_balanced(ledger),
        unique_idempotency_keys(instructions),
        settlements_map_to_instructions(ledger, instructions, events),
        single_financial_effect(ledger, instructions),
        ledger_matches_expected(ledger, instructions),
        no_missing_settlements(instructions, events),
        event_integrity(instructions, events),
    ]
    return IntegrityReport(status="healthy" if all(c.passed for c in checks) else "violated",
                           checks=checks, ts=utcnow())
