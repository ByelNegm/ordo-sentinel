import json
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import pytest
from pydantic import TypeAdapter

from app.models import Event


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
                if httpx.get(url + "/api/overview", timeout=0.5).status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.05)
        else:
            pytest.fail("uvicorn did not become ready")
        yield url
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()


def test_named_sse_frames_heartbeat_and_complete_lifecycle(live_url):
    adapter = TypeAdapter(Event)
    with httpx.Client(base_url=live_url, timeout=20) as client:
        with client.stream("GET", "/api/stream") as response:
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-cache"
            assert response.headers["x-accel-buffering"] == "no"
            assert response.headers["content-type"].startswith("text/event-stream")
            lines = response.iter_lines()
            assert next(lines) == ": connected"
            start = time.monotonic()
            for line in lines:
                if line == ": heartbeat":
                    assert time.monotonic() - start >= 14
                    break
            assert client.post("/api/faults/duplicate").status_code == 200
            assert client.post("/api/traffic/start").status_code == 200
            states, types, incidents = [], set(), []
            name = None
            for line in lines:
                if line.startswith("event: "):
                    name = line[7:]
                if not line.startswith("data: "):
                    continue
                envelope = json.loads(line[6:])
                adapter.validate_python(envelope)
                assert envelope["type"] == name
                types.add(name)
                if name == "incident.updated":
                    incidents.append(envelope["data"])
                    states.append(envelope["data"]["status"])
                    if envelope["data"]["status"] == "awaiting_approval":
                        identifier = envelope["data"]["id"]
                        assert client.post("/api/traffic/stop").status_code == 200
                        assert client.post("/api/incidents/" + identifier + "/approve",
                                           json={"actor": "ops.lead@bank"}).json()["status"] == "resolved"
                        assert client.post("/api/services/settlement-svc/release").status_code == 200
                        assert client.post("/api/reset").status_code == 200
                if name == "reset":
                    break
            assert {"payment.accepted", "settlement.posted", "integrity.updated", "incident.updated",
                    "service.updated", "audit.appended", "reset"} <= types
            expected = ["detected", "investigating", "contained", "validating",
                        "awaiting_approval", "correcting", "resolved"]
            distinct = [state for i, state in enumerate(states) if i == 0 or state != states[i - 1]]
            assert distinct == expected
            assert incidents[-1]["verification"]["status"] == "healthy"
