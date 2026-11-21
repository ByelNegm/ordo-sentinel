"""Lead-owned HTTP wiring; run one worker because demo state is process-local."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .bank import Bank, BankError, FIXTURES
from .bus import EventBus
from .models import (AccountUpdated, AccountUpdatedEvent, Alert, AlertResolved,
                     AlertResolvedEvent, DecisionRequest, ScenarioStatus,
                     ScenarioStatusEvent, State, Txn)
from .scenario import ScenarioRunner

HEARTBEAT_SECONDS = 15


def create_app() -> FastAPI:
    bank, bus = Bank(), EventBus()
    runner = ScenarioRunner(bank, bus)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await runner.stop()

    app = FastAPI(title="Ordo Sentinel", lifespan=lifespan)
    app.state.bank, app.state.bus, app.state.runner = bank, bus, runner
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    app.mount("/fixtures", StaticFiles(directory=FIXTURES), name="fixtures")

    @app.exception_handler(BankError)
    async def bank_error(request: Request, exc: BankError):
        return JSONResponse(status_code=exc.status, content={"detail": exc.detail})

    @app.get("/api/state", response_model=State)
    async def state():
        return bank.snapshot()

    @app.get("/api/transactions", response_model=list[Txn])
    async def transactions(limit: int = Query(50, ge=1, le=200)):
        return sorted(bank.transactions.values(), key=lambda t: t.ts, reverse=True)[:limit]

    @app.get("/api/alerts", response_model=list[Alert])
    async def alerts():
        return list(bank.alerts.values())

    @app.post("/api/scenario/{name}/start", response_model=ScenarioStatus)
    async def start(name: Literal["normal", "drain"]):
        if runner.running:
            raise BankError(409, "Scenario already running")
        return runner.start(name)

    @app.post("/api/reset", response_model=State)
    async def reset():
        await runner.stop()
        result = bank.reset()
        now = datetime.now(timezone.utc)
        await bus.publish(AccountUpdatedEvent(ts=now, data=bank.account_update()))
        await bus.publish(ScenarioStatusEvent(ts=now, data=ScenarioStatus(name="idle", step=0, total=0)))
        return result

    @app.post("/api/alerts/{alert_id}/decision", response_model=AlertResolved)
    async def decision(alert_id: str, body: DecisionRequest):
        result = bank.resolve(alert_id, body.decision)
        now = datetime.now(timezone.utc)
        await bus.publish(AlertResolvedEvent(ts=now, data=result))
        await bus.publish(AccountUpdatedEvent(ts=now, data=bank.account_update()))
        return result

    @app.post("/api/clients/{client_id}/unfreeze", response_model=AccountUpdated)
    async def unfreeze(client_id: str):
        result = bank.unfreeze(client_id)
        await bus.publish(AccountUpdatedEvent(ts=datetime.now(timezone.utc), data=result))
        return result

    @app.get("/api/stream")
    async def stream(request: Request):
        async def frames():
            async with bus.subscribe() as queue:
                yield ": connected\n\n"
                while not await request.is_disconnected():
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                        yield f"data: {event.model_dump_json()}\n\n"
                    except asyncio.TimeoutError:
                        yield ": heartbeat\n\n"
        return StreamingResponse(frames(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


app = create_app()
