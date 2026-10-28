// @vitest-environment node
/**
 * S4-T1 AC3 — `canonicalJson` and `buildKey` (src/hash/key.ts).
 * Fails until the module exists.
 */
import { describe, expect, it } from "vitest";
import { buildKey, canonicalJson } from "./key";
import { sha256Hex } from "./sha256";

describe("canonicalJson", () => {
  it("test_canonicalJson_object_keys_are_sorted_without_spaces", () => {
    expect(canonicalJson({ b: 1, a: 2 })).toBe('{"a":2,"b":1}');
  });

  it("test_canonicalJson_nested_keys_are_sorted_at_every_level", () => {
    expect(canonicalJson({ z: { y: 1, x: [{ d: 1, c: 2 }] }, a: null })).toBe(
      '{"a":null,"z":{"x":[{"c":2,"d":1}],"y":1}}',
    );
  });

  it("test_canonicalJson_arrays_keep_their_order", () => {
    expect(canonicalJson([3, 1, 2])).toBe("[3,1,2]");
  });

  it("test_canonicalJson_scalars_use_json_form", () => {
    expect(canonicalJson('a"b')).toBe('"a\\"b"');
    expect(canonicalJson(1.5)).toBe("1.5");
    expect(canonicalJson(true)).toBe("true");
    expect(canonicalJson(false)).toBe("false");
    expect(canonicalJson(null)).toBe("null");
  });

  it("test_canonicalJson_same_object_in_other_key_order_gives_same_text", () => {
    expect(canonicalJson({ a: 1, b: { c: 1, d: 2 } })).toBe(
      canonicalJson({ b: { d: 2, c: 1 }, a: 1 }),
    );
  });

  it.each([
    ["undefined", undefined],
    ["NaN", Number.NaN],
    ["Infinity", Number.POSITIVE_INFINITY],
    ["function", () => 1],
    ["Date", new Date(0)],
    ["symbol", Symbol("x")],
    ["bigint", 1n],
    ["Map", new Map()],
    [
      "class instance",
      new (class Foo {
        x = 1;
      })(),
    ],
    ["undefined property", { a: undefined }],
    ["nested NaN", { a: [1, { b: Number.NaN }] }],
    ["nested Date", { a: [new Date(0)] }],
  ])("test_canonicalJson_%s_throws", (_name, value) => {
    expect(() => canonicalJson(value)).toThrow();
  });
});

describe("buildKey", () => {
  it("test_buildKey_equals_sha256_of_canonical_json_with_version_1", async () => {
    const parts = { side: "A", topics: ["x", "y"] };
    expect(await buildKey(parts)).toBe(await sha256Hex(canonicalJson({ v: 1, ...parts })));
  });

  it("test_buildKey_result_is_64_lower_case_hex", async () => {
    expect(await buildKey({ a: "x" })).toMatch(/^[0-9a-f]{64}$/);
  });

  it("test_buildKey_part_order_does_not_change_the_key", async () => {
    expect(await buildKey({ a: "x", b: "y" })).toBe(await buildKey({ b: "y", a: "x" }));
  });

  it("test_buildKey_array_order_changes_the_key", async () => {
    expect(await buildKey({ docs: ["h1", "h2"] })).not.toBe(await buildKey({ docs: ["h2", "h1"] }));
  });

  it("test_buildKey_other_value_changes_the_key", async () => {
    expect(await buildKey({ a: "x" })).not.toBe(await buildKey({ a: "y" }));
  });

  it("test_buildKey_unsupported_part_rejects", async () => {
    await expect(buildKey({ a: undefined } as never)).rejects.toThrow();
    await expect(buildKey({ a: Number.NaN })).rejects.toThrow();
    await expect(buildKey({ a: new Date(0) } as never)).rejects.toThrow();
  });
});
