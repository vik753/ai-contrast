/** S7-T3 review LOW 2 — model-provided attributes and synonyms obey the same caps as imports. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse } from "../test/provider-fakes";
import { attr, stubTopicsFetch, topic } from "../test/topics-fakes";
import { expandSynonyms, proposeAttributes } from "./api";

afterEach(() => vi.unstubAllGlobals());
const base = { provider: "anthropic", model: "m1", key: "k" } as const;

const propose = async (attributes: unknown[]) => {
  stubTopicsFetch(() => jsonResponse(200, { attributes, dropped: 0 }));
  return proposeAttributes({ ...base, topic: topic() });
};
const expand = async (over: Record<string, unknown>) => {
  stubTopicsFetch(() =>
    jsonResponse(200, { synonyms_en: [], synonyms_uk: [], synonyms_ru: [], dropped: 0, ...over }),
  );
  return expandSynonyms({ ...base, topic: topic() });
};
const UNKNOWN = { ok: false, code: "unknown" };

describe("reply caps", () => {
  it("test_valid_attribute_passes", async () => {
    expect((await propose([attr({ id: "limit_1" })])).ok).toBe(true);
  });
  it.each(["A b", "x".repeat(65), "", "a-b"])("test_attribute_id_%j_is_unknown", async (id) => {
    expect(await propose([attr({ id })])).toEqual(UNKNOWN);
  });
  it("test_long_label_unit_or_value_is_unknown", async () => {
    expect(await propose([attr({ label: "l".repeat(201) })])).toEqual(UNKNOWN);
    expect(await propose([attr({ units: ["u".repeat(33)] })])).toEqual(UNKNOWN);
    expect(await propose([attr({ values: ["v".repeat(61)] })])).toEqual(UNKNOWN);
    expect(await propose([attr({ label: "" })])).toEqual(UNKNOWN);
  });
  it("test_long_or_empty_synonym_is_unknown", async () => {
    expect(await expand({ synonyms_en: ["s".repeat(61)] })).toEqual(UNKNOWN);
    expect(await expand({ synonyms_uk: [""] })).toEqual(UNKNOWN);
    expect((await expand({ synonyms_ru: ["ok"] })).ok).toBe(true);
  });
});
