# ADR 0003 — Cloudflare Pages for the frontend

- Status: accepted
- Date: 2026-10-19

## Context

The client API key lives in the browser. The main defense against key theft through XSS is a strict Content Security Policy sent as an HTTP header, plus `frame-ancestors`, HSTS and other headers.
GitHub Pages cannot set custom HTTP headers. A `<meta>` CSP does not support `frame-ancestors` and some other directives.

## Decision

- Host the frontend on Cloudflare Pages. Security headers live in `frontend/public/_headers`.
- GitHub Pages stays a fallback only.

## Consequences

- Full control over security headers. Free tier, no card.
- One more account for the customer (Cloudflare).
- The backend stays on Render (ADR 0001 keeps it stateless, so the free tier fits).
