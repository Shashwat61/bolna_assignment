"""Atom feed parser for status-page entries.

Wraps the ``feedparser`` library and extracts the fields relevant to
status monitoring: incident ID, title, last-updated timestamp, and
summary text (with HTML stripped).
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass

import feedparser  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(raw: str) -> str:
    """Remove HTML tags and decode entities from *raw*."""
    text = _HTML_TAG_RE.sub("", raw)
    return html.unescape(text).strip()


@dataclass
class ParsedEntry:
    """A single parsed feed entry."""

    entry_id: str
    title: str
    updated: str
    summary: str


class FeedParser:
    """Stateless parser that converts raw Atom XML into :class:`ParsedEntry` objects."""

    def parse(self, content: str, provider_name: str) -> list[ParsedEntry]:
        """Parse *content* (Atom XML) and return a list of entries.

        Parameters
        ----------
        content:
            Raw XML string of the Atom feed.
        provider_name:
            Used for log messages only.
        """
        feed = feedparser.parse(content)

        if feed.bozo and not feed.entries:
            logger.warning(
                "Feed from %s could not be parsed: %s",
                provider_name,
                feed.bozo_exception,
            )
            return []

        entries: list[ParsedEntry] = []
        for entry in feed.entries:
            entry_id: str = getattr(entry, "id", "") or ""
            title: str = getattr(entry, "title", "") or ""
            updated: str = getattr(entry, "updated", "") or ""

            # Prefer the full summary; fall back to content field.
            raw_summary: str = ""
            if hasattr(entry, "summary"):
                raw_summary = entry.summary
            elif hasattr(entry, "content") and entry.content:
                raw_summary = entry.content[0].get("value", "")

            summary = _strip_html(raw_summary)

            if not entry_id:
                logger.debug(
                    "Skipping entry without id in %s feed", provider_name
                )
                continue

            entries.append(
                ParsedEntry(
                    entry_id=entry_id,
                    title=title,
                    updated=updated,
                    summary=summary,
                )
            )

        logger.debug(
            "Parsed %d entries from %s feed", len(entries), provider_name
        )
        return entries
