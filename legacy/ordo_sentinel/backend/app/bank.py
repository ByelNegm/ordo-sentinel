"""Process-local bank. Mutations are synchronous on the app event loop."""

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from random import Random
from statistics import mean, pstdev

from .models import Account, AccountUpdated, Alert, AlertResolved, Counterparty, Risk, State, Txn
from .risk import CustomerBaseline, RiskContext

# main.py uses this to serve the development fixtures.
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
UAE = timezone(timedelta(hours=4))
NORMAL_START = datetime(2025, 11, 21, 13, tzinfo=UAE)
DRAIN_START = datetime(2025, 11, 22, 2, tzinfo=UAE)
RECENT_WINDOW = timedelta(minutes=1)

GROCER = Counterparty(name="Neighborhood Grocer", iban="AE000000000000000000001",
                       country="AE", is_new=False, offshore=False)
CAFE = Counterparty(name="Corner Café", iban="AE000000000000000000005",
                     country="AE", is_new=False, offshore=False)
UTILITY = Counterparty(name="City Utilities", iban="AE000000000000000000006",
                        country="AE", is_new=False, offshore=False)


def _seed_history() -> tuple[Txn, ...]:
    rng = Random(91)
    history = []
    for days_ago in range(90, 0, -1):
        date = NORMAL_START - timedelta(days=days_ago)
        for hour in sorted(rng.sample(range(8, 22), 2)):
            payee = rng.choice((GROCER, CAFE, UTILITY))
            amount = rng.randrange(15, 350)
            channel, client_id = "card", "card_001"
            if payee == UTILITY:
                amount = rng.randrange(350, 1250)
                channel, client_id = ("api", "api_aisha_bills") if days_ago % 3 == 0 else ("app", "app_aisha")
            history.append(Txn(
                id=f"hist_{len(history) + 1:03}",
                ts=date.replace(hour=hour, minute=rng.randrange(60)),
                amount=amount, currency="AED", direction="out", counterparty=payee.model_copy(),
                channel=channel, client_id=client_id,
                device_id="device_known", risk=Risk(score=0, level="low", factors=[]),
                decision="allow", status="posted",
            ))
    return tuple(history)


def _catalog() -> list[Txn]:
    script = [
        Txn(id="txn_normal", ts=NORMAL_START, amount=85, currency="AED",
            direction="out", counterparty=GROCER.model_copy(),
            channel="card", client_id="card_001", device_id="device_known",
            risk=Risk(score=0, level="low", factors=[]), decision="allow", status="posted")
    ]
    for step, (txn_id, amount, name, iban, country) in enumerate((
        ("txn_drain_001", 1200, "New Services A", "AE000000000000000000002", "AE"),
        ("txn_drain_002", 1800, "New Services B", "AE000000000000000000003", "AE"),
        ("txn_wire", 450000, "Pelagic Holdings", "SC000000000000000000004", "SC"),
    )):
        script.append(Txn(
            id=txn_id, ts=DRAIN_START + timedelta(seconds=step), amount=amount,
            currency="AED", direction="out",
            counterparty=Counterparty(name=name, iban=iban, country=country,
                                      is_new=True, offshore=country != "AE"),
            channel="api", client_id="api_partner_7", device_id="device_api_new",
            risk=Risk(score=0, level="low", factors=[]),
            decision="hold" if country == "AE" else "freeze",
            status="held" if country == "AE" else "blocked",
        ))
    return script


class BankError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(detail)


class Bank:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> State:
        self.state = State(
            account=Account(id="acct_001", name="Aisha Al Mansoori", balance=520000,
                            available=520000, held=0, currency="AED"),
            frozen_clients=[], protected_amount=0, scenario="idle",
        )
        self.history = _seed_history()
        amounts = [txn.amount for txn in self.history]
        hours = Counter(txn.ts.hour for txn in self.history)
        self.baseline = CustomerBaseline(
            hour_histogram=[hours[hour] for hour in range(24)],
            amount_mean=mean(amounts), amount_std=pstdev(amounts),
            known_payees={txn.counterparty.iban for txn in self.history},
            known_devices={txn.device_id for txn in self.history},
            known_api_clients={txn.client_id for txn in self.history if txn.channel == "api"},
        )
        self.catalog = _catalog()
        self.known_clients = {txn.client_id for txn in self.history}
        self.transactions: dict[str, Txn] = {}
        self.alerts: dict[str, Alert] = {}
        self.resolutions: dict[str, AlertResolved] = {}
        self.protected_ids: set[str] = set()
        return self.snapshot()

    def snapshot(self) -> State:
        return self.state.model_copy(deep=True)

    def account_update(self) -> AccountUpdated:
        account = self.state.account
        return AccountUpdated(
            balance=account.balance, available=account.available, held=account.held,
            frozen_clients=self.state.frozen_clients.copy(),
            protected_amount=self.state.protected_amount,
        )

    def recent_transactions(self, candidate: Txn) -> list[Txn]:
        start = candidate.ts - RECENT_WINDOW
        return [txn for txn in self.transactions.values()
                if txn.id != candidate.id and start <= txn.ts <= candidate.ts]

    def cumulative_outflow(self, candidate: Txn, recent: list[Txn]) -> float:
        """Count prior outgoing instructions in the window and the candidate once."""
        amount = sum(txn.amount for txn in recent if txn.direction == "out")
        if candidate.direction == "out":
            amount += candidate.amount
        return round(amount, 2)

    def risk_context(self, candidate: Txn) -> RiskContext:
        recent = self.recent_transactions(candidate)
        return RiskContext(
            balance=self.state.account.balance, cumulative_drain=self.cumulative_outflow(candidate, recent),
            recent_transactions=recent, baseline=self.baseline,
        )

    def _available(self) -> None:
        account = self.state.account
        account.available = round(account.balance - account.held, 2)

    def _change_balance(self, txn: Txn) -> None:
        account = self.state.account
        delta = txn.amount if txn.direction == "in" else -txn.amount
        account.balance = round(account.balance + delta, 2)

    def post(self, txn: Txn) -> None:
        """Post once after policy."""
        if txn.id in self.transactions:
            return
        if txn.direction == "out" and txn.amount > self.state.account.available:
            raise BankError(409, "Insufficient available funds")
        self.transactions[txn.id] = txn.model_copy(update={"status": "posted", "decision": "allow"}, deep=True)
        self.known_clients.add(txn.client_id)
        self._change_balance(txn)
        self._available()

    def hold(self, txn: Txn) -> None:
        """Hold once, reserving outgoing amounts without debiting the balance."""
        if txn.id in self.transactions:
            return
        account = self.state.account
        if txn.direction == "out":
            if txn.amount > account.available:
                raise BankError(409, "Insufficient available funds")
            account.held = round(account.held + txn.amount, 2)
        self.transactions[txn.id] = txn.model_copy(update={"status": "held", "decision": "hold"}, deep=True)
        self.known_clients.add(txn.client_id)
        self._available()

    def block(self, txn: Txn) -> None:
        """Block without reserving funds and freeze the originating client."""
        if txn.id not in self.transactions:
            self.transactions[txn.id] = txn.model_copy(update={"status": "blocked", "decision": "freeze"}, deep=True)
            self.freeze(txn.client_id)

    def freeze(self, client_id: str) -> None:
        self.known_clients.add(client_id)
        if client_id not in self.state.frozen_clients:
            self.state.frozen_clients.append(client_id)

    def unfreeze(self, client_id: str) -> AccountUpdated:
        if client_id not in self.known_clients:
            raise BankError(404, "Client not found")
        if client_id in self.state.frozen_clients:
            self.state.frozen_clients.remove(client_id)
        return self.account_update()

    def upsert_alert(self, alert: Alert) -> None:
        if alert.id in self.resolutions:
            return
        if not alert.txn_ids or any(txn_id not in self.transactions for txn_id in alert.txn_ids):
            raise BankError(409, "Alert must reference recorded transactions")
        self.alerts[alert.id] = alert.model_copy(deep=True)

    def resolve(self, alert_id: str, decision: str) -> AlertResolved:
        """Apply a customer decision once, validating a group before changing funds."""
        if decision not in ("confirm", "deny"):
            raise BankError(422, "Decision must be confirm or deny")
        expected = "confirmed" if decision == "confirm" else "denied"
        if prior := self.resolutions.get(alert_id):
            if prior.resolution != expected:
                raise BankError(409, "Alert already resolved differently")
            return prior
        if alert_id not in self.alerts:
            raise BankError(404, "Alert not found")
        return self._resolve(AlertResolved(id=alert_id, resolution=expected, by="customer"))

    def expire_alerts(self, now: datetime) -> list[AlertResolved]:
        due = [alert.id for alert in self.alerts.values() if alert.expires_at <= now]
        return [self._resolve(AlertResolved(id=alert_id, resolution="expired", by="auto"))
                for alert_id in due]

    def _resolve(self, result: AlertResolved) -> AlertResolved:
        txns = [self.transactions[txn_id]
                for txn_id in dict.fromkeys(self.alerts[result.id].txn_ids)]
        confirmed = result.resolution == "confirmed"
        if confirmed:
            if any(txn.client_id in self.state.frozen_clients for txn in txns):
                raise BankError(409, "Client is frozen; confirmation cannot post funds")
            if any(txn.status != "held" for txn in txns):
                raise BankError(409, "Only held transactions can be confirmed")

        account = self.state.account
        for txn in txns:
            prevented = txn.status == "held" or txn.decision == "freeze"
            if txn.status == "held":
                if txn.direction == "out":
                    account.held = round(account.held - txn.amount, 2)
                if confirmed:
                    self._change_balance(txn)
                txn.status = "posted" if confirmed else "blocked"
            if (result.resolution == "denied" and prevented and txn.direction == "out"
                    and txn.id not in self.protected_ids):
                self.state.protected_amount = round(self.state.protected_amount + txn.amount, 2)
                self.protected_ids.add(txn.id)
        self._available()
        self.resolutions[result.id] = result
        del self.alerts[result.id]
        return result
