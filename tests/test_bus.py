"""Tests for events.bus.EventBus."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from events.bus import EventBus
from events.models import StatusEvent


def _make_event(provider: str = "TestProvider") -> StatusEvent:
    return StatusEvent(
        provider=provider,
        product="TestProduct",
        status="Investigating",
        message="Something happened.",
        timestamp=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        incident_id="inc-test",
        event_type="new",
    )


@pytest.mark.asyncio
async def test_publish_subscribe(event_bus: EventBus) -> None:
    """A subscriber should receive an event that is published."""
    received: list[StatusEvent] = []
    event = _make_event()

    async def consume() -> None:
        async for e in event_bus.subscribe():
            received.append(e)
            break  # stop after first event

    consumer_task = asyncio.create_task(consume())
    # Small delay to let the subscriber register.
    await asyncio.sleep(0.05)
    await event_bus.publish(event)
    await asyncio.wait_for(consumer_task, timeout=2.0)

    assert len(received) == 1
    assert received[0] is event


@pytest.mark.asyncio
async def test_fan_out_multiple_subscribers(event_bus: EventBus) -> None:
    """Multiple subscribers should each receive every published event."""
    received_a: list[StatusEvent] = []
    received_b: list[StatusEvent] = []
    event = _make_event()

    async def consume(dest: list[StatusEvent]) -> None:
        async for e in event_bus.subscribe():
            dest.append(e)
            break

    task_a = asyncio.create_task(consume(received_a))
    task_b = asyncio.create_task(consume(received_b))
    await asyncio.sleep(0.05)

    await event_bus.publish(event)
    await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=2.0)

    assert len(received_a) == 1
    assert len(received_b) == 1
    assert received_a[0] is event
    assert received_b[0] is event


@pytest.mark.asyncio
async def test_subscriber_cleanup_after_close(event_bus: EventBus) -> None:
    """When an async generator is closed, the subscriber queue is removed."""
    gen = event_bus.subscribe()
    # Advance the generator to register the subscription.
    sub = gen.__aiter__()
    # We need to actually enter the generator to register it.
    # Start it in a task that will break after first event.
    received: list[StatusEvent] = []

    async def consume() -> None:
        async for e in gen:
            received.append(e)
            break
        # Explicitly close the generator to trigger the finally block.
        await gen.aclose()

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    assert event_bus.size() == 1

    # Publish an event so the consumer can break out.
    await event_bus.publish(_make_event())
    await asyncio.wait_for(task, timeout=2.0)

    # After the generator closes, give a moment for cleanup.
    await asyncio.sleep(0.05)
    assert event_bus.size() == 0


@pytest.mark.asyncio
async def test_size_reflects_active_subscribers(event_bus: EventBus) -> None:
    """size() should match the number of active subscriber queues."""
    assert event_bus.size() == 0

    events_received: list[list[StatusEvent]] = [[], []]

    async def consume(dest: list[StatusEvent]) -> None:
        async for e in event_bus.subscribe():
            dest.append(e)
            break

    task1 = asyncio.create_task(consume(events_received[0]))
    await asyncio.sleep(0.05)
    assert event_bus.size() == 1

    task2 = asyncio.create_task(consume(events_received[1]))
    await asyncio.sleep(0.05)
    assert event_bus.size() == 2

    # Publish to let both consumers finish.
    await event_bus.publish(_make_event())
    await asyncio.wait_for(asyncio.gather(task1, task2), timeout=2.0)
    await asyncio.sleep(0.05)
    assert event_bus.size() == 0
