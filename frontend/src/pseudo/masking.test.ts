/**
 * S5b-T3 AC 2, 3, 3a, 4 (logic part): placeholders, unmask rules, manual masking,
 * masked text, acknowledged spans. Pure functions, no DOM.
 *
 * ASSUMED API of `src/pseudo/masking.ts` (types: `Review` is an immutable value):
 *   startReview(segmentation, label): Review
 *   placeholderOf(review, entityId): string | null     // null when unmasked
 *   canUnmask(review, entityId): boolean
 *   unmaskEntity(review, entityId): Review             // all occurrences; same review if not allowed
 *   unmaskOccurrence(review, entityId, index): Review  // one occurrence (index in span order)
 *   equalOccurrences(review, span): Span[]             // all equal texts in the document (incl. span)
 *   maskSelection(review, span, cls): Review           // only this span
 *   maskAllEqual(review, span, cls): Review           // every equal text
 *   maskedClauses(review): { id: string; text: string }[]
 *   acknowledgedUnmasked(review): [string, number, number][]   // clause-relative, sorted
 *   applyUnmaskedIdentifiers(review, spans): Review    // pre-mask spans from the server
 *   mappingOf(review): ReadonlyMap<string, string>     // placeholder -> original
 * Clause text = the spans of the clause joined with "\n", heading included.
 */
import { describe, expect, it } from "vitest";
import {
  BLOCKS,
  ENTITIES,
  EXPECTED_MASKED,
  maskedSpan,
  must,
  occurrences,
  parsedFixture,
} from "../test/pseudo-fakes";
import * as masking from "./masking";

const texts = (r: unknown) => masking.maskedClauses(r as never).map((c) => c.text);
const start = async () => masking.startReview(await parsedFixture(), "A");
const at = (b: number, needle: string, n = 0) => must(occurrences(BLOCKS, b, needle)[n]);

describe("placeholders and masked text", () => {
  it("test_masked_text_equals_expected_for_fixture", async () => {
    expect(texts(await start())).toEqual(EXPECTED_MASKED);
  });

  it("test_masked_clauses_keep_clause_ids", async () => {
    const ids = masking.maskedClauses(await start()).map((c) => c.id);
    expect(ids).toEqual(["c1", "c2", "c3"]);
  });

  it("test_placeholders_numbered_in_first_occurrence_order_not_list_order", async () => {
    const r = await start();
    expect(masking.placeholderOf(r, "e3")).toBe("[A.ORG_1]"); // ACME first in text, listed last
    expect(masking.placeholderOf(r, "e2")).toBe("[A.ORG_2]");
    expect(masking.placeholderOf(r, "e5")).toBe("[A.TAX_ID_1]");
    expect(masking.placeholderOf(r, "e6")).toBe("[A.TAX_ID_2]");
  });

  it("test_placeholder_uses_contract_label", async () => {
    const r = masking.startReview(await parsedFixture(), "B");
    expect(masking.placeholderOf(r, "e1")).toBe("[B.PERSON_1]");
    expect(texts(r).join("")).not.toContain("[A.");
  });

  it("test_all_occurrences_of_one_entity_share_one_placeholder", async () => {
    expect(texts(await start())[0]?.match(/\[A\.PERSON_1\]/g)).toHaveLength(2);
  });

  it("test_masked_text_never_contains_original_values", async () => {
    const joined = texts(await start()).join("\n");
    for (const secret of ["ACME", "Smith", "Beta", "seller@", "1234567890", "9876543210"]) {
      expect(joined).not.toContain(secret);
    }
  });

  it("test_mapping_maps_each_placeholder_to_its_original", async () => {
    const m = masking.mappingOf(await start());
    expect(m.get("[A.ORG_1]")).toBe("ACME LLC");
    expect(m.get("[A.PERSON_1]")).toBe("John Smith");
    expect(m.get("[A.TAX_ID_2]")).toBe("9876543210");
    expect(m.size).toBe(6);
  });

  it("test_heading_is_part_of_masked_clause_text", async () => {
    const blocks = [{ text: "1. Parties ACME LLC", part: "body" as const, page: null }];
    const reply = {
      clauses: [
        {
          id: "c1",
          number: "1",
          level: 1,
          part_index: 0,
          section_kind: null,
          part: "body",
          pages: [],
          spans: [[0, 0, 19]],
          heading_span: [0, 3, 10],
        },
      ],
      blocks,
      removed: [],
      warnings: [],
      detector_version: "det-1",
      entities: [{ id: "e1", class: "ORG", precision: "normal", spans: [[0, 11, 19]] }],
      requisites: [],
      neutralized: [],
    };
    const seg = await parsedFixture({}, blocks, reply);
    expect(texts(masking.startReview(seg, "A"))).toEqual(["1. Parties [A.ORG_1]"]);
  });
});

describe("unmasking rules", () => {
  it("test_high_precision_entity_cannot_be_unmasked", async () => {
    const r = await start();
    expect(masking.canUnmask(r, "e4")).toBe(false);
    expect(texts(masking.unmaskEntity(r, "e4"))).toEqual(EXPECTED_MASKED);
  });

  it("test_checksum_code_with_context_cannot_be_unmasked", async () => {
    expect(masking.canUnmask(await start(), "e5")).toBe(false);
  });

  it("test_checksum_code_normal_without_context_cannot_be_unmasked", async () => {
    const r = await start();
    expect(masking.canUnmask(r, "e6")).toBe(false);
    expect(texts(masking.unmaskEntity(r, "e6"))).toEqual(EXPECTED_MASKED);
  });

  it("test_normal_entity_can_be_unmasked", async () => {
    expect(masking.canUnmask(await start(), "e1")).toBe(true);
  });

  it("test_unmask_entity_restores_every_occurrence", async () => {
    const r = masking.unmaskEntity(await start(), "e1");
    expect(texts(r)[0]).toBe(
      "Seller [A.ORG_1] and John Smith agree. John Smith pays [A.ORG_1] within 30 days.",
    );
    expect(masking.placeholderOf(r, "e1")).toBeNull();
  });

  it("test_unmask_one_occurrence_leaves_the_others_masked", async () => {
    const r = masking.unmaskOccurrence(await start(), "e1", 1);
    expect(texts(r)[0]).toBe(
      "Seller [A.ORG_1] and [A.PERSON_1] agree. John Smith pays [A.ORG_1] within 30 days.",
    );
    expect(masking.placeholderOf(r, "e1")).toBe("[A.PERSON_1]");
  });

  it("test_unmask_one_occurrence_of_high_entity_is_refused", async () => {
    expect(texts(masking.unmaskOccurrence(await start(), "e4", 0))).toEqual(EXPECTED_MASKED);
  });

  it("test_numbering_has_no_gaps_after_unmasking", async () => {
    const r = masking.unmaskEntity(await start(), "e3"); // ACME out; Beta becomes ORG_1
    expect(masking.placeholderOf(r, "e2")).toBe("[A.ORG_1]");
    expect(texts(r)[2]).toBe("Ref code [A.TAX_ID_2] applies to [A.ORG_1].");
  });

  it("test_acknowledged_unmasked_lists_clause_relative_spans_of_unmasked_occurrences", async () => {
    const r = masking.unmaskOccurrence(await start(), "e1", 1);
    // Offsets are in the MASKED clause text (the server sees only that).
    const masked = texts(r)[0] ?? "";
    const [s, e] = maskedSpan(masked, "John Smith");
    expect(masking.acknowledgedUnmasked(r)).toEqual([["c1", s, e]]);
    // Earlier placeholders change the length: the original offset is a different number.
    expect(s).not.toBe(at(0, "John Smith", 1)[1]);
  });

  it("test_acknowledged_unmasked_after_unmask_entity_is_sorted_and_complete", async () => {
    const r = masking.unmaskEntity(await start(), "e3");
    const masked = texts(r)[0] ?? "";
    const a = maskedSpan(masked, "ACME LLC", 0);
    const b = maskedSpan(masked, "ACME LLC", 1);
    expect(masking.acknowledgedUnmasked(r)).toEqual([
      ["c1", a[0], a[1]],
      ["c1", b[0], b[1]],
    ]);
    expect(b[0]).not.toBe(at(0, "ACME LLC", 1)[1]);
  });

  it("test_acknowledged_unmasked_is_empty_when_nothing_unmasked", async () => {
    expect(masking.acknowledgedUnmasked(await start())).toEqual([]);
  });
});

describe("manual masking", () => {
  it("test_equal_occurrences_lists_every_equal_text", async () => {
    const found = masking.equalOccurrences(await start(), at(0, "John Smith", 0));
    expect(found).toEqual(occurrences(BLOCKS, 0, "John Smith"));
  });

  it("test_equal_occurrences_across_clauses_includes_all", async () => {
    // "applies" occurs once; "code" occurs in block 1 ("tax code") and block 2 ("Ref code").
    const code1 = at(1, "code");
    const found = masking.equalOccurrences(await start(), code1);
    expect(found).toHaveLength(2);
    expect(found).toContainEqual(code1);
    expect(found).toContainEqual(at(2, "code"));
  });

  it("test_mask_selection_masks_only_the_selected_span_with_class", async () => {
    const r = masking.maskSelection(await start(), at(1, "code"), "ADDRESS");
    expect(texts(r)[1]).toBe("Contact: [A.EMAIL_1], tax [A.ADDRESS_1] [A.TAX_ID_1].");
    expect(texts(r)[2]).toContain("Ref code");
  });

  it("test_mask_all_equal_masks_every_occurrence_under_one_placeholder", async () => {
    const r = masking.maskAllEqual(await start(), at(1, "code"), "ADDRESS");
    expect(texts(r)[1]).toBe("Contact: [A.EMAIL_1], tax [A.ADDRESS_1] [A.TAX_ID_1].");
    expect(texts(r)[2]).toBe("Ref [A.ADDRESS_1] [A.TAX_ID_2] applies to [A.ORG_2].");
  });

  it("test_manual_entity_is_numbered_by_position_with_detected_ones", async () => {
    // A manual ORG before ACME in the text takes ORG_1; ACME becomes ORG_2, Beta ORG_3.
    const r = masking.maskSelection(await start(), at(0, "Seller"), "ORG");
    expect(texts(r)[0]).toBe(
      "[A.ORG_1] [A.ORG_2] and [A.PERSON_1] agree. [A.PERSON_1] pays [A.ORG_2] within 30 days.",
    );
    expect(texts(r)[2]).toContain("[A.ORG_3]");
  });

  it("test_manual_mask_original_is_kept_in_mapping_only", async () => {
    const r = masking.maskSelection(await start(), at(0, "agree"), "HEALTH");
    expect(masking.mappingOf(r).get("[A.HEALTH_1]")).toBe("agree");
    expect(texts(r).join("")).not.toContain("agree");
  });

  it("test_manual_mask_unknown_class_is_refused", async () => {
    const r = await start();
    expect(texts(masking.maskSelection(r, at(0, "agree"), "SECRET"))).toEqual(EXPECTED_MASKED);
  });

  it("test_manual_mask_over_a_placeholder_or_partial_entity_is_refused_or_merged_safely", async () => {
    // Selecting only "ACME" (part of the entity "ACME LLC") must not leave "LLC" next to a split
    // mask that exposes the name: the result never contains "ACME".
    const [b, s] = at(0, "ACME LLC");
    const r = masking.maskSelection(await start(), [b, s, s + 4], "ORG");
    expect(texts(r).join("")).not.toContain("ACME");
  });
});

describe("server answers fed back", () => {
  it("test_apply_unmasked_identifiers_remasks_an_unmasked_occurrence", async () => {
    const unmasked = masking.unmaskEntity(await start(), "e3");
    // The server span is in masked text; the client maps it back to the original position.
    const [s, e] = maskedSpan(texts(unmasked)[0] ?? "", "ACME LLC", 1);
    expect(s).not.toBe(at(0, "ACME LLC", 1)[1]);
    const r = masking.applyUnmaskedIdentifiers(unmasked, [["c1", s, e]]);
    expect(texts(r)[0]).toContain("pays [A.ORG");
    expect(texts(r)[0]).not.toContain("ACME LLC within");
  });

  it("test_apply_unmasked_identifiers_masks_unknown_text_with_a_valid_placeholder", async () => {
    const [s, e] = maskedSpan(EXPECTED_MASKED[0] ?? "", "30 days");
    expect(s).not.toBe(at(0, "30 days")[1]);
    const r = masking.applyUnmaskedIdentifiers(await start(), [["c1", s, e]]);
    const line = texts(r)[0] ?? "";
    expect(line).not.toContain("30 days");
    expect(line).toMatch(/within \[A\.[A-Z_]+_[1-9]\d*\]\./);
  });

  it("test_apply_unmasked_identifiers_ignores_unknown_clause", async () => {
    const r = masking.applyUnmaskedIdentifiers(await start(), [["c99", 0, 3]]);
    expect(texts(r)).toEqual(EXPECTED_MASKED);
  });

  it("test_entity_list_fixture_is_the_one_we_expect", () => {
    expect(ENTITIES).toHaveLength(6);
  });
});
