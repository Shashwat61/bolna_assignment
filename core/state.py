"""In-memory state management for feed polling.

Tracks per-provider HTTP caching headers (ETag / Last-Modified) and
previously seen feed entries so the system can detect new and updated
incidents without re-emitting duplicates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ProviderState:
    """Mutable state kept for a single status-page provider."""

    etag: Optional[str] = None
    last_modified: Optional[str] = None
    # Mapping of entry_id -> updated timestamp string.
    seen_entries: dict[str, str] = field(default_factory=dict)


class StateManager:
    """Centralised store for all provider states.

    All access is synchronous because state is modified only from the
    owning asyncio task (one task per provider), so no locking is needed.
    """

    def __init__(self) -> None:
        self._states: dict[str, ProviderState] = {}

    def get_state(self, provider_name: str) -> ProviderState:
        """Return the state for *provider_name*, creating it if absent."""
        if provider_name not in self._states:
            logger.debug("Initialising state for provider %s", provider_name)
            self._states[provider_name] = ProviderState()
        return self._states[provider_name]

    def update_etag(
        self,
        provider_name: str,
        etag: Optional[str],
        last_modified: Optional[str],
    ) -> None:
        """Persist the latest HTTP caching headers for *provider_name*."""
        state = self.get_state(provider_name)
        state.etag = etag
        state.last_modified = last_modified
        logger.debug(
            "Updated caching headers for %s — etag=%s, last_modified=%s",
            provider_name,
            etag,
            last_modified,
        )

    def is_new_or_updated(
        self, provider_name: str, entry_id: str, updated: str
    ) -> tuple[bool, str]:
        """Check whether *entry_id* is new or has been updated.

        Returns
        -------
        (changed, change_type)
            *changed* is ``True`` when the entry should be processed.
            *change_type* is ``"new"``, ``"updated"``, or ``""``
            (empty string when nothing changed).
        """
        state = self.get_state(provider_name)
        if entry_id not in state.seen_entries:
            return True, "new"
        if state.seen_entries[entry_id] != updated:
            return True, "updated"
        return False, ""

    def mark_seen(
        self, provider_name: str, entry_id: str, updated: str
    ) -> None:
        """Record *entry_id* with its *updated* timestamp as seen."""
        state = self.get_state(provider_name)
        state.seen_entries[entry_id] = updated
