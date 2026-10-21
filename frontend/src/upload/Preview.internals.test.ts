/** S3-T4 (developer tests): code-to-message mapping and warning grouping. */
import { describe, expect, it } from "vitest";
import { groupWarnings, reasonKey, warningKey } from "./Preview";

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
