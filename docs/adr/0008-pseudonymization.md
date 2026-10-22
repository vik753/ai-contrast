# ADR 0008 — Pseudonymization before any AI call

- Status: accepted (customer decisions, 2026-10-20); design revised after the security design review of PR #11
- Date: 2026-10-20
- Related: ADR 0009 (prompt injection), ADR 0004 (text extraction), ADR 0001 (stateless), ADR 0007 (free default model)

## Context

The customer wants no names of companies, legal entities or people to reach an AI provider. Contracts are compared only by their conditions and are labelled "Contract A", "Contract B" and so on. Contracts also contain other identifiers: codes, accounts, addresses, contacts, document numbers, vehicle data.

The result is **pseudonymized, not anonymous** (see Residual risk).

## Decision

### 1. What is masked (customer decision: all identifiers)

Placeholders are **document-scoped and typed**: `[A.ORG_1]`, `[B.PERSON_2]`. The same value gets the same placeholder everywhere in one document.

| Class | Examples |
| --- | --- |
| `ORG` | Companies, legal entities, banks, insurers, notaries, sole proprietors (ФОП is both `ORG` and `PERSON`), organizations without a legal form ("Нова Пошта"), brand and product names that point to a party ("КАСКО «Оптимум»") |
| `PERSON` | Full names, initials forms ("Іваненко І.І.", "І. І. Іваненко"), Latin transliteration (IVANENKO), female and vocative forms, non-declining surnames (-ко), double surnames, surnames that are common words (Коваль, Мельник, Rose) |
| `TAX_ID` | ЄДРПОУ, РНОКПП / ІПН, УНЗР (contains the date of birth), ИНН, ОГРН, ОГРНИП, КПП, ОКПО, СНИЛС, VAT numbers |
| `ACCOUNT` | IBAN (with or without spaces), account numbers, МФО, SWIFT/BIC, card numbers |
| `ADDRESS` | Postal and registered addresses; the full address of leased or insured property; cadastral numbers |
| `PHONE`, `EMAIL`, `URL` | Including domains without a scheme, obfuscated emails ("info(at)…"), messenger handles |
| `PERSONAL_DOC` | Passport, ID card, driver licence data, dates of birth |
| `DOC_NO` | Contract, policy, certificate, invoice, power-of-attorney ("довіреність № … від …"), licence (НБУ / ЦБ), notary registry and court case numbers |
| `VEHICLE` | VIN, registration plate, vehicle registration certificate |
| `SIGNATURE` | Signature lines ("____ /Іваненко І.І./"), e-signature (КЕП) stamp text and certificate serials |
| `HEALTH` | Health data of named insured persons (special category) |

Kept, because they are conditions: role words defined by the contract ("Страховик", "Орендар", "Buyer"), amounts, percentages, terms, dates of obligations, territory of cover at city level.

A defined term that equals a masked name ("(далі — «Іваненко»)") is masked too.

### 2. Pipeline

1. **Extract** (ADR 0004 as revised by ADR 0009) and **clean** (ADR 0009 Layer 1). **Split** into sections and clauses (stage 5).
2. **Requisites section, line by line.** A section whose heading matches (`Реквізити та підписи сторін`, `Реквизиты и подписи сторон`, `Signatures`, `Details of the parties` and similar) is processed line by line. A line is dropped only if it consists entirely of identifiers, their labels (`ЄДРПОУ:`, `IBAN:`, `Адреса:`), role words and signature lines. Any other line — one with a verb or obligation marker (зобов'язується, погоджується, підписанням, обязуется, соглашается, agrees, shall, waives) or with non-identifier tokens above a small threshold — is kept, masked and analyzed as a clause, and gets 🟡 "condition found in the requisites section". Dropped lines are shown struck through in the preview and counted as "not analyzed" in the result.
3. **Neutralize placeholder look-alikes** in the source text (for example a literal `[ORG_2]`): the brackets are changed and the hit counts as suspicious (ADR 0009 Layer 2).
4. **Detect** on the backend, inside the parsing subprocess with time and memory limits:
   - preamble definitions ("ТОВ «…» (далі — Страховик), в особі директора …", "… (hereinafter the Insurer), represented by …") and every later occurrence, including UK/RU case forms (stem matching);
   - rules for legal forms, quoted names, signature lines, "в особі / в лице / represented by";
   - format rules with checksums where they exist (ЄДРПОУ, РНОКПП, IBAN, cards). **Checksummed codes need context:** a context keyword within a few tokens (ЄДРПОУ, код, ІПН, РНОКПП, ИНН, ОГРН, ОКПО, СНИЛС, IBAN, tax, identification) or a position inside the requisites section. A number followed by a currency, `%` or a unit of time, area or quantity, or written as an amount (thousand separators, decimals), never matches a code rule. A checksum match without context is only a proposal that the client can unmask;
   - PDF running headers and footers and DOCX headers and footers: lines repeated across pages are masked or dropped with a count;
   - detection runs on de-hyphenated text and on a confusable skeleton (UTS #39) so split and homoglyph values match; masks are applied to the original offsets.
   - linear-time patterns only; caps on entities and spans per document. **A cap fails closed:** the document is rejected with `too_many_identifiers`, never sent partly masked.
   - A masked token directly next to a currency, `%` or a unit gets 🟡 "a value next to an amount was masked, check it" on that clause.
   No ML model in v1 (memory and supply chain). Accuracy is measured by the eval.
5. **Mandatory preview** in the browser: every replacement, every dropped or removed part (ADR 0009) is shown. The client can mask more words and unmask false positives — except the high-precision classes (checksummed codes **with context**, IBAN, cards, emails, phones, URLs, legal form plus quoted name), which cannot be unmasked. "Everything is correct, send" starts the analysis.
6. **Mask in the browser.** The browser builds the masked clauses. The mapping `placeholder → original` stays in the browser; it is never sent to the backend's AI endpoints or to an AI provider.
7. **Server safety pass (fail closed).** The analysis endpoint receives the masked clauses as an untrusted DTO (`UntrustedMaskedClause`) plus the detector version that produced the proposals. The server never changes confirmed text silently, and logs hold counts only.
   - **Version check.** A detector version different from the server's is rejected with `detector_version_mismatch`; the UI asks the client to reload and runs detection again.
   - **Cleaning check.** ADR 0009 Layer 1 cleaning is idempotent. The server runs it on the submitted text only as a check: if it would change anything, the request is rejected with `input_not_clean`. Offsets are never mapped between two different texts.
   - **High-precision rules.** On a hit the server returns `unmasked_identifier` with span offsets (never values). The browser pre-masks those spans, shows them highlighted in the preview and asks the client to confirm again. Nothing is sent without a new confirmation.
8. **Labels.** Documents are `A`, `B`, `C`. File names (including the multipart and `Content-Disposition` names), PDF Info and XMP, DOCX `docProps` (core, app, custom), embedded files and Google document titles are never parsed into text, never logged and never sent to an AI provider.

### 3. Type gate (enforced at runtime and by a policy test)

- `PseudonymizedDocument`, `PseudonymizedText` (short strings) and `ConfirmedTopic` (ADR 0009 Layer 3) are frozen dataclasses with slots, **not** Pydantic models. Their constructors check a module-private sentinel at runtime; only `safety_pass()` can create them. `ConfirmedTopic` is created after masking, the Layer 2 check, the length cap and a placeholder-free check.
- Request bodies use different types (`UntrustedMaskedClause`). The gate type never appears in a request model.
- The `AIProvider` port accepts only domain types: the gate types, enums and constants. **No `str` parameter** anywhere on the port.
- Custom topics, synonyms, the client's side and AI-suggested topics pass through the detector and become `PseudonymizedText`; a confirmed topic becomes `ConfirmedTopic` (ADR 0009 Layer 3). The connection test sends a constant probe.
- An AST policy test (like `test_repo_policy.py`) fails, outside the module, on a constructor call, `cast(PseudonymizedDocument…)`, `__new__` or `object.__setattr__` on a gate type, on use of the sentinel, and on the gate type in any request model.
- Repair and retry calls re-send the same gate values plus an error-code enum; previous model output never re-enters a prompt.

### 4. Results and storage

- Model output and quotes use placeholders. Quotes are verified against the masked text.
- The browser restores names only at offsets it created, and in model free text only for tokens issued for that document. Toggle "show placeholders".
- Cache key = SHA-256 of the final masked text (client edits included) plus prompt and model versions (full key parts: ADR 0013 point 8). The mapping is **never stored** (ADR 0013 point 9a): a cached result holds placeholders only, and on a hit the browser restores names with the mapping of the current session.
- Exports (PDF, JSON) use placeholders by default; restored names only after an explicit choice with a warning.
- SSE events and error bodies carry codes only.

### 5. OCR via AI is removed from v1

Page images cannot be pseudonymized reliably. Scans are recognized only in the browser with Tesseract.js.

### 6. Tests

- **AI payload canaries on the wire:** raw HTTP requests captured with httpx `MockTransport` under the real `anthropic` and `openai` adapters (URL, every header, the whole JSON body including `metadata`, `user`, `safety_identifier`, `prompt_cache_key`), plus a fake `AIProvider`. Every AI call type: topic suggestion, synonym expansion, tagging, re-check, analysis, repair, retry, connection test.
- Canary coverage: every class in UK/RU/EN with case forms, initials, transliteration, female forms; zero-width-split, homoglyph and hyphenated variants; every location (preamble, body, headings, tables, footnotes, PDF running headers and footers, text boxes, content controls, tracked insertions, requisites, placeholder spoofing); everything outside the text (file name, PDF and DOCX metadata, Google title, export file name, custom topics, side text, suggested topics); every input path (PDF, DOCX, TXT, browser OCR text, Google export).
- Negative checks: no canary in logs, SSE events, error bodies or `422` responses; a frontend test intercepts `fetch` and asserts that the mapping and original values are never in the analysis request.
- Canary matching is case-insensitive, after NFKC, on the confusable skeleton and with separators removed.
- Fail-closed tests: every detection cap; `detector_version_mismatch`; `input_not_clean`; no request is sent after `unmasked_identifier` without a new confirmation; a checksum-valid number followed by a currency, `%` or a unit is not masked as a code; an obligation line in the requisites section is kept and analyzed.
- The eval measures recall **and precision** per class and per language.

## Consequences

- Identifiers do not reach any AI provider, including the free default model, as far as the detector, the safety pass and the client's preview catch them.
- Our backend still sees the original text in memory during extraction and detection (nothing is stored, ADR 0001).

## Residual risk

- **Pseudonymized, not anonymous.** The masks protect the client's personal data and identifiers. They do not hide a counterparty whose terms are public: insurers' standard terms, product wording and tariffs, or public procurement data (Prozorro) can re-identify a party, and language models are good at such inference.
- The UI never says "anonymous". The privacy policy states that pseudonymized data is still personal data (GDPR recital 26).
- Automatic detection is never complete; the mandatory preview is the final control.
