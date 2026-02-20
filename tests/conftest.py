"""Shared fixtures for the Status Page Monitor test suite."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from events.bus import EventBus
from events.models import StatusEvent


@pytest.fixture
def event_bus() -> EventBus:
    """Return a fresh EventBus instance."""
    return EventBus()


@pytest.fixture
def sample_status_event() -> StatusEvent:
    """Return a realistic StatusEvent for use in tests."""
    return StatusEvent(
        provider="GitHub",
        product="Actions",
        status="Degraded performance",
        message="We are investigating reports of degraded performance for Actions.",
        timestamp=datetime(2025, 6, 15, 10, 30, 0, tzinfo=timezone.utc),
        incident_id="inc-12345",
        event_type="new",
    )


@pytest.fixture
def sample_atom_feed() -> str:
    """Return a realistic Atom XML feed string with 3 entries."""
    return """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>GitHub Status - Incident History</title>
  <updated>2025-06-15T12:00:00Z</updated>

  <entry>
    <id>incident-001</id>
    <title>Degraded performance for Actions</title>
    <updated>2025-06-15T10:30:00Z</updated>
    <summary type="html">
      &lt;p&gt;We are investigating degraded performance.&lt;/p&gt;
      &lt;p&gt;Affected components: Actions, Pages&lt;/p&gt;
    </summary>
  </entry>

  <entry>
    <id>incident-002</id>
    <title>API requests failing</title>
    <updated>2025-06-14T08:00:00Z</updated>
    <summary type="html">
      &lt;p&gt;Elevated error rates on the REST API.&lt;/p&gt;
    </summary>
  </entry>

  <entry>
    <id>incident-003</id>
    <title>Copilot service disruption</title>
    <updated>2025-06-13T16:45:00Z</updated>
    <summary type="html">
      &lt;p&gt;Service disruption detected.&lt;/p&gt;
      &lt;p&gt;Affected components: Copilot&lt;/p&gt;
    </summary>
  </entry>
</feed>
"""
