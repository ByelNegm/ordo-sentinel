from datetime import datetime, timedelta, timezone
from time import perf_counter

import pytest

from app.bank import Bank
from app.models import Counterparty, Risk, Txn
from app.policy import PolicyContext, decide
from app.risk import CustomerBaseline, RiskContext, score


NOW = datetime(2025, 11, 22, 13, tzinfo=timezone(timedelta(hours=4)))


def transaction(**updates):
    values = dict(
        id="candidate", ts=NOW, amount=100, currency="AED", direction="out",
        counterparty=Counterparty(name="Known payee", iban="AE001", country="AE",
                                  is_new=False, offshore=False),
        channel="app", client_id="known_client", device_id="known_device",
        risk=Risk(score=100, level="critical", factors=[]), decision="allow", status="posted",
    )
    values.update(updates)
    return Txn(**values)


def baseline():
    return [transaction(id=f"baseline_{day}", ts=NOW - timedelta(days=day),
                        amount=80 + (day % 5) * 10) for day in range(1, 91)]


def factors(txn, history=None, balance=520000, drain=0):
    result = score(txn, RiskContext(balance, drain, baseline() if history is None else history))
    assert result.score == min(100, sum(f.weight for f in result.factors))
    assert all(f.label and f.weight > 0 for f in result.factors)
    return {f.code: f.weight for f in result.factors}


def test_normal_and_empty_history_ignore_fixture_risk():
    for history in ([], baseline()):
        result = score(transaction(), RiskContext(520000, 0, history))
        assert result == Risk(score=0, level="low", factors=[])


def customer_baseline():
    histogram = [0] * 24
    histogram[2] = 90
    return CustomerBaseline(histogram, 100, 20, {"AE001"}, {"known_device"}, {"known_client"})


def test_populated_baseline_prefers_habits_over_conflicting_history():
    txn = transaction(ts=NOW.replace(hour=2), channel="api")
    txn.counterparty.is_new = True
    history = [transaction(id="old", ts=NOW - timedelta(days=1), amount=1,
                           device_id="other", client_id="other")]
    history[0].counterparty.iban = "other"
    ctx = RiskContext(520000, recent_transactions=history, baseline=customer_baseline())
    assert score(txn, ctx) == Risk(score=0, level="low", factors=[])


def test_populated_baseline_deviations_fire_without_history():
    txn = transaction(amount=10000, channel="api", device_id="new", client_id="new")
    txn.counterparty.is_new = True
    txn.counterparty.iban = "new"
    ctx = RiskContext(520000, baseline=customer_baseline())
    result = {f.code: f.weight for f in score(txn, ctx).factors}
    assert result == {"AMOUNT_ZSCORE": 25, "UNUSUAL_HOUR": 18, "NEW_PAYEE": 16,
                      "NEW_API_CLIENT": 10, "NEW_DEVICE": 8}


def test_partial_baseline_falls_back_per_field():
    txn = transaction(channel="api")
    ctx = RiskContext(520000, recent_transactions=baseline(),
                      baseline=CustomerBaseline(known_api_clients={"known_client"}))
    assert score(txn, ctx).score == 0


def test_context_defaults_are_independent_and_positional_calls_still_work():
    first, second = RiskContext(), RiskContext()
    first.baseline.hour_histogram[2] = 1
    first.baseline.known_payees.add("AE001")
    first.baseline.known_devices.add("device")
    first.baseline.known_api_clients.add("client")
    first.recent_transactions.append(transaction())
    assert second.baseline == CustomerBaseline()
    assert second.balance == second.cumulative_drain == 0
    assert second.recent_transactions == []
    assert RiskContext(520000, 3000, []).baseline == CustomerBaseline()


@pytest.mark.parametrize("values", [
    {"hour_histogram": [0] * 23}, {"hour_histogram": [-1] + [0] * 23},
    {"hour_histogram": [float("nan")] + [0] * 23},
    {"amount_mean": -1}, {"amount_std": float("inf")},
])
def test_invalid_baseline(values):
    with pytest.raises(ValueError):
        CustomerBaseline(**values)


def test_cold_start_overnight_api_scores_and_levels():
    bank = Bank()
    first, second = bank.catalog[1:3]
    assert score(first, RiskContext(520000)).score == 52
    assert score(first, RiskContext(520000)).level == "medium"
    result = score(second, RiskContext(520000, 3000, [first]))
    assert result.score == 70 and result.level == "high"


@pytest.mark.parametrize("amount,weight", [(100, None), (200, 5), (10000, 25)])
def test_amount_zscore(amount, weight):
    assert factors(transaction(amount=amount)).get("AMOUNT_ZSCORE") == weight


def test_constant_and_zero_baselines():
    for amount in (0, 100):
        history = [transaction(id="old", ts=NOW - timedelta(days=1), amount=amount)]
        assert "AMOUNT_ZSCORE" not in factors(transaction(amount=amount), history)
        assert factors(transaction(amount=10000), history)["AMOUNT_ZSCORE"] == 25


def test_baseline_excludes_stale_future_self_incoming_and_unapproved():
    txn = transaction(amount=10000)
    history = [transaction(id="stale", ts=NOW - timedelta(days=90, seconds=1)),
               transaction(id="future", ts=NOW + timedelta(seconds=1)),
               transaction(id=txn.id),
               transaction(id="credit", direction="in"),
               transaction(id="held", status="held", decision="hold"),
               transaction(id="blocked", status="blocked", decision="freeze")]
    assert "AMOUNT_ZSCORE" not in factors(txn, history)
    assert "AMOUNT_ZSCORE" in factors(txn, [transaction(id="edge", ts=NOW - timedelta(days=90))])


@pytest.mark.parametrize("hour,unusual", [(2, True), (10, True), (11, False), (13, False), (15, False), (16, True)])
def test_customer_hour_habit(hour, unusual):
    assert ("UNUSUAL_HOUR" in factors(transaction(ts=NOW.replace(hour=hour)))) == unusual


def test_hour_habit_wraps_midnight_and_normalizes_timezone():
    history = [transaction(id="night", ts=(NOW - timedelta(days=1)).replace(hour=23))]
    assert "UNUSUAL_HOUR" not in factors(transaction(ts=NOW.replace(hour=1)), history)
    equivalent = [t.model_copy(update={"ts": t.ts.astimezone(timezone.utc)}) for t in baseline()]
    assert "UNUSUAL_HOUR" not in factors(transaction(), equivalent)


@pytest.mark.parametrize("seconds,active", [(0, True), (1, True), (60, True), (61, False), (-1, False)])
def test_velocity_window_includes_held_and_blocked(seconds, active):
    history = [transaction(id="attempt", ts=NOW - timedelta(seconds=seconds),
                           status="blocked", decision="freeze")]
    assert ("VELOCITY" in factors(transaction(), history)) == active


def test_velocity_excludes_self_and_credits_and_deduplicates():
    assert "VELOCITY" not in factors(transaction(), [transaction(), transaction(id="credit", direction="in")])
    old = transaction(id="old", ts=NOW - timedelta(seconds=1))
    assert factors(transaction(), [old, old])["VELOCITY"] == 18


def test_new_payee_uses_customer_history():
    payee = transaction().counterparty.model_copy(update={"is_new": True})
    assert "NEW_PAYEE" not in factors(transaction(counterparty=payee))
    assert factors(transaction(counterparty=payee), [])["NEW_PAYEE"] == 16
    payee.iban = "AE002"
    assert factors(transaction(counterparty=payee))["NEW_PAYEE"] == 16


def test_new_device_and_api_client():
    assert "NEW_DEVICE" not in factors(transaction(channel="api"))
    assert "NEW_API_CLIENT" not in factors(transaction(channel="api"))
    result = factors(transaction(channel="api", client_id="new", device_id="new"))
    assert result["NEW_API_CLIENT"] == 10 and result["NEW_DEVICE"] == 8
    assert "NEW_API_CLIENT" not in factors(transaction(client_id="new"))
    assert factors(transaction(device_id="new"))["NEW_DEVICE"] == 8
    held = transaction(id="held", client_id="new", device_id="new", status="held", decision="hold")
    assert "NEW_API_CLIENT" in factors(transaction(channel="api", client_id="new"), [held])


@pytest.mark.parametrize("country,offshore,code,weight", [
    ("AE", False, None, None), ("GB", False, "CROSS_BORDER", 10),
    ("SC", False, "OFFSHORE", 15), ("AE", True, "OFFSHORE", 15),
])
def test_destination_factors(country, offshore, code, weight):
    payee = transaction().counterparty.model_copy(update={"country": country, "offshore": offshore})
    result = factors(transaction(counterparty=payee))
    assert result == ({code: weight} if code else {})


def test_home_country_is_customer_specific():
    txn = transaction()
    txn.counterparty.country = "GB"
    history = baseline()
    for t in history:
        t.counterparty.country = "GB"
    assert "CROSS_BORDER" not in factors(txn, history)
    txn.counterparty.country = "AE"
    assert factors(txn, history)["CROSS_BORDER"] == 10


@pytest.mark.parametrize("drain,weight", [(0, None), (52000, None), (52000.01, 7),
                                         (156000, 7), (156000.01, 14)])
def test_cumulative_drain(drain, weight):
    assert factors(transaction(), drain=drain).get("BALANCE_DRAIN") == weight


def test_zero_balance_and_incoming():
    assert factors(transaction(), balance=0, drain=1)["BALANCE_DRAIN"] == 14
    assert factors(transaction(), balance=0) == {}
    assert score(transaction(direction="in"), RiskContext(0, 1)).score == 0


@pytest.mark.parametrize("field", ["balance", "cumulative_drain"])
@pytest.mark.parametrize("value", [-1, float("inf"), float("nan")])
def test_invalid_context(field, value):
    ctx = RiskContext(520000)
    setattr(ctx, field, value)
    with pytest.raises(ValueError, match="finite and nonnegative"):
        score(transaction(), ctx)


def test_deterministic_nonmutating_and_clamped():
    txn = Bank().catalog[-1]
    ctx = RiskContext(520000, 453000, baseline())
    before = txn.model_dump()
    history_before = [t.model_dump() for t in ctx.recent_transactions]
    result = score(txn, ctx)
    assert result == score(txn, ctx)
    assert result.score == 100 and result.level == "critical"
    assert txn.model_dump() == before
    assert [t.model_dump() for t in ctx.recent_transactions] == history_before


def test_average_risk_and_policy_latency_under_five_ms():
    history = [transaction(id=f"history_{i}", ts=NOW - timedelta(hours=i + 1),
                           amount=80 + i % 50) for i in range(1000)]
    txn = transaction(amount=450000, channel="api")
    risk_ctx = RiskContext(520000, 453000, history)
    policy_ctx = PolicyContext(520000, 453000)
    start = perf_counter()
    for _ in range(500):
        assert decide(score(txn, risk_ctx), policy_ctx) == "freeze"
    average_ms = (perf_counter() - start) * 1000 / 500
    assert average_ms < 5, f"Average risk+policy latency: {average_ms:.3f}ms"
