# Status Page Monitor

Automatically tracks and logs service incidents from status pages (OpenAI, GitHub, etc.) using their public Atom feeds. Designed to scale from a handful of providers to 100+ without code changes.

## Quick Start

```bash
pip install -r requirements.txt
python main.py
```

Runs continuously, printing new/updated incidents to the console. Stop with `Ctrl+C`.

## Adding a Provider

Edit `config/providers.yaml`:

```yaml
providers:
  - name: "OpenAI"
    feed_url: "https://status.openai.com/feed.atom"
    poll_interval_seconds: 30
  - name: "GitHub"
    feed_url: "https://www.githubstatus.com/history.atom"
    poll_interval_seconds: 45
  # Add more here — no code changes needed
```

## Architecture

```
main.py  ──→  PollScheduler  ──→  FeedFetcher  ──→  HTTP (Atom feeds)
                    │                                      │
                    ▼                                      ▼
              FeedParser + StateManager  ◀── parse XML + detect changes
                    │
                    ▼
               EventBus (asyncio.Queue with fan-out)
                    │
                    ▼
              ConsoleConsumer (prints formatted output)
```

**Event-based polling system** — polling is an implementation detail of the ingestion layer. Consumers never poll; they react to events pushed onto an `asyncio.Queue`.

### Key Components

| Component | File | Responsibility |
|---|---|---|
| Scheduler | `core/scheduler.py` | Spawns one async task per provider with staggered starts and jitter |
| Fetcher | `core/fetcher.py` | HTTP client with conditional headers (`ETag`/`If-Modified-Since`) and semaphore-based concurrency control |
| Parser | `core/parser.py` | Atom XML parsing via `feedparser`, HTML stripping, component extraction |
| State | `core/state.py` | Tracks seen entries (`{entry_id: updated}`) and HTTP caching headers per provider |
| Event Bus | `events/bus.py` | Fan-out `asyncio.Queue` — each subscriber gets its own queue |
| Consumer | `consumers/console.py` | Abstract base + console implementation — prints formatted incident output |

### Design Decisions

**Why Atom feed polling?** After investigating OpenAI's status page, there is no SSE, no WebSocket, no WebSub hub. The page's own frontend uses HTTP polling. Atom feeds are universally available across status page providers, and the `<id>` + `<updated>` pair makes change detection trivial.

**Why conditional HTTP headers?** Most polls return `304 Not Modified` with an empty body. This makes monitoring 100+ feeds bandwidth-efficient — the majority of requests are near-zero cost.

**Why asyncio.Queue as event bus?** For a single-process system, it's the simplest correct solution. Zero dependencies, FIFO ordering, built-in backpressure. The fan-out abstraction makes swapping to Redis Streams trivial when needed.

### Resilience

- **Per-provider isolation**: One provider's failure (timeout, DNS error, malformed feed) never affects others.
- **Exponential backoff**: After consecutive failures, poll interval doubles (capped at `base * 2^5`) and resets on success.
- **Deduplication**: Tracks both incident ID and its `updated` timestamp — repeated updates don't produce duplicate output.
- **Graceful shutdown**: `SIGINT`/`SIGTERM` cancel all tasks cleanly.

## Scaling Path

See [SCALING.md](SCALING.md) for the full analysis. In brief:

| Scale | Approach |
|---|---|
| 1–100 providers | Current: single async process (this repo) |
| 100–500 providers | Add Redis for persistent state + Redis Streams for durable events |
| 500–2000+ providers | Distributed workers with Kafka/RabbitMQ + PostgreSQL state |

Each tier is an incremental upgrade — the core polling logic and provider abstraction never changes.
