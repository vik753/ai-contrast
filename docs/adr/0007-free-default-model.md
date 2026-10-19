# ADR 0007 — Free default model, demo mode and a free-key hint

- Status: accepted (customer decision, 2026-10-19)
- Date: 2026-10-19

## Context

The customer wants a free model selected by default, so a visitor can try AI Contrast without an API key. A visitor who wants more can enter their own key for any provider.

Research (October 2026):

- Every free AI API needs a key. A default free model therefore needs **our own** key on the server.
- Google Gemini (AI Studio) has the largest free tier and the best free models, but Google uses free-tier content to improve its products and human reviewers may read it (outside the EEA, UK and Switzerland). That breaks our privacy promise for contracts.
- Cloudflare Workers AI: 10,000 Neurons per day free; does not use customer content for training and does not retain inputs or outputs. `@cf/openai/gpt-oss-120b` costs 31,818 / 68,182 Neurons per million input / output tokens. Estimate: ~2,600 Neurons per analysis of two ~15-page contracts → about 3–4 analyses per day for all users together. OpenAI-compatible endpoint available.
- Groq free tier: 200,000 tokens/day and 8,000 tokens/minute per model; logs may be kept up to 30 days. OpenRouter free: 50 requests/day. Cerebras: no permanent free tier.

## Decision

Three layers:

1. **Demo mode.** Built-in synthetic sample contracts with precomputed results, shipped as static data with the frontend. No key, no AI call, no cost. (Stage 10; sample contracts by `domain-analyst`.)
2. **Free default provider ("AI Contrast Free").** Preset selected by default:
   - Cloudflare Workers AI through its OpenAI-compatible endpoint `https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai/v1/`, via the `openai` SDK adapter.
   - Model: `@cf/openai/gpt-oss-120b` for analysis. A cheaper Workers AI model may be used for tagging if the eval shows equal quality (stage 11).
   - Credentials `CF_ACCOUNT_ID` and `CF_AI_TOKEN` (token scoped to Workers AI only) live only in the hosting environment (Render secret env vars). Never in the repository, never sent to the browser, never logged.
   - The Cloudflare account stays on the **Workers Free** plan, so usage above 10,000 Neurons per day fails instead of being billed. Moving to Workers Paid ($5/month, $0.011 per 1,000 Neurons above the free allocation) is a separate customer decision.
   - Abuse controls: Cloudflare Turnstile check on free-mode analyses; per-IP daily limit; in-memory global daily Neuron budget below the free allocation; stricter size limits in free mode (initial: 2 documents, 30 pages in total).
   - When the free quota is used up, the API returns `429` with code `free_quota_exhausted`, and the UI offers the client to enter their own key.
   - The UI states: free mode runs on Cloudflare Workers AI; Cloudflare does not train on or keep the content.
3. **Free-key hint.** A "Get a free Gemini key" link (Google AI Studio) with an honest warning: on Google's free tier, content may be used to improve Google's products and may be read by reviewers. Gemini is reached through its OpenAI-compatible endpoint with the client's own key.

## Consequences

- The server now holds its **own** operational secrets: `CF_AI_TOKEN`, `CF_ACCOUNT_ID` and the Turnstile secret key. It still never stores client secrets. `CLAUDE.md` rule 1 and the threat model (T10) are updated.
- Free mode serves only a few analyses per day. That is expected: it is a trial, not the main path.
- Model quality for Ukrainian and Russian contracts must be measured by the eval (stage 11). If it is too low, the free default model changes; this ADR is updated.
- Customer actions later (stages 6 and 13): Cloudflare account (also needed for Pages), a Workers AI API token, a Turnstile widget, and Render secret env vars.
