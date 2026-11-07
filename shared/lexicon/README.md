# Lexicons for analysis verification (S9-T0)

Checked-in data for `app/analysis/verify/` (ADR 0019 points 3 and 4). Every file is JSON with a `version` number.
Entries are **literal words and phrases, never regular expressions**. Code must not build a regex from them
that can backtrack. Use a linear scan (for example Aho-Corasick or a token walk).

## One normalization function (security rule)

Lexicon entries and contract text go through the **same single function in code**, and nothing is compared before it ran.
The function does, in this order:

1. Unicode NFKC.
2. Case folding (`casefold`).
3. `ё` becomes `е` (before the skeleton, so the skeleton cannot turn it into another letter first).
4. All apostrophes fold to U+0027: `'`, U+2019, U+2018, `` ` ``, U+02BC, U+FF07.
5. All hyphens and dashes fold to U+002D: U+2010 to U+2015, U+2011, U+2212 (and the ASCII hyphen).
6. The UTS #39 confusable skeleton, so that look-alike letters (Latin `a`, Cyrillic `а`) compare equal.
7. Runs of whitespace fold to one space.

Entries are normalized once at load time with this function. A second, different normalizer anywhere in the verification code is a defect (it opens a bypass: text that looks like an exception marker to the reader but not to the code).

## How entries match

- **Phrases.** A multi-word entry matches the normalized text word by word. Whitespace between the words is flexible (any run of whitespace or a line break matches one space of the entry). Punctuation inside the entry (for example the comma in `при условии, что`) must match.
- **Word-start prefix.** An entry matches only at the start of a word in the text. The last word of an entry may be a stem, so `крім`, `кроме`, `винятком`, `лишь` also match longer forms (`лишь`, `кроме того`). EN entries must also end at a word boundary.
- **Longest match** wins at one position.
- Over-matching is accepted (over-capping is cheaper than a missed exception). The eval measures the rate of capped greens on honest contracts.

**Overlaps.** A phrase that is both in `clause_references.json` `self_reference` and in `relative_references.json` is a relative reference: `relative_references` wins, and the green is capped (`unresolved_reference`).

## Files

| File | Used by | Shape |
| --- | --- | --- |
| `exception_markers.json` | `check_exceptions` | `{en, uk, ru}` phrases, plus `added_in_review` |
| `global_override_markers.json` | `global_override` | `{en, uk, ru}` phrases, plus `added_in_review` |
| `clause_references.json` | cross-references, `too_many_references` | `prefixes`, `joiners`, `range_words`, `self_reference` |
| `relative_references.json` | `unresolved_reference` | `{en, uk, ru}` phrases of references that code cannot resolve |
| `unit_words.json` | `number_mismatch` | `percent_marks`, and per catalog unit `{en, uk, ru}` words |
| `number_words.json` | `number_mismatch` | per language: atoms with case forms |
| `sentence_abbreviations.json` | quote expansion | `never_end` and `may_end` per language |

### Origin of entries

The first drafts of the two marker files follow the wording of ADR 0009 and typical contract wording; they are not a verbatim copy of an ADR list. Entries added after the S9-T0 review are listed under `added_in_review` in each file, and also stand in the main lists. The generic entries (for example `however`, `проте`, `однак`, `в разі`, `лишь`, `попри`) were kept on purpose: the tech lead prefers over-capping.

## Details

- **Clause references.** After a prefix, a number is digit groups joined by dots (`4.2.1`), optionally with a parenthesised letter or digit. A trailing dot is punctuation. `joiners` allow `clauses 4.1 and 4.2`. `range_words` and the dash (all dash variants fold to `-`) expand a range (`6.1-6.4`, `пунктами 6.1 по 6.4`) to every existing clause number between the ends. Code **also** treats any dotted number in a clause that matches an existing clause number as a reference, with or without a prefix.
- **Unresolved references.** `relative_references.json` lists references with no clause number (`above`, `вище`, `the Rules`, `Правила`, `the Schedule`, `настоящий раздел`). A clause that holds one cannot be checked, so a green on it is capped with `unresolved_reference`. Stems such as `вышеуказанн` follow the prefix rule.
- **Units.** Check `working_days` before `days`, and `percent_of_sum` / `percent_of_loss` before a bare percent. A percent unit needs a percent mark and, within 60 characters after it, a qualifier phrase of the unit. A bare percent fits neither unit. Currency symbols may stand before or after the number.
- **Number words.** `number_words.json` holds atoms only: 0 to 19, tens, hundreds 100 to 900, `1000` (thousand words), `1000000`, `0.5` (half), `1.5` (`півтора`, `полтора`, `one and a half`), and dozen/`десяток` under 12/10. In v1 code reads only 0 to 100 and the compounds 21 to 99 (`twenty-five`, `двадцять п'ять`, `двадцати пяти`), and the pattern digits plus words (`десять (10)`); the words and the digits must agree. Every other listed form (hundreds above 100, thousand, million, half, one and a half, dozen) is recognised as a number word but **not read**: next to a unit word it gives `number_mismatch` (fail closed). A separator followed by exactly three digits in a single group (`2.500`, `1,000`) is ambiguous and also gives `number_mismatch`; `1 000` and `1.000.000` are read.
- **Scale words.** `number_words.json` also has a top-level `scale_words` object (`en`, `uk`, `ru`): `thousand`, `million`, `billion`, `k`, `m`, `bn`, `тис.`, `млн`, `млрд`, `тыс.` and their forms. A scale word right after a number (`USD 10 million`, `10 тис. грн`, `5k`) makes the number unmatchable (`number_mismatch` for any claimed value), because the claimed value could be the digits or the scaled amount.
- **Allowlist grammar for numbers.** A number is readable only when all of these hold; otherwise it is unmatchable (`number_mismatch` for any claimed value). (a) It is digits with the allowed separators only, and nothing but space, letters or plain punctuation touches it (`10/1000`, `10·1000`, `10^3`, `10±2`, `10×` are unreadable). (b) The token before it (or before its currency, in `USD 10`) is the start of a sentence or clause (`. ; : ! ? (`, a line break) or ends a phrase of `safe_before_number` (`within`, `протягом`, `в течение`, `у розмірі`, ...). There is no `up to`/`до` and no multiplier. (c) After its unit, percent mark or currency (or after the number, when the currency stands first) comes a terminator (`. ; : )`, a line break, the end), a phrase of `safe_after_unit` (`after`, `of`, `з`, `від`, `от`, ...), or a `per_words` word (`per`, `на`) followed by a `per_targets` word (`event`, `випадок`, `случай`, ...). A comma, `and` or any other word is not allowed. (d) The sentence holds no `scale_words` word (a one-letter scale such as `k` counts only right after a digit). A clause that states a scale (a scale word of four letters or more that does not stand right after a number: `amounts in thousands`, `суми в тисячах`) makes every number of the document unreadable.
- **Fail closed.** If a number word next to a unit word cannot be parsed by the code (not in the lists, or not composable), the result is `number_mismatch`, never a pass.
- **Abbreviations.** A dot after a `never_end` token is never a sentence end. A dot after a `may_end` token ends the sentence only if the next word starts with an uppercase letter or a list marker. Clause numbers such as `4.2.` are not sentence ends.

## Sources

Wording of markers comes from typical contract and insurance rule wording and from the statutes quoted in `shared/topics/README.md`. The lists are working data for tests, not a legal taxonomy. They were not validated against a corpus.

- Ukrainian graphic abbreviations (UK list): Ukrainian orthography 2019, section on abbreviations, https://mon.gov.ua/static-objects/mon/sites/1/zagalna%20serednya/Pravopys.2019/ukr.pravopys-2019.pdf
- Russian numeral declension (RU forms): https://www.oshibok-net.ru/storage/b/2016/06/06/Sklonenie_chislitelnykh.pdf
- Ukrainian numeral declension (UK forms): textbook tables, for example https://naurok.com.ua/test/vidminyuvannya-chislivnikiv-1466165.html
- Civil Code of Ukraine (wording of "except", "unless", insurance and lease terms): https://zakon.rada.gov.ua/laws/show/435-15
- Unicode UTS #39 (confusables): https://unicode.org/reports/tr39/

The search results were not fetched in full. Check the forms and abbreviations against the sources before the lists are treated as complete.
