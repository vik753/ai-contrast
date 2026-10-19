# ADR 0002 — Official provider SDKs instead of LiteLLM

- Status: accepted
- Date: 2026-10-19

## Context

The first plan used LiteLLM to reach any provider. On 2026-03-24, malicious LiteLLM versions 1.82.7 and 1.82.8 were published to PyPI. They stole LLM API keys, cloud keys, SSH keys and `.env` secrets. Attackers got publishing access through the project's CI/CD.

AI Contrast handles other people's API keys. Every extra dependency in the request path is a direct risk to those keys.

## Decision

- The application depends on an `AIProvider` port only.
- Two adapters:
  - `anthropic` SDK — Anthropic models, native prompt caching;
  - `openai` SDK — OpenAI and any OpenAI-compatible API (Google Gemini, Mistral, OpenRouter, Groq and others) via a base URL.
- LiteLLM is not used.

## Consequences

- Fewer transitive dependencies and a smaller attack surface.
- Some provider-specific features need adapter code.
- Replacing an SDK touches one adapter file only.
