"""Tests for core.scheduler.PollScheduler."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.fetcher import FetchResult
from core.scheduler import PollScheduler, _STAGGER_DELAY
from core.state import StateManager
from events.bus import EventBus


def _make_fetch_result(
    status_code: int = 200,
    content: str | None = "<feed></feed>",
    etag: str | None = None,
    last_modified: str | None = None,
) -> FetchResult:
    return FetchResult(
        status_code=status_code,
        content=content,
        etag=etag,
        last_modified=last_modified,
    )


def _make_provider(name: str = "TestProvider", interval: int = 30) -> dict:
    return {
        "name": name,
        "feed_url": f"https://status.example.com/{name}/feed.atom",
        "poll_interval_seconds": interval,
    }


@pytest.mark.asyncio
async def test_start_creates_tasks() -> None:
    """start() should create one task per provider."""
    event_bus = EventBus()
    state_manager = StateManager()
    fetcher = MagicMock()
    fetcher.fetch = AsyncMock(return_value=_make_fetch_result(status_code=304, content=None))

    providers = [_make_provider("Provider1"), _make_provider("Provider2")]
    scheduler = PollScheduler(
        providers=providers,
        event_bus=event_bus,
        fetcher=fetcher,
        state_manager=state_manager,
    )

    await scheduler.start()
    assert len(scheduler._tasks) == 2
    # Cleanup
    await scheduler.stop()


@pytest.mark.asyncio
async def test_stop_cancels_all_tasks() -> None:
    """stop() should cancel and clear all tasks."""
    event_bus = EventBus()
    state_manager = StateManager()
    fetcher = MagicMock()
    fetcher.fetch = AsyncMock(return_value=_make_fetch_result(status_code=304, content=None))

    scheduler = PollScheduler(
        providers=[_make_provider()],
        event_bus=event_bus,
        fetcher=fetcher,
        state_manager=state_manager,
    )

    await scheduler.start()
    assert len(scheduler._tasks) == 1

    await scheduler.stop()
    assert len(scheduler._tasks) == 0


@pytest.mark.asyncio
async def test_exponential_backoff_on_failure() -> None:
    """When the fetcher raises, sleep time should increase exponentially."""
    event_bus = EventBus()
    state_manager = StateManager()
    fetcher = MagicMock()
    # Fetcher always raises an exception.
    fetcher.fetch = AsyncMock(side_effect=RuntimeError("network error"))

    provider = _make_provider(interval=10)
    scheduler = PollScheduler(
        providers=[provider],
        event_bus=event_bus,
        fetcher=fetcher,
        state_manager=state_manager,
    )

    sleep_times: list[float] = []

    original_sleep = asyncio.sleep

    async def mock_sleep(delay: float) -> None:
        sleep_times.append(delay)
        # Only let a few iterations run, then cancel.
        if len(sleep_times) >= 3:
            raise asyncio.CancelledError()
        # For stagger delay, use original.
        if delay == _STAGGER_DELAY:
            return

    with patch("core.scheduler.asyncio.sleep", side_effect=mock_sleep):
        with patch("core.scheduler.random.uniform", return_value=0):
            await scheduler.start()
            # Wait for tasks to run.
            try:
                await asyncio.gather(*scheduler._tasks, return_exceptions=True)
            except asyncio.CancelledError:
                pass

    # Filter out stagger delays.
    backoff_times = [t for t in sleep_times if t != _STAGGER_DELAY]
    # With failure_count 1, 2, 3: backoff = 10*2^1=20, 10*2^2=40, 10*2^3=80
    assert len(backoff_times) >= 2
    assert backoff_times[0] < backoff_times[1], (
        f"Expected increasing backoff: {backoff_times}"
    )


@pytest.mark.asyncio
async def test_successful_poll_resets_failure_count() -> None:
    """After a successful poll, the next sleep should use the base interval (no backoff)."""
    event_bus = EventBus()
    state_manager = StateManager()
    fetcher = MagicMock()

    call_count = 0

    async def fetch_side_effect(*args, **kwargs) -> FetchResult:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("temporary failure")
        # Return 304 for subsequent calls (no content to parse).
        return _make_fetch_result(status_code=304, content=None)

    fetcher.fetch = AsyncMock(side_effect=fetch_side_effect)

    provider = _make_provider(interval=10)
    scheduler = PollScheduler(
        providers=[provider],
        event_bus=event_bus,
        fetcher=fetcher,
        state_manager=state_manager,
    )

    sleep_times: list[float] = []

    async def mock_sleep(delay: float) -> None:
        sleep_times.append(delay)
        if len(sleep_times) >= 3:
            raise asyncio.CancelledError()

    with patch("core.scheduler.asyncio.sleep", side_effect=mock_sleep):
        with patch("core.scheduler.random.uniform", return_value=0):
            await scheduler.start()
            try:
                await asyncio.gather(*scheduler._tasks, return_exceptions=True)
            except asyncio.CancelledError:
                pass

    backoff_times = [t for t in sleep_times if t != _STAGGER_DELAY]
    # First call fails -> backoff = 10*2^1 = 20
    # Second call succeeds -> sleep = 10 (base interval, jitter=0)
    assert len(backoff_times) >= 2
    assert backoff_times[0] == 20  # failure backoff
    assert backoff_times[1] == 10  # reset to base interval


@pytest.mark.asyncio
async def test_staggered_startup_timing() -> None:
    """Tasks should be started with a stagger delay between them."""
    event_bus = EventBus()
    state_manager = StateManager()
    fetcher = MagicMock()
    fetcher.fetch = AsyncMock(return_value=_make_fetch_result(status_code=304, content=None))

    providers = [_make_provider("A"), _make_provider("B"), _make_provider("C")]

    sleep_calls: list[float] = []

    original_sleep = asyncio.sleep

    async def tracking_sleep(delay: float) -> None:
        sleep_calls.append(delay)
        # Let stagger delays proceed immediately.
        if delay == _STAGGER_DELAY:
            return
        # Cancel the polling loop after first poll.
        raise asyncio.CancelledError()

    scheduler = PollScheduler(
        providers=providers,
        event_bus=event_bus,
        fetcher=fetcher,
        state_manager=state_manager,
    )

    with patch("core.scheduler.asyncio.sleep", side_effect=tracking_sleep):
        await scheduler.start()
        try:
            await asyncio.gather(*scheduler._tasks, return_exceptions=True)
        except asyncio.CancelledError:
            pass

    # There should be stagger delays between the 2nd and 3rd provider launches.
    stagger_calls = [t for t in sleep_calls if t == _STAGGER_DELAY]
    assert len(stagger_calls) >= 2, (
        f"Expected at least 2 stagger delays for 3 providers, got {stagger_calls}"
    )
