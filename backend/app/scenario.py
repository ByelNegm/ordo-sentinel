"""Run deterministic demo instructions through the bank's risk and policy path."""

import asyncio
import logging
from collections.abc import Coroutine
from datetime import datetime, timedelta
from typing import Any, Literal

from . import explainer
from .bank import CAFE, DRAIN_START, NORMAL_START, Bank, BankError
from .bus import EventBus
from .models import (
    AccountUpdatedEvent,
    Alert,
    AlertCreatedEvent,
    AlertResolvedEvent,
    CustomerMessage,
    Explanation,
    Factor,
    ScenarioStatus,
    ScenarioStatusEvent,
    Txn,
    TxnScoredEvent,
)
from .policy import PolicyContext, decide
from .risk import score

logger = logging.getLogger(__name__)
ALERT_TTL = timedelta(minutes=5)
ARABIC_DIGITS = str.maketrans("0123456789,.", "٠١٢٣٤٥٦٧٨٩٬٫")

Scenario = Literal["normal", "drain"]


def _with_explanation(alert: Alert, explanation: Explanation) -> Alert:
    return alert.model_copy(update={
        "customer_message": explanation.customer_message,
        "analyst_explanation": explanation.analyst_explanation,
    })


def _template(alert_id: str, txns: list[Txn], expires_at: datetime) -> Alert:
    txn = txns[-1]
    amount = f"{sum(t.amount for t in txns):,.2f}".removesuffix(".00")
    amount_ar = amount.translate(ARABIC_DIGITS)
    if txn.status == "blocked":
        destination = "offshore wire" if txn.counterparty.offshore else "transfer"
        title = f"AED {amount} {destination} blocked"
        explanation = f"The bank froze client {txn.client_id} and blocked the instruction before posting."
        message = CustomerMessage(
            en=f"We blocked an unusual AED {amount} transfer. Your money hasn't left. "
               "Choose Deny if you didn't make the transfer.",
            ar=f"حظرنا تحويلاً غير معتاد بقيمة {amount_ar} درهم. لم تغادر أموالك الحساب. "
               "اختر «رفض» إذا لم تُجرِ التحويل.",
        )
    else:
        title = "Unusual overnight API transfers" if txn.channel == "api" else "Unusual payment held"
        explanation = f"AED {amount} is held pending customer confirmation. Client {txn.client_id}."
        message = CustomerMessage(
            en=f"We paused unusual activity totaling AED {amount}. Your money hasn't left. "
               "Choose Confirm if you recognize it or Deny if you don't.",
            ar=f"أوقفنا مؤقتاً نشاطاً غير معتاد بقيمة {amount_ar} درهم. لم تغادر أموالك الحساب. "
               "اختر «تأكيد» إذا كنت تعرف هذا النشاط أو «رفض» إذا لم تتعرّف عليه.",
        )

    factors = {factor.code: factor.label for t in txns for factor in t.risk.factors}
    if factors:
        explanation += " " + ". ".join(f"{label} ({code})" for code, label in factors.items()) + "."
    return Alert(
        id=alert_id, txn_ids=[t.id for t in txns],
        severity="critical" if txn.status == "blocked" else max(txns, key=lambda t: t.risk.score).risk.level,
        title=title, analyst_explanation=explanation, customer_message=message,
        actions=["confirm", "deny"], expires_at=expires_at,
    )


class ScenarioRunner:
    def __init__(self, bank: Bank, bus: EventBus, pace: float = 1.0) -> None:
        self.bank, self.bus, self.pace = bank, bus, pace
        self.task: asyncio.Task[None] | None = None
        self._stop_lock = asyncio.Lock()
        self._background: set[asyncio.Task[None]] = set()

    @property
    def running(self) -> bool:
        return self._stop_lock.locked() or (self.task is not None and not self.task.done())

    def start(self, name: Scenario) -> ScenarioStatus:
        """Schedule the script and reject starts throughout reset cancellation."""
        if self.running:
            raise BankError(409, "Scenario already running")
        self.bank.state.scenario = name
        self.task = asyncio.create_task(self._run(name))
        self.task.add_done_callback(self._log_failure)
        return ScenarioStatus(name=name, step=0, total=3)

    async def stop(self) -> None:
        """Cancel and join both the run and all alert work before bank reset."""
        async with self._stop_lock:
            tasks = [*self._background]
            if self.task is not None:
                tasks.append(self.task)
            for task in tasks:
                task.cancel()
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                self.task = None

    @staticmethod
    def _log_failure(task: asyncio.Task[None]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("Demo task failed", exc_info=error)

    def _spawn(self, work: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(work)
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        task.add_done_callback(self._log_failure)

    async def _publish_status(self, name: Scenario, step: int, total: int, ts: datetime) -> None:
        await self.bus.publish(ScenarioStatusEvent(ts=ts, data=ScenarioStatus(name=name, step=step, total=total)))

    async def _run(self, name: Scenario) -> None:
        if name == "normal":
            base = self.bank.catalog[0]
            script = [base.model_copy(update={"id": f"txn_normal_{step}", "amount": amount, "counterparty": payee})
                      for step, (amount, payee) in enumerate(((25, CAFE), (30, base.counterparty),
                                                             (30, base.counterparty)), start=1)]
            start = NORMAL_START
        else:
            script = self.bank.catalog[1:]
            start = DRAIN_START
        latest = max((txn.ts for txn in self.bank.transactions.values()), default=start - timedelta(days=1))
        if latest >= start:
            start = start + timedelta(days=(latest.date() - start.date()).days)
            if start <= latest:
                start += timedelta(days=1)

        pace = self.pace
        # Give an immediately connecting SSE subscriber time to attach.
        await asyncio.sleep(0.1 * pace)
        await self._expire(start)
        await self._publish_status(name, 0, len(script), start)
        for step, template in enumerate(script):
            if step:
                await asyncio.sleep(pace)
            ts = start + timedelta(seconds=step)
            txn_id = template.id if ts.date() == template.ts.date() else f"{template.id}_{ts:%Y%m%d}"
            txn = template.model_copy(update={"id": txn_id, "ts": ts}, deep=True)
            await self._submit(txn, pace)
            await self._publish_status(name, step + 1, len(script), ts)

    async def _submit(self, txn: Txn, pace: float) -> None:
        ctx = self.bank.risk_context(txn)
        txn.risk = score(txn, ctx)
        client_frozen = txn.client_id in self.bank.state.frozen_clients
        decision = decide(txn.risk, PolicyContext(ctx.balance, ctx.cumulative_drain, client_frozen))
        if client_frozen:
            txn.risk.factors.append(Factor(
                code="CLIENT_ALREADY_FROZEN",
                label="Connected service already frozen",
                weight=0,
            ))
        {"allow": self.bank.post, "hold": self.bank.hold, "freeze": self.bank.block}[decision](txn)
        posted = self.bank.transactions[txn.id]
        alert = self._alert(posted) if posted.status != "posted" else None
        if alert is not None:
            txns = [self.bank.transactions[txn_id].model_copy(deep=True) for txn_id in alert.txn_ids]
            try:
                alert = _with_explanation(alert, explainer.explain(alert, txns=txns, balance=ctx.balance))
            except Exception:
                logger.debug("Template unavailable for %s", alert.id, exc_info=True)
            new_alert = alert.id not in self.bank.alerts
            self.bank.upsert_alert(alert)
            if new_alert:
                self._spawn(self._expire_after(alert.expires_at, posted.ts, pace))

        await self.bus.publish(TxnScoredEvent(ts=posted.ts, data=posted))
        if alert is not None:
            await self.bus.publish(AlertCreatedEvent(ts=posted.ts, data=alert))
            self._spawn(self._enrich(alert, posted.ts, txns, ctx.balance))
        await self.bus.publish(AccountUpdatedEvent(ts=posted.ts, data=self.bank.account_update()))

    def _alert(self, txn: Txn) -> Alert:
        burst = txn.status == "held" and txn.id.startswith("txn_drain_")
        if burst:
            _, _, suffix = txn.id.removeprefix("txn_drain_").partition("_")
            alert_id = f"alert_burst_{suffix}" if suffix else "alert_burst"
            if group := self.bank.alerts.get(alert_id):
                txns = [self.bank.transactions[txn_id] for txn_id in group.txn_ids]
                return _template(alert_id, [*txns, txn], group.expires_at)
            if alert_id in self.bank.resolutions:
                # The earlier instruction already got a decision. The new hold needs its own alert.
                alert_id = txn.id.replace("txn_", "alert_", 1)
        else:
            alert_id = txn.id.replace("txn_", "alert_", 1)
        return _template(alert_id, [txn], txn.ts + ALERT_TTL)

    async def _expire_after(self, expires_at: datetime, now: datetime, pace: float) -> None:
        delay = (expires_at - now).total_seconds()
        # pace=0 skips waits between instructions while keeping decision time available.
        await asyncio.sleep(delay * (pace or 1.0))
        await self._expire(expires_at)

    async def _expire(self, now: datetime) -> None:
        for result in self.bank.expire_alerts(now):
            await self.bus.publish(AlertResolvedEvent(ts=now, data=result))
            await self.bus.publish(AccountUpdatedEvent(ts=now, data=self.bank.account_update()))

    async def _enrich(self, alert: Alert, ts: datetime, txns: list[Txn], balance: float) -> None:
        try:
            explanation = await explainer.enrich(alert.model_copy(deep=True), txns=txns, balance=balance)
        except Exception:
            logger.debug("Explanation unavailable for %s", alert.id, exc_info=True)
            return
        if explanation is not None and self.bank.alerts.get(alert.id) == alert:
            enriched = _with_explanation(alert, explanation)
            if enriched != alert:
                self.bank.upsert_alert(enriched)
                await self.bus.publish(AlertCreatedEvent(ts=ts, data=enriched))
