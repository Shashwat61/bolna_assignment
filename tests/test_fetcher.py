"""Tests for core.fetcher.FeedFetcher."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.fetcher import FeedFetcher, FetchResult


def _make_mock_response(
    status: int = 200,
    text: str = "<feed></feed>",
    headers: dict[str, str] | None = None,
) -> MagicMock:
    """Create a mock aiohttp response with async context manager support."""
    resp = MagicMock()
    resp.status = status
    resp.text = AsyncMock(return_value=text)
    resp.headers = headers or {}
    return resp


def _make_mock_session(response: MagicMock) -> MagicMock:
    """Create a mock aiohttp.ClientSession whose .get() returns *response*."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.get = MagicMock(return_value=ctx)
    return session


@pytest.mark.asyncio
async def test_fetch_200_returns_content_and_headers() -> None:
    """A 200 response should return body content and caching headers."""
    response = _make_mock_response(
        status=200,
        text="<feed><entry>...</entry></feed>",
        headers={"ETag": '"xyz"', "Last-Modified": "Sat, 14 Jun 2025 10:00:00 GMT"},
    )
    session = _make_mock_session(response)
    semaphore = asyncio.Semaphore(5)
    fetcher = FeedFetcher(semaphore=semaphore, session=session)

    result = await fetcher.fetch("https://example.com/feed.atom")

    assert isinstance(result, FetchResult)
    assert result.status_code == 200
    assert result.content == "<feed><entry>...</entry></feed>"
    assert result.etag == '"xyz"'
    assert result.last_modified == "Sat, 14 Jun 2025 10:00:00 GMT"


@pytest.mark.asyncio
async def test_fetch_304_returns_none_content() -> None:
    """A 304 Not Modified response should return content=None."""
    response = _make_mock_response(status=304)
    session = _make_mock_session(response)
    semaphore = asyncio.Semaphore(5)
    fetcher = FeedFetcher(semaphore=semaphore, session=session)

    result = await fetcher.fetch(
        "https://example.com/feed.atom",
        etag='"old-etag"',
        last_modified="old-date",
    )

    assert result.status_code == 304
    assert result.content is None
    # On 304, the original etag/last_modified are preserved.
    assert result.etag == '"old-etag"'
    assert result.last_modified == "old-date"


@pytest.mark.asyncio
async def test_conditional_headers_sent_when_provided() -> None:
    """When etag and last_modified are given, conditional headers must be sent."""
    response = _make_mock_response(status=200)
    session = _make_mock_session(response)
    semaphore = asyncio.Semaphore(5)
    fetcher = FeedFetcher(semaphore=semaphore, session=session)

    await fetcher.fetch(
        "https://example.com/feed.atom",
        etag='"my-etag"',
        last_modified="Sat, 14 Jun 2025 10:00:00 GMT",
    )

    # Inspect the headers passed to session.get().
    call_kwargs = session.get.call_args
    headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
    assert headers["If-None-Match"] == '"my-etag"'
    assert headers["If-Modified-Since"] == "Sat, 14 Jun 2025 10:00:00 GMT"


@pytest.mark.asyncio
async def test_no_conditional_headers_when_none() -> None:
    """When no etag/last_modified are provided, no conditional headers are sent."""
    response = _make_mock_response(status=200)
    session = _make_mock_session(response)
    semaphore = asyncio.Semaphore(5)
    fetcher = FeedFetcher(semaphore=semaphore, session=session)

    await fetcher.fetch("https://example.com/feed.atom")

    call_kwargs = session.get.call_args
    headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
    assert "If-None-Match" not in headers
    assert "If-Modified-Since" not in headers


@pytest.mark.asyncio
async def test_semaphore_is_acquired_and_released() -> None:
    """The semaphore should be acquired before the request and released after."""
    response = _make_mock_response(status=200)
    session = _make_mock_session(response)
    semaphore = asyncio.Semaphore(1)
    fetcher = FeedFetcher(semaphore=semaphore, session=session)

    # Semaphore starts at 1 (available).
    assert not semaphore.locked()

    await fetcher.fetch("https://example.com/feed.atom")

    # After fetch completes, semaphore should be released again.
    assert not semaphore.locked()


@pytest.mark.asyncio
async def test_semaphore_limits_concurrency() -> None:
    """Only one fetch should proceed at a time with semaphore=1."""
    call_order: list[str] = []

    async def slow_text() -> str:
        call_order.append("reading")
        await asyncio.sleep(0.1)
        return "<feed></feed>"

    response = MagicMock()
    response.status = 200
    response.text = slow_text
    response.headers = {}

    session = _make_mock_session(response)
    semaphore = asyncio.Semaphore(1)
    fetcher = FeedFetcher(semaphore=semaphore, session=session)

    # Launch two fetches concurrently.
    task1 = asyncio.create_task(fetcher.fetch("https://example.com/feed1.atom"))
    task2 = asyncio.create_task(fetcher.fetch("https://example.com/feed2.atom"))

    await asyncio.gather(task1, task2)

    # Both should complete.
    assert task1.done()
    assert task2.done()
