"""Poll scheduler — spawns and manages one async task per provider.

Each task independently loops: fetch -> parse -> detect changes ->
publish events -> sleep.  Failures in one provider never affect others.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Any

from core.fetcher import FeedFetcher
from core.parser import FeedParser
from core.state import StateManager
from events.bus import EventBus
from events.models import StatusEvent

logger = logging.getLogger(__name__)

_STAGGER_DELAY = 0.3  # seconds between task launches
_MAX_JITTER = 5.0      # max random jitter added to poll interval
_MAX_BACKOFF_EXP = 5   # cap for the exponent in exponential backoff


class PollScheduler:
    """Manages the lifecycle of per-provider polling tasks.

    Parameters
    ----------
    providers:
        List of provider config dicts, each expected to contain at least
        ``name``, ``feed_url``, and ``poll_interval_seconds``.
    event_bus:
        Shared :class:`EventBus` to publish detected status changes.
    fetcher:
        Shared :class:`FeedFetcher` for HTTP requests.
    state_manager:
        Shared :class:`StateManager` that tracks seen entries and caching
        headers.
    """

    def __init__(
        self,
        providers: list[dict[str, Any]],
        event_bus: EventBus,
        fetcher: FeedFetcher,
        state_manager: StateManager,
    ) -> None:
        self._providers = providers
        self._event_bus = event_bus
        self._fetcher = fetcher
        self._state_manager = state_manager
        self._parser = FeedParser()
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        """Spawn a polling task for every configured provider.

        Tasks are started with a small stagger to avoid a thundering-herd
        of HTTP requests at boot time.
        """
        for index, provider_cfg in enumerate(self._providers):
            if index > 0:
                await asyncio.sleep(_STAGGER_DELAY)
            task = asyncio.create_task(
                self._poll_loop(provider_cfg),
                name=f"poll-{provider_cfg.get('name', index)}",
            )
            self._tasks.append(task)
            logger.info(
                "Started polling task for %s (interval=%ss)",
                provider_cfg.get("name"),
                provider_cfg.get("poll_interval_seconds"),
            )

    async def stop(self) -> None:
        """Cancel all running polling tasks and wait for them to finish."""
        for task in self._tasks:
            task.cancel()
        results = await asyncio.gather(*self._tasks, return_exceptions=True)
        for task, result in zip(self._tasks, results):
            if isinstance(result, Exception) and not isinstance(
                result, asyncio.CancelledError
            ):
                logger.error(
                    "Task %s raised during shutdown: %s", task.get_name(), result
                )
        self._tasks.clear()
        logger.info("All polling tasks stopped")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _poll_loop(self, provider_cfg: dict[str, Any]) -> None:
        """Infinite polling loop for a single provider."""
        name: str = provider_cfg["name"]
        product: str = provider_cfg.get("product", name)
        feed_url: str = provider_cfg["feed_url"]
        base_interval: int = provider_cfg.get("poll_interval_seconds", 30)
        failure_count = 0

        while True:
            try:
                await self._poll_once(name, product, feed_url)
                failure_count = 0
                sleep_time = base_interval + random.uniform(0, _MAX_JITTER)
            except asyncio.CancelledError:
                logger.info("Polling task for %s cancelled", name)
                raise
            except Exception:
                failure_count += 1
                backoff = base_interval * (
                    2 ** min(failure_count, _MAX_BACKOFF_EXP)
                )
                sleep_time = backoff + random.uniform(0, _MAX_JITTER)
                logger.exception(
                    "Error polling %s (failure #%d, backing off %.1fs)",
                    name,
                    failure_count,
                    sleep_time,
                )

            await asyncio.sleep(sleep_time)

    async def _poll_once(self, name: str, product: str, feed_url: str) -> None:
        """Execute a single fetch-parse-publish cycle for *name*."""
        state = self._state_manager.get_state(name)

        logger.info("Polling %s — %s", name, feed_url)

        result = await self._fetcher.fetch(
            url=feed_url,
            etag=state.etag,
            last_modified=state.last_modified,
        )

        if result.status_code == 304:
            logger.info("%s: 304 Not Modified — no changes", name)
            return

        logger.info(
            "%s: %d — received %d bytes",
            name,
            result.status_code,
            len(result.content) if result.content else 0,
        )

        # Update caching headers regardless of whether content changed.
        self._state_manager.update_etag(name, result.etag, result.last_modified)

        if result.content is None:
            return

        entries = self._parser.parse(result.content, name)

        for entry in entries:
            changed, change_type = self._state_manager.is_new_or_updated(
                name, entry.entry_id, entry.updated
            )
            if not changed:
                continue

            self._state_manager.mark_seen(name, entry.entry_id, entry.updated)

            # Parse the updated timestamp; fall back to now if unparseable.
            try:
                timestamp = datetime.fromisoformat(entry.updated)
            except (ValueError, TypeError):
                timestamp = datetime.now(tz=timezone.utc)

            event = StatusEvent(
                provider=name,
                product=f"{product} - {entry.title}",
                status=entry.title,
                message=entry.summary,
                timestamp=timestamp,
                incident_id=entry.entry_id,
                event_type=change_type,  # type: ignore[arg-type]
            )
            await self._event_bus.publish(event)
            logger.info(
                "%s event for %s — %s",
                change_type.upper(),
                name,
                entry.title,
            )
            logger.info(
                "Event detail — id=%s, product=%s, status=%s, summary=%.200s",
                event.incident_id,
                event.product,
                event.status,
                event.message,
            )
