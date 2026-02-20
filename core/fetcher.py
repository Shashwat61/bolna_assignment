"""Async HTTP fetcher with conditional-request support.

Uses ``aiohttp`` to fetch Atom feeds efficiently.  Conditional headers
(``If-None-Match`` / ``If-Modified-Since``) allow servers to return
``304 Not Modified`` when content has not changed, saving bandwidth and
processing time.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


@dataclass
class FetchResult:
    """Outcome of a single HTTP feed fetch."""

    status_code: int
    content: Optional[str]
    etag: Optional[str]
    last_modified: Optional[str]


class FeedFetcher:
    """Fetches feed URLs with concurrency control and conditional headers.

    Parameters
    ----------
    semaphore:
        An :class:`asyncio.Semaphore` that caps the number of concurrent
        HTTP requests across all providers.
    session:
        A shared :class:`aiohttp.ClientSession` for connection pooling.
    """

    def __init__(
        self,
        semaphore: asyncio.Semaphore,
        session: aiohttp.ClientSession,
    ) -> None:
        self._semaphore = semaphore
        self._session = session

    async def fetch(
        self,
        url: str,
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
    ) -> FetchResult:
        """Fetch *url*, honouring cached *etag* and *last_modified*.

        Returns a :class:`FetchResult`.  When the server responds with
        ``304 Not Modified``, ``content`` will be ``None``.
        """
        headers: dict[str, str] = {}
        if etag is not None:
            headers["If-None-Match"] = etag
        if last_modified is not None:
            headers["If-Modified-Since"] = last_modified

        async with self._semaphore:
            async with self._session.get(
                url, headers=headers, timeout=_REQUEST_TIMEOUT
            ) as response:
                if response.status == 304:
                    return FetchResult(
                        status_code=304,
                        content=None,
                        etag=etag,
                        last_modified=last_modified,
                    )

                body = await response.text()
                return FetchResult(
                    status_code=response.status,
                    content=body,
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                )
