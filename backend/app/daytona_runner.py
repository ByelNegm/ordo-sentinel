"""Optional remote confirmation of an authoritative local, isolated validation."""
import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

from .models import SandboxReport

REPORT_FIELDS = {"passed", "checks_before", "checks_after", "balances_before", "balances_after"}
WORKSPACE = "/home/daytona/blackbox"


def financial_result(report: SandboxReport) -> dict:
    return report.model_dump(mode="json", by_alias=True, include=REPORT_FIELDS)


class DaytonaValidator:
    def __init__(self, timeout: float = 8.0) -> None:
        self.key = os.getenv("DAYTONA_API_KEY")
        self.enabled = bool(self.key) and os.getenv("BLACKBOX_DAYTONA") != "0"
        self.timeout = timeout
        self.client = None
        self.sandbox = None
        self.ready = False
        self.task: asyncio.Task | None = None
        self.note = ("warming up" if self.enabled else
                     "disabled by BLACKBOX_DAYTONA=0" if os.getenv("BLACKBOX_DAYTONA") == "0"
                     else "DAYTONA_API_KEY not configured")
        self.lock = asyncio.Lock()

    def start(self) -> None:
        if self.enabled and self.task is None:
            self.task = asyncio.create_task(self._warm())

    def _error(self, error: Exception) -> str:
        message = str(error)
        if self.key:
            message = message.replace(self.key, "[redacted]")
        return f"{type(error).__name__}: {message}"[:240]

    async def _warm(self) -> None:
        try:
            await asyncio.wait_for(self._prepare(), timeout=90)
            self.ready = True
            self.note = "ready"
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.note = self._error(error)

    async def _prepare(self) -> None:
        from daytona import AsyncDaytona, DaytonaConfig
        from daytona.v0 import CreateSandboxFromSnapshotParams

        self.client = AsyncDaytona(DaytonaConfig(api_key=self.key, otel_enabled=False))
        self.sandbox = await self.client.v0.create(CreateSandboxFromSnapshotParams(
            language="python", public=False, auto_stop_interval=15,
            auto_delete_interval=1, ttl_minutes=60,
            labels={"app": "blackbox-validation"},
        ), timeout=60)
        result = await self.sandbox.process.exec(
            f"mkdir -p {WORKSPACE}/app && python -m pip install -q 'pydantic>=2.9,<3'",
            timeout=45,
        )
        if result.exit_code != 0:
            raise RuntimeError("Remote Python dependency preparation failed")
        root = Path(__file__).parent
        await self.sandbox.fs.upload_file(b"", f"{WORKSPACE}/app/__init__.py", timeout=10)
        for name in ("models.py", "ledger.py", "bank.py", "integrity.py", "remote_check.py"):
            await self.sandbox.fs.upload_file(
                (root / name).read_bytes(), f"{WORKSPACE}/app/{name}", timeout=10)

    async def validate(self, payload: dict, local: SandboxReport) -> SandboxReport:
        result = local.model_copy(deep=True)
        result.runner = "local"
        result.runner_id = None
        result.remote_match = None
        result.runner_note = self.note
        if not self.ready:
            return result
        if not local.passed:
            result.runner_note = "Local proposal validation failed; remote confirmation skipped"
            return result
        try:
            remote = await asyncio.wait_for(self._serialized_run(payload), timeout=self.timeout)
            parsed = SandboxReport.model_validate(remote)
            if financial_result(parsed) != financial_result(local):
                result.remote_match = False
                result.runner_note = "Remote result differed; authoritative local validation retained"
                return result
            result.runner = "daytona"
            result.runner_id = self.sandbox.id
            result.remote_match = True
            result.runner_note = "All seven remote checks and copied balances match local validation"
        except asyncio.TimeoutError:
            result.runner_note = f"Remote validation timed out after {self.timeout:g}s"
        except Exception as error:
            result.runner_note = self._error(error)
        return result

    async def _serialized_run(self, payload: dict) -> dict:
        async with self.lock:
            path = f"{WORKSPACE}/validation-{uuid4().hex}.json"
            await self.sandbox.fs.upload_file(
                json.dumps(payload).encode(), path, timeout=6)
            response = await self.sandbox.process.exec(
                f"python -m app.remote_check {path}", cwd=WORKSPACE, timeout=7)
            if response.exit_code != 0:
                raise RuntimeError("Remote integrity checker exited unsuccessfully")
            return json.loads(response.result)

    async def close(self) -> None:
        self.ready = False
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        try:
            if self.sandbox is not None:
                await asyncio.wait_for(
                    self.client.v0.delete(self.sandbox, timeout=10), timeout=12)
                self.sandbox = None
        except Exception as error:
            self.note = "Cleanup: " + self._error(error)
        finally:
            if self.client is not None:
                await self.client.close()
                self.client = None
