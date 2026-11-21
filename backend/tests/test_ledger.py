import hashlib

import pytest
from pydantic import ValidationError

from app.bank import Bank, canonical_hash
from app.integrity import inspect
from app.ledger import Ledger, reversed_lines
from app.models import JournalEntry, PostingLine, utcnow
from app.settlement import SettlementService


def entry(identifier="entry-1", amount=12345):
    return JournalEntry(
        id=identifier, kind="settlement", instruction_id="payment-1", event_id="event-1",
        corrects_entry_id=None, lines=[
            PostingLine(account="a", side="debit", amount_minor=amount),
            PostingLine(account="b", side="credit", amount_minor=amount)],
        ts=utcnow(), actor="settlement-svc",
    )


def test_double_entry_derived_balances_and_append_only_snapshots():
    ledger = Ledger(["a", "b"])
    original = entry()
    ledger.append(original)
    before = ledger.serialize()
    assert ledger.balances() == {"a": -12345, "b": 12345}
    original.lines[0].amount_minor = 1
    detached = ledger.entries[0]
    detached.lines.append(PostingLine(account="a", side="credit", amount_minor=1))
    assert ledger.serialize() == before
    assert not hasattr(ledger, "delete") and not hasattr(ledger, "update")
    with pytest.raises(ValueError):
        ledger.append(entry())
    assert ledger.serialize() == before


@pytest.mark.parametrize("amount", [1.2, 100.0, True, "100", 0, -1])
def test_money_rejects_floats_strings_booleans_and_nonpositive(amount):
    with pytest.raises(ValidationError):
        entry(amount=amount)


def test_invalid_postings_and_compensation_batch_are_atomic():
    ledger = Ledger(["a", "b"])
    ledger.append(entry())
    before = ledger.serialize()
    for invalid in (
        entry("unbalanced").model_copy(update={"lines": [
            PostingLine(account="a", side="debit", amount_minor=5),
            PostingLine(account="b", side="credit", amount_minor=4)]}),
        entry("unknown").model_copy(update={"lines": [
            PostingLine(account="missing", side="debit", amount_minor=12345),
            PostingLine(account="b", side="credit", amount_minor=12345)]}),
    ):
        with pytest.raises(ValueError):
            ledger.append(invalid)
        assert ledger.serialize() == before
    correction = entry("correction-1").model_copy(update={
        "kind": "compensation", "event_id": None, "corrects_entry_id": "entry-1",
        "lines": [PostingLine.model_validate(line) for line in reversed_lines(entry())],
        "actor": "ops.lead@bank",
    })
    bad = correction.model_copy(update={"id": "bad", "corrects_entry_id": "unknown"})
    with pytest.raises(ValueError):
        ledger.append_batch([(correction, "incident:entry-1"), (bad, "incident:unknown")])
    assert ledger.serialize() == before
    ledger.append_batch([(correction, "incident:entry-1")])
    assert ledger.balances() == {"a": 0, "b": 0}
    after = ledger.serialize()
    ledger.append_batch([(correction, "incident:entry-1")])
    assert ledger.serialize() == after
    with pytest.raises(ValueError):
        ledger.append(correction.model_copy(update={"id": "second-correction"}))


def test_deterministic_seed_and_independent_instruction_hash():
    banks = []
    for _ in range(2):
        bank = Bank()
        service = SettlementService(bank)
        bank.seed(service)
        banks.append(bank)
        report = inspect(bank.ledger, bank.instructions, bank.events)
        assert report.status == "healthy" and len(report.checks) == 7
        assert all(c.passed for c in report.checks)
        assert len(bank.accounts) == 12
        assert len(bank.instructions) == len(bank.events) == len(bank.ledger.entries) == 100
        assert all(i.status == "settled" and i.settlement_count == 1 for i in bank.instructions.values())
        assert all(type(value) is int for value in bank.ledger.balances().values())
    assert banks[0].ledger.serialize() == banks[1].ledger.serialize()
    sample = banks[0].instructions["payment-000001"]
    canonical = f"{sample.id}|{sample.debtor}|{sample.creditor}|{sample.amount_minor}"
    assert sample.expected_hash == hashlib.sha256(canonical.encode()).hexdigest()
    assert sample.expected_hash == canonical_hash(sample.id, sample.debtor, sample.creditor, sample.amount_minor)


def test_instruction_keys_are_unique_and_settlement_retry_is_normally_idempotent():
    bank = Bank()
    instruction = bank.create_instruction("customer-01", "customer-02", 500, "same-key")
    assert bank.create_instruction("customer-01", "customer-02", 500, "same-key") is instruction
    with pytest.raises(ValueError):
        bank.create_instruction("customer-01", "customer-02", 501, "same-key")
    service = SettlementService(bank)
    service.enqueue(instruction)
    service.process_queue()
    before = bank.ledger.serialize()
    service.enqueue(instruction)
    service.process_queue()
    assert bank.ledger.serialize() == before
    assert len(bank.events) == 1


def test_real_duplicate_has_two_balanced_effects_and_only_two_failing_checks():
    bank = Bank()
    service = SettlementService(bank)
    bank.seed(service)
    payment = bank.next_payment()
    service.inject("duplicate")
    service.enqueue(payment)
    observations = []
    service.process_queue(lambda event, entry: observations.append(
        inspect(bank.ledger, bank.instructions, bank.events)))
    assert observations[0].status == "healthy"
    report = observations[1]
    assert {c.name for c in report.checks if not c.passed} == {
        "single_financial_effect", "ledger_matches_expected"}
    assert next(c for c in report.checks if c.name == "ledger_balanced").passed
    events = [e for e in bank.events if e.instruction_id == payment.id]
    entries = [e for e in bank.ledger.entries if e.instruction_id == payment.id]
    assert len(events) == len(entries) == payment.settlement_count == 2
    assert events[0].id != events[1].id
    assert events[0].payload_hash == events[1].payload_hash == payment.expected_hash
    assert entries[0].event_id != entries[1].event_id
    assert all(e.actor == "settlement-svc" for e in entries)
    assert service.service.fault is None
