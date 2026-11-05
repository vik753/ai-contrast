/** S7-T3 AC2 — import is untrusted input; export round-trips. */
import { describe, expect, it } from "vitest";
import { attr, topic } from "../test/topics-fakes";
import { MAX_IMPORT_BYTES, exportTopics, importTopics } from "./transfer";
import type { TopicDefinition } from "./types";

const t = (over: Record<string, unknown> = {}) => topic(over) as unknown as TopicDefinition;
const file = (topics: unknown[], extra: Record<string, unknown> = {}) =>
  JSON.stringify({ version: 1, topics, ...extra });
const code = (text: string) => {
  const r = importTopics(text);
  return r.ok ? "ok" : r.code;
};

describe("importTopics / exportTopics", () => {
  it("test_export_import_round_trips", () => {
    const list = [
      t(),
      t({ origin: "suggested", topic_id: "suggested_1", description: "", attributes: [] }),
    ];
    expect(importTopics(exportTopics(list))).toEqual({ ok: true, topics: list });
  });

  it("test_max_is_256_kib", () => {
    expect(MAX_IMPORT_BYTES).toBe(262144);
  });

  it("test_over_256_kib_is_too_large_even_if_not_json", () => {
    expect(code("x".repeat(MAX_IMPORT_BYTES + 1))).toBe("too_large");
  });

  it("test_size_is_counted_in_utf8_bytes", () => {
    expect(code("я".repeat(MAX_IMPORT_BYTES / 2 + 1))).toBe("too_large");
  });

  it("test_not_json_is_invalid_json", () => {
    expect(code("{nope")).toBe("invalid_json");
  });

  it.each(["__proto__", "constructor", "prototype"])("test_forbidden_key_%s_anywhere", (k) => {
    const raw = `{"version":1,"topics":[{"origin":"custom","${k}":{"x":1}}]}`;
    expect(code(raw)).toBe("forbidden_key");
    const deep = `{"version":1,"topics":[],"a":{"b":[{"${k}":1}]}}`;
    expect(code(deep)).toBe("forbidden_key");
  });

  it("test_extra_key_at_top_level_or_topic_or_attribute_is_invalid_shape", () => {
    expect(code(file([t()], { extra: 1 }))).toBe("invalid_shape");
    expect(code(file([{ ...t(), extra: 1 }]))).toBe("invalid_shape");
    expect(code(file([t({ attributes: [attr({ extra: 1 })] })]))).toBe("invalid_shape");
  });

  it("test_wrong_types_and_enums_are_invalid_shape", () => {
    expect(code(file([t({ title: 5 })]))).toBe("invalid_shape");
    expect(code(file([t({ origin: "catalog" })]))).toBe("invalid_shape");
    expect(code(file([t({ attributes: [attr({ type: "blob" })] })]))).toBe("invalid_shape");
    expect(code(file([t({ attributes: [attr({ direction_source: "model" })] })]))).toBe(
      "invalid_shape",
    );
    expect(code(file("nope" as unknown as unknown[]))).toBe("invalid_shape");
    expect(code(JSON.stringify({ version: 2, topics: [] }))).toBe("invalid_shape");
    expect(code("[]")).toBe("invalid_shape");
  });

  it("test_missing_key_is_invalid_shape", () => {
    const { title: _title, ...rest } = topic();
    expect(code(file([rest]))).toBe("invalid_shape");
  });

  it("test_over_cap_lists_are_too_many", () => {
    const many = (n: number, f: (i: number) => unknown) =>
      Array.from({ length: n }, (_, i) => f(i));
    expect(code(file(many(11, (i) => t({ topic_id: `custom_${i}` }))))).toBe("too_many");
    expect(code(file([t({ attributes: many(13, (i) => attr({ id: `a${i}` })) })]))).toBe(
      "too_many",
    );
    expect(
      code(file([t({ attributes: [attr({ type: "enum", values: many(31, (i) => `v${i}`) })] })])),
    ).toBe("too_many");
    expect(code(file([t({ synonyms_en: many(41, (i) => `syn${i}`) })]))).toBe("too_many");
  });

  it("test_text_over_length_caps_is_too_many", () => {
    expect(code(file([t({ title: "n".repeat(81) })]))).toBe("too_many");
    expect(code(file([t({ description: "d".repeat(201) })]))).toBe("too_many");
  });

  it("test_import_never_throws_on_garbage", () => {
    for (const g of ["", "null", "0", '"s"', "{}", "\u0000", "[[[["]) {
      expect(() => importTopics(g)).not.toThrow();
      expect(importTopics(g).ok).toBe(false);
    }
  });
});
