/**
 * S3-T6b item 2, item 7 — `parseGoogleDocLink` (src/api/googleDoc.ts).
 * Threat: T7 (only a full Google Docs document link is accepted; only the ID is kept).
 *
 * Decision: leading and trailing whitespace (also a pasted newline) is trimmed;
 * whitespace or a line break inside the text is refused.
 *
 * These tests fail until `src/api/googleDoc.ts` exists.
 */
import { describe, expect, it } from "vitest";
import { parseGoogleDocLink } from "./googleDoc";

const ID = "1AbCdEfGhIjKlMnOpQrStUvWx_-9";
const BASE = "https://docs.google.com/document/d/";

function id(length: number, fill = "a"): string {
  return fill.repeat(length);
}

describe("valid links return the ID", () => {
  it.each([
    [`${BASE}${ID}`],
    [`${BASE}${ID}/`],
    [`${BASE}${ID}/edit`],
    [`${BASE}${ID}/view`],
    [`${BASE}${ID}/preview`],
    [`${BASE}${ID}/copy`],
    [`${BASE}${ID}/edit?usp=sharing`],
    [`${BASE}${ID}/edit#heading=h.abc123`],
    [`${BASE}${ID}/edit?tab=t.0&usp=sharing#heading=h.abc123`],
    [`${BASE}${ID}?usp=sharing`],
    [`${BASE}${ID}#bookmark=id.xyz`],
    [`${BASE}${ID}/`.replace("https://docs", "https://DOCS")],
  ])("test_parse_valid_link_%s_returns_id", (link) => {
    expect(parseGoogleDocLink(link)).toBe(ID);
  });

  it.each([[25], [26], [100]])("test_parse_id_of_%i_chars_is_accepted", (length) => {
    const value = id(length, "Z");
    expect(parseGoogleDocLink(`${BASE}${value}/edit`)).toBe(value);
  });

  it.each([["_"], ["-"], ["9"]])("test_parse_id_made_of_%s_is_accepted", (ch) => {
    const value = id(30, ch);
    expect(parseGoogleDocLink(`${BASE}${value}`)).toBe(value);
  });

  it("test_parse_link_with_surrounding_whitespace_is_trimmed", () => {
    expect(parseGoogleDocLink(`  \n${BASE}${ID}/edit \t\r\n`)).toBe(ID);
  });
});

describe("invalid links return null", () => {
  it.each([
    ["other host", `https://example.com/document/d/${ID}/edit`],
    ["lookalike suffix host", `https://docs.google.com.evil.com/document/d/${ID}/edit`],
    ["lookalike prefix host", `https://evil-docs.google.com/document/d/${ID}/edit`],
    ["subdomain host", `https://x.docs.google.com/document/d/${ID}/edit`],
    ["trailing dot host", `https://docs.google.com./document/d/${ID}/edit`],
    ["drive host", `https://drive.google.com/document/d/${ID}/edit`],
    ["host in the path", `https://evil.com/docs.google.com/document/d/${ID}/edit`],
    ["host in the query", `https://evil.com/document/d/${ID}/edit?x=docs.google.com`],
    ["http scheme", `http://docs.google.com/document/d/${ID}/edit`],
    ["javascript scheme", `javascript:alert(1)//docs.google.com/document/d/${ID}`],
    ["data scheme", `data:text/html,docs.google.com/document/d/${ID}`],
    ["no scheme", `docs.google.com/document/d/${ID}/edit`],
    ["scheme-relative", `//docs.google.com/document/d/${ID}/edit`],
    ["user name", `https://user@docs.google.com/document/d/${ID}/edit`],
    ["user and password", `https://user:pass@docs.google.com/document/d/${ID}/edit`],
    ["password only", `https://:pass@docs.google.com/document/d/${ID}/edit`],
    ["host spoof by user info", `https://docs.google.com@evil.com/document/d/${ID}/edit`],
    ["port 8443", `https://docs.google.com:8443/document/d/${ID}/edit`],
    ["port 80", `https://docs.google.com:80/document/d/${ID}/edit`],
    ["account form /u/0/", `${BASE.replace("/d/", "/u/0/d/")}${ID}/edit`],
    ["published form", `https://docs.google.com/document/d/e/2PACX-${id(40)}/pub`],
    ["published form with short id", `https://docs.google.com/document/d/e/${ID}/pub`],
    ["spreadsheet path", `https://docs.google.com/spreadsheets/d/${ID}/edit`],
    ["presentation path", `https://docs.google.com/presentation/d/${ID}/edit`],
    ["forms path", `https://docs.google.com/forms/d/${ID}/edit`],
    ["no document segment", `https://docs.google.com/d/${ID}/edit`],
    ["id 24 chars", `${BASE}${id(24)}/edit`],
    ["id 101 chars", `${BASE}${id(101)}/edit`],
    ["id with dot", `${BASE}${id(12)}.${id(12)}/edit`],
    ["id with plus", `${BASE}${id(12)}+${id(12)}/edit`],
    ["id percent-encoded", `${BASE}%41${id(29)}/edit`],
    ["id with space", `${BASE}${id(12)} ${id(12)}/edit`],
    ["unknown suffix", `${BASE}${ID}/export`],
    ["suffix export with format", `${BASE}${ID}/export?format=docx`],
    ["extra segment after edit", `${BASE}${ID}/edit/more`],
    ["suffix in upper case", `${BASE}${ID}/EDIT`],
    ["double slash before suffix", `${BASE}${ID}//edit`],
    ["missing id", BASE],
    ["missing id with suffix", `${BASE}/edit`],
    ["path traversal", `${BASE}${ID}/../../x`],
    ["empty string", ""],
    ["whitespace only", "   \n\t"],
    ["plain text", "my contract"],
    ["only the id", ID],
    ["internal space", `${BASE}${ID}/edit  extra`],
    ["internal newline", `${BASE}${ID}\n/edit`],
    ["two links", `${BASE}${ID}/edit ${BASE}${ID}/edit`],
  ])("test_parse_%s_returns_null", (_name, link) => {
    expect(parseGoogleDocLink(link)).toBeNull();
  });

  it("test_parse_very_long_input_returns_null_without_throwing", () => {
    expect(parseGoogleDocLink(`${BASE}${ID}/edit?${"a=b&".repeat(100_000)}`)).toBe(ID);
    expect(parseGoogleDocLink("x".repeat(1_000_000))).toBeNull();
  });
});
