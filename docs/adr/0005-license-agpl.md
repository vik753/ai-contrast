# ADR 0005 — License: AGPL-3.0-only

- Status: accepted
- Date: 2026-10-19

## Context

The repository is public. The customer wants the code to be free to use, but anyone who runs it as a network service must publish their source code.

## Decision

- License: GNU Affero General Public License v3.0 only (`AGPL-3.0-only`).
- Copyright holder: Ihor (vik753). As the copyright holder he can still offer the product under other terms (dual licensing).
- AGPL section 13: the UI shows a "Source code" link to this repository.
- External contributions, if accepted later, need a contributor agreement to keep dual licensing possible.

## Consequences

- Competitors cannot run a closed modified copy as a service.
- Some companies avoid AGPL code. This does not affect the customer's own use.
