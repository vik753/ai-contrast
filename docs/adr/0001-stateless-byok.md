# ADR 0001 — Stateless backend with BYOK, no database in v1

- Status: accepted
- Date: 2026-10-19

## Context

The first plan had PostgreSQL (Neon) for results, cache, topic templates and encrypted API keys.
The customer asked: can v1 work without any storage on the server?

## Decision

- The backend is stateless. It keeps nothing between requests: no database, no files on disk, no server cache.
- BYOK: the client brings their own provider API key. It is sent with each request in a header and is never stored on the server.
- Cache, history and custom topic lists live in the browser (IndexedDB) behind a `CacheStore` port.
- Ready topic templates are JSON files in the repository.
- Long analyses stream progress and results over SSE in the same request. No job queue.

## Consequences

- Positive: nothing to steal on the server; simpler code; one service less; any instance can serve any request; privacy is a selling point.
- Negative: history does not sync between devices; clearing the browser deletes cache and history; no server-side statistics.
- A database can be added later behind `CacheStore` without changing the analysis code.
- No accounts in v1. CSRF does not apply (no cookies).
