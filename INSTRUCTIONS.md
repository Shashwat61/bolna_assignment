# Status Page Monitor — Implementation Instructions

## Problem Statement

Build a Python script that automatically tracks and logs service updates from the [OpenAI Status Page](https://status.openai.com/) and is architecturally designed to scale to 100+ similar status pages.

When a new incident, outage, or degradation is detected, print:
- The affected product/service
- The latest status message or event

```
[2025-11-03 14:32:00] Product: OpenAI API - Chat Completions
Status: Degraded performance due to upstream issue
```

## Key Discovery (from investigation)

- OpenAI's status page is powered by **incident.io** (not Atlassian Statuspage)
- The page exposes **Atom feed** at `https://status.openai.com/feed.atom`
- The page exposes **JSON API** at `https://status.openai.com/proxy/status.openai.com`
- **No SSE, no WebSocket, no WebSub hub** — the page's own frontend uses HTTP polling
- The Atom feed has structured `<entry>` elements with unique `<id>`, `<updated>` timestamps, and `<summary>` containing incident details and affected components

## Architecture Overview

### Core Approach: Atom Feed + Async Conditional Polling + Event Bus

This is an **event-based architecture** where:
- Polling is an implementation detail of the ingestion layer (made efficient with HTTP conditional headers)
- Consumers never poll — they react to events pushed onto an `asyncio.Queue`
- Adding a new provider = adding a config entry, not writing new code

### Components to Build

#### 1. Provider Registry (`providers.yaml` or `providers.json`)

A config file listing all status page providers to monitor:

```yaml
providers:
  - name: "OpenAI"
    feed_url: "https://status.openai.com/feed.atom"
    poll_interval_seconds: 30
  - name: "GitHub"  
    feed_url: "https://www.githubstatus.com/history.atom"
    poll_interval_seconds: 45
  # ... 100+ more
```

#### 2. Async Polling Engine

- **Scheduler**: Reads the provider registry, spawns one `asyncio.Task` per provider with staggered start times (don't fire all at once)
- **HTTP Fetcher**: Uses `aiohttp` with conditional headers (`If-None-Match` / `If-Modified-Since`). On `304` → skip. On `200` → proceed to parsing
- **Semaphore**: `asyncio.Semaphore(20)` to cap concurrent HTTP requests — prevents flooding when monitoring 100+ feeds
- **Jitter**: Add random delay (0-5s) to each poll interval to prevent synchronization over time

#### 3. Feed Parser & Change Detector

- Use `feedparser` library to parse Atom XML
- Maintain in-memory state per provider: `{ provider_name: { last_etag, last_modified, seen_entry_ids: { entry_id: updated_timestamp } } }`
- For each entry in parsed feed:
  - If `entry.id` not in `seen_entry_ids` → **new incident** → emit event
  - If `entry.id` in `seen_entry_ids` but `entry.updated` changed → **incident updated** → emit event
  - Otherwise → skip
- Update local state after processing

#### 4. Event Bus (`asyncio.Queue`)

- Single shared `asyncio.Queue` instance
- Polling tasks push structured event objects:

```python
@dataclass
class StatusEvent:
    provider: str           # "OpenAI"
    product: str            # "Chat Completions"
    status: str             # "Degraded Performance"
    message: str            # Full status message
    timestamp: datetime     # When the incident was updated
    incident_id: str        # Unique incident identifier
    event_type: str         # "new" or "updated"
```

#### 5. Consumer(s)

- A separate `asyncio.Task` running `while True: event = await queue.get()`
- For the assignment: **Console Logger** that prints formatted output
- Architecture allows plugging in additional consumers (Slack, webhook, etc.) without modifying polling logic

### Project Structure

```
status-monitor/
├── main.py                 # Entry point — starts orchestrator
├── config/
│   └── providers.yaml      # Provider registry
├── core/
│   ├── scheduler.py        # Spawns and manages polling tasks
│   ├── fetcher.py          # aiohttp client with conditional headers
│   ├── parser.py           # Atom feed parsing + change detection
│   └── state.py            # In-memory state management
├── events/
│   ├── bus.py              # asyncio.Queue wrapper
│   └── models.py           # StatusEvent dataclass
├── consumers/
│   └── console.py          # Console output handler
├── requirements.txt
└── README.md
```

### Dependencies

```
aiohttp
feedparser
pyyaml
```

### Key Implementation Details

1. **Conditional HTTP headers** — This is critical for efficiency. First request returns `ETag` and `Last-Modified` headers. Store them. Send them back on subsequent requests as `If-None-Match` and `If-Modified-Since`. Server returns `304 Not Modified` with empty body when nothing changed.

2. **Staggered task startup** — When spawning 100 tasks, add `await asyncio.sleep(index * 0.3)` so they don't all fire at second 0.

3. **Graceful error handling** — Individual provider failures (timeout, DNS error, malformed feed) should not crash the entire system. Log the error, back off with exponential delay, retry.

4. **Backoff on repeated failures** — If a provider fails 3 times in a row, increase its poll interval exponentially (30s → 60s → 120s) and reset on success.

5. **Deduplication** — Incidents get updated multiple times. Track both the incident ID and its last-seen `updated` timestamp to avoid duplicate console output.

### Running

```bash
pip install aiohttp feedparser pyyaml
python main.py
```

Should start polling immediately and print to console whenever a new or updated incident is detected. Runs indefinitely until interrupted with Ctrl+C.

### What a Good Submission Looks Like

- Clean async code with proper error handling
- Provider abstraction that makes adding new feeds trivial (just a YAML entry)
- Conditional HTTP headers actually working (log 304 vs 200 counts)
- Deduplication logic preventing duplicate output
- README explaining the architecture decisions and tradeoffs
- Mention of scaling path (Redis, workers) without over-engineering the current solution
