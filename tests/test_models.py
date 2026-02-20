"""Tests for events.models.StatusEvent."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from events.models import StatusEvent


class TestStatusEventCreation:
    """Verify that StatusEvent instances are created correctly."""

    def test_creation_with_all_fields(self) -> None:
        ts = datetime(2025, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        event = StatusEvent(
            provider="GitHub",
            product="Actions",
            status="Degraded performance",
            message="Investigating issues.",
            timestamp=ts,
            incident_id="inc-001",
            event_type="new",
        )
        assert event.provider == "GitHub"
        assert event.product == "Actions"
        assert event.status == "Degraded performance"
        assert event.message == "Investigating issues."
        assert event.timestamp == ts
        assert event.incident_id == "inc-001"
        assert event.event_type == "new"

    def test_event_type_updated(self) -> None:
        ts = datetime(2025, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        event = StatusEvent(
            provider="AWS",
            product="EC2",
            status="Resolved",
            message="Issue resolved.",
            timestamp=ts,
            incident_id="inc-002",
            event_type="updated",
        )
        assert event.event_type == "updated"


class TestFrozenImmutability:
    """StatusEvent is a frozen dataclass and must reject attribute mutation."""

    def test_cannot_set_provider(self, sample_status_event: StatusEvent) -> None:
        with pytest.raises(FrozenInstanceError):
            sample_status_event.provider = "AWS"  # type: ignore[misc]

    def test_cannot_set_product(self, sample_status_event: StatusEvent) -> None:
        with pytest.raises(FrozenInstanceError):
            sample_status_event.product = "Lambda"  # type: ignore[misc]

    def test_cannot_set_status(self, sample_status_event: StatusEvent) -> None:
        with pytest.raises(FrozenInstanceError):
            sample_status_event.status = "Resolved"  # type: ignore[misc]


class TestFormattedOutput:
    """Verify formatted_output() produces the expected human-readable format."""

    def test_formatted_output_content(self, sample_status_event: StatusEvent) -> None:
        output = sample_status_event.formatted_output()
        assert "[2025-06-15 10:30:00]" in output
        assert "Product: GitHub - Actions" in output
        assert "Status: Degraded performance" in output
        assert "We are investigating" in output

    def test_formatted_output_multiline(self, sample_status_event: StatusEvent) -> None:
        output = sample_status_event.formatted_output()
        lines = output.split("\n")
        assert len(lines) == 2
        assert lines[0].startswith("[")
        assert lines[1].strip().startswith("Status:")


class TestStrDelegatesToFormattedOutput:
    """__str__ should return the same value as formatted_output()."""

    def test_str_equals_formatted_output(self, sample_status_event: StatusEvent) -> None:
        assert str(sample_status_event) == sample_status_event.formatted_output()
