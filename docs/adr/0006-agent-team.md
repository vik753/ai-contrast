# ADR 0006 — Agent team and review workflow

- Status: accepted
- Date: 2026-10-19

## Context

The tech lead (Claude, main session) builds the app with a team of agents. The customer wants independent writing, testing and review.

## Decision

Agents live in `.claude/agents/`:

| Agent | Role | Model | Effort |
| --- | --- | --- | --- |
| `backend-dev` | Python, FastAPI, extraction, AI layer, Docker, CI | opus | medium |
| `frontend-dev` | React, TypeScript, i18n, OCR, IndexedDB, result table, a11y | opus | medium |
| `test-engineer` | Tests from acceptance criteria, e2e, security tests | opus | medium |
| `code-reviewer` | Code quality and architecture review, read-only | opus | medium (high until 2026-10-21) |
| `security-reviewer` | Review against the threat model, dependency audit, read-only | opus | high |
| `ai-eval-engineer` | Prompts, schemas, golden set, metrics | opus | high |
| `domain-analyst` | Topic templates in 3 languages, rating criteria, synthetic contracts | sonnet | medium |
| `docs-writer` | Repo docs, ADRs, progress log | sonnet | medium |

Rules:

- The author never reviews their own work. Reviewers start in a fresh context.
- Tests are written from acceptance criteria, not from the implementation.
- Reviewers do not edit code; they report findings.
- Escalation: after two failed attempts the tech lead reruns a task with `effort: high`.
- The environment variable `CLAUDE_CODE_EFFORT_LEVEL` is not set, so per-agent `effort` applies.
- **Revision 2026-10-21 (token economy, customer request):** `code-reviewer` runs at medium effort; `security-reviewer` stays at high. Repeat reviews are delta reviews by the reviewer who requested changes. Test-first by `test-engineer` for new criteria and BLOCKER/HIGH/MAJOR findings; developers add tests for MINOR/NIT fixes. Agent reports are at most 300 words. See `CLAUDE.md`, "Token economy".

## Consequences

- Higher quality and fewer blind spots; more tokens per task.
- Strong models and high effort go where mistakes are hardest to notice: security, review, eval.
