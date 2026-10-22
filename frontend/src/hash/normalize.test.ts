// @vitest-environment node
/**
 * S4-T1 AC2 — `normalizeForHash` (src/hash/normalize.ts), ADR 0013 point 8.
 * Fails until the module exists.
 */
import { describe, expect, it } from "vitest";
import { normalizeForHash } from "./normalize";
import { sha256Hex } from "./sha256";

const TABLE: readonly (readonly [string, string, string])[] = [
  ["crlf", "a\r\nb", "a\nb"],
  ["lone cr", "a\rb", "a\nb"],
  ["mixed breaks", "a\r\n\r\nb\rc", "a\n\nb\nc"],
  ["tab", "a\tb", "a b"],
  ["tabs", "a\t\tb", "a b"],
  ["run of spaces", "a     b", "a b"],
  ["spaces and tabs", "a \t  b", "a b"],
  ["trailing spaces on a line", "a   \nb", "a\nb"],
  ["trailing tab on a line", "a\t\nb", "a\nb"],
  ["three breaks", "a\n\n\nb", "a\n\nb"],
  ["many breaks", "a\n\n\n\n\n\nb", "a\n\nb"],
  ["two breaks stay", "a\n\nb", "a\n\nb"],
  ["one break stays", "a\nb", "a\nb"],
  ["blank lines with spaces", "a\n  \n \nb", "a\n\nb"],
  ["leading and trailing spaces", "   a   ", "a"],
  ["leading and trailing breaks", "\n\n a \n\n", "a"],
  ["only white space", " \t\r\n \n", ""],
  ["empty", "", ""],
  ["case is kept", "Aa", "Aa"],
  ["nfd to nfc", "é", "é"],
  ["cyrillic nfd to nfc", "й", "й"],
];

describe("normalizeForHash table", () => {
  it.each(TABLE)("test_normalizeForHash_%s_gives_expected", (_name, input, expected) => {
    expect(normalizeForHash(input)).toBe(expected);
  });

  it.each(TABLE)("test_normalizeForHash_%s_is_idempotent", (_name, input) => {
    const once = normalizeForHash(input);
    expect(normalizeForHash(once)).toBe(once);
  });
});

describe("normalizeForHash and hashes", () => {
  it("test_normalizeForHash_nfd_and_nfc_input_give_the_same_hash", async () => {
    const nfc = "Café й";
    const nfd = "Café й";
    expect(nfd).not.toBe(nfc);
    expect(await sha256Hex(normalizeForHash(nfd))).toBe(await sha256Hex(normalizeForHash(nfc)));
  });

  it("test_normalizeForHash_cyrillic_and_latin_lookalikes_give_different_hashes", async () => {
    const latin = "contract a";
    const cyrillic = "contract а"; // U+0430 CYRILLIC SMALL LETTER A
    expect(normalizeForHash(cyrillic)).not.toBe(normalizeForHash(latin));
    expect(await sha256Hex(normalizeForHash(cyrillic))).not.toBe(
      await sha256Hex(normalizeForHash(latin)),
    );
  });
});
