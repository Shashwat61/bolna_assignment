"""SSE consumer — streams status events to browser clients via Server-Sent Events."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from pathlib import Path

from aiohttp import web

from consumers.console import Consumer
from events.bus import EventBus
from events.models import StatusEvent

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent.parent / "static"


class SSEConsumer(Consumer):
    """Serves an SSE endpoint and a simple HTML frontend.

    Each browser connection gets its own EventBus subscription,
    so multiple clients can connect independently.
    """

    def __init__(
        self,
        event_bus: EventBus,
        host: str = "0.0.0.0",
        port: int = 8085,
    ) -> None:
        self._event_bus = event_bus
        self._host = host
        self._port = port
        self._running = False
        self._app = web.Application()
        self._app.router.add_get("/", self._handle_index)
        self._app.router.add_get("/events", self._handle_sse)
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        """Start the HTTP server (non-blocking)."""
        self._running = True
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.info("SSE server running at http://%s:%s", self._host, self._port)

    async def stop(self) -> None:
        """Shut down the HTTP server."""
        self._running = False
        if self._runner:
            await self._runner.cleanup()
        logger.info("SSE server stopped")

    async def _handle_index(self, request: web.Request) -> web.Response:
        """Serve the HTML frontend."""
        html_path = _STATIC_DIR / "index.html"
        return web.Response(
            text=html_path.read_text(),
            content_type="text/html",
        )

    async def _handle_sse(self, request: web.Request) -> web.StreamResponse:
        """Stream events to a single browser client via SSE."""
        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
            },
        )
        await response.prepare(request)
        logger.info("SSE client connected from %s", request.remote)

        try:
            async for event in self._event_bus.subscribe():
                if not self._running:
                    break
                data = json.dumps(self._serialize_event(event))
                await response.write(f"data: {data}\n\n".encode("utf-8"))
        except (ConnectionResetError, ConnectionError, asyncio.CancelledError):
            pass

        logger.info("SSE client disconnected from %s", request.remote)
        return response

    @staticmethod
    def _serialize_event(event: StatusEvent) -> dict:
        """Convert a StatusEvent to a JSON-serializable dict."""
        d = asdict(event)
        d["timestamp"] = event.timestamp.isoformat()
        return d
