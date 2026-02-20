"""Console consumer — prints formatted status events to stdout."""

from __future__ import annotations

import abc
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from events.bus import EventBus
    from events.models import StatusEvent

logger = logging.getLogger(__name__)


class Consumer(abc.ABC):
    """Abstract base class that every event consumer must implement."""

    @abc.abstractmethod
    async def start(self) -> None:
        """Begin consuming events.  Runs until :meth:`stop` is called."""

    @abc.abstractmethod
    async def stop(self) -> None:
        """Signal the consumer to shut down gracefully."""


class ConsoleConsumer(Consumer):
    """Subscribes to an :class:`EventBus` and prints each event to stdout.

    Parameters
    ----------
    event_bus:
        The shared event bus to subscribe to.
    """

    _SEPARATOR = "-" * 40

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._running: bool = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Subscribe to the event bus and print events until stopped."""
        self._running = True
        logger.info("ConsoleConsumer started — waiting for events")

        async for event in self._event_bus.subscribe():
            if not self._running:
                break
            formatted = self._format_event(event)
            print(formatted)

        logger.info("ConsoleConsumer stopped")

    async def stop(self) -> None:
        """Signal the consumer loop to exit after the current event."""
        logger.info("ConsoleConsumer stopping")
        self._running = False

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_event(event: StatusEvent) -> str:
        """Return a human-readable block for *event*.

        Example output::

            [2025-11-03 14:32:00] [NEW] Provider: OpenAI
            Product: Chat Completions
            Status: Degraded performance due to upstream issue
            ----------------------------------------
        """
        tag = "UPDATED" if event.event_type == "updated" else "NEW"
        ts = event.timestamp.strftime("%Y-%m-%d %H:%M:%S")

        return (
            f"[{ts}] [{tag}] Provider: {event.provider}\n"
            f"Product: {event.product}\n"
            f"Status: {event.status}"
            + (f" {event.message}" if event.message else "")
            + f"\n{ConsoleConsumer._SEPARATOR}"
        )
