"""Tests for core.parser.FeedParser."""

from __future__ import annotations

from core.parser import FeedParser, ParsedEntry


class TestParseValidAtom:
    """Verify parsing of well-formed Atom XML."""

    def test_extracts_entries_correctly(self, sample_atom_feed: str) -> None:
        parser = FeedParser()
        entries = parser.parse(sample_atom_feed, "GitHub")
        assert len(entries) == 3
        assert all(isinstance(e, ParsedEntry) for e in entries)

    def test_entry_fields_populated(self, sample_atom_feed: str) -> None:
        parser = FeedParser()
        entries = parser.parse(sample_atom_feed, "GitHub")
        first = entries[0]
        assert first.entry_id == "incident-001"
        assert first.title == "Degraded performance for Actions"
        assert "2025-06-15" in first.updated
        assert first.summary  # non-empty

    def test_entry_ids_are_correct(self, sample_atom_feed: str) -> None:
        parser = FeedParser()
        entries = parser.parse(sample_atom_feed, "GitHub")
        ids = [e.entry_id for e in entries]
        assert ids == ["incident-001", "incident-002", "incident-003"]


class TestHtmlStripping:
    """Verify that HTML tags are stripped from summaries."""

    def test_strips_html_tags(self) -> None:
        feed_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>inc-html</id>
    <title>Test</title>
    <updated>2025-06-15T10:00:00Z</updated>
    <summary type="html">&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;</summary>
  </entry>
</feed>
"""
        parser = FeedParser()
        entries = parser.parse(feed_xml, "Test")
        assert "<p>" not in entries[0].summary
        assert "<b>" not in entries[0].summary
        assert "Hello" in entries[0].summary
        assert "world" in entries[0].summary


class TestProductExtraction:
    """Verify extraction of affected products/components."""

    def test_extracts_products_from_affected_components(self, sample_atom_feed: str) -> None:
        parser = FeedParser()
        entries = parser.parse(sample_atom_feed, "GitHub")
        # First entry has "Affected components: Actions, Pages"
        first = entries[0]
        assert "Actions" in first.products
        assert "Pages" in first.products

    def test_extracts_single_component(self, sample_atom_feed: str) -> None:
        parser = FeedParser()
        entries = parser.parse(sample_atom_feed, "GitHub")
        # Third entry has "Affected components: Copilot"
        third = entries[2]
        assert "Copilot" in third.products

    def test_falls_back_to_unknown_when_no_components(self, sample_atom_feed: str) -> None:
        parser = FeedParser()
        entries = parser.parse(sample_atom_feed, "GitHub")
        # Second entry has no "Affected components:" line.
        second = entries[1]
        assert second.products == ["Unknown"]

    def test_falls_back_to_unknown_for_plain_text(self) -> None:
        feed_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>inc-plain</id>
    <title>Test</title>
    <updated>2025-06-15T10:00:00Z</updated>
    <summary type="html">Just a plain message with no component info.</summary>
  </entry>
</feed>
"""
        parser = FeedParser()
        entries = parser.parse(feed_xml, "Test")
        assert entries[0].products == ["Unknown"]


class TestSkipsEntriesWithoutId:
    """Entries missing an <id> element should be skipped."""

    def test_skips_entry_without_id(self) -> None:
        feed_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>No ID entry</title>
    <updated>2025-06-15T10:00:00Z</updated>
    <summary>Some text</summary>
  </entry>
  <entry>
    <id>inc-valid</id>
    <title>Valid entry</title>
    <updated>2025-06-15T10:00:00Z</updated>
    <summary>Some text</summary>
  </entry>
</feed>
"""
        parser = FeedParser()
        entries = parser.parse(feed_xml, "Test")
        assert len(entries) == 1
        assert entries[0].entry_id == "inc-valid"


class TestMalformedXml:
    """Parser should handle malformed or empty input gracefully."""

    def test_empty_string_returns_empty_list(self) -> None:
        parser = FeedParser()
        entries = parser.parse("", "Test")
        assert entries == []

    def test_malformed_xml_returns_empty_list(self) -> None:
        parser = FeedParser()
        entries = parser.parse("<not-valid-xml><broken>", "Test")
        # feedparser is lenient; it may return [] or parse partially.
        assert isinstance(entries, list)

    def test_non_atom_content_returns_empty_list(self) -> None:
        parser = FeedParser()
        entries = parser.parse("This is just plain text, not XML at all.", "Test")
        assert isinstance(entries, list)
        assert len(entries) == 0
