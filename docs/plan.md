# AI Contrast — plan

The customer's master copy of the plan (in Russian, with theory notes) lives in his Obsidian vault.
This file is the working copy for the team.

## Requirements

1. Upload two or more contracts. One contract may consist of several files (the main text plus annexes, for example the insurer's rules); they are analyzed as one document.
2. Formats: PDF with text, scanned PDF, DOCX, Google Docs, plain text.
   - Apple Pages: the UI asks the client to export to PDF and shows how.
   - Google Docs: import by link, or upload of an exported DOCX or PDF.
3. Comparison topics, three modes that can be combined and edited before the analysis:
   - ready template: car insurance (KASKO), compulsory motor liability (OSAGO), lease, property insurance;
   - topics suggested by AI from the uploaded contracts;
   - the client's own topics.
4. The client chooses their side (for example: insured party, buyer, supplier).
5. AI provider (ADR 0007):
   - **Default:** "AI Contrast Free" — Cloudflare Workers AI `gpt-oss-120b` with our key; works without a client key; small daily quota; Turnstile check.
   - **Own key:** the client chooses a provider and model and enters their own API key. Known providers have preset base URLs. A custom base URL is an advanced setting.
   - **Free-key hint:** "Get a free Gemini key" link with a warning about Google's free-tier data use.
   - **Demo:** sample contracts with precomputed results, no key and no AI call.
6. Comparison by clause and by meaning, not by number or title.
7. Result: a table with ratings — green (favorable), yellow (attention), red (unfavorable). Each cell has an explanation and a contract quote. Color is always paired with an icon and a text label.
8. The server stores nothing: no contracts, keys or results.
9. Re-upload of the same contracts is detected. The client chooses: cached result or new analysis. The cache lives in the browser.
10. Minimal token usage without quality loss. The client sees an estimated cost before the analysis starts.
11. Contract languages: English, Ukrainian, Russian. Contracts in different languages can be compared with each other in v1.
12. UI languages: English (default), Ukrainian, Russian.
13. Security from the first stage: `docs/security/threat-model.md`.
14. **Pseudonymization (ADR 0008).** No identifier reaches an AI provider: names of companies, legal entities and people, tax and registry codes, bank accounts, addresses, contacts, personal documents, document numbers, vehicle data. Documents are labelled A, B, C. Lines of the requisites and signatures section that hold only identifiers are removed; a condition found there is kept and analyzed. A preview with all replacements is mandatory before any AI call. The browser restores names in the results locally.

## Analysis pipeline

1. **Upload.** The browser hashes each file and checks its cache. The browser OCRs scans with Tesseract.js. Other files go to the backend.
2. **Extract.** The backend extracts text in memory and detects the language.
3. **Cache check.** The browser hashes the normalized text. On a hit the client chooses: cached result or new analysis.
4. **Split.** The backend splits text into clauses by numbering and headings. No AI.
4a. **Pseudonymize (ADR 0008).** The backend drops identifier-only lines of the requisites section and detects identifiers. The browser shows a mandatory preview; the client confirms or edits the masks. The mapping stays in the browser. The backend runs a safety pass before any AI call.
5. **Topics.** Template, AI suggestion or own topics. Every topic has typed attributes (ADR 0009 Layer 3): templates ship them; for other topics a model proposes them from the topic name only, and the client confirms. A cheap model expands each topic with synonyms.
6. **Cost estimate.** Estimated tokens and cost. The client confirms.
7. **Tag.** Per document. Keyword tags from code plus model tags; a cheap model tags each clause with topics (several tags allowed), a strong model checks low-confidence cases. Untagged clauses go to "Other" and are still rated.
8. **Analyze.** Per document (ADR 0009): a strong model receives the clauses of **one** contract for one topic, the client's side and the UI language, and fills the topic attributes with values and quotes. Findings in the UI language, quotes in the original language. Strict JSON. Code then compares the documents by attribute values; free-text attributes are shown side by side.
9. **Verify.** Schema validation, quote verification against the source text, and the green rules (exceptions, numbers with units, warnings).
10. **Result.** Streamed by topic over SSE. The browser renders the table and stores the result in IndexedDB if history is on.

## Stages

| # | Stage | Result |
| --- | --- | --- |
| 0 | Project rules | Threat model, agent team, rules, ADRs, repository security settings. |
| 1 | Scaffold | Monorepo, Docker Compose, FastAPI, React, i18n (en/uk/ru), baseline security headers, CI (lint, tests, pip-audit, npm audit, CodeQL), Dependabot. One command to run. |
| 2 | File upload | Multi-file form; several files per contract (main text plus annexes); one file per request as raw bytes, no file name sent (ADR 0010); type by magic bytes; size and count limits; in-memory handling. |
| 3 | Text extraction | pdfplumber, python-docx, TXT; zip bomb and XXE defenses; subprocess parsing with limits; Google Docs by link and via Picker; `.pages` hint; Tesseract.js OCR with confidence; language detection. Read what the person reads (ADR 0009 Layer 0): DOCX parts resolved through relationships, own DOCX walker (headers and footers included), PDF render-mode device, damaged-PDF detection, material "Not read" warnings, references to documents not provided, provably-invisible text removal shown in the preview. |
| 4 | Browser hash and cache | Web Crypto, IndexedDB, `CacheStore` port, "already analyzed" dialog, 90-day retention, history toggle, "Clear all". |
| 5 | Clause splitting | By numbering and headings, no AI. |
| 5b | Pseudonymization | Input cleaning against hidden prompt injection (ADR 0009: Unicode format characters, invisible PDF text, hidden DOCX content), requisites section line by line, identifier detection (preamble definitions, case forms, legal forms, code formats with context), caps that fail closed, mandatory preview with manual masks, browser-side mapping, server safety pass, `PseudonymizedDocument` type gate for the AI layer, AI payload canary tests, redaction recall in the eval (ADR 0008). |
| 6 | Model connection | `AIProvider` port, `anthropic` and `openai` adapters, presets, custom URL with SSRF guard, key handling and log canary, key storage options, test request. Free default provider (Cloudflare Workers AI) with Turnstile and daily quotas; free-key hint for Gemini (ADR 0007). |
| 7 | Topic catalog | Templates as JSON in the repo (3 languages) with typed attributes per topic, AI-suggested topics, own topics (browser storage, export/import), attribute proposal from the topic name only, client confirmation (`ConfirmedTopic`), synonym expansion, client side selection. |
| 8 | Clause tagging | Cheap model tags, strong model checks low confidence, "Other" bucket. Per document; deterministic keyword tags joined with model tags; "Other" clauses scanned and rated (ADR 0009). |
| 9 | Analysis | Prompt with instruction/data separation, strict JSON, Pydantic, quote verification, SSE progress, cross-language comparison, missing-topic findings. Prompt injection controls (ADR 0009): random boundaries, sandwich rules, `injection_suspected` field, deterministic exception rule, number check. Map-reduce: one document per call, comparison by code from topic attributes, policy test "no call with two documents". |
| 10 | Result table | Colors with icons and labels, explanations, quotes, "Other", plain-text rendering, export to PDF and JSON. Demo mode with sample contracts and precomputed results (ADR 0007). |
| 11 | Token economy and quality | Prompt caching, per-topic cache, model routing, cost estimate, eval on a golden set. Adversarial prompt-injection set: attack success 0 beyond the clean-vs-clean variance; for AI-layer changes the eval result on the PR head is recorded in the PR (ADR 0009). |
| 12 | Security audit | Threat model review, OWASP ZAP, manual pentest (OWASP Top 10, OWASP Top 10 for LLM), header check, real contracts in 3 languages. |
| 13 | Deploy | Cloudflare Pages, Render, GitHub Actions deploy, header check on the production domain. |

## Hosting (checked 2026-10-19)

| Part | Service | Free tier |
| --- | --- | --- |
| Frontend | Cloudflare Pages | Free, no card, custom headers via `_headers`. |
| Backend | Render | 750 h/month, ~512 MB RAM, sleeps after 15 min, ~1 min cold start, 5 GB bandwidth/month. |
| Backend fallback | Google Cloud Run | 180,000 vCPU-seconds and 2M requests/month; needs a card. |

## Open questions

- Domain and trademark check for "AI Contrast".
- Provider presets for v1. Proposal: AI Contrast Free (Cloudflare), Anthropic, OpenAI, Google Gemini, Mistral, OpenRouter.
- Workers Paid ($5/month) to raise the free quota — customer decision, later.
