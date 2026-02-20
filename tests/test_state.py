"""Tests for core.state.StateManager and ProviderState."""

from __future__ import annotations

from core.state import ProviderState, StateManager


class TestGetState:
    """Verify get_state behaviour for known and unknown providers."""

    def test_creates_new_state_for_unknown_provider(self) -> None:
        sm = StateManager()
        state = sm.get_state("NewProvider")
        assert isinstance(state, ProviderState)
        assert state.etag is None
        assert state.last_modified is None
        assert state.seen_entries == {}

    def test_returns_same_object_for_same_provider(self) -> None:
        sm = StateManager()
        state1 = sm.get_state("GitHub")
        state2 = sm.get_state("GitHub")
        assert state1 is state2

    def test_different_providers_get_different_states(self) -> None:
        sm = StateManager()
        s1 = sm.get_state("GitHub")
        s2 = sm.get_state("AWS")
        assert s1 is not s2


class TestUpdateEtag:
    """Verify that update_etag persists caching header values."""

    def test_update_etag_persists_values(self) -> None:
        sm = StateManager()
        sm.update_etag("GitHub", etag='"abc123"', last_modified="Sat, 14 Jun 2025 10:00:00 GMT")
        state = sm.get_state("GitHub")
        assert state.etag == '"abc123"'
        assert state.last_modified == "Sat, 14 Jun 2025 10:00:00 GMT"

    def test_update_etag_overwrites_previous(self) -> None:
        sm = StateManager()
        sm.update_etag("GitHub", etag='"old"', last_modified="old-date")
        sm.update_etag("GitHub", etag='"new"', last_modified="new-date")
        state = sm.get_state("GitHub")
        assert state.etag == '"new"'
        assert state.last_modified == "new-date"

    def test_update_etag_with_none(self) -> None:
        sm = StateManager()
        sm.update_etag("GitHub", etag='"abc"', last_modified="some-date")
        sm.update_etag("GitHub", etag=None, last_modified=None)
        state = sm.get_state("GitHub")
        assert state.etag is None
        assert state.last_modified is None


class TestIsNewOrUpdated:
    """Verify detection of new, updated, and unchanged entries."""

    def test_returns_new_for_unseen_entry(self) -> None:
        sm = StateManager()
        changed, change_type = sm.is_new_or_updated("GitHub", "inc-001", "2025-06-15T10:00:00Z")
        assert changed is True
        assert change_type == "new"

    def test_returns_updated_for_changed_timestamp(self) -> None:
        sm = StateManager()
        sm.mark_seen("GitHub", "inc-001", "2025-06-15T10:00:00Z")
        changed, change_type = sm.is_new_or_updated("GitHub", "inc-001", "2025-06-15T12:00:00Z")
        assert changed is True
        assert change_type == "updated"

    def test_returns_empty_for_unchanged_entry(self) -> None:
        sm = StateManager()
        sm.mark_seen("GitHub", "inc-001", "2025-06-15T10:00:00Z")
        changed, change_type = sm.is_new_or_updated("GitHub", "inc-001", "2025-06-15T10:00:00Z")
        assert changed is False
        assert change_type == ""


class TestMarkSeen:
    """Verify mark_seen records entries correctly."""

    def test_mark_seen_records_entry(self) -> None:
        sm = StateManager()
        sm.mark_seen("GitHub", "inc-001", "2025-06-15T10:00:00Z")
        state = sm.get_state("GitHub")
        assert "inc-001" in state.seen_entries
        assert state.seen_entries["inc-001"] == "2025-06-15T10:00:00Z"

    def test_mark_seen_updates_existing_entry(self) -> None:
        sm = StateManager()
        sm.mark_seen("GitHub", "inc-001", "2025-06-15T10:00:00Z")
        sm.mark_seen("GitHub", "inc-001", "2025-06-15T12:00:00Z")
        state = sm.get_state("GitHub")
        assert state.seen_entries["inc-001"] == "2025-06-15T12:00:00Z"
