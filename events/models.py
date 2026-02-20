from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class StatusEvent:
    """Represents a single status event emitted by a provider scraper."""

    provider: str
    product: str
    status: str
    message: str
    timestamp: datetime
    incident_id: str
    event_type: Literal["new", "updated"]

    def formatted_output(self) -> str:
        """Return a human-readable log line for this event."""
        ts = self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"[{ts}] Product: {self.provider} - {self.product}\n"
            f"  Status: {self.status} {self.message}"
        )

    def __str__(self) -> str:
        return self.formatted_output()
