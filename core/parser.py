"""Atom feed parser for status-page entries.

Wraps the ``feedparser`` library and extracts the fields relevant to
status monitoring: incident ID, title, last-updated timestamp, summary
text (with HTML stripped), and affected products/components.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import feedparser  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
# Heuristic patterns used to extract affected component names from summary
# text.  Atom feeds from incident.io / Atlassian Statuspage often embed
# component names as bold items, list items, or after keywords like
# "Affected components:" or "Components:".
_COMPONENT_LINE_RE = re.compile(
    r"(?:affected\s+components?|components?)\s*:\s*(.+)",
    re.IGNORECASE,
)


def _strip_html(raw: str) -> str:
    """Remove HTML tags and decode entities from *raw*."""
    text = _HTML_TAG_RE.sub("", raw)
    return html.unescape(text).strip()


def _extract_products(text: str) -> list[str]:
    """Best-effort extraction of affected product names from *text*.

    Falls back to ``["Unknown"]`` when no components can be identified.
    """
    match = _COMPONENT_LINE_RE.search(text)
    if match:
        raw_components = match.group(1)
        # Components are often comma- or semicolon-separated.
        products = [
            c.strip()
            for c in re.split(r"[,;]", raw_components)
            if c.strip()
        ]
        if products:
            return products

    return ["Unknown"]


@dataclass
class ParsedEntry:
    """A single parsed feed entry."""

    entry_id: str
    title: str
    updated: str
    summary: str
    products: list[str] = field(default_factory=list)


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
            products = _extract_products(summary)

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
                    products=products,
                )
            )

        logger.debug(
            "Parsed %d entries from %s feed", len(entries), provider_name
        )
        return entries
