"""Builder C: EN/AR customer messages and analyst narratives for hold/freeze alerts.

`explain` is synchronous and template-only (no network), so it never delays
enforcement. `enrich` is an optional async LLM rewrite (OPENAI_API_KEY or
ANTHROPIC_API_KEY) capped at 1s total, cached by alert content, returning None
on any problem. The LLM only rewrites text; it never decides anything.
"""
import asyncio
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import httpx

from .models import Alert, CustomerMessage, Explanation, Txn

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
LLM_TIMEOUT = float(os.getenv("ORDO_LLM_TIMEOUT", "1"))
_CACHE: dict[str, Explanation] = {}
_AR_DIGITS = str.maketrans("0123456789,.", "٠١٢٣٤٥٦٧٨٩٬٫")


def _fixture_txns() -> dict[str, Txn]:
    try:
        rows = json.loads((FIXTURES / "transactions.json").read_text())
        return {t.id: t for t in (Txn.model_validate(r) for r in rows)}
    except Exception:
        return {}


def _fixture_balance() -> float | None:
    try:
        return float(json.loads((FIXTURES / "state.json").read_text())["account"]["balance"])
    except Exception:
        return None


def _money(amount: float) -> str:
    return f"{amount:,.2f}".removesuffix(".00")


def _ar(text: str) -> str:
    return text.translate(_AR_DIGITS)


def _clock(ts: datetime) -> tuple[str, str]:
    h = ts.hour % 12 or 12
    en = f"{h}:{ts.minute:02d}" if ts.minute else str(h)
    am = ts.hour < 12
    return f"{en} {'AM' if am else 'PM'}", f"الساعة {_ar(en)} {'صباحاً' if am else 'مساءً'}"


def _is_night(ts: datetime) -> bool:
    return ts.hour < 6 or ts.hour >= 22


def _ar_payments(n: int) -> str:
    if n == 1:
        return "دفعة غير معتادة"
    if n == 2:
        return "دفعتين غير معتادتين"
    if 3 <= n <= 10:
        return f"{_ar(str(n))} دفعات غير معتادة"
    return f"{_ar(str(n))} دفعة غير معتادة"


def _reason_codes(txns: list[Txn]) -> list[str]:
    seen: dict[str, float] = {}
    for t in txns:
        for f in t.risk.factors:
            seen[f.code] = max(seen.get(f.code, 0), f.weight)
    return [c for c, _ in sorted(seen.items(), key=lambda kv: -kv[1])]


def _customer(txns: list[Txn]) -> CustomerMessage:
    n = len(txns)
    total = sum(t.amount for t in txns)
    freeze = any(t.decision == "freeze" for t in txns)
    overseas = any(t.counterparty.offshore or t.counterparty.country != "AE" for t in txns)
    new_client = any(f.code in ("NEW_API_CLIENT", "NEW_DEVICE") for t in txns for f in t.risk.factors)
    night = any(_is_night(t.ts) for t in txns)
    amt_en, amt_ar = f"AED {_money(total)}", f"{_ar(_money(total))} درهم"
    clock_en, clock_ar = _clock(min(t.ts for t in txns))

    kind_en = "overseas " if overseas else ""
    kind_ar = " خارجية" if overseas else ""
    if n == 1:
        what_en = f"an unusual {amt_en} {kind_en}payment" + (f" at {clock_en}" if night else "")
        what_ar = f"دفعة{kind_ar} غير معتادة بقيمة {amt_ar}" + (f" {clock_ar}" if night else "")
    else:
        what_en = f"{n} unusual{' overnight' if night else ''} {kind_en}payments totaling {amt_en}"
        what_ar = (f"{_ar_payments(n)}{' إلى الخارج' if overseas else ''}{' ليلاً' if night else ''} بقيمة إجمالية {amt_ar}")
    src_en = " from a connected service you haven't used before" if new_client else ""
    src_ar = " من خدمة متصلة لم تستخدميها من قبل" if new_client else ""
    it_en, them_ar = ("it", "ها") if n == 1 else ("them", "هما" if n == 2 else "ها")
    was_en = "this was" if n == 1 else "these were"

    if freeze:
        en = (f"We blocked {what_en}{src_en}. Your money has not left your account, "
              f"and we have paused that service's access. If {was_en} not you, tap Deny. "
              f"If you made {it_en}, contact us to verify {it_en}; nothing will be sent automatically. "
              f"Never share your verification codes with anyone.")
        ar = (f"حظرنا {what_ar}{src_ar}. لم تغادر أموالك حسابك، وأوقفنا وصول هذه الخدمة مؤقتاً. "
              f"إذا لم تكوني أنتِ من أجرا{them_ar} فاضغطي «رفض». وإن كنتِ أنتِ، فتواصلي معنا للتحقق؛ "
              f"لن يُرسَل أي مبلغ تلقائياً. لا تشاركي رموز التحقق مع أي شخص.")
    else:
        en = (f"We paused {what_en}{src_en}. Your money has not left your account. "
              f"If {was_en} you, tap Confirm. If not, tap Deny and we will cancel {it_en}.")
        ar = (f"أوقفنا مؤقتاً {what_ar}{src_ar}. لم تغادر أموالك حسابك. "
              f"إذا كنتِ أنتِ من أجرا{them_ar} فاضغطي «تأكيد»، وإن لم تكوني أنتِ فاضغطي «رفض» وسنلغي{them_ar}.")
    return CustomerMessage(en=en, ar=ar)


def _analyst(txns: list[Txn], balance: float | None) -> str:
    n = len(txns)
    total = sum(t.amount for t in txns)
    freeze = [t for t in txns if t.decision == "freeze"]
    clients = sorted({t.client_id for t in txns})
    devices = sorted({t.device_id for t in txns})
    payees = ", ".join(dict.fromkeys(f"{t.counterparty.name} ({t.counterparty.country}"
                                     f"{', offshore' if t.counterparty.offshore else ''}"
                                     f"{', new' if t.counterparty.is_new else ''})" for t in txns))
    top = max(txns, key=lambda t: t.risk.score)
    channel = "/".join(sorted({t.channel for t in txns}))
    start = min(t.ts for t in txns).strftime("%H:%M")
    parts = [f"{n} outbound {channel} transfer{'s' if n > 1 else ''} totaling AED {_money(total)} at {start} "
             f"from client {', '.join(clients)} on device {', '.join(devices)} to {payees}.",
             f"Reason codes: {', '.join(_reason_codes(txns)) or 'none'}; "
             f"max risk {top.risk.score}/100 ({top.risk.level}).",]
    if balance:
        parts.append(f"Amount is {total / balance * 100:.2f}% of the AED {_money(balance)} balance.")
    if freeze:
        frozen = sorted({t.client_id for t in freeze})
        parts.append(f"Deterministic policy blocked AED {_money(sum(t.amount for t in freeze))} and froze "
                     f"client {', '.join(frozen)} before posting; funds have not left. "
                     f"Successful authentication is not evidence of customer intent.")
    held = sum(t.amount for t in txns if t.decision == "hold")
    if held:
        parts.append(f"AED {_money(held)} is held pending an independent customer decision.")
    return " ".join(parts)


def template_explanation(alert: Alert, txns: list[Txn] | None = None,
                         balance: float | None = None) -> Explanation:
    """Instant deterministic EN/AR + analyst text; never raises."""
    try:
        given = {t.id: t for t in txns or []}
        if not all(i in given for i in alert.txn_ids):
            given = {**_fixture_txns(), **given}
        if not alert.txn_ids or not all(i in given for i in alert.txn_ids):
            raise ValueError("missing alert transactions")
        txns = [given[i] for i in alert.txn_ids]
        if balance is None:
            balance = _fixture_balance()
        return Explanation(customer_message=_customer(txns), analyst_explanation=_analyst(txns, balance))
    except Exception:
        return Explanation(customer_message=alert.customer_message.model_copy(deep=True),
                           analyst_explanation=alert.analyst_explanation)


_PROMPT = (
    "You rewrite bank fraud-alert text. Do NOT change any facts, amounts, decisions or actions; "
    "do not add advice beyond what is given. Keep the customer message calm, plain, short, and keep "
    "that the money has not left the account and what to tap (Confirm/Deny; Arabic «تأكيد»/«رفض»). "
    "Arabic must be correct Modern Standard Arabic with Arabic-Indic digits. Keep the analyst text "
    "concise and keep every reason code, amount, client and device id. Reply with JSON only: "
    '{"en": str, "ar": str, "analyst": str}.\n\nInput:\n')


def _provider() -> str | None:
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


async def _llm_rewrite(base: Explanation) -> Explanation:
    """Ask the configured LLM to polish template text. Raises on any problem."""
    provider = _provider()
    payload = json.dumps({"en": base.customer_message.en, "ar": base.customer_message.ar,
                          "analyst": base.analyst_explanation}, ensure_ascii=False)
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        if provider == "openai":
            r = await client.post(
                os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1") + "/chat/completions",
                headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
                json={"model": os.getenv("ORDO_LLM_MODEL", "gpt-4o-mini"), "temperature": 0.2,
                      "response_format": {"type": "json_object"},
                      "messages": [{"role": "user", "content": _PROMPT + payload}]})
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
        elif provider == "anthropic":
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
                json={"model": os.getenv("ORDO_LLM_MODEL", "claude-3-5-haiku-latest"), "max_tokens": 800,
                      "messages": [{"role": "user", "content": _PROMPT + payload}]})
            r.raise_for_status()
            text = r.json()["content"][0]["text"]
        else:
            raise RuntimeError("no LLM configured")
    data = json.loads(text[text.index("{"): text.rindex("}") + 1])
    out = {k: data[k].strip() for k in ("en", "ar", "analyst")}
    if not all(out.values()) or any(len(v) > 1200 for v in out.values()):
        raise ValueError("invalid LLM reply")
    return Explanation(customer_message=CustomerMessage(en=out["en"], ar=out["ar"]),
                       analyst_explanation=out["analyst"])


def _cache_key(alert: Alert, base: Explanation) -> str:
    raw = json.dumps([alert.id, alert.txn_ids, alert.severity, base.model_dump()], sort_keys=True,
                     ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


class _Explained(Explanation):
    """Explanation that can also be awaited, so legacy `await explain(...)` callers keep working."""

    def __await__(self):
        if False:
            yield
        return Explanation.model_validate(self.model_dump())


def explain(alert: Alert, txns: list[Txn] | None = None,
            balance: float | None = None) -> Explanation:
    """Synchronous, template-only, no network: safe on the enforcement path.

    txns/balance are optional live context (defaults: fixture transactions by
    alert.txn_ids and fixture balance).
    """
    return _Explained.model_validate(template_explanation(alert, txns, balance).model_dump())


async def enrich(alert: Alert, txns: list[Txn] | None = None,
                 balance: float | None = None) -> Explanation | None:
    """Optional LLM rewrite of the template text, capped at LLM_TIMEOUT seconds total.

    Returns None when no key is set or on any error/timeout. Cached by alert content.
    Intended to run as a background task; the LLM never decides anything.
    """
    if _provider() is None:
        return None
    base = template_explanation(alert, txns, balance)
    key = _cache_key(alert, base)
    if key in _CACHE:
        return _CACHE[key].model_copy(deep=True)
    try:
        result = await asyncio.wait_for(_llm_rewrite(base), LLM_TIMEOUT)
    except Exception:
        return None
    _CACHE[key] = result
    return result.model_copy(deep=True)
