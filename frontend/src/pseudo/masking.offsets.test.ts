/** S5b-T3 (own tests): server spans are offsets in the masked clause text. */
import { describe, expect, it } from "vitest";
import { EXPECTED_MASKED, parsedFixture } from "../test/pseudo-fakes";
import * as masking from "./masking";

const start = async () => masking.startReview(await parsedFixture(), "A");

describe("masked-text offsets", () => {
  it("test_span_inside_a_placeholder_is_unmapped_and_changes_nothing", async () => {
    const r = await start();
    const at = (EXPECTED_MASKED[0] ?? "").indexOf("[A.ORG_1]");
    const spans: [string, number, number][] = [["c1", at + 1, at + 4]];
    expect(masking.unmappedSpans(r, spans)).toEqual(spans);
    expect(masking.maskedClauses(masking.applyUnmaskedIdentifiers(r, spans))).toEqual(
      masking.maskedClauses(r),
    );
  });

  it("test_unknown_clause_is_unmapped", async () => {
    const r = await start();
    expect(masking.unmappedSpans(r, [["c9", 0, 2]])).toHaveLength(1);
  });

  it("test_span_in_plain_text_is_mapped", async () => {
    const r = await start();
    const at = (EXPECTED_MASKED[0] ?? "").indexOf("30 days");
    expect(masking.unmappedSpans(r, [["c1", at, at + 7]])).toEqual([]);
  });
});
