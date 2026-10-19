# Progress

How to resume after a break: read this file, then continue with the first unchecked task in `docs/agent/TASKS.md`.

## Stage status

| # | Stage | Status |
| --- | --- | --- |
| 0 | Project rules | done |
| 1 | Scaffold | next |
| 2 | File upload | planned |
| 3 | Text extraction | planned |
| 4 | Browser hash and cache | planned |
| 5 | Clause splitting | planned |
| 6 | Model connection | planned |
| 7 | Topic catalog | planned |
| 8 | Clause tagging | planned |
| 9 | Analysis | planned |
| 10 | Result table | planned |
| 11 | Token economy and quality | planned |
| 12 | Security audit | planned |
| 13 | Deploy | planned |

## Customer decisions (2026-10-19)

- Stateless backend, BYOK, no database in v1 (ADR 0001).
- Official `anthropic` and `openai` SDKs instead of LiteLLM (ADR 0002).
- Frontend on Cloudflare Pages (ADR 0003).
- pdfplumber and python-docx instead of Docling (ADR 0004).
- License AGPL-3.0-only, public repository (ADR 0005).
- Agent team and review workflow (ADR 0006).
- Carte blanche for the tech lead. Report to the customer after each stage. Ask only on disputed questions and blockers.

## Log

- 2026-10-19 — Stage 0 done: `CLAUDE.md`, `README.md`, `SECURITY.md`, `LICENSE`, threat model, plan, ADR 0001–0006, eight agents in `.claude/agents/`, repository security settings.
