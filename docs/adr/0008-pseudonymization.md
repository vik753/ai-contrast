# ADR 0008 — Pseudonymization before any AI call

- Status: accepted (customer decision, 2026-10-20)
- Date: 2026-10-20

## Context

The customer wants no names of companies, legal entities or signatories to reach an AI provider. Contracts are compared only by their conditions. Documents are labelled "Contract A", "Contract B" and so on.

Contracts also contain other identifiers: tax and registry codes, bank accounts, addresses, phones, emails, passport data, policy and contract numbers, vehicle data.

## Decision

### What is removed (customer decision: all identifiers)

Each identifier is replaced by a typed, numbered placeholder. The same value gets the same placeholder everywhere in one document.

| Placeholder | What it replaces |
| --- | --- |
| `[ORG_n]` | Names of companies, legal entities, banks, insurers, sole proprietors (with their legal form: ТОВ, ПрАТ, АТ, ФОП, ООО, ПАО, LLC, Ltd, GmbH, JSC and others) |
| `[PERSON_n]` | Names of people: signatories, representatives, insured persons, beneficiaries |
| `[TAX_ID_n]` | ЄДРПОУ, РНОКПП / ІПН, ИНН, ОГРН, VAT numbers and similar codes |
| `[ACCOUNT_n]` | IBAN, bank account numbers, МФО, SWIFT/BIC, card numbers |
| `[ADDRESS_n]` | Postal and registered addresses |
| `[PHONE_n]`, `[EMAIL_n]`, `[URL_n]` | Contact data |
| `[PERSONAL_DOC_n]` | Passport, ID card and driver licence data, dates of birth |
| `[DOC_NO_n]` | Contract, policy, certificate and invoice numbers |
| `[VEHICLE_n]` | VIN, registration plate, vehicle registration certificate |

Kept, because they are conditions: role words defined by the contract ("Страховик", "Страхувальник", "Орендар", "Buyer"), amounts, percentages, terms and periods, dates of obligations, places that are part of a condition only at city level (for example the territory of cover).

The whole "requisites and signatures" section (`Реквізити та підписи сторін`, `Адреси та реквізити сторін`, `Реквизиты и подписи сторон`, `Signatures`, `Details of the parties` and similar) is removed: it holds no conditions.

### Pipeline

1. **Extract** (stage 3), **split** into sections and clauses (stage 5).
2. **Drop** the requisites and signature sections.
3. **Detect** identifiers on the backend:
   - definitions in the preamble ("ТОВ «…» (далі — Страховик), в особі директора …", "… (hereinafter the Insurer), represented by …"), then every later occurrence, including Ukrainian and Russian case forms (stem matching);
   - rules for legal forms, quoted company names, signature lines, "в особі / в лице / represented by";
   - format rules for codes, IBAN, phones, emails, URLs, VIN, plates, document numbers (with checksums where they exist).
   No ML model in v1: NER models need hundreds of MB (the backend has 512 MB) and add supply-chain risk. Accuracy is measured by the eval; an ML detector is a later option.
4. **Preview (mandatory).** The browser shows the text with every replacement highlighted. The client can mask more words or unmask a false positive. The button "Everything is correct, send" starts the analysis. Without this step no AI call is possible.
5. **Mask in the browser.** The browser builds the pseudonymized clauses from the original text, the detected spans and the client's edits. The mapping `placeholder → original` stays in the browser (memory and, with history on, IndexedDB). It is never sent to the backend or to an AI provider.
6. **Server safety pass.** The analysis endpoint receives only pseudonymized clauses. The backend runs the detector again on them and masks anything left (defense in depth). Only the result of this pass can be sent to an AI provider.
7. **Document labels.** Documents are `A`, `B`, `C`. File names, PDF metadata and Google document titles never reach an AI provider.

### Type-level guarantee

- The AI layer (`AIProvider` port) accepts only a `PseudonymizedDocument` (or clauses of it).
- Only the pseudonymization module can construct that type (private constructor / factory).
- Raw text cannot be passed to an AI call: `mypy --strict` rejects it.

### Results

- Model output and quotes use placeholders.
- Quotes are verified against the pseudonymized text (what the model saw).
- The browser restores the original names locally for display, with a toggle "show placeholders". The restored text never leaves the browser.

### OCR via AI is removed from v1

The "OCR via AI" button would send page images, and names cannot be removed from an image reliably. Scans are recognized only in the browser with Tesseract.js. A later version may OCR locally and then pseudonymize the text.

## Consequences

- No identifiers reach any AI provider, including the free default model (ADR 0007), as far as the detector and the client's preview catch them.
- Our backend still sees the original text in memory during extraction and detection (stateless, nothing stored; ADR 0001).
- Automatic detection is never 100 %: the mandatory preview is the final control. The eval measures redaction recall on a golden set with planted identifiers in three languages; the target is 100 % on the golden set.
- Cache keys include the pseudonymization version.
- A new test class: the **AI payload canary** — planted names and codes in test contracts must never appear in any request recorded by a fake `AIProvider`.
