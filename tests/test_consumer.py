"""Tests for consumers.console.ConsoleConsumer and Consumer ABC."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from consumers.console import Consumer, ConsoleConsumer
from events.models import StatusEvent


def _make_event(event_type: str = "new") -> StatusEvent:
    return StatusEvent(
        provider="GitHub",
        product="Actions",
        status="Degraded performance",
        message="We are investigating issues.",
        timestamp=datetime(2025, 6, 15, 10, 30, 0, tzinfo=timezone.utc),
        incident_id="inc-001",
        event_type=event_type,  # type: ignore[arg-type]
    )


class TestConsoleConsumerFormatEvent:
    """Verify _format_event output for different event types."""

    def test_format_new_event(self) -> None:
        event = _make_event(event_type="new")
        output = ConsoleConsumer._format_event(event)

        assert "[NEW]" in output
        assert "[2025-06-15 10:30:00]" in output
        assert "Provider: GitHub" in output
        assert "Product: Actions" in output
        assert "Status: Degraded performance" in output
        assert "We are investigating issues." in output
        assert "-" * 40 in output

    def test_format_updated_event(self) -> None:
        event = _make_event(event_type="updated")
        output = ConsoleConsumer._format_event(event)

        assert "[UPDATED]" in output
        assert "[NEW]" not in output
        assert "Provider: GitHub" in output

    def test_format_event_with_empty_message(self) -> None:
        event = StatusEvent(
            provider="AWS",
            product="EC2",
            status="Resolved",
            message="",
            timestamp=datetime(2025, 6, 15, 14, 0, 0, tzinfo=timezone.utc),
            incident_id="inc-002",
            event_type="new",
        )
        output = ConsoleConsumer._format_event(event)
        # When message is empty, the status line should not have trailing space.
        assert "Status: Resolved\n" in output

    def test_format_event_contains_separator(self) -> None:
        event = _make_event()
        output = ConsoleConsumer._format_event(event)
        assert output.endswith("-" * 40)


class TestConsumerABCCannotBeInstantiated:
    """The abstract Consumer class must not be instantiable."""

    def test_cannot_instantiate_consumer_abc(self) -> None:
        with pytest.raises(TypeError):
            Consumer()  # type: ignore[abstract]
