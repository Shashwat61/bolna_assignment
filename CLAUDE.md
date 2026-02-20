# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Status Page Monitor — a Python async application that polls Atom feeds from service status pages (OpenAI, GitHub, etc.) and logs new/updated incidents. Designed to scale from 1 to 100+ providers without code changes.

## Build & Run

```bash
pip install aiohttp feedparser pyyaml
python main.py
```

Runs indefinitely, polling configured providers. Stop with Ctrl+C.

## Architecture

**Event-based async polling system** with five layers:

1. **Provider Registry** (`config/providers.yaml`) — YAML config listing feed URLs and poll intervals. Adding a provider = adding a YAML entry.
2. **Scheduler** (`core/scheduler.py`) — Spawns one `asyncio.Task` per provider with staggered starts (`index * 0.3s` delay) and jitter to prevent thundering herd.
3. **Fetcher** (`core/fetcher.py`) — `aiohttp` client using conditional HTTP headers (`If-None-Match`/`If-Modified-Since`). 304 = skip, 200 = parse. Capped by `asyncio.Semaphore(20)`.
4. **Parser + State** (`core/parser.py`, `core/state.py`) — `feedparser` for Atom XML. Deduplication via `{entry_id: updated_timestamp}` dict. Emits events only for new or updated entries.
5. **Event Bus + Consumers** (`events/bus.py`, `consumers/console.py`) — `asyncio.Queue` decouples polling from output. Consumers run as separate async tasks.

**Key data structure:**
```python
@dataclass
class StatusEvent:
    provider: str
    product: str
    status: str
    message: str
    timestamp: datetime
    incident_id: str
    event_type: str  # "new" or "updated"
```

## Critical Implementation Details

- **Conditional HTTP headers are required** — store ETag/Last-Modified from responses, send back on next request. Most polls should return 304.
- **Exponential backoff on failure** — 3 consecutive failures → double poll interval (30s → 60s → 120s), reset on success.
- **Individual provider failures must not crash the system** — catch, log, back off, continue.
- **Atom feed chosen over RSS/JSON** — `<id>` + `<updated>` pair enables reliable cross-provider change detection with `feedparser`.

## Dependencies

- `aiohttp` — async HTTP client
- `feedparser` — Atom/RSS parsing
- `pyyaml` — provider config loading
