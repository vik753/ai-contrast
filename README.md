# AI Contrast

Compare two or more contracts clause by clause with AI.

AI Contrast shows what is the same, what is different, and what to watch out for.
Every finding has a rating for your side of the deal, an explanation and a verified quote from the contract:

- 🟢 **Favorable** for you
- 🟡 **Attention** needed
- 🔴 **Unfavorable** or risky for you

> **Status:** in development. Stage 0 (project rules), stage 1 (scaffold), stage 2 (file upload), stage 3 (text extraction) and stage 4 (browser hash and cache) are done. See [`docs/plan.md`](docs/plan.md).
> You can add contracts and files, and the server extracts and shows their text. Contract comparison is not built yet.

## Principles

- **We store nothing.** The server keeps no contracts, no API keys and no results. There is no database.
- **Bring your own key.** You choose the AI provider and use your own API key. You control the cost.
- **Your history stays with you.** Cache, history and custom topic lists live in your browser only.
- **Compare by meaning.** Clauses are matched by topic, not by number or title. Contracts in different languages can be compared with each other.
- **English, Ukrainian, Russian.** For contracts and for the interface.

> **Privacy note.** Contract text is sent to the AI provider that you choose. That provider has its own data policy.

## How it works

1. Upload contracts: PDF (text or scan), DOCX, plain text, or Google Docs by public link ("Anyone with the link can view"). One contract may have several files (main text plus annexes). Files are checked by type and size. File names stay in your browser.
2. Choose topics: a ready template, topics suggested by AI, or your own.
3. Choose your side: for example, the insured party, the buyer or the supplier.
4. Choose the AI provider and enter your API key.
5. Get a color-coded comparison table, topic by topic.

Data and history: results are saved only in this browser, and only if you turn it on (off by default). Saved results are kept for 90 days. The "Delete all data" button removes them at once.

## Tech

React + TypeScript frontend, Python + FastAPI stateless backend, official Anthropic and OpenAI SDKs.
Details: [`CLAUDE.md`](CLAUDE.md), [`docs/adr/`](docs/adr/).

## Run locally

No secrets and no `.env` file are needed.

### Prerequisites

- With Docker: Docker Engine 28.0 or later, or Docker Desktop. Engine 28.0 is required for LAN isolation of published ports.
- Without Docker: Python 3.13 with [uv](https://docs.astral.sh/uv/), and Node 22.13 or later.

### Start with Docker Compose

On Linux, create the `node_modules` and `public/ocr` directories first. Then Docker does not create them as root (`public/ocr` is the volume for the generated OCR assets):

```bash
mkdir -p frontend/node_modules frontend/public/ocr
```

Build and start the stack:

```bash
docker compose up --build
```

Wait until both services are healthy. The first start is slow because `npm ci` runs in the frontend container.

- Frontend: http://localhost:5173. You see the AI Contrast page.
- Backend health: http://localhost:8000/api/health. You see `{"status":"ok","version":"0.1.0"}`.

Ports are bound to `127.0.0.1`. Other machines cannot reach them.

Stop the stack:

```bash
docker compose down
```

### Notes

- **Backend changes.** The backend runs from its image and has no hot reload. After you change backend code, run `docker compose up --build backend`.
- **Linux, `node_modules` or `public/ocr` owned by root.** If you skipped `mkdir -p frontend/node_modules frontend/public/ocr`, a later `npm ci` or `npm run dev` on the host can fail. Fix it with `sudo rm -rf frontend/node_modules frontend/public/ocr`.
- **Linux, write access to `./frontend`.** The frontend container runs as `node` (uid 1000) and the `./frontend` bind mount is read-write. If your user id is also 1000, the container can change files in `./frontend`. Review `git diff` before you commit.
- **WSL2 hot reload.** If the code is on the Windows file system, file events do not reach the container. Enable polling (Vite `server.watch.usePolling: true`) or keep the code in the Linux file system.

### Run without Docker

Commands for the backend, the frontend and all checks are in the "Commands" section of [`CLAUDE.md`](CLAUDE.md).

## Security

Security model: [`docs/security/threat-model.md`](docs/security/threat-model.md).
To report a vulnerability, see [`SECURITY.md`](SECURITY.md).

## License

Copyright (C) 2026 Ihor (vik753).

AI Contrast is free software under the [GNU Affero General Public License v3.0 only](LICENSE).
If you run a modified version as a network service, you must offer its source code to the users of that service.
