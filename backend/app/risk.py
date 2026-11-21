"""Builder A: replace fixture risk with deterministic rules/customer statistics."""
from dataclasses import dataclass, field

from .models import Risk, Txn


@dataclass
class RiskContext:
    balance: float
    cumulative_drain: float = 0
    recent_transactions: list[Txn] = field(default_factory=list)


def score(txn: Txn, ctx: RiskContext) -> Risk:
    """Return 0–100 score/reasons; skeleton preserves the fixture's scored risk."""
    return txn.risk.model_copy(deep=True)
