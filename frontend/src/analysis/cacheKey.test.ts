// @vitest-environment node
/** S9-T4 AC4 — one `CacheKey` type, the analysis key, the `contractTextHash` null case. */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { SELECTION } from "../test/tagging-fakes";
import { buildAnalysisKey, flagsHash, selectionSignature } from "./cacheKey";

const HEX64 = /^[0-9a-f]{64}$/;
const PARTS = {
  documentDigest: "a".repeat(64),
  contractTextHash: "c".repeat(64),
  selectionSignature: "d".repeat(64),
  analysisVersion: "av-1",
  domain: "kasko",
  side: "insured",
  model: "gpt-strong",
  language: "en",
  flagsHash: "e".repeat(64),
};
const keyOf = (over: Record<string, unknown> = {}) => buildAnalysisKey({ ...PARTS, ...over });

describe("buildAnalysisKey", () => {
  it("test_key_is_64_hex_and_stable", async () => {
    const k = await keyOf();
    expect(k).toMatch(HEX64);
    expect(await keyOf()).toBe(k);
  });

  it.each([
    ["documentDigest", "b".repeat(64)],
    ["contractTextHash", "9".repeat(64)],
    ["selectionSignature", "8".repeat(64)],
    ["analysisVersion", "av-2"],
    ["domain", "life"],
    ["side", "insurer"],
    ["model", "gpt-other"],
    ["language", "uk"],
    ["flagsHash", "7".repeat(64)],
  ])("test_key_changes_with_%s", async (field, v) => {
    expect(await keyOf({ [field]: v })).not.toBe(await keyOf());
  });

  it("test_null_contract_text_hash_gives_no_key", async () => {
    expect(await keyOf({ contractTextHash: null })).toBeNull();
  });

  it("test_parts_do_not_collide_across_field_boundaries", async () => {
    expect(await keyOf({ domain: "ab", side: "c" })).not.toBe(
      await keyOf({ domain: "a", side: "bc" }),
    );
  });
});

describe("selectionSignature", () => {
  it("test_same_content_same_signature_in_any_catalog_order", async () => {
    const rev = { ...SELECTION, catalog: [...SELECTION.catalog].reverse() };
    const s = await selectionSignature(SELECTION);
    expect(s).toMatch(HEX64);
    expect(await selectionSignature(rev)).toBe(s);
  });
  it("test_catalog_version_change_changes_the_signature", async () => {
    const first = SELECTION.catalog[0];
    const other = {
      ...SELECTION,
      catalog: [{ ...first, catalog_version: "v2" }, ...SELECTION.catalog.slice(1)],
    };
    expect(await selectionSignature(other as never)).not.toBe(await selectionSignature(SELECTION));
  });
  it("test_dropping_a_topic_changes_the_signature", async () => {
    const less = { ...SELECTION, catalog: SELECTION.catalog.slice(1) };
    expect(await selectionSignature(less)).not.toBe(await selectionSignature(SELECTION));
  });
});

describe("flagsHash", () => {
  it("test_order_and_duplicates_do_not_matter", async () => {
    const a = await flagsHash(["not_read_material", "hidden_text_removed"]);
    expect(a).toMatch(HEX64);
    expect(
      await flagsHash(["hidden_text_removed", "not_read_material", "hidden_text_removed"]),
    ).toBe(a);
  });
  it("test_no_flags_differs_from_one_flag", async () => {
    expect(await flagsHash([])).not.toBe(await flagsHash(["not_read_material"]));
  });
});

describe("one CacheKey type", () => {
  const src = join(__dirname, "..");
  const walk = (d: string): string[] =>
    readdirSync(d).flatMap((f) => {
      const p = join(d, f);
      return statSync(p).isDirectory() ? walk(p) : [p];
    });
  const files = walk(src).filter((f) => /\.tsx?$/.test(f) && !f.includes(".test."));

  it("test_cachekey_is_declared_in_exactly_one_source_file", () => {
    const decl = files.filter((f) => /\btype\s+CacheKey\s*=/.test(readFileSync(f, "utf8")));
    expect(decl).toEqual([join(src, "hash", "key.ts")]);
  });
  it("test_cache_store_port_uses_that_type", () => {
    const port = readFileSync(join(src, "storage", "cacheStore.ts"), "utf8");
    expect(port).not.toMatch(/\btype\s+CacheKey\s*=/);
    expect(port).toMatch(/CacheKey/);
  });
});
