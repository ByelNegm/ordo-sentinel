import re

import pytest

from app.bank import Bank, PURPOSES, canonical_hash
from app.settlement import SettlementService
from conftest import awaiting_incident


def test_deterministic_uae_identities_references_and_purpose_amounts():
    banks = []
    for _ in range(2):
        bank = Bank()
        bank.seed(SettlementService(bank))
        banks.append(bank)
        ibans = [a.iban for a in bank.account_snapshots()]
        assert len(set(ibans)) == 12
        for iban in ibans:
            assert re.fullmatch(r"AE\d{21}", iban)
            assert int(iban[4:] + "1014" + iban[2:4]) % 97 == 1
        references = set()
        for payment in bank.instructions.values():
            assert re.fullmatch(r"FT26325[A-Z0-9]{5}", payment.reference)
            references.add(payment.reference)
            label, low, high = PURPOSES[payment.purpose]
            assert low <= payment.amount_minor <= high
            assert payment.amount_minor % 100 != 0
            assert payment.purpose_label == label
            assert payment.debtor_name == bank.accounts[payment.debtor].name
            assert payment.creditor_name == bank.accounts[payment.creditor].name
            assert payment.expected_hash == canonical_hash(payment.id, payment.debtor, payment.creditor, payment.amount_minor)
        assert len(references) == 100
    assert banks[0].account_snapshots() == banks[1].account_snapshots()
    assert banks[0].instructions == banks[1].instructions
    assert banks[0].ledger.serialize() == banks[1].ledger.serialize()


@pytest.mark.parametrize("kind,phrase", [
    ("duplicate", "settled twice"), ("missing", "never settled"), ("tamper", "instead of"),
])
def test_incident_summary_uses_real_payment_and_account_display_data(client, kind, phrase):
    client.post("/api/faults/" + kind)
    client.post("/api/traffic/start")
    incident = awaiting_incident(client)
    client.post("/api/traffic/stop")
    payments = client.get("/api/payments?limit=500").json()
    payment = next(p for p in payments if p["id"] == incident["affected_payments"][0])
    for field in ("reference", "debtor_name", "creditor_name"):
        assert payment[field] in incident["summary_text"]
        assert payment[field] in incident["root_cause"]["summary"]
    assert payment["purpose_label"] in incident["summary_text"]
    assert phrase in incident["summary_text"]
    if kind == "tamper":
        amount = payment["amount_minor"] + 100
        assert f"AED {amount // 100:,}.{amount % 100:02}" in incident["summary_text"]


def test_metadata_invalid_purpose_and_legacy_model_defaults():
    bank = Bank()
    with pytest.raises(ValueError, match="purpose"):
        bank.create_instruction("customer-01", "customer-02", 12345, purpose="UNKNOWN")
