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

  it("test_acknowledged_list_is_sorted_and_without_overlap", async () => {
    let r = await start();
    for (const id of ["e1", "e2", "e3"]) r = masking.unmaskEntity(r, id);
    const list = masking.acknowledgedUnmasked(r);
    expect(list.length).toBeGreaterThan(3);
    // The server's rule: sorted by (clause order, start), each start at or after the last end.
    const order = (id: string) => Number(id.slice(1));
    for (let i = 1; i < list.length; i += 1) {
      const [a, b] = [list[i - 1], list[i]];
      if (a === undefined || b === undefined) throw new Error("hole");
      expect(order(b[0])).toBeGreaterThanOrEqual(order(a[0]));
      if (a[0] === b[0]) expect(b[1]).toBeGreaterThanOrEqual(a[2]);
    }
  });
});
