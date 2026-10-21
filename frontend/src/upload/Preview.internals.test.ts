/** S3-T4 (developer tests): code-to-message mapping and warning grouping. */
import { describe, expect, it } from "vitest";
import {
  PREVIEW_BLOCK_LIMIT,
  PREVIEW_CHAR_LIMIT,
  defaultView,
  groupWarnings,
  reasonKey,
  warningKey,
} from "./Preview";

describe("warning and reason keys", () => {
  it.each(["__proto__", "toString", "constructor", "future_code"])(
    "test_unknown_or_inherited_code_%s_is_generic",
    (code) => {
      expect(warningKey(code)).toBe("upload.preview.warning.unknown");
      expect(reasonKey(code)).toBe("upload.preview.removed.reason.other");
    },
  );

  it("test_known_codes_map_to_their_keys", () => {
    expect(warningKey("pdf_edited")).toBe("upload.preview.warning.pdf_edited");
    expect(reasonKey("same_color")).toBe("upload.preview.removed.reason.same_color");
  });
});

describe("groupWarnings", () => {
  it("test_same_message_is_grouped_with_sorted_unique_pages", () => {
    expect(
      groupWarnings([
        { code: "borderline_text", page: 3 },
        { code: "future_a", page: null },
        { code: "borderline_text", page: 1 },
        { code: "borderline_text", page: 3 },
        { code: "future_b", page: 2 },
      ]),
    ).toEqual([
      { key: "upload.preview.warning.borderline_text", pages: [1, 3] },
      { key: "upload.preview.warning.unknown", pages: [2] },
    ]);
  });

  it("test_no_warnings_give_no_groups", () => {
    expect(groupWarnings([])).toEqual([]);
  });
});

describe("defaultView", () => {
  const block = (text: string) => ({ text, part: "body" as const, page: null });

  it("test_one_1000000_character_block_is_cut_to_50000_and_marked", () => {
    const view = defaultView([block("a".repeat(1_000_000))]);
    expect(view.shown).toHaveLength(1);
    expect(view.shown[0]?.text.length).toBe(PREVIEW_CHAR_LIMIT);
    expect(view.shown[0]?.shortened).toBe(true);
    expect(view.complete).toBe(false);
  });

  it("test_character_cap_comes_before_block_cap", () => {
    const view = defaultView(Array.from({ length: 10 }, () => block("a".repeat(20_000))));
    expect(view.shown.map((item) => item.text.length)).toEqual([20_000, 20_000, 10_000]);
    expect(view.shown.at(-1)?.shortened).toBe(true);
  });

  it("test_block_cap_comes_before_character_cap", () => {
    const view = defaultView(Array.from({ length: 201 }, () => block("a")));
    expect(view.shown).toHaveLength(PREVIEW_BLOCK_LIMIT);
    expect(view.shown.every((item) => !item.shortened)).toBe(true);
    expect(view.complete).toBe(false);
  });

  it("test_exact_character_cap_is_complete_without_marker", () => {
    const view = defaultView([block("a".repeat(PREVIEW_CHAR_LIMIT))]);
    expect(view.complete).toBe(true);
    expect(view.shown[0]?.shortened).toBe(false);
  });

  it("test_cut_never_splits_a_surrogate_pair", () => {
    const view = defaultView([block("a" + "😀".repeat(10))], 200, 4);
    expect(view.shown[0]?.text).toBe("a😀");
  });

  it("test_block_after_full_budget_is_not_shown", () => {
    const view = defaultView([block("abcd"), block("e")], 200, 4);
    expect(view.shown.map((item) => item.text)).toEqual(["abcd"]);
    expect(view.complete).toBe(false);
  });
});
