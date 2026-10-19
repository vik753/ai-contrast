# AI Contrast

Compare two or more contracts clause by clause with AI.

AI Contrast shows what is the same, what is different, and what to watch out for.
Every finding has a rating for your side of the deal, an explanation and a verified quote from the contract:

- 🟢 **Favorable** for you
- 🟡 **Attention** needed
- 🔴 **Unfavorable** or risky for you

> **Status:** in development. Stage 0 (project rules) is done. See [`docs/plan.md`](docs/plan.md).

## Principles

- **We store nothing.** The server keeps no contracts, no API keys and no results. There is no database.
- **Bring your own key.** You choose the AI provider and use your own API key. You control the cost.
- **Your history stays with you.** Cache, history and custom topic lists live in your browser only.
- **Compare by meaning.** Clauses are matched by topic, not by number or title. Contracts in different languages can be compared with each other.
- **English, Ukrainian, Russian.** For contracts and for the interface.

> **Privacy note.** Contract text is sent to the AI provider that you choose. That provider has its own data policy.

## How it works

1. Upload contracts: PDF (text or scan), DOCX, plain text, or a Google Docs link.
2. Choose topics: a ready template, topics suggested by AI, or your own.
3. Choose your side: for example, the insured party, the buyer or the supplier.
4. Choose the AI provider and enter your API key.
5. Get a color-coded comparison table, topic by topic.

## Tech

React + TypeScript frontend, Python + FastAPI stateless backend, official Anthropic and OpenAI SDKs.
Details: [`CLAUDE.md`](CLAUDE.md), [`docs/adr/`](docs/adr/).

## Security

Security model: [`docs/security/threat-model.md`](docs/security/threat-model.md).
To report a vulnerability, see [`SECURITY.md`](SECURITY.md).

## License

Copyright (C) 2026 Ihor (vik753).

AI Contrast is free software under the [GNU Affero General Public License v3.0 only](LICENSE).
If you run a modified version as a network service, you must offer its source code to the users of that service.
