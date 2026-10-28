# Segmentation fixtures (S5-T0)

One JSON file per case, synthetic text only. Format: `name`, `language`, `description`, `blocks` (`text`, `part`, `page`), `expected` (`clauses`, `warnings`).
`starts_with` is a 20-40 character prefix of the clause's first block (the whole block if shorter), for boundary checks. Tests rebuild clause text from spans. Clauses are listed in document order (order of the first span).

## Conventions used for the expected results

- `number` is stored as written without trailing `.` or `)`, and without the article word (`Стаття 5.` gives `5`, `II.` gives `II`).
- A clause starts at every numbered line, article-word line, Roman line, and heading line (numbered title, all-caps short line, annex heading, requisites heading). Unnumbered blocks that follow continue that clause.
- A numbered section title is a heading and also starts a clause; its `heading` is its own title without the number. Sub-clauses carry the nearest section heading.
- Text before the first start is one `preamble` clause (body blocks only).
- Non-body parts (footnote, endnote, header, footer, textbox): one clause per block, number and heading null, `part` equal to the block part, whatever the text starts with.
- Running lines (security review): exact match, in the first or last 2 lines of a page, on at least 3 pages and at least half of the pages, at most 120 characters, never a clause start or heading. One `running` clause at the first occurrence; other occurrences are covered by it. Running lines in these fixtures end with a period so they are not heading-like. A line that differs by digits is not an exact match.
- `requisites` only when the whole heading line is in the closed list (case-insensitive); the clause ends at the next clause start or heading; a numbered clause is never `requisites`.
- A new all-caps annex heading opens a new numbering scope: no restart or duplicate warnings across it.
- `numbering_restart`: the number returns to the first value after higher ones. `duplicate_number`: the same number as the previous clause. One warning per occurrence.

## Files

- `01_uk_insurance_decimal3` - preamble, numbered caps titles, decimal numbering to 3 levels.
- `02_ru_lease_lettered` - sentence-case titles, lettered items (а, б, в) stay in the parent.
- `03_en_services_article` - `Article N. Title`.
- `04_uk_stattya_unnumbered_body` - `Стаття N. Title` with unnumbered paragraphs.
- `05_ru_statya_inline` - `Статья N.` with inline text (heading null).
- `06_en_roman_sections` - Roman sections with continuous Arabic clauses.
- `07_uk_lettered_items` - Cyrillic lettered items.
- `08_en_lettered_nested` - `(a)` and nested `(i)` items.
- `09_uk_allcaps_unnumbered_headings` - unnumbered all-caps headings.
- `10_ru_requisites_numbered` - numbered requisites heading.
- `11_uk_requisites_unnumbered_caps` - unnumbered caps requisites, obligation line kept.
- `12_en_signatures_titlecase` - unnumbered title-case `Signatures` at the end.
- `13_uk_footnotes` - footnotes starting with `1.` are not numbering.
- `14_ru_docx_parts` - header, footer, textbox, endnote parts.
- `15_uk_pdf_running` - running header and footer on 4 pages, clause across a page break.
- `16_en_pdf_running_threshold` - 3 of 6 pages is running; 2 pages is not.
- `17_ru_pdf_page_numbers_footer` - footer differing by digits is not running.
- `18_uk_no_numbering` - fallback, `no_numbering_found`.
- `19_en_numbering_gap` - `numbering_gap`.
- `20_ru_numbering_restart` - `numbering_restart`.
- `21_uk_duplicate_number` - `duplicate_number`.
- `22_en_annex_own_numbering` - annex with its own numbering, no warnings.
- `23_uk_razdel_paren` - `Розділ N.` and `1.1)` style.
- `24_en_section_paragraph_sign` - `§ N` and `Section N.`.
- `25_uk_pdf_long_sentence_not_collapsed` - 150+ character sentence repeated on every page stays body.
- `26_uk_pdf_short_sentence_collapsed` - short sentence repeated on every page becomes one running clause.
- `27_en_pdf_numbered_line_repeats` - repeated numbered line is never running.
- `28_en_early_signatures` - early `Signatures` followed by numbered clauses.
- `29_uk_requisites_mid_document` - requisites in the middle.
- `30_ru_requisites_not_exact` - near-miss heading is not requisites.
