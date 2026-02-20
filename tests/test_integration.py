"""End-to-end integration test for the Status Page Monitor pipeline.

Creates all core components, publishes a mock feed response, and verifies
that the ConsoleConsumer receives and correctly formats the resulting events.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from consumers.console import ConsoleConsumer
from core.fetcher import FeedFetcher, FetchResult
from core.parser import FeedParser
from core.scheduler import PollScheduler
from core.state import StateManager
from events.bus import EventBus


SAMPLE_FEED = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>TestProvider Status</title>
  <updated>2025-06-15T12:00:00Z</updated>
  <entry>
    <id>incident-integration-001</id>
    <title>Service disruption</title>
    <updated>2025-06-15T10:30:00+00:00</updated>
    <summary type="html">
      &lt;p&gt;We are investigating a service disruption.&lt;/p&gt;
      &lt;p&gt;Affected components: API, Dashboard&lt;/p&gt;
    </summary>
  </entry>
</feed>
"""


@pytest.mark.asyncio
async def test_end_to_end_pipeline() -> None:
    """Full pipeline: fetch -> parse -> state check -> publish -> consume."""
    # -- Setup components --
    event_bus = EventBus()
    state_manager = StateManager()

    # Mock fetcher that returns our sample feed once, then 304s.
    fetcher = MagicMock(spec=FeedFetcher)
    call_count = 0

    async def mock_fetch(*args, **kwargs) -> FetchResult:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return FetchResult(
                status_code=200,
                content=SAMPLE_FEED,
                etag='"test-etag"',
                last_modified="Sun, 15 Jun 2025 12:00:00 GMT",
            )
        return FetchResult(
            status_code=304,
            content=None,
            etag='"test-etag"',
            last_modified="Sun, 15 Jun 2025 12:00:00 GMT",
        )

    fetcher.fetch = AsyncMock(side_effect=mock_fetch)

    provider_cfg = {
        "name": "IntegrationTest",
        "product": "IntegrationTest API",
        "feed_url": "https://status.example.com/feed.atom",
        "poll_interval_seconds": 60,
    }

    scheduler = PollScheduler(
        providers=[provider_cfg],
        event_bus=event_bus,
        fetcher=fetcher,
        state_manager=state_manager,
    )

    # -- Collect events from the bus --
    received_events: list = []

    async def collect_events() -> None:
        async for event in event_bus.subscribe():
            received_events.append(event)
            # The sample feed has 1 entry; product = provider name.
            if len(received_events) >= 1:
                break

    collector_task = asyncio.create_task(collect_events())

    # Give the subscriber time to register.
    await asyncio.sleep(0.05)

    # -- Also test ConsoleConsumer formatting via captured print --
    printed_lines: list[str] = []

    async def consumer_task_fn() -> None:
        consumer = ConsoleConsumer(event_bus=event_bus)
        # We'll subscribe but just collect a couple of events.
        count = 0
        async for event in event_bus.subscribe():
            formatted = consumer._format_event(event)
            printed_lines.append(formatted)
            count += 1
            if count >= 1:
                break

    consumer_task = asyncio.create_task(consumer_task_fn())
    await asyncio.sleep(0.05)

    # -- Run the scheduler for one poll cycle --
    # Patch asyncio.sleep so the poll loop doesn't actually wait.
    poll_count = 0

    async def fast_sleep(delay: float) -> None:
        nonlocal poll_count
        poll_count += 1
        if poll_count >= 2:
            raise asyncio.CancelledError()

    with patch("core.scheduler.asyncio.sleep", side_effect=fast_sleep):
        await scheduler.start()
        try:
            await asyncio.gather(*scheduler._tasks, return_exceptions=True)
        except asyncio.CancelledError:
            pass

    # -- Wait for events to be collected --
    await asyncio.wait_for(collector_task, timeout=5.0)
    await asyncio.wait_for(consumer_task, timeout=5.0)

    # -- Assertions --
    # 1. One event per entry; product = provider name.
    assert len(received_events) == 1

    event = received_events[0]
    assert event.provider == "IntegrationTest"
    assert event.product == "IntegrationTest API - Service disruption"
    assert event.event_type == "new"

    # 2. ConsoleConsumer formatting should include key fields.
    assert len(printed_lines) == 1
    for line in printed_lines:
        assert "[NEW]" in line
        assert "Provider: IntegrationTest" in line
        assert "Service disruption" in line
        assert "-" * 40 in line

    # 3. State manager should have recorded the entry as seen.
    state = state_manager.get_state("IntegrationTest")
    assert "incident-integration-001" in state.seen_entries
    assert state.etag == '"test-etag"'
