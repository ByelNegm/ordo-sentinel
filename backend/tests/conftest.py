import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    with TestClient(create_app(traffic_interval=0.02, step_delay=0, missing_grace=0)) as client:
        yield client


def wait_for(check, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for backend lifecycle")


def awaiting_incident(client):
    def find():
        incidents = client.get("/api/incidents").json()
        assert not any(i["status"] == "failed" for i in incidents), incidents
        return next((i for i in incidents if i["status"] == "awaiting_approval"), None)
    return wait_for(find)


def duplicate_via_http(client):
    assert client.post("/api/faults/duplicate").status_code == 200
    assert client.post("/api/traffic/start").json() == {"running": True}
    incident = awaiting_incident(client)
    wait_for(lambda: client.get("/api/overview").json()["volume"]["held"] > 0)
    assert client.post("/api/traffic/stop").json() == {"running": False}
    return client.get("/api/incidents/" + incident["id"]).json()
