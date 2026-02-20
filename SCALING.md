# Scaling, Future Upgrades & Tradeoffs

## Current Architecture

**Single-process async polling with asyncio.Queue as the event bus.**

### What We Have Now

| Component | Technology | Why |
|---|---|---|
| Concurrency | `asyncio` + `aiohttp` | Non-blocking I/O, handles 100s of concurrent tasks in one process |
| Feed Format | Atom XML via `feedparser` | Structured, has unique IDs + update timestamps for reliable diffing |
| Efficiency | HTTP Conditional Headers (ETag / If-Modified-Since) | 99% of requests return `304` with empty body — near-zero bandwidth |
| Event Bus | `asyncio.Queue` | In-memory, zero dependencies, perfect for single-process |
| State | In-memory Python dict | Fast lookups, no DB overhead |
| Config | YAML provider registry | Add a new provider = add 3 lines of YAML |

---

## Scaling Tiers

### Tier 1: Current (1-100 providers) — Single Process

**Capacity**: Comfortably handles 100+ providers on a single machine.

**Why it works**:
- asyncio can manage thousands of concurrent I/O-bound tasks
- Semaphore (max 20 concurrent requests) prevents resource spikes
- 304 responses make idle providers essentially free
- Staggered polling + jitter prevents thundering herd

**Bottleneck**: Single point of failure. If the process dies, monitoring stops entirely.

---

### Tier 2: Growth (100-500 providers) — Add Persistence + Resilience

**Upgrades needed**:

1. **Replace in-memory state with Redis/SQLite**
   - ETags, seen IDs, and last-modified timestamps persist across restarts
   - Process crash → restart → picks up where it left off without re-processing old incidents

2. **Replace asyncio.Queue with Redis Pub/Sub or Redis Streams**
   - Events survive process restarts
   - Multiple consumer processes can subscribe independently
   - Redis Streams give you consumer groups — different consumers (console, Slack, PagerDuty) each get every event exactly once

3. **Add health monitoring**
   - Expose a `/health` endpoint
   - Track per-provider metrics: last successful poll, failure count, average response time
   - Alert if a provider hasn't been successfully polled in N minutes

**Pros**:
- Still relatively simple — one polling process, one Redis instance
- Fault tolerant — restarts don't lose state
- Multiple output channels without code changes

**Cons**:
- Redis dependency adds operational complexity
- Still a single polling process — if it's down, no new events are detected

---

### Tier 3: Scale (500-2000+ providers) — Distributed Workers

**Upgrades needed**:

1. **Shard providers across multiple worker processes**
   - Worker 1 handles providers A-M, Worker 2 handles N-Z (or by hash)
   - Each worker is stateless — reads its assigned providers from a central registry
   - If a worker dies, its providers get redistributed to surviving workers

2. **Central coordinator / leader election**
   - One process manages the provider registry and assigns shards to workers
   - Uses Redis or etcd for leader election and coordination
   - Workers heartbeat to the coordinator — missed heartbeats trigger reassignment

3. **Replace Redis Pub/Sub with a proper message broker**
   - RabbitMQ or Apache Kafka for durable, ordered event delivery
   - Kafka gives you replay capability — re-process historical events if a consumer was down
   - RabbitMQ gives you routing — different event types go to different queues

4. **Centralized state store**
   - PostgreSQL or Redis Cluster for shared ETags and seen-entry state
   - Workers read/write state to the shared store
   - Handles concurrent access from multiple workers

**Pros**:
- Horizontally scalable — add workers to handle more providers
- High availability — no single point of failure
- Event durability — nothing lost on crashes

**Cons**:
- Significant operational complexity (Kafka/RabbitMQ clusters, coordinator logic)
- Distributed state management is hard (race conditions, split-brain scenarios)
- Cost of infrastructure increases substantially

---

## Approach Comparison

### Polling (Current) vs Webhooks vs SSE

| Aspect | Atom Feed Polling | Webhooks | SSE/WebSocket |
|---|---|---|---|
| **Latency** | Poll interval dependent (30-60s) | Near real-time (seconds) | Real-time (milliseconds) |
| **Reliability** | High — you control the schedule | Medium — depends on provider's delivery | Low — connection drops, reconnection logic |
| **Scalability** | Linear with providers (mitigated by 304s) | Excellent — zero work until event arrives | Poor — one persistent connection per provider |
| **Setup Complexity** | Low — just HTTP GET requests | Medium — need public endpoint (ngrok/hosting) | High — fragile, undocumented endpoints |
| **Provider Support** | Universal — every status page has a feed | Partial — not all providers offer webhooks | Rare — most status pages don't expose SSE |
| **Self-contained** | Yes — no external dependencies | No — need publicly reachable server | Yes — but fragile |

**Why we chose polling**: After investigating OpenAI's status page, we confirmed there's no SSE, no WebSocket, no WebSub hub. The page's own frontend uses HTTP polling. Atom feed polling with conditional headers is the most reliable, universal, and self-contained approach.

---

## Event Bus Comparison

| Aspect | asyncio.Queue | Redis Pub/Sub | Redis Streams | RabbitMQ | Kafka |
|---|---|---|---|---|---|
| **Persistence** | None (in-memory) | None (fire-and-forget) | Yes (with TTL) | Yes (acknowledgment) | Yes (log-based) |
| **Multi-consumer** | Manual fan-out | Yes (broadcast) | Yes (consumer groups) | Yes (queues/exchanges) | Yes (consumer groups) |
| **Replay** | No | No | Yes (read from offset) | No (once consumed) | Yes (read from offset) |
| **Ordering** | FIFO guaranteed | Not guaranteed | Guaranteed per stream | Per-queue FIFO | Per-partition FIFO |
| **Dependencies** | None | Redis server | Redis server | RabbitMQ server | Kafka + Zookeeper |
| **Best for** | Single process, < 100 providers | Simple multi-process | Durable multi-consumer | Complex routing | High-throughput, replay |

**Why we chose asyncio.Queue**: For a single-process system monitoring 100 providers, it's the simplest correct solution. Zero dependencies, FIFO ordering, built-in backpressure. The abstraction layer makes swapping to Redis Streams trivial when needed.

---

## Feed Format Comparison

| Aspect | Atom | RSS | JSON API |
|---|---|---|---|
| **Update detection** | Excellent — `<id>` + `<updated>` per entry | Weak — `<guid>` exists but `<pubDate>` less reliable | Excellent — structured fields |
| **Standardization** | Strict spec (RFC 4287) | Loose — implementations vary | Provider-specific |
| **Availability** | Universal — nearly every status page | Universal | Provider-specific endpoints |
| **Portability** | Same parser works across providers | Same parser, but quirks per provider | Need custom parser per provider |
| **Payload size** | Medium (XML overhead) | Medium (XML overhead) | Small (JSON) |

**Why we chose Atom**: Most portable across 100+ providers. Strict spec means `feedparser` handles all of them consistently. The `<id>` + `<updated>` pair makes change detection trivial and reliable.

---

## Known Limitations & Mitigations

| Limitation | Impact | Mitigation |
|---|---|---|
| Poll interval = detection delay | Up to 30-60s lag vs real-time | Acceptable for status monitoring; reduce interval for critical providers |
| In-memory state lost on crash | Re-processes recent incidents on restart (duplicate output) | Add idempotency in consumers; upgrade to Redis state store |
| Single process | No high availability | Deploy with process supervisor (systemd, Docker restart policy); upgrade to workers at scale |
| Feed format changes | Parser breaks silently | Add validation checks; alert on parse failures; test with multiple feed versions |
| Rate limiting by providers | 429 responses, potential IP ban | Respect `Retry-After` headers; exponential backoff; never poll faster than 15s |

---

## Upgrade Path Summary

```
Current (Assignment)
  asyncio.Queue + in-memory state + single process
  Good for: 1-100 providers, demo, take-home

    ↓ Add Redis for state + events

Phase 2 (Production MVP)
  Redis Streams + persistent state + health monitoring
  Good for: 100-500 providers, internal tool

    ↓ Add workers + coordinator

Phase 3 (Production Scale)
  Kafka/RabbitMQ + distributed workers + PostgreSQL state
  Good for: 500-2000+ providers, SaaS product
```

Each phase is an incremental upgrade — the core polling logic and provider abstraction never changes.
