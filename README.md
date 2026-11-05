# AI Contrast

Compare two or more contracts clause by clause with AI.

AI Contrast shows what is the same, what is different, and what to watch out for.
Every finding has a rating for your side of the deal, an explanation and a verified quote from the contract:

- 🟢 **Favorable** for you
- 🟡 **Attention** needed
- 🔴 **Unfavorable** or risky for you

> **Status:** in development. Stage 0 (project rules), stage 1 (scaffold), stage 2 (file upload), stage 3 (text extraction), stage 4 (browser hash and cache), stage 5 (clause splitting), stage 5b (pseudonymization), stage 6 (model connection) and stage 7 (topic catalog) are done. See [`docs/plan.md`](docs/plan.md).
> You can add contracts and files, the server extracts their text and splits it into clauses, you check the masked identifiers, you test the connection to an AI provider, and you prepare the topics. Contract comparison is not built yet.

## Principles

- **We store nothing.** The server keeps no contracts, no API keys and no results. There is no database.
- **Bring your own key.** You choose the AI provider and use your own API key. You control the cost.
- **Your history stays with you.** Cache, history and custom topic lists live in your browser only.
- **Compare by meaning.** Clauses are matched by topic, not by number or title. Contracts in different languages can be compared with each other.
- **English, Ukrainian, Russian.** For contracts and for the interface.

> **Privacy note.** Contract text is sent to the AI provider that you choose. That provider has its own data policy.

## How it works

1. Upload contracts: PDF (text or scan), DOCX, plain text, or Google Docs by public link ("Anyone with the link can view"). One contract may have several files (main text plus annexes). Files are checked by type and size. File names stay in your browser. The text of each file is split into clauses by numbering and headings, without AI. The preview shows the clauses.
2. Choose topics: a ready template, topics suggested by AI, or your own.
3. Choose your side: for example, the insured party, the buyer or the supplier.
4. Choose the AI provider and enter your API key.
5. Get a color-coded comparison table, topic by topic.

Data and history: results are saved only in this browser, and only if you turn it on (off by default). Saved results are kept for 90 days. The "Delete all data" button removes them at once.

## Names are replaced before any AI call

Names and other identifiers (companies, people, codes, accounts, addresses, contacts) are replaced by placeholders such as `[A.ORG_1]` before any AI call. You check every replacement in the preview and confirm it. The mapping between placeholders and real values stays in your browser. The result is pseudonymized, not anonymous: check the preview carefully.

## Topics

A topic is a subject of comparison, for example "Deductible" or "Payment term". The topic panel has these parts:

- **Domain and side.** Choose a domain (KASKO, OSAGO, lease or property insurance) and your side in it (for example insured, insurer, tenant or landlord). The domain and the side are required for AI suggestions and for your own topics.
- **Templates.** Each domain has ready topics in English, Ukrainian and Russian. All are selected by default. You can turn each one off. A template topic has typed attributes (amounts, percentages, durations, lists of values) and a direction for your side, for example "lower is better". The catalog lives in [`shared/topics/`](shared/topics/README.md).
- **Suggestions.** The button "Suggest from my contracts" asks the AI for topics, one call for each contract. It reads only the masked text. You accept each suggestion yourself. The suggestion text is checked before you see it, and refused names are counted as "dropped". This button needs confirmed masked contracts; in this build it stays inactive until stage 9 connects the panel to them.
- **Own topics.** Write a name and an optional description, press "Propose attributes", edit the attribute list and confirm. The AI proposes attributes without any contract text. The direction of an attribute starts at "none", and you choose it. Names and descriptions must not contain identifiers; the panel marks the offending part. Text that tries to address an AI is refused: reword the name.
- **Limit.** You can keep up to 10 own topics.
- **Storage.** Own topics stay in memory. "Save my topics on this device" is opt-in and writes them to `localStorage` (key `aic.topics.v1`; names, descriptions, attributes and synonyms, never contract text). "Delete all data" removes them.
- **Export and import.** You can export your topics as a JSON file and import them back. Import is checked strictly: at most 256 KiB, a fixed shape and the same limits as the server. A file that fails is rejected as a whole.

In free mode, the first topic call solves a Cloudflare check and gives a short pass (15 minutes, 20 calls), so you do not solve a check for every topic. Topic calls have their own daily quota. Details: [`docs/adr/0017-topic-catalog.md`](docs/adr/0017-topic-catalog.md).

## AI providers and your key

Open the provider settings to choose where the masked text goes.

- **AI Contrast Free (default).** A free model on Cloudflare Workers AI (`@cf/openai/gpt-oss-120b`) with our token. You need no key. Quotas are small: a few calls per day for each client and a daily budget for all users. When the quota is used up, use your own key. The UI states which provider processes the text and its data policy.
- **Your own key.** Presets: Anthropic, OpenAI, Google Gemini, Mistral and OpenRouter. Choose a model from the suggestions or enter a model ID. Gemini has a free key; the UI warns that Google may use free-tier data. Create a separate key for AI Contrast and set a spending limit.
- **Custom URL (advanced).** Any OpenAI-compatible service under an `https` host name. The server accepts only a public host name on port 443. IP addresses, local hosts and `http` are refused (see [`docs/security/threat-model.md`](docs/security/threat-model.md), T2). Local models work only in development (`ALLOW_PRIVATE_PROVIDER_URLS=true`).
- **Test connection.** The button sends one fixed tiny request. The server returns only "ok" or an error code, never model text.

Where your key lives:

- By default the key stays in `sessionStorage` and disappears when you close the tab.
- "Remember on this device" is opt-in. It stores the key in `localStorage` and shows a warning.
- "Forget key" removes the key of the selected provider. "Delete all data" in "Data and history" removes all keys and empties the open key field.
- The browser sends the key only to our backend, only in the `X-Provider-Key` header. The server holds it for one request, never logs it and never stores it.

Free mode and the Cloudflare check: free mode uses Cloudflare Turnstile against bots. The Cloudflare script runs only in a small separate page (the "Turnstile frame") on its own origin, in a sandboxed iframe. It never runs in the app page, so it cannot read your keys. The frame loads only in free mode, not on page load. Details: [`docs/adr/0016-model-connection.md`](docs/adr/0016-model-connection.md).

Free mode needs server settings (`CF_ACCOUNT_ID`, `CF_AI_TOKEN`, `TURNSTILE_SECRET_KEY`, `TURNSTILE_EXPECTED_HOSTNAME`). Without them the server answers `free_mode_unavailable`. For local tests of the frame, run `npm run dev:turnstile` in `frontend/` (it serves `http://localhost:5174` and uses Cloudflare's test site key).

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
