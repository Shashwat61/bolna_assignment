from __future__ import annotations

import asyncio
from typing import AsyncGenerator

from events.models import StatusEvent


class EventBus:
    """Fan-out event bus backed by :class:`asyncio.Queue`.

    Every call to :meth:`subscribe` creates a dedicated queue.  When an event
    is published via :meth:`publish`, it is placed into **every** subscriber
    queue so that multiple independent consumers each receive a copy.
    """

    def __init__(self) -> None:
        self._subscriber_queues: list[asyncio.Queue[StatusEvent]] = []
        self._lock = asyncio.Lock()

    async def publish(self, event: StatusEvent) -> None:
        """Broadcast *event* to all current subscribers."""
        async with self._lock:
            for queue in self._subscriber_queues:
                await queue.put(event)

    async def subscribe(self) -> AsyncGenerator[StatusEvent, None]:
        """Create a new subscription and yield events as they arrive.

        The returned async generator will block on each iteration until the
        next event is published.  It is safe to have many concurrent
        subscriptions — each one receives every event independently.
        """
        queue: asyncio.Queue[StatusEvent] = asyncio.Queue()
        async with self._lock:
            self._subscriber_queues.append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            async with self._lock:
                self._subscriber_queues.remove(queue)

    def size(self) -> int:
        """Return the number of active subscriber queues."""
        return len(self._subscriber_queues)
