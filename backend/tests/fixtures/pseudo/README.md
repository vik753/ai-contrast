# Pseudonymization identifier corpus (S5b-T0)

Synthetic contract fragments in UK, RU and EN for the detector (`/api/segment`, ADR 0008 and ADR 0015).
All people, companies and numbers are fictional. Checksummed values are valid by checksum but belong to nobody.
Files were written and checked by hand (no code was run): the test-engineer should add a one-time test that recomputes every checksum and every span (`text[start:end]` must be one of `value_forms`).

## File format

```
{"name", "language", "description",
 "blocks": [{"text", "part", "page"}],
 "expected": {
   "entities":   [{"class", "precision": "high"|"normal", "value_forms": [...], "spans": [[block, start, end]]}],
   "requisites": [{"block", "line_text_starts_with", "action": "drop"|"keep"}],
   "neutralized": [[block, start, end]],
   "warnings": [codes],
   "must_not_mask": [str]}}
```

- Offsets are Python code-point offsets into the block text after ADR 0009 Layer 1 cleaning. End is exclusive. Fixtures contain no invisible characters, except the two VARIANTS files (34, 35), which use `\u` escapes and say in `description` which text the spans refer to.
- `value_forms` lists the distinct surface strings of an entity; `text[start:end]` of every span must be in this list.
- `must_not_mask`: case-sensitive strings. No occurrence of the string in the cleaned blocks may overlap any entity span (any class).
- `requisites`: one record per line of the requisites section (one line = one block). The heading itself has no record. The `drop` rule: every token is an identifier, a closed-list label, a role word or part of a signature line. A line with an obligation marker or other words is `keep` (examples: `Неустойка 50 %`, `Іваненко І.І. відмовляється від претензій`).
- Warnings are file-level codes: `requisites_condition`, `placeholder_lookalike`, `masked_next_to_amount`.
- Entity order in a file follows the first span; the test must compare as sets.

## Span decisions made in this corpus (the tech lead can overrule)

1. Legal form plus quoted name: the span covers the legal form and both guillemets (`ТОВ «Альфа Захист»`). Legal form with a quoted name = `high`; legal-form suffix without quotes (`Northwind Logistics Ltd.`, `ФОП …`) = `normal`.
2. Quoted name without a legal form (`КАСКО «Оптимум»`, `«Швидкий Кур'єр»`, `(далі — «Іваненко»)`): span = text inside the guillemets only. `normal`.
3. ФОП: one ORG entity (`ФОП` + name) and one PERSON entity (name only); spans overlap.
4. Signature line: SIGNATURE span = underscores through the closing slash; the name inside is also a PERSON entity (overlap). A КЕП certificate serial is SIGNATURE (span = serial).
5. Address after a keyword ends before the final full stop of the sentence. Cadastral number = ADDRESS.
6. DOC_NO: span = the number after `№` only; the document word and the issue date stay.
7. Passport: span = series and number without the label `серія`. HEALTH: span = the diagnosis phrase after `діагноз`.
8. Titles (Mr., Ms., пані) are not used in the corpus.
9. `precision: high` only for checksum codes with context (ЄДРПОУ, РНОКПП, ИНН, ОГРН, ОГРНИП, СНИЛС, ОКПО), IBAN, card, email, phone, URL/bare domain, legal form plus quoted name. КПП, МФО, BIC/SWIFT, VAT, R/S accounts, УНЗР, VIN, plates, handles are `normal`.
10. A checksum-valid number without context (file 15) is a `normal` TAX_ID proposal. A number with a bad check digit and no context gives nothing.
11. Line-end hyphen split (file 34, block 3): the span includes the hyphen and the newline.

## Generated checksum values

| Value | Kind | Algorithm |
| --- | --- | --- |
| 21045679 | ЄДРПОУ | weights 1..7, sum 130, 130 mod 11 = 9 |
| 13579243 | ЄДРПОУ | weights 1..7, sum 135, mod 11 = 3 (amount in file 13 only) |
| 12345678 | ЄДРПОУ | weights 1..7, sum 140, mod 11 = 8 (amount in files 13, 14) |
| 38126404 | ЄДРПОУ (30M–60M) | weights 7,1,2,3,4,5,6; sum 81, mod 11 = 4 |
| 64001830 | ЄДРПОУ (>60M) | weights 1..7, sum 88, mod 11 = 0 |
| 10000062 | ЄДРПОУ, second round | first sum 43, mod 11 = 10; weights 3..9: sum 57, mod 11 = 2 |
| 3012345670 | РНОКПП | weights −1,5,7,9,4,6,10,5,7; sum 187; (187 mod 11) mod 10 = 0 |
| 3521741827 | РНОКПП | same weights; sum 161; (161 mod 11) mod 10 = 7 |
| 7712345671 | ИНН-10 | weights 2,4,10,3,5,9,4,6,8; sum 221; (221 mod 11) mod 10 = 1 |
| 504712345623 | ИНН-12 | n11 weights 7,2,4,10,3,5,9,4,6,8: sum 255 → 2; n12 weights 3,7,2,4,10,3,5,9,4,6,8: sum 190 → 3 |
| 1027700123450 | ОГРН | (first 12 digits mod 11) mod 10 = 0 |
| 316774600012348 | ОГРНИП | (first 14 digits mod 13) mod 10 = 8 |
| 112-233-445 95 | СНИЛС | weights 9..1, sum 95 (< 100) → 95 |
| UA863204782600123456789012345 | IBAN UA | MFO 320478, account 2600123456789012345; N = BBAN+`UA00` as digits `301000`; 98 − (N mod 97) = 98 − 12 = 86 |
| UA423052990000262001987654321 | IBAN UA | MFO 305299, account 0000262001987654321; 98 − 56 = 42 |
| 4276 3800 1234 5679 | card (Luhn) | Luhn sum 70 |
| GB82 WEST 1234 5698 7654 32, DE89 3704 0044 0532 0130 00, 4111 1111 1111 1111 | public documentation examples | valid by design |

Without checksum (format only): КПП 771201001, МФО 320478, BIC EXMPUA2XXXX and WESTGB2L, VAT DE123456789, Tax ID 98-7654321, р/с 40702810900000012345, БИК 044500123, УНЗР 19850314-12345, VIN WVWZZZ3CZ9E123456 and XTA210930Y2765432, cadastral 5110100000:01:001:0123.
Invalid on purpose: 21045678 (check digit should be 9).

## Files

| File | Covers |
| --- | --- |
| 01_uk_preamble_org_person | UK preamble, ТОВ + quoted name, "в особі", defined terms, case forms, city kept |
| 02_ru_preamble_org_person | RU preamble, ООО, "в лице", female representative |
| 03_en_preamble_org_person | EN preamble, "represented by", surname Rose vs verb "rose" |
| 04_uk_person_forms | initials both orders, dative, female double surname, vocative |
| 05_uk_common_word_surnames | Коваль, Мельник vs common nouns |
| 06_en_translit_person | Latin transliteration grouped with Cyrillic |
| 07_ru_person_forms | RU non-declining -ко, female forms, double surname |
| 08_uk_fop | ФОП as ORG and PERSON, РНОКПП |
| 09_uk_tax_ids_context | ЄДРПОУ (all weight ranges), РНОКПП with context |
| 10_ru_tax_ids | ИНН 10/12, КПП, ОГРН, ОКПО, ОГРНИП, СНИЛС |
| 11_uk_iban_card | IBAN with/without spaces, card, МФО, SWIFT |
| 12_en_iban_vat_card | foreign IBAN, BIC, VAT, card |
| 13_uk_amounts_checksum_neg | checksum-valid amounts, units, % (negative) |
| 14_ru_amounts_checksum_neg | same in RU (negative) |
| 15_uk_checksum_no_context | normal proposals without context |
| 16_uk_contacts | email, obfuscated email, phones, URL, bare domain, handle |
| 17_ru_contacts | RU phone, email, domain |
| 18_en_contacts | EN phone, obfuscated email, URL |
| 19_uk_address_cadastral | address, cadastral number, city-level territory kept |
| 20_ru_address | RU addresses |
| 21_uk_personal_doc_health | passport, DOB, ID card, driver licence, УНЗР, HEALTH |
| 22_uk_doc_numbers | contract, policy, довіреність, licence, case number |
| 23_ru_doc_numbers | RU document numbers |
| 24_uk_vehicle | VIN, plate, registration certificate |
| 25_ru_vehicle | VIN, RU plate, ПТС |
| 26_uk_signature_lines | signature lines, КЕП serial |
| 27_uk_requisites_section | requisites drop/keep decisions, UK |
| 28_ru_requisites_section | requisites drop/keep decisions, RU |
| 29_en_requisites_section | requisites drop/keep decisions, EN |
| 30_uk_locations | header, heading, body, footnote, text box, footer |
| 31_uk_quoted_names | quoted product and party names |
| 32_uk_defined_term_name | defined term equal to a masked name |
| 33_uk_placeholder_lookalikes | neutralized look-alikes (ASCII and skeleton) |
| 34_uk_variants_invisible_hyphen | zero-width, soft hyphen, line-end hyphen (VARIANTS) |
| 35_uk_variants_homoglyph | Latin homoglyphs in name, IBAN, ORG (VARIANTS) |
| 36_uk_masked_next_to_amount | warning masked_next_to_amount |
| 37_uk_negative_controls | roles, city, dates, amounts (UK) |
| 38_en_negative_controls | same (EN) |
| 39_ru_negative_controls | same (RU) |

## Round 3 (detector training corpus, files 40-68)

Written from failure categories only. Spans were counted by hand: the test-engineer's one-time check must recompute every span. Span conventions as above. New decisions: a bare domain with a path is one URL span (domain and path); a VAT span is the country prefix and digits without the word `VAT`; a driver licence and a passport span exclude the label; a passport span runs from the first series digit through the number; an address span includes a unit prefix and a trailing country.

### Round 3 checksum values

| Value | Kind | Algorithm |
| --- | --- | --- |
| 780123456724 | ИНН-12 (files 46, 64) | n11 weights 7,2,4,10,3,5,9,4,6,8 on 7,8,0,1,2,3,4,5,6,7: sum 244, 244 mod 11 = 2; n12 weights 3,7,2,4,10,3,5,9,4,6,8 on 7,8,0,1,2,3,4,5,6,7,2: sum 257, 257 mod 11 = 4 |
| 502987654365 | ИНН-12 (file 46) | n11: digits 5,0,2,9,8,7,6,5,4,3: sum 314, mod 11 = 6; n12 on 5,0,2,9,8,7,6,5,4,3,6: sum 313, mod 11 = 5 |
| 780123456725 | ИНН-12, invalid on purpose (file 46) | n12 should be 4 |
| 7712345671, 3012345670, 3521741827 | valid 10-digit numbers reused as quantities (files 59-61, 60) | see Generated checksum values above |
| 21045679 | ЄДРПОУ (file 63) | see above |

Without checksum (format only): accounts 40702810900000045678 and 30101810400000000123, UK sort codes and 8-digit accounts, VAT numbers `DE 812 3456 78`, `PL 526 1234 56`, `GB 123 4567 89`, Tax ID `55-1234567`, plates, driver licence and passport numbers. UK phones are from Ofcom drama ranges; toll-free numbers are fictional.

| File | Covers |
| --- | --- |
| 40_uk_phone_tollfree | `0 800 …` in spaced groups after a label |
| 41_ru_phone_tollfree | `8-800-…` after an imperative verb |
| 42_en_phone_uk_national | UK `0XXX XXX XXXX` after lower-case "phone" |
| 43_en_url_domain_path | bare domain plus path |
| 44_ru_org_full_legal_form | spelled-out legal form plus quoted name |
| 45_uk_vat_foreign | VAT with country prefix and inner spaces |
| 46_ru_inn12_grouped | ИНН-12 in 4-digit groups, alone in a block; invalid twin (negative) |
| 47_ru_accounts_spelled | 20-digit account after spelled-out labels |
| 48_en_sortcode_account | sort code and 8-digit account |
| 49_uk_driver_licence | 3 letters + 6 digits after "посвідчення водія" |
| 50_ru_passport_series_number | `серия NN NN № NNNNNN` |
| 51_ru_plate_spaced | plate with spaces |
| 52_en_person_title_lines | name, job title on its own line |
| 53_en_person_notice_leadin | name after notice lead-ins, common-noun surnames |
| 54_en_person_authorised_signatory | full name after "Authorised signatory:" |
| 55_en_person_sentence_subject | name as line-start subject, capitalised-word negatives |
| 56_en_person_cyrillic_parens | Latin name plus Cyrillic form in brackets |
| 57_en_address_country_unit | trailing country, "Warehouse N," prefix |
| 58_en_address_translit_unit | "Unit N," prefix, transliterated foreign address |
| 59-61 `_quantities_units_neg` | checksum-valid 10-digit quantities with piece/mass units (RU, UK, EN) |
| 62_en_requisites_heading_variant | invented heading, `E-mail:`, two pairs on a line, second role + name |
| 63_uk_requisites_bank_email_roles | `Банк: «…»`, `E-mail:`, two pairs, two-word and second role |
| 64_ru_requisites_two_pairs_roles | same in RU, spelled-out legal form, spelled-out account |
| 65_en_requisites_second_variant | second heading, two account pairs, VAT, name as subject in section |
| 66-68 `_negative_controls_r3` | near-miss negatives (EN, UK, RU) |
