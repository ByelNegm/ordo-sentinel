"""Builder A: deterministic money policy; never call an LLM here."""
from dataclasses import dataclass
from math import isfinite

from .models import Decision, Risk


@dataclass
class PolicyContext:
    balance: float
    cumulative_drain: float
    client_frozen: bool = False


def decide(risk: Risk, ctx: PolicyContext) -> Decision:
    """Hold requests step-up; freeze targets the originating client, never the account.

    cumulative_drain includes the candidate once, in AED.
    """
    if any(not isfinite(v) or v < 0 for v in (ctx.balance, ctx.cumulative_drain)):
        raise ValueError("Balance and cumulative drain must be finite and nonnegative")
    if ctx.client_frozen or risk.score > 75 or ctx.cumulative_drain > ctx.balance * 0.30:
        return "freeze"
    return "hold" if risk.score >= 40 else "allow"
