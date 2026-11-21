"""Deterministic rules over the customer's preceding 90 days of activity."""
from collections import Counter
from dataclasses import dataclass, field
from math import isfinite, sqrt

from .models import Factor, Risk, Txn


BASELINE_SECONDS = 90 * 24 * 60 * 60
BURST_SECONDS = 60
OFFSHORE_COUNTRIES = frozenset({"SC", "KY", "VG", "BM", "BS", "PA", "JE", "GG", "IM", "MU"})


@dataclass
class RiskContext:
    balance: float
    cumulative_drain: float = 0
    recent_transactions: list[Txn] = field(default_factory=list)


def score(txn: Txn, ctx: RiskContext) -> Risk:
    """Use posted/allowed history as baseline; held/blocked attempts only affect velocity.

    Empty history uses a daytime (06–23), domestic-AE cold start, not synthetic
    customer statistics. Cumulative drain includes this candidate once, in AED.
    """
    if any(not isfinite(v) or v < 0 for v in (ctx.balance, ctx.cumulative_drain)):
        raise ValueError("Balance and cumulative drain must be finite and nonnegative")
    if txn.direction == "in":
        return Risk(score=0, level="low", factors=[])

    now = txn.ts.timestamp()
    history = []
    burst_count = 0
    seen = {txn.id}
    for previous in ctx.recent_transactions:
        age = now - previous.ts.timestamp()
        if previous.id in seen or previous.direction != "out" or not 0 <= age <= BASELINE_SECONDS:
            continue
        seen.add(previous.id)
        if age <= BURST_SECONDS:
            burst_count += 1
        if previous.status == "posted" and previous.decision == "allow":
            history.append(previous)

    factors = []

    def add(code: str, label: str, weight: int) -> None:
        factors.append(Factor(code=code, label=label, weight=weight))

    if history:
        mean = sum(t.amount for t in history) / len(history)
        deviation = sqrt(sum((t.amount - mean) ** 2 for t in history) / len(history))
        # A 10%/AED 1 floor keeps a constant or tiny baseline well-defined.
        z_score = (txn.amount - mean) / max(deviation, mean * 0.10, 1.0)
        if z_score >= 3:
            # Tiny posted purchases should not alone escalate a small transfer to freeze.
            add("AMOUNT_ZSCORE", "Amount exceeds the 90-day baseline by at least 3 standard deviations",
                25 if txn.amount > ctx.balance * 0.01 else 5)

    hours = {t.ts.astimezone(txn.ts.tzinfo).hour for t in history}
    unusual_hour = (all(min((txn.ts.hour - h) % 24, (h - txn.ts.hour) % 24) > 2 for h in hours)
                    if hours else txn.ts.hour < 6 or txn.ts.hour >= 23)
    if unusual_hour:
        add("UNUSUAL_HOUR", "Outside usual customer hours", 18)
    if burst_count:
        add("VELOCITY", "Multiple outgoing instructions within 60 seconds", 18)
    known_payees = {t.counterparty.iban for t in history}
    if txn.counterparty.is_new and txn.counterparty.iban not in known_payees:
        add("NEW_PAYEE", "First payment to payee", 16)
    if txn.channel == "api" and txn.client_id not in {t.client_id for t in history}:
        add("NEW_API_CLIENT", "Unfamiliar API client", 10)
    if txn.device_id not in {t.device_id for t in history} and (history or txn.channel == "api"):
        add("NEW_DEVICE", "Unfamiliar device", 8)

    country_counts = Counter(t.counterparty.country for t in history)
    home_country = min(country_counts, key=lambda c: (-country_counts[c], c)) if country_counts else "AE"
    if txn.counterparty.offshore or txn.counterparty.country in OFFSHORE_COUNTRIES:
        add("OFFSHORE", "Demo offshore destination", 15)
    elif txn.counterparty.country != home_country:
        add("CROSS_BORDER", "Destination outside usual customer country", 10)
    if ctx.cumulative_drain > ctx.balance * 0.30:
        add("BALANCE_DRAIN", "Over 30% of balance targeted", 14)
    elif ctx.cumulative_drain > ctx.balance * 0.10:
        add("BALANCE_DRAIN", "Over 10% of balance targeted", 7)

    total = min(100, int(sum(f.weight for f in factors)))
    level = "critical" if total > 75 else "high" if total >= 60 else "medium" if total >= 40 else "low"
    return Risk(score=total, level=level, factors=factors)
