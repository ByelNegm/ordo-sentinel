import asyncio

import pytest

from app.bank import Bank
from app.bus import EventBus
from app.models import Risk
from app.policy import PolicyContext, decide
from app.scenario import ScenarioRunner


@pytest.mark.parametrize("value,expected", [(0, "allow"), (39, "allow"), (40, "hold"),
                                           (59, "hold"), (60, "hold"), (75, "hold"),
                                           (76, "freeze"), (100, "freeze")])
def test_score_thresholds(value, expected):
    assert decide(Risk(score=value, level="low", factors=[]), PolicyContext(520000, 0)) == expected


@pytest.mark.parametrize("balance,drain,expected", [
    (520000, 156000, "allow"), (520000, 156000.01, "freeze"),
    (100, 30, "allow"), (100, 30.01, "freeze"), (0, 0, "allow"), (0, 0.01, "freeze"),
])
def test_drain_threshold_and_zero_balance(balance, drain, expected):
    assert decide(Risk(score=0, level="low", factors=[]), PolicyContext(balance, drain)) == expected


def test_frozen_client_cannot_post_even_at_zero_risk():
    assert decide(Risk(score=0, level="low", factors=[]), PolicyContext(520000, 0, True)) == "freeze"


@pytest.mark.parametrize("field", ["balance", "cumulative_drain"])
@pytest.mark.parametrize("value", [-1, float("inf"), float("nan")])
def test_invalid_context(field, value):
    ctx = PolicyContext(520000, 0)
    setattr(ctx, field, value)
    with pytest.raises(ValueError, match="finite and nonnegative"):
        decide(Risk(score=0, level="low", factors=[]), ctx)


@pytest.mark.parametrize("normal_first", [False, True])
def test_scripted_scenario_scores_instructions_and_freezes_only_client(normal_first):
    async def run():
        bank = Bank()
        runner = ScenarioRunner(bank, EventBus(), pace=0)
        if normal_first:
            await runner._run("normal")
            assert sum(t.amount for t in bank.transactions.values()) == 85
            assert all(t.decision == "allow" for t in bank.transactions.values())
        await runner._run("drain")
        first = bank.transactions["txn_drain_001"]
        second = bank.transactions["txn_drain_002"]
        wire = bank.transactions["txn_wire"]
        assert first.decision == second.decision == "hold"
        assert first.status == second.status == "held"
        assert 40 <= first.risk.score <= second.risk.score <= 75
        assert wire.decision == "freeze" and wire.status == "blocked"
        assert wire.risk.score > 75
        assert {"OFFSHORE", "BALANCE_DRAIN", "VELOCITY"} <= {f.code for f in wire.risk.factors}
        assert bank.state.frozen_clients == [wire.client_id]
        assert bank.state.account.balance == (519915 if normal_first else 520000)
        assert bank.state.account.held == 3000
        bank.resolve("alert_wire", "deny")
        assert bank.state.protected_amount == 450000
        bank.post(bank.catalog[0].model_copy(update={"id": "unrelated_card"}, deep=True))
        assert bank.transactions["unrelated_card"].status == "posted"

    asyncio.run(run())
