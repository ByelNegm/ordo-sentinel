import asyncio
import json

import pytest

from app import explainer
from app.bank import FIXTURES
from app.models import Alert, Explanation, Txn

ALERTS = {a["id"]: Alert.model_validate(a) for a in json.loads((FIXTURES / "alerts.json").read_text())}
TXNS = {t["id"]: Txn.model_validate(t) for t in json.loads((FIXTURES / "transactions.json").read_text())}


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    explainer._CACHE.clear()


def run(alert, **kw):
    return asyncio.run(explainer.explain(alert, **kw))


def test_burst_hold_template():
    e = run(ALERTS["alert_burst"])
    en, ar = e.customer_message.en, e.customer_message.ar
    assert "paused 2 unusual overnight payments totaling AED 3,000" in en
    assert "has not left" in en and "Confirm" in en and "Deny" in en
    assert "دفعتين غير معتادتين" in ar and "٣٬٠٠٠ درهم" in ar
    assert "لم تغادر أموالك حسابك" in ar and "«تأكيد»" in ar and "«رفض»" in ar
    assert not any(c.isascii() and c.isdigit() for c in ar)
    for s in ("UNUSUAL_HOUR", "NEW_PAYEE", "NEW_API_CLIENT", "VELOCITY", "AED 3,000",
              "api_partner_7", "device_api_new", "held pending"):
        assert s in e.analyst_explanation


def test_wire_freeze_template():
    e = run(ALERTS["alert_wire"])
    en, ar = e.customer_message.en, e.customer_message.ar
    assert "blocked an unusual AED 450,000 overseas payment at 2 AM" in en
    assert "has not left" in en and "Deny" in en
    assert "حظرنا دفعة خارجية غير معتادة بقيمة ٤٥٠٬٠٠٠ درهم الساعة ٢ صباحاً" in ar
    assert "لم تغادر أموالك حسابك" in ar
    for s in ("AMOUNT_ZSCORE", "OFFSHORE", "BALANCE_DRAIN", "AED 450,000", "Pelagic Holdings (SC",
              "froze client api_partner_7", "device_api_new", "86.54%"):
        assert s in e.analyst_explanation


def test_explicit_txns_and_balance():
    e = run(ALERTS["alert_wire"], txns=[TXNS["txn_wire"]], balance=519915)
    assert "86.55%" in e.analyst_explanation


def test_unknown_txns_falls_back_to_alert_text():
    a = ALERTS["alert_wire"].model_copy(update={"txn_ids": ["nope"]})
    e = run(a)
    assert e.customer_message == a.customer_message
    assert e.analyst_explanation == a.analyst_explanation


def test_no_key_never_calls_llm(monkeypatch):
    async def boom(base):
        raise AssertionError("LLM must not be called without a key")
    monkeypatch.setattr(explainer, "_llm_rewrite", boom)
    assert run(ALERTS["alert_burst"]) == explainer.template_explanation(ALERTS["alert_burst"])


@pytest.mark.parametrize("exc", [RuntimeError("500"), asyncio.TimeoutError(), ValueError("bad json")])
def test_llm_error_falls_back_to_template(monkeypatch, exc):
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    async def fail(base):
        raise exc
    monkeypatch.setattr(explainer, "_llm_rewrite", fail)
    assert run(ALERTS["alert_wire"]) == explainer.template_explanation(ALERTS["alert_wire"])


def test_llm_http_timeout_falls_back(monkeypatch):
    import httpx
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    async def slow_post(self, *a, **kw):
        raise httpx.ReadTimeout("timeout")
    monkeypatch.setattr(httpx.AsyncClient, "post", slow_post)
    assert run(ALERTS["alert_burst"]) == explainer.template_explanation(ALERTS["alert_burst"])


def test_llm_result_cached(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    calls = []

    async def rewrite(base):
        calls.append(1)
        return Explanation.model_validate({"customer_message": {"en": "polished", "ar": "مصقول"},
                                           "analyst_explanation": "polished analyst"})
    monkeypatch.setattr(explainer, "_llm_rewrite", rewrite)
    first = run(ALERTS["alert_wire"])
    second = run(ALERTS["alert_wire"])
    assert first == second and first.customer_message.en == "polished"
    assert len(calls) == 1
    run(ALERTS["alert_burst"])
    assert len(calls) == 2
