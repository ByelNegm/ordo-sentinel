"""BLACKBOX HTTP/SSE wiring. One process, synthetic data, no production authorization."""
import asyncio
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .incident import ActionError
from .models import (ActorRequest, AuditRecord, FaultResponse, Incident, IntegrityReport,
                     JournalEntry, Overview, PaymentInstruction, Service, SettlementEvent,
                     TrafficStatus)
from .traffic import Runtime

HEARTBEAT_SECONDS = 15


def create_app(*, traffic_interval: float = 1.5, step_delay: float = 1.0) -> FastAPI:
    runtime = Runtime(traffic_interval, step_delay)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await runtime.stop()

    app = FastAPI(title="BLACKBOX", lifespan=lifespan)
    app.state.runtime = runtime
    app.add_middleware(CORSMiddleware,
                       allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.exception_handler(ActionError)
    async def action_error(request: Request, exc: ActionError):
        return JSONResponse(status_code=exc.status, content={"detail": exc.detail})

    @app.get("/api/overview", response_model=Overview)
    async def overview():
        async with runtime.lock:
            return runtime.overview()

    @app.get("/api/payments", response_model=list[PaymentInstruction])
    async def payments(limit: int = Query(50, ge=1)):
        async with runtime.lock:
            return list(reversed(list(runtime.bank.instructions.values())))[:limit]

    @app.get("/api/settlements", response_model=list[SettlementEvent])
    async def settlements(limit: int = Query(50, ge=1)):
        async with runtime.lock:
            return list(reversed(runtime.bank.events))[:limit]

    @app.get("/api/ledger", response_model=list[JournalEntry])
    async def ledger(limit: int = Query(100, ge=1)):
        async with runtime.lock:
            return list(reversed(runtime.bank.ledger.entries))[:limit]

    @app.get("/api/integrity", response_model=IntegrityReport)
    async def integrity():
        async with runtime.lock:
            return runtime.coordinator.report()

    @app.get("/api/incidents", response_model=list[Incident])
    async def incidents():
        async with runtime.lock:
            return list(reversed(list(runtime.coordinator.incidents.values())))

    @app.get("/api/incidents/{identifier}", response_model=Incident)
    async def incident(identifier: str):
        async with runtime.lock:
            return runtime.coordinator.get(identifier)

    @app.get("/api/audit", response_model=list[AuditRecord])
    async def audit(limit: int = Query(100, ge=1)):
        async with runtime.lock:
            return list(reversed(runtime.coordinator.audit))[:limit]

    @app.post("/api/reset", response_model=Overview)
    async def reset():
        return await runtime.reset()

    @app.post("/api/traffic/start", response_model=TrafficStatus)
    async def traffic_start():
        return await runtime.set_traffic(True)

    @app.post("/api/traffic/stop", response_model=TrafficStatus)
    async def traffic_stop():
        return await runtime.set_traffic(False)

    @app.post("/api/faults/{kind}", response_model=FaultResponse)
    async def fault(kind: Literal["duplicate", "missing", "tamper"]):
        return await runtime.inject(kind)

    @app.post("/api/incidents/{identifier}/approve", response_model=Incident)
    async def approve(identifier: str, body: ActorRequest):
        async with runtime.lock:
            return await runtime.coordinator.approve(identifier, body.actor)

    @app.post("/api/incidents/{identifier}/reject", response_model=Incident)
    async def reject(identifier: str, body: ActorRequest):
        async with runtime.lock:
            return await runtime.coordinator.reject(identifier, body.actor)

    @app.post("/api/services/settlement-svc/release", response_model=Service)
    async def release():
        return await runtime.release()

    @app.get("/api/stream")
    async def stream(request: Request):
        async def frames():
            async with runtime.bus.subscribe() as queue:
                yield ": connected\n\n"
                while not await request.is_disconnected():
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                        yield (f"event: {event.type}\n"
                               f"data: {event.model_dump_json(by_alias=True)}\n\n")
                    except asyncio.TimeoutError:
                        yield ": heartbeat\n\n"
        return StreamingResponse(frames(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


app = create_app()
