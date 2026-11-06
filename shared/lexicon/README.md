# Lexicons for analysis verification (S9-T0)

Checked-in data for `app/analysis/verify/` (ADR 0019 points 3 and 4). All files are JSON with `"version": 1`.
Entries are **literal words and phrases, never regular expressions**. Code must not build a regex from them
that can backtrack; use a linear scan (for example Aho-Corasick or a token walk).

## Matching rules (shared)

- Case-fold the text and the entry. Normalize the apostrophes U+2019 and U+02BC to U+0027, and `ё` to `е` for comparison only.
- Fold runs of whitespace to one space.
- An entry matches at a word boundary on the left. UK and RU entries that are a word stem (for example `крім`, `кроме`) also match longer forms; EN entries match whole words.
- Prefer the longest match at one position.

## Files

| File | Used by | Shape |
| --- | --- | --- |
| `exception_markers.json` | `check_exceptions` | `{en, uk, ru}`: lists of phrases |
| `global_override_markers.json` | `global_override` | `{en, uk, ru}`: lists of phrases |
| `clause_references.json` | cross-reference closure, `too_many_references`, `document_flags` | `prefixes` (words before a clause number), `joiners` (between several numbers), `self_reference` (not a reference), `relative` (a reference without a number, cannot be resolved), `external` (points outside the document) |
| `unit_words.json` | `number_mismatch` | `percent_marks`, and per catalog unit `{en, uk, ru}` word lists |
| `number_words.json` | `number_mismatch` | atoms 0 to 19, tens 20 to 90 and 100 per language, with case forms and genders |
| `sentence_abbreviations.json` | quote expansion | `never_end` and `may_end` per language |

## Details

- **Clause numbers** are not in a list: after a prefix, a number is digit groups joined by dots (`4.2.1`), optionally followed by a parenthesised letter or digit. A trailing dot is punctuation. Joiners allow `clauses 4.1 and 4.2`.
- **Units.** Check `working_days` before `days`, and `percent_of_sum` / `percent_of_loss` before a bare percent. A percent unit needs a percent mark and, within 60 characters after it, a qualifier phrase of the unit (`percent_of_sum`, `percent_of_loss`). A bare percent with no qualifier fits neither unit. Currency symbols may stand before or after the number.
- **Number words.** Compose 21 to 99 as tens plus units (`twenty-five`, `двадцять п'ять`, `двадцати пяти`), any case combination. Accept `a hundred` and `сто`. Digits accept `1 000`, `1,000`, `1 000,50`, `1.5` and `1,5`. The pattern `десять (10)` is a number written twice; the two must agree. If they disagree, the number is a `number_mismatch` (see the attack case `number_words_mismatch`).
- **Abbreviations.** A dot after a `never_end` token is never a sentence end. A dot after a `may_end` token ends the sentence only if the next word starts with an uppercase letter or a list marker. Clause numbers such as `4.2.` are not sentence ends.
- `relative` and `external` references have no clause number to look up. S9-T1 decides how they feed the `unprovided_references` flag (open question, not fixed here).

## Sources

Wording of markers comes from typical contract and insurance rule wording and from the statutes quoted in `shared/topics/README.md`. The lists are working data for tests, not a legal taxonomy. They were not validated against a corpus.

- Ukrainian graphic abbreviations (UK list): Ukrainian orthography 2019, section on abbreviations, https://mon.gov.ua/static-objects/mon/sites/1/zagalna%20serednya/Pravopys.2019/ukr.pravopys-2019.pdf
- Russian numeral declension (RU forms): https://www.oshibok-net.ru/storage/b/2016/06/06/Sklonenie_chislitelnykh.pdf
- Ukrainian numeral declension (UK forms): textbook tables, for example https://naurok.com.ua/test/vidminyuvannya-chislivnikiv-1466165.html
- Civil Code of Ukraine (wording of "except", "unless", insurance and lease terms): https://zakon.rada.gov.ua/laws/show/435-15

The search results were not fetched in full. Check the forms and abbreviations against the sources before the lists are treated as complete.
