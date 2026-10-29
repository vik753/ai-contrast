# Held-out identifier corpus (S5b-T4, ADR 0015 point 7)

15 synthetic contract fragments (UK 5, RU 5, EN 5; two are mixed-language) for the detector eval.
Developers must not read this folder (TASKS S5b-T4); the eval report shows aggregate numbers per class and language only.
The format and the span conventions are the same as in `backend/tests/fixtures/pseudo/README.md`.
All people, companies, addresses and numbers are fictional. No value is copied from the main corpus.
Files were written and counted by hand (no code was run). The harness must run a one-time check: recompute every checksum below, and check that `text[start:end]` of every span is in `value_forms`.

## Added span decisions (the tech lead can overrule)

1. A spelled-out legal form plus quoted name (`Акционерное общество «…»`) is ORG `high`; the span covers the whole legal form.
2. `ИП` + name is ORG `normal` plus PERSON (same rule as ФОП).
3. A checksum-valid number alone in a block or without a keyword (`33108 52645`, `41920653`, `7723 9156 4063`) is a `normal` TAX_ID proposal. A checksum-valid number next to a unit (`грн`, `кг`, `копійок`, `EUR`, `g`, `pcs`, `cents`) is an amount: no entity.
4. English `No.` and `Case No.` behave like `№`: the span is the number only.
5. Toll-free (`0 800 …`, `8-800-…`) and national UK (`0161 …`) numbers are PHONE `high`.
6. Requisites headings are variants of the main corpus (`Адреса та реквізити сторін`, `Юридические адреса и реквизиты сторон`, `Signatures and company details`). If the heading list is closed, treat the variant as the generalization test.
7. A person in Latin, Cyrillic and Cyrillic initials is one entity (h05, h15).

## Generated checksum values

| Value | Kind | Algorithm |
| --- | --- | --- |
| 25871405 | ЄДРПОУ (<30M) | weights 1..7, sum 93, 93 mod 11 = 5 |
| 72941636 | ЄДРПОУ (>60M) | weights 1..7, sum 116, mod 11 = 6 |
| 19406259 | ЄДРПОУ (<30M) | weights 1..7, sum 108, mod 11 = 9 |
| 41920653 | ЄДРПОУ (30M–60M) | weights 7,1,2,3,4,5,6; sum 113, mod 11 = 3 |
| 3310852645 | РНОКПП | weights −1,5,7,9,4,6,10,5,7; sum 159; (159 mod 11) mod 10 = 5 |
| 2951374086 | РНОКПП | same weights; sum 237; (237 mod 11) mod 10 = 6 (amount only) |
| 2670419358 | РНОКПП | same weights; sum 239; (239 mod 11) mod 10 = 8 (amount only) |
| 7842105938 | ИНН-10 | weights 2,4,10,3,5,9,4,6,8; sum 195; (195 mod 11) mod 10 = 8 |
| 5026379142 | ИНН-10 | same weights; sum 200; (200 mod 11) mod 10 = 2 |
| 615829437179 | ИНН-12 | n11 weights 7,2,4,10,3,5,9,4,6,8: sum 293 → 7; n12 weights 3,7,2,4,10,3,5,9,4,6,8: sum 251 → 9 |
| 772391564063 | ИНН-12 | n11 sum 226 → 6; n12 sum 322 → 3 |
| 1157746123457 | ОГРН | (first 12 digits mod 11) mod 10 = 7 |
| 1025020012346 | ОГРН | (first 12 digits mod 11) mod 10 = 6 |
| 304770000012347 | ОГРНИП | (first 14 digits mod 13) mod 10 = 7 |
| 173-409-261 64 | СНИЛС | weights 9..1, sum 165 > 101, 165 mod 101 = 64 |
| UA473003460000260045678123900 | IBAN UA | MFO 300346, account 0000260045678123900; N = BBAN+`301000`; 98 − (N mod 97) = 98 − 51 = 47 |
| 5168 7550 1234 5670 | card (Luhn) | Luhn sum 50 |
| 4149 6290 0987 6541 | card (Luhn) | Luhn sum 80 |
| FR14 2004 1010 0505 0001 3M02 606, IT60 X054 2811 1010 0000 0123 456, GB29 NWBK 6016 1331 9268 19 | public IBAN examples | valid by design |

Without checksum (format only): passport 36 19 № 905247; КПП 784201001, 502601001; МФО 300346; BIC PSSTFRPPSCE, BCITITMM, NWBKGB2L; SWIFT CAIXESBB; р/с 40702810500001234567, 40702810200100098765; к/с 30101810700000000555; БИК 044030555, 044525777; VAT DE 284 719 036, GB987654321, NL823456791B01; EIN 47-3829164, 13-0098765, 83-1204567; UK sort code 20-45-61, account 31926819; VIN VF1HJD40765432109, Z94CB41ABGR123456, WF0XXXTTGXKY12345.
Check on the 8-digit UK account 31926819: it is not a valid ЄДРПОУ (weights 7,1,…: sum 116, mod 11 = 6, digit is 9).

## Files

| File | Covers |
| --- | --- |
| h01_uk_table_flattened | table as lines, split РНОКПП without keyword, standalone ЄДРПОУ, AT + quotes, initials, HEALTH |
| h02_uk_requisites_long | 14-line requisites section, bank in quotes, drop/keep mix |
| h03_uk_docs_vehicle_health | VIN, plate, certificate, passport, DOB, HEALTH, 4 DOC_NO, driver licence |
| h04_uk_contacts_amounts_ocr | email, URL, phones, address + person, handle; amounts that are valid codes; OCR noise |
| h05_uk_en_mixed | UK text with English party, Latin/Cyrillic person, GB IBAN, VAT, UK address |
| h06_ru_preamble_person_org | AO spelled out, ИП, case forms, initials, Сорока, hyphenated ООО |
| h07_ru_tax_accounts | ИНН 10/12, КПП, ОГРН, ОГРНИП, accounts, card, split ИНН-12, HEALTH |
| h08_ru_requisites_long | 13-line requisites section, ПАО, signature, drop/keep mix |
| h09_ru_docs_vehicle_health_contacts | VIN, plate, ПТС, passport, DOB, СНИЛС, HEALTH, 4 DOC_NO, 8-800, email, domain |
| h10_ru_amounts_ocr_signature | amounts that are valid codes; OCR noise; signature with spaces; address; obfuscated email; URL |
| h11_en_table_flattened | table as lines, Inc./GmbH, apostrophe and hyphen names, initials, addresses, Fisher |
| h12_en_accounts_tax | FR/IT IBAN, BIC, EIN, VAT, card, sort code, amounts that are valid codes |
| h13_en_contacts_docs_vehicle | notice block, phones, URLs, (at) email, No. numbers, passport, DOB, HEALTH, plate, VIN |
| h14_en_requisites_signatures | 14-line requisites section, signature with initials, drop/keep mix |
| h15_en_uk_mixed_ocr | EN text with Ukrainian party, EDRPOU, 3-script person, signatures, OCR noise, amounts |
