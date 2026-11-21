import asyncio
import json
import time

import httpx
import pytest

from app import explainer
from app.bank import FIXTURES
from app.models import Alert, Explanation, Txn

ALERTS = {a["id"]: Alert.model_validate(a) for a in json.loads((FIXTURES / "alerts.json").read_text())}
TXNS = {t["id"]: Txn.model_validate(t) for t in json.loads((FIXTURES / "transactions.json").read_text())}
POLISHED = Explanation.model_validate({"customer_message": {"en": "polished", "ar": "مصقول"},
                                       "analyst_explanation": "polished analyst"})


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    explainer._CACHE.clear()


def enrich(alert, **kw):
    return asyncio.run(explainer.enrich(alert, **kw))


def test_burst_hold_template():
    e = explainer.explain(ALERTS["alert_burst"])
    en, ar = e.customer_message.en, e.customer_message.ar
    assert "paused 2 unusual overnight payments totaling AED 3,000" in en
    assert "has not left" in en and "Confirm" in en and "Deny" in en
    assert "دفعتين غير معتادتين" in ar and "٣٬٠٠٠ درهم" in ar
    assert "لم تغادر أموالك حسابك" in ar and "فاضغطي «تأكيد»" in ar and "فاضغطي «رفض»" in ar
    assert "تكوني" in ar and "تستخدميها" in ar
    assert not any(c.isascii() and c.isdigit() for c in ar)
    for s in ("UNUSUAL_HOUR", "NEW_PAYEE", "NEW_API_CLIENT", "VELOCITY", "AED 3,000",
              "api_partner_7", "device_api_new", "held pending"):
        assert s in e.analyst_explanation


def test_wire_freeze_template():
    e = explainer.explain(ALERTS["alert_wire"])
    en, ar = e.customer_message.en, e.customer_message.ar
    assert "blocked an unusual AED 450,000 overseas payment at 2 AM" in en
    assert "has not left" in en and "Deny" in en
    assert "tap Confirm" not in en and "«تأكيد»" not in ar  # confirming a blocked payment returns 409
    assert "حظرنا دفعة خارجية غير معتادة بقيمة ٤٥٠٬٠٠٠ درهم الساعة ٢ صباحاً" in ar
    assert "لم تغادر أموالك حسابك" in ar and "لا تشاركي" in ar
    for s in ("AMOUNT_ZSCORE", "OFFSHORE", "BALANCE_DRAIN", "AED 450,000", "Pelagic Holdings (SC",
              "froze client api_partner_7", "device_api_new", "86.54%"):
        assert s in e.analyst_explanation


def test_explicit_txns_and_balance():
    e = explainer.explain(ALERTS["alert_wire"], txns=[TXNS["txn_wire"]], balance=519915)
    assert "86.55%" in e.analyst_explanation


def test_only_alert_txns_are_described():
    e = explainer.explain(ALERTS["alert_wire"], txns=[TXNS["txn_drain_001"], TXNS["txn_wire"]])
    assert "AED 450,000" in e.customer_message.en and "AED 451,200" not in e.analyst_explanation


def test_missing_txns_fall_back_to_alert_text():
    for ids in (["nope"], ["txn_wire", "nope"]):
        a = ALERTS["alert_wire"].model_copy(update={"txn_ids": ids})
        e = explainer.explain(a, txns=[TXNS["txn_drain_001"]])
        assert e.customer_message == a.customer_message
        assert e.analyst_explanation == a.analyst_explanation


def test_explain_is_sync_and_offline_even_with_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    async def boom(*a, **kw):
        raise AssertionError("explain must not touch the network")
    monkeypatch.setattr(explainer, "_llm_rewrite", boom)
    monkeypatch.setattr(httpx.AsyncClient, "post", boom)
    e = explainer.explain(ALERTS["alert_wire"])
    assert isinstance(e, Explanation) and "AED 450,000" in e.customer_message.en
    assert asyncio.run(_await(e)) == explainer.template_explanation(ALERTS["alert_wire"])


async def _await(x):
    return await x  # legacy `await explain(...)` callers keep working


def test_enrich_without_key_returns_none(monkeypatch):
    async def boom(base):
        raise AssertionError("LLM must not be called without a key")
    monkeypatch.setattr(explainer, "_llm_rewrite", boom)
    assert enrich(ALERTS["alert_burst"]) is None


@pytest.mark.parametrize("exc", [RuntimeError("500"), ValueError("bad json"),
                                 httpx.ReadTimeout("timeout")])
def test_enrich_error_returns_none(monkeypatch, exc):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    async def fail(*a, **kw):
        raise exc
    monkeypatch.setattr(httpx.AsyncClient, "post", fail)
    assert enrich(ALERTS["alert_wire"]) is None


def test_enrich_times_out_in_about_one_second(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    async def hang(*a, **kw):
        await asyncio.sleep(30)
    monkeypatch.setattr(httpx.AsyncClient, "post", hang)
    start = time.perf_counter()
    assert enrich(ALERTS["alert_wire"]) is None
    assert 0.9 <= time.perf_counter() - start < 1.5


def test_enrich_result_cached(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    calls = []

    async def rewrite(base):
        calls.append(1)
        return POLISHED
    monkeypatch.setattr(explainer, "_llm_rewrite", rewrite)
    first = enrich(ALERTS["alert_wire"])
    second = enrich(ALERTS["alert_wire"])
    assert first == second == POLISHED
    assert len(calls) == 1
    enrich(ALERTS["alert_burst"])
    assert len(calls) == 2
