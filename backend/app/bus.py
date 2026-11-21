"""Lead-owned process-local fanout. Subscribe before publishing; no replay guarantee."""
import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from .models import Event


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[Event]] = set()

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[Event]]:
        """Yield a bounded subscriber queue; slow consumers reconnect via snapshots."""
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    async def publish(self, event: Event) -> None:
        """Fan out without letting a disconnected/slow browser block policy."""
        for queue in tuple(self._subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event.model_copy(deep=True))
