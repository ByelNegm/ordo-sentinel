"""Builder B: process-local bank. Methods are synchronous/atomic on the app event loop."""
import json
from pathlib import Path

from .models import (AccountUpdated, Alert, AlertResolved, State, Txn)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


class BankError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail


class Bank:
    def __init__(self) -> None:
        self.catalog = [Txn.model_validate(t) for t in json.loads(
            (FIXTURES / "transactions.json").read_text())]
        self.known_clients = {t.client_id for t in self.catalog}
        self.reset()

    def reset(self) -> State:
        """Restore fixture seed and clear live records; baseline expansion is Builder B work."""
        self.state = State.model_validate_json((FIXTURES / "state.json").read_text())
        self.transactions: dict[str, Txn] = {}
        self.alerts: dict[str, Alert] = {}
        self.resolutions: dict[str, AlertResolved] = {}
        self.protected_ids: set[str] = set()
        return self.snapshot()

    def snapshot(self) -> State:
        return self.state.model_copy(deep=True)

    def account_update(self) -> AccountUpdated:
        a = self.state.account
        return AccountUpdated(balance=a.balance, available=a.available, held=a.held,
                              frozen_clients=self.state.frozen_clients.copy(),
                              protected_amount=self.state.protected_amount)

    def _available(self) -> None:
        self.state.account.available = self.state.account.balance - self.state.account.held

    def post(self, txn: Txn) -> None:
        """Post once; caller has already applied policy."""
        if txn.id in self.transactions:
            return
        if txn.direction == "out" and txn.amount > self.state.account.available:
            raise BankError(409, "Insufficient available funds")
        self.transactions[txn.id] = txn.model_copy(update={"status": "posted", "decision": "allow"}, deep=True)
        self.state.account.balance += txn.amount if txn.direction == "in" else -txn.amount
        self._available()

    def hold(self, txn: Txn) -> None:
        """Reserve once without debiting posted balance."""
        if txn.id in self.transactions:
            return
        if txn.amount > self.state.account.available:
            raise BankError(409, "Insufficient available funds")
        self.transactions[txn.id] = txn.model_copy(update={"status": "held", "decision": "hold"}, deep=True)
        self.state.account.held += txn.amount
        self._available()

    def block(self, txn: Txn) -> None:
        """Block without reserving funds; freeze the originating client."""
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
        if alert.id not in self.resolutions:
            self.alerts[alert.id] = alert.model_copy(deep=True)

    def resolve(self, alert_id: str, decision: str) -> AlertResolved:
        """Apply customer decision once; blocked transactions never post via confirm."""
        resolution = "confirmed" if decision == "confirm" else "denied"
        if alert_id in self.resolutions:
            result = self.resolutions[alert_id]
            if result.resolution != resolution:
                raise BankError(409, "Alert already resolved differently")
            return result
        if alert_id not in self.alerts:
            raise BankError(404, "Alert not found")
        txns = [self.transactions[t] for t in self.alerts[alert_id].txn_ids]
        if decision == "confirm" and any(
            t.client_id in self.state.frozen_clients or t.status == "blocked" for t in txns
        ):
            raise BankError(409, "Client is frozen; confirmation cannot post funds")
        for txn in txns:
            if txn.status == "held":
                self.state.account.held -= txn.amount
                if decision == "confirm":
                    self.state.account.balance -= txn.amount
                txn.status = "posted" if decision == "confirm" else "blocked"
            if decision == "deny" and txn.id not in self.protected_ids:
                self.state.protected_amount += txn.amount
                self.protected_ids.add(txn.id)
        self._available()
        result = AlertResolved(id=alert_id, resolution=resolution, by="customer")
        self.resolutions[alert_id] = result
        del self.alerts[alert_id]
        return result
