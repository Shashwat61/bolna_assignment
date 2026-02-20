"""Entry point for the Status Page Monitor.

Loads provider configuration, wires up all components, and runs the
async polling loop until interrupted with Ctrl+C.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

import aiohttp
import yaml

from core.fetcher import FeedFetcher
from core.scheduler import PollScheduler
from core.state import StateManager
from events.bus import EventBus
from consumers.console import ConsoleConsumer

_CONFIG_PATH = Path(__file__).parent / "config" / "providers.yaml"
_MAX_CONCURRENT_REQUESTS = 20

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _load_providers(path: Path) -> list[dict]:
    """Read the YAML provider registry and return the provider list."""
    with open(path) as fh:
        config = yaml.safe_load(fh)
    providers = config.get("providers", [])
    logger.info("Loaded %d provider(s) from %s", len(providers), path)
    return providers


async def main() -> None:
    providers = _load_providers(_CONFIG_PATH)
    if not providers:
        logger.error("No providers configured — exiting")
        sys.exit(1)

    event_bus = EventBus()
    state_manager = StateManager()
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)

    async with aiohttp.ClientSession() as session:
        fetcher = FeedFetcher(semaphore=semaphore, session=session)
        scheduler = PollScheduler(
            providers=providers,
            event_bus=event_bus,
            fetcher=fetcher,
            state_manager=state_manager,
        )
        consumer = ConsoleConsumer(event_bus=event_bus)

        # Run consumer in background, then start the scheduler.
        consumer_task = asyncio.create_task(consumer.start(), name="console-consumer")
        await scheduler.start()

        # Wait until interrupted.
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)

        logger.info("Status Page Monitor running — press Ctrl+C to stop")
        await stop_event.wait()

        # Graceful shutdown.
        logger.info("Shutting down…")
        await scheduler.stop()
        await consumer.stop()
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass

    logger.info("Goodbye")


if __name__ == "__main__":
    asyncio.run(main())
