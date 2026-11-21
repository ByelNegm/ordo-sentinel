import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.bank import FIXTURES, Bank
from app.main import create_app
from app.models import (EVENT_ADAPTER, AccountUpdated, Alert, AlertResolved,
                        ScenarioStatus, State, Txn)
from app.policy import PolicyContext, decide


@pytest.fixture
def client():
    app = create_app()
    app.state.runner.pace = 0.02
    with TestClient(app) as client:
        yield client


def wait_done(client):
    deadline = time.monotonic() + 2
    while client.app.state.runner.running and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not client.app.state.runner.running
    task = client.app.state.runner.task
    if task:
        assert task.exception() is None


def drain(client):
    response = client.post("/api/scenario/drain/start")
    assert response.status_code == 200
    ScenarioStatus.model_validate(response.json())
    wait_done(client)


def test_fixtures_validate():
    State.model_validate_json((FIXTURES / "state.json").read_text())
    for item in json.loads((FIXTURES / "transactions.json").read_text()):
        Txn.model_validate(item)
    for item in json.loads((FIXTURES / "alerts.json").read_text()):
        Alert.model_validate(item)
    for line in (FIXTURES / "events.ndjson").read_text().splitlines():
        EVENT_ADAPTER.validate_json(line)
    bad = json.loads((FIXTURES / "state.json").read_text())
    bad["unexpected"] = True
    with pytest.raises(ValidationError):
        State.model_validate(bad)


def test_initial_empty_state_and_fixture_serving(client):
    assert State.model_validate(client.get("/api/state").json()).account.balance == 520000
    assert client.get("/api/transactions").json() == []
    assert client.get("/api/alerts").json() == []
    assert client.get("/fixtures/state.json").json()["scenario"] == "idle"
    assert client.get("/api/transactions?limit=0").status_code == 422
    assert client.get("/api/transactions?limit=201").status_code == 422
    assert client.post("/api/scenario/invalid/start").status_code == 422
    assert client.post("/api/alerts/missing/decision", json={"decision": "deny"}).status_code == 404
    assert client.post("/api/alerts/missing/decision", json={"decision": "other"}).status_code == 422
    assert client.post("/api/clients/missing/unfreeze").status_code == 404


def test_normal_drain_deny_and_reset(client):
    assert client.post("/api/scenario/normal/start").json() == {"name": "normal", "step": 0, "total": 3}
    wait_done(client)
    assert client.get("/api/state").json()["account"]["balance"] == 519915
    drain(client)
    txns = [Txn.model_validate(t) for t in client.get("/api/transactions").json()]
    assert txns[0].id == "txn_wire" and txns[0].status == "blocked"
    assert len(client.get("/api/transactions?limit=1").json()) == 1
    alerts = [Alert.model_validate(a) for a in client.get("/api/alerts").json()]
    assert {a.id for a in alerts} == {"alert_burst", "alert_wire"}
    assert client.get("/api/state").json()["account"]["held"] == 3000
    assert client.post("/api/alerts/alert_wire/decision", json={"decision": "confirm"}).status_code == 409
    response = client.post("/api/alerts/alert_wire/decision", json={"decision": "deny"})
    assert AlertResolved.model_validate(response.json()).resolution == "denied"
    assert client.post("/api/alerts/alert_wire/decision", json={"decision": "deny"}).status_code == 200
    state = State.model_validate(client.get("/api/state").json())
    assert state.protected_amount == 450000 and state.account.balance == 519915
    assert state.account.available == 516915
    assert state.frozen_clients == ["api_partner_7"]
    assert client.post("/api/alerts/alert_wire/decision", json={"decision": "confirm"}).status_code == 409
    response = client.post("/api/clients/api_partner_7/unfreeze")
    assert AccountUpdated.model_validate(response.json()).frozen_clients == []
    assert client.post("/api/clients/api_partner_7/unfreeze").status_code == 200
    assert client.post("/api/alerts/alert_wire/decision", json={"decision": "confirm"}).status_code == 409
    response = client.post("/api/alerts/alert_burst/decision", json={"decision": "deny"})
    assert response.status_code == 200
    assert client.get("/api/state").json()["protected_amount"] == 453000
    assert client.get("/api/state").json()["account"]["held"] == 0
    assert client.get("/api/alerts").json() == []
    reset = State.model_validate(client.post("/api/reset").json())
    assert reset.scenario == "idle" and reset.account.balance == 520000
    assert reset.protected_amount == 0 and reset.frozen_clients == []
    assert client.get("/api/transactions").json() == []


def test_confirm_eligible_holds(client):
    drain(client)
    client.post("/api/clients/api_partner_7/unfreeze")
    response = client.post("/api/alerts/alert_burst/decision", json={"decision": "confirm"})
    assert AlertResolved.model_validate(response.json()).resolution == "confirmed"
    account = client.get("/api/state").json()["account"]
    assert account["balance"] == account["available"] == 517000
    assert account["held"] == 0


def test_overlap_and_cancel_reset(client):
    client.app.state.runner.pace = 1
    assert client.post("/api/scenario/drain/start").status_code == 200
    assert client.post("/api/scenario/normal/start").status_code == 409
    assert client.post("/api/reset").status_code == 200
    time.sleep(0.15)
    assert client.get("/api/transactions").json() == []
    assert not client.app.state.runner.running


@pytest.mark.parametrize("value,expected", [(39, "allow"), (40, "hold"), (75, "hold"), (76, "freeze")])
def test_policy_boundaries(value, expected):
    risk = Bank().catalog[0].risk.model_copy(update={"score": value})
    assert decide(risk, PolicyContext(520000, 1000)) == expected
    assert decide(risk, PolicyContext(520000, 156001)) == "freeze"


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:5173"])
def test_cors(client, origin):
    response = client.options("/api/reset", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST"})
    assert response.headers["access-control-allow-origin"] == origin


@pytest.fixture
def live_url():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail(process.stderr.read().decode())
            try:
                if httpx.get(url + "/api/state", timeout=0.2).status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.05)
        else:
            pytest.fail("uvicorn did not become ready in 10 seconds")
        yield url
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()


def test_sse_drain_and_heartbeat(live_url):
    with httpx.Client(base_url=live_url, timeout=20) as client:
        with client.stream("GET", "/api/stream") as response:
            assert response.status_code == 200
            assert response.headers["x-accel-buffering"] == "no"
            assert response.headers["cache-control"] == "no-cache"
            assert response.headers["content-type"].startswith("text/event-stream")
            lines = response.iter_lines()
            assert next(lines) == ": connected"
            assert client.post("/api/scenario/drain/start").status_code == 200
            seen = []
            deadline = time.monotonic() + 19
            for line in lines:
                assert time.monotonic() < deadline
                if line.startswith("data: "):
                    event = EVENT_ADAPTER.validate_json(line[6:])
                    seen.append(event)
                if line == ": heartbeat":
                    break
            assert any(e.type == "txn.scored" and e.data.id == "txn_wire" for e in seen)
            assert any(e.type == "account.updated" and e.data.frozen_clients for e in seen)
            assert line == ": heartbeat"
