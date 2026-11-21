from datetime import timedelta

import pytest

from app.bank import Bank, BankError
from app.models import Alert, CustomerMessage


def make_alert(alert_id, *txns):
    return Alert(
        id=alert_id, txn_ids=[txn.id for txn in txns], severity="high",
        title="Review transfers", analyst_explanation="Customer review required.",
        customer_message=CustomerMessage(en="Was this you?", ar="هل أجريت هذه العملية؟"),
        actions=["confirm", "deny"], expires_at=txns[-1].ts + timedelta(minutes=5),
    )


def test_seed_history_and_reset_are_repeatable():
    bank = Bank()
    initial = bank.snapshot()
    history = bank.history
    baseline = bank.baseline

    assert initial.account.name == "Aisha Al Mansoori"
    assert initial.account.balance == initial.account.available == 520_000
    assert len({txn.ts.date() for txn in history}) == 90
    assert len(baseline.hour_histogram) == 24
    assert len(history) == sum(baseline.hour_histogram) == 180
    assert baseline.hour_histogram[13] > 0 and baseline.hour_histogram[2] == 0
    assert baseline.amount_mean > 0 and baseline.amount_std > 0
    assert "app_aisha" in bank.known_clients
    assert baseline.known_api_clients == {"api_aisha_bills"}
    assert bank.catalog[0].counterparty.iban in baseline.known_payees
    assert bank.catalog[0].device_id in baseline.known_devices
    assert not bank.transactions

    wire = bank.catalog[-1]
    bank.block(wire)
    bank.upsert_alert(make_alert("wire", wire))
    bank.resolve("wire", "deny")
    assert bank.reset() == initial
    assert not bank.transactions and not bank.alerts and not bank.resolutions
    assert bank.history == history and bank.baseline == baseline
    with pytest.raises(BankError) as exc:
        bank.unfreeze(wire.client_id)
    assert exc.value.status == 404
    assert bank.unfreeze("app_aisha").frozen_clients == []


def test_risk_window_counts_outgoing_attempts_of_each_status_and_candidate_once():
    bank = Bank()
    wire = bank.catalog[-1]

    def sample(txn_id, offset, amount, direction="out"):
        return wire.model_copy(update={
            "id": txn_id, "ts": wire.ts + timedelta(seconds=offset), "amount": amount,
            "direction": direction,
        })

    bank.post(sample("stale", -61, 500))
    bank.post(sample("posted", -60, 10))
    bank.hold(sample("held", -20, 15))
    bank.block(sample("blocked", -10, 25))
    bank.post(sample("inbound", -5, 75, "in"))
    bank.post(sample("future", 1, 100))
    bank.block(wire)

    context = bank.risk_context(wire)
    assert [txn.id for txn in context.recent_transactions] == ["posted", "held", "blocked", "inbound"]
    assert context.cumulative_drain == 450_050
    assert context.balance == bank.snapshot().account.balance
    assert wire.client_id not in bank.baseline.known_api_clients


def test_grouped_confirm_is_atomic_and_preserves_cents():
    bank = Bank()
    one = bank.catalog[1].model_copy(update={"amount": 0.17})
    two = bank.catalog[2].model_copy(update={"amount": 0.48, "client_id": "app_aisha"})
    bank.hold(one)
    bank.hold(two)
    bank.hold(two)
    bank.upsert_alert(make_alert("burst", one, two))
    bank.freeze(two.client_id)
    frozen = bank.snapshot()

    with pytest.raises(BankError) as exc:
        bank.resolve("burst", "confirm")
    assert exc.value.status == 409
    assert bank.snapshot() == frozen
    assert all(txn.status == "held" for txn in bank.transactions.values())

    bank.unfreeze(two.client_id)
    result = bank.resolve("burst", "confirm")
    assert bank.resolve("burst", "confirm") == result
    assert result.resolution == "confirmed"
    account = bank.snapshot().account
    assert account.balance == account.available == 519_999.35
    assert account.held == 0


def test_expiry_releases_holds_without_protection_or_unfreeze():
    bank = Bank()
    first, second, wire = bank.catalog[1:]
    bank.hold(first)
    bank.hold(second)
    bank.block(wire)
    burst_alert = make_alert("burst", first, second)
    wire_alert = make_alert("wire", wire)
    bank.upsert_alert(burst_alert)
    bank.upsert_alert(wire_alert)

    assert bank.expire_alerts(burst_alert.expires_at - timedelta(microseconds=1)) == []
    [expiry] = bank.expire_alerts(burst_alert.expires_at)
    assert (expiry.id, expiry.resolution, expiry.by) == ("burst", "expired", "auto")
    assert list(bank.alerts) == ["wire"]
    assert bank.transactions[first.id].status == bank.transactions[second.id].status == "blocked"
    [expiry] = bank.expire_alerts(wire_alert.expires_at)
    assert (expiry.id, expiry.resolution, expiry.by) == ("wire", "expired", "auto")
    assert bank.expire_alerts(wire_alert.expires_at) == []
    with pytest.raises(BankError) as exc:
        bank.resolve("wire", "deny")
    assert exc.value.status == 409
    assert bank.state.protected_amount == bank.state.account.held == 0
    assert bank.state.account.available == bank.state.account.balance == 520_000
    assert bank.state.frozen_clients == [wire.client_id]
