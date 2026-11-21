"""Deterministic rules over the customer's preceding 90 days of activity."""
from collections import Counter
from dataclasses import dataclass, field
from math import isfinite, sqrt

from .models import Factor, Risk, Txn


BASELINE_SECONDS = 90 * 24 * 60 * 60
BURST_SECONDS = 60
OFFSHORE_COUNTRIES = frozenset({"SC", "KY", "VG", "BM", "BS", "PA", "JE", "GG", "IM", "MU"})


@dataclass
class CustomerBaseline:
    hour_histogram: list[int] = field(default_factory=lambda: [0] * 24)
    amount_mean: float = 0
    amount_std: float = 0
    known_payees: set[str] = field(default_factory=set)
    known_devices: set[str] = field(default_factory=set)
    known_api_clients: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if len(self.hour_histogram) != 24 or any(
            not isfinite(v) or v < 0 for v in self.hour_histogram
        ):
            raise ValueError("Hour histogram must contain 24 finite nonnegative values")
        if any(not isfinite(v) or v < 0 for v in (self.amount_mean, self.amount_std)):
            raise ValueError("Amount statistics must be finite and nonnegative")


@dataclass
class RiskContext:
    balance: float = 0
    cumulative_drain: float = 0
    recent_transactions: list[Txn] = field(default_factory=list)
    baseline: CustomerBaseline = field(default_factory=CustomerBaseline)


def score(txn: Txn, ctx: RiskContext) -> Risk:
    """Prefer populated baseline fields, otherwise derive from posted history (incl. confirmed holds).

    Held/blocked attempts only affect velocity.
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
        if previous.status == "posted":
            history.append(previous)

    factors = []

    def add(code: str, label: str, weight: int) -> None:
        factors.append(Factor(code=code, label=label, weight=weight))

    baseline = ctx.baseline
    has_amount_stats = baseline.amount_mean > 0 or baseline.amount_std > 0
    if has_amount_stats or history:
        mean = baseline.amount_mean if has_amount_stats else sum(t.amount for t in history) / len(history)
        deviation = (baseline.amount_std if has_amount_stats else
                     sqrt(sum((t.amount - mean) ** 2 for t in history) / len(history)))
        # A 10%/AED 1 floor keeps a constant or tiny baseline well-defined.
        z_score = (txn.amount - mean) / max(deviation, mean * 0.10, 1.0)
        if z_score >= 3:
            # Tiny posted purchases should not alone escalate a small transfer to freeze.
            add("AMOUNT_ZSCORE", "Amount exceeds the 90-day baseline by at least 3 standard deviations",
                25 if txn.amount > ctx.balance * 0.01 else 5)

    hours = ({hour for hour, count in enumerate(baseline.hour_histogram) if count > 0}
             if any(baseline.hour_histogram) else
             {t.ts.astimezone(txn.ts.tzinfo).hour for t in history})
    unusual_hour = (all(min((txn.ts.hour - h) % 24, (h - txn.ts.hour) % 24) > 2 for h in hours)
                    if hours else txn.ts.hour < 6 or txn.ts.hour >= 23)
    if unusual_hour:
        add("UNUSUAL_HOUR", "Outside usual customer hours", 18)
    if burst_count:
        add("VELOCITY", "Multiple outgoing instructions within 60 seconds", 18)
    known_payees = baseline.known_payees or {t.counterparty.iban for t in history}
    if txn.counterparty.is_new and txn.counterparty.iban not in known_payees:
        add("NEW_PAYEE", "First payment to payee", 16)
    known_clients = baseline.known_api_clients or {t.client_id for t in history}
    if txn.channel == "api" and txn.client_id not in known_clients:
        add("NEW_API_CLIENT", "Unfamiliar API client", 10)
    known_devices = baseline.known_devices or {t.device_id for t in history}
    if txn.device_id not in known_devices and (known_devices or txn.channel == "api"):
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
