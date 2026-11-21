"""Frozen HTTP/SSE contract. Changes require lead approval."""
from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

Decision = Literal["allow", "hold", "freeze"]
ScenarioName = Literal["idle", "normal", "drain"]
Level = Literal["low", "medium", "high", "critical"]
Money = Annotated[float, Field(ge=0, multiple_of=0.01, allow_inf_nan=False)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Account(Model):
    id: str
    name: str
    balance: Money
    available: Money
    held: Money
    currency: Literal["AED"]


class State(Model):
    account: Account
    frozen_clients: list[str]
    protected_amount: Money
    scenario: ScenarioName


class Factor(Model):
    code: str
    label: str
    weight: float


class Risk(Model):
    score: int = Field(ge=0, le=100)
    level: Level
    factors: list[Factor]


class Counterparty(Model):
    name: str
    iban: str
    country: str = Field(pattern=r"^[A-Z]{2}$")
    is_new: bool
    offshore: bool


class Txn(Model):
    id: str
    ts: datetime
    amount: Money
    currency: Literal["AED"]
    direction: Literal["out", "in"]
    counterparty: Counterparty
    channel: Literal["api", "app", "card"]
    client_id: str
    device_id: str
    risk: Risk
    decision: Decision
    status: Literal["posted", "held", "blocked"]


class CustomerMessage(Model):
    en: str
    ar: str


class Explanation(Model):
    customer_message: CustomerMessage
    analyst_explanation: str


class Alert(Explanation):
    id: str
    txn_ids: list[str]
    severity: Level
    title: str
    actions: list[Literal["confirm", "deny"]]
    expires_at: datetime


class DecisionRequest(Model):
    decision: Literal["confirm", "deny"]


class AlertResolved(Model):
    id: str
    resolution: Literal["confirmed", "denied", "expired"]
    by: Literal["customer", "analyst", "auto"]


class AccountUpdated(Model):
    balance: Money
    available: Money
    held: Money
    frozen_clients: list[str]
    protected_amount: Money


class ScenarioStatus(Model):
    name: ScenarioName
    step: int = Field(ge=0)
    total: int = Field(ge=0)


class EventEnvelope(Model):
    type: str
    ts: datetime
    data: dict


class TxnScoredEvent(Model):
    type: Literal["txn.scored"] = "txn.scored"
    ts: datetime
    data: Txn


class AlertCreatedEvent(Model):
    type: Literal["alert.created"] = "alert.created"
    ts: datetime
    data: Alert


class AlertResolvedEvent(Model):
    type: Literal["alert.resolved"] = "alert.resolved"
    ts: datetime
    data: AlertResolved


class AccountUpdatedEvent(Model):
    type: Literal["account.updated"] = "account.updated"
    ts: datetime
    data: AccountUpdated


class ScenarioStatusEvent(Model):
    type: Literal["scenario.status"] = "scenario.status"
    ts: datetime
    data: ScenarioStatus


Event = Annotated[Union[TxnScoredEvent, AlertCreatedEvent, AlertResolvedEvent,
                        AccountUpdatedEvent, ScenarioStatusEvent], Field(discriminator="type")]
EVENT_ADAPTER = TypeAdapter(Event)
