"""Frozen BLACKBOX v1 wire shapes; see docs/API_CONTRACT.md."""
from datetime import datetime, timezone
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StrictInt

Money = Annotated[StrictInt, Field(ge=0)]
PositiveMoney = Annotated[StrictInt, Field(gt=0)]
Status = Literal["healthy", "violated", "recovering"]
Fault = Literal["duplicate", "missing", "tamper"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Account(Model):
    id: str
    name: str
    type: Literal["customer", "internal"]
    balance_minor: StrictInt


class Service(Model):
    id: Literal["settlement-svc"] = "settlement-svc"
    status: Literal["running", "quarantined"] = "running"
    fault: Fault | None = None
    processed: int = 0


class PaymentInstruction(Model):
    id: str
    idempotency_key: str
    debtor: str
    creditor: str
    amount_minor: PositiveMoney
    currency: Literal["AED"] = "AED"
    created_at: datetime
    status: Literal["accepted", "settled", "held", "missing", "discrepancy"] = "accepted"
    settlement_count: int = 0
    expected_hash: str


class SettlementEvent(Model):
    id: str
    instruction_id: str
    seq: int
    service: str
    debtor: str
    creditor: str
    amount_minor: PositiveMoney
    payload_hash: str
    ts: datetime


class PostingLine(Model):
    account: str
    side: Literal["debit", "credit"]
    amount_minor: PositiveMoney


class JournalEntry(Model):
    id: str
    kind: Literal["settlement", "compensation"]
    instruction_id: str
    event_id: str | None
    corrects_entry_id: str | None
    lines: list[PostingLine]
    ts: datetime
    actor: str


class Check(Model):
    name: str
    passed: bool = Field(alias="pass")
    detail: str


class IntegrityReport(Model):
    status: Status
    checks: list[Check]
    ts: datetime


class TimelineItem(Model):
    ts: datetime
    kind: Literal["instruction", "settlement", "posting", "detection", "investigation",
                  "containment", "proposal", "sandbox", "approval", "correction", "verification"]
    ref: str | None
    detail: str


class RootCause(Model):
    service: str
    summary: str
    confidence: Literal["high", "medium", "low"]
    method: Literal["deterministic", "llm"]


class Lineage(Model):
    instruction_id: str
    event_ids: list[str]
    entry_ids: list[str]


class Containment(Model):
    service: str
    action: Literal["quarantine"]
    at: datetime
    held_instructions: int


class Proposal(Model):
    id: str
    description: str
    entries: list[JournalEntry]


class SandboxReport(Model):
    passed: bool
    checks_before: list[Check]
    checks_after: list[Check]
    balances_before: dict[str, StrictInt]
    balances_after: dict[str, StrictInt]
    ts: datetime


class SandboxChallengeRequest(Model):
    variant: Literal["wrong_amount", "reverse_original"]


class SandboxChallengeResponse(Model):
    variant: Literal["wrong_amount", "reverse_original"]
    proposal: Proposal
    sandbox: SandboxReport
    ledger_unchanged: bool


class Approval(Model):
    actor: str
    at: datetime


class Incident(Model):
    id: str
    type: Literal["duplicate_settlement", "missing_settlement", "tampered_settlement"]
    status: Literal["detected", "investigating", "contained", "validating", "awaiting_approval",
                    "correcting", "resolved", "rejected", "failed"]
    detected_at: datetime
    violations: list[Check]
    affected_payments: list[str]
    affected_accounts: list[str]
    impact_minor: Money
    root_cause: RootCause
    lineage: list[Lineage]
    timeline: list[TimelineItem]
    containment: Containment | None = None
    proposal: Proposal | None = None
    sandbox: SandboxReport | None = None
    approval: Approval | None = None
    corrections: list[str] = Field(default_factory=list)
    verification: IntegrityReport | None = None


class AuditRecord(Model):
    id: str
    ts: datetime
    actor: str
    action: str
    ref: str | None
    detail: str


class Totals(Model):
    debits_minor: Money
    credits_minor: Money
    ledger_entries: int


class Volume(Model):
    instructions: int
    settled: int
    pending: int
    held: int


class IntegritySummary(Model):
    status: Status
    failing_checks: int


class Overview(Model):
    accounts: list[Account]
    totals: Totals
    volume: Volume
    services: list[Service]
    integrity: IntegritySummary
    open_incidents: int
    traffic_running: bool


class ActorRequest(Model):
    actor: str


class TrafficStatus(Model):
    running: bool


class FaultResponse(Model):
    fault: Fault
    service: Literal["settlement-svc"] = "settlement-svc"


class PostedSettlement(Model):
    event: SettlementEvent
    entry: JournalEntry


class PaymentAccepted(Model):
    type: Literal["payment.accepted"] = "payment.accepted"
    ts: datetime
    data: PaymentInstruction


class SettlementPosted(Model):
    type: Literal["settlement.posted"] = "settlement.posted"
    ts: datetime
    data: PostedSettlement


class IntegrityUpdated(Model):
    type: Literal["integrity.updated"] = "integrity.updated"
    ts: datetime
    data: IntegrityReport


class IncidentUpdated(Model):
    type: Literal["incident.updated"] = "incident.updated"
    ts: datetime
    data: Incident


class ServiceUpdated(Model):
    type: Literal["service.updated"] = "service.updated"
    ts: datetime
    data: Service


class AuditAppended(Model):
    type: Literal["audit.appended"] = "audit.appended"
    ts: datetime
    data: AuditRecord


class Reset(Model):
    type: Literal["reset"] = "reset"
    ts: datetime
    data: Overview


Event = Annotated[Union[PaymentAccepted, SettlementPosted, IntegrityUpdated, IncidentUpdated,
                        ServiceUpdated, AuditAppended, Reset], Field(discriminator="type")]
