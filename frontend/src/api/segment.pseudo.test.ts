/**
 * S5b-T3 AC (ADR 0015 point 1): strict validation of the new `/api/segment` fields.
 * Every violation fails closed as `invalid_response`.
 * Must fail before the implementation exists (the client ignores or rejects the new fields).
 */
import { describe, expect, it } from "vitest";
import { segmentBlocks } from "./segment";
import { body, segmentReply } from "../test/segment-fakes";
import { jsonResponse } from "../test/upload-fakes";
import { BLOCKS, ENTITIES, fixtureReply, DETECTOR_VERSION } from "../test/pseudo-fakes";

async function call(reply: Record<string, unknown>, status = 200, blocks = BLOCKS) {
  return segmentBlocks(blocks, null, {
    fetchImpl: () => Promise.resolve(jsonResponse(status, reply)),
  });
}
const invalid = async (overrides: Record<string, unknown>, blocks = BLOCKS) => {
  const r = await call(fixtureReply(overrides), 200, blocks);
  expect(r).toEqual({ ok: false, code: "invalid_response" });
};
const ent = (patch: Record<string, unknown>) => [{ ...ENTITIES[0], ...patch }];

describe("new segment fields", () => {
  it("test_segment_reply_valid_with_entities_is_accepted", async () => {
    const r = await call(fixtureReply());
    expect(r.ok).toBe(true);
    if (r.ok) {
      const s = r.segmentation as unknown as {
        detectorVersion: string;
        entities: { id: string; cls: string; precision: string }[];
      };
      expect(s.detectorVersion).toBe(DETECTOR_VERSION);
      expect(s.entities.map((e) => e.id)).toEqual(ENTITIES.map((e) => e.id));
      expect(s.entities[3]?.cls).toBe("EMAIL");
    }
  });

  it.each(["detector_version", "entities", "requisites", "neutralized"])(
    "test_segment_reply_missing_%s_is_invalid_response",
    async (key) => {
      const reply = fixtureReply();
      Reflect.deleteProperty(reply, key);
      expect(await call(reply)).toEqual({ ok: false, code: "invalid_response" });
    },
  );

  it("test_segment_entity_unknown_class_is_invalid_response", () =>
    invalid({ entities: ent({ class: "SECRET" }) }));
  it("test_segment_entity_unknown_precision_is_invalid_response", () =>
    invalid({ entities: ent({ precision: "low" }) }));
  it("test_segment_entity_value_string_key_is_invalid_response", () =>
    invalid({ entities: ent({ value: "John Smith" }) }));
  it("test_segment_entity_without_spans_is_invalid_response", () =>
    invalid({ entities: ent({ spans: [] }) }));
  it("test_segment_entity_span_past_block_end_is_invalid_response", () =>
    invalid({ entities: ent({ spans: [[0, 5, 9999]] }) }));
  it("test_segment_entity_span_unknown_block_is_invalid_response", () =>
    invalid({ entities: ent({ spans: [[9, 0, 2]] }) }));
  it("test_segment_entity_span_start_after_end_is_invalid_response", () =>
    invalid({ entities: ent({ spans: [[0, 8, 3]] }) }));
  it("test_segment_entity_bad_id_is_invalid_response", () =>
    invalid({ entities: ent({ id: "x1" }) }));
  it("test_segment_detector_version_with_space_is_invalid_response", () =>
    invalid({ detector_version: "bad version!" }));
  it("test_segment_detector_version_too_long_is_invalid_response", () =>
    invalid({ detector_version: "a".repeat(65) }));
  it("test_segment_entities_not_a_list_is_invalid_response", () => invalid({ entities: {} }));

  it("test_segment_two_entities_overlapping_same_class_is_invalid_response", () =>
    invalid({
      entities: [
        { id: "e1", class: "EMAIL", precision: "high", spans: [[1, 9, 28]] },
        { id: "e2", class: "URL", precision: "high", spans: [[1, 20, 30]] },
      ],
    }));

  it("test_segment_spans_of_one_entity_overlapping_is_invalid_response", () =>
    invalid({
      entities: ent({
        spans: [
          [0, 7, 15],
          [0, 10, 18],
        ],
      }),
    }));

  it("test_segment_org_and_person_overlap_is_accepted", async () => {
    const r = await call(
      fixtureReply({
        entities: [
          { id: "e1", class: "ORG", precision: "normal", spans: [[0, 7, 15]] },
          { id: "e2", class: "PERSON", precision: "normal", spans: [[0, 7, 12]] },
        ],
      }),
    );
    expect(r.ok).toBe(true);
  });

  it("test_segment_signature_overlap_with_person_is_accepted", async () => {
    const r = await call(
      fixtureReply({
        entities: [
          { id: "e1", class: "SIGNATURE", precision: "high", spans: [[0, 0, 40]] },
          { id: "e2", class: "PERSON", precision: "normal", spans: [[0, 20, 30]] },
        ],
      }),
    );
    expect(r.ok).toBe(true);
  });

  it("test_segment_more_than_5000_entities_is_invalid_response", async () => {
    const blocks = [body("x ".repeat(5_100))];
    const entities = Array.from({ length: 5_001 }, (_, i) => ({
      id: `e${String(i + 1)}`,
      class: "ORG",
      precision: "normal",
      spans: [[0, i * 2, i * 2 + 1]],
    }));
    await invalid({ ...segmentReply(blocks), entities }, blocks);
  });

  it("test_segment_5000_entities_exactly_is_accepted", async () => {
    const blocks = [body("x ".repeat(5_100))];
    const entities = Array.from({ length: 5_000 }, (_, i) => ({
      id: `e${String(i + 1)}`,
      class: "ORG",
      precision: "normal",
      spans: [[0, i * 2, i * 2 + 1]],
    }));
    const r = await call({ ...fixtureReply(), ...segmentReply(blocks), entities }, 200, blocks);
    expect(r.ok).toBe(true);
  });

  it("test_segment_more_than_50000_spans_is_invalid_response", async () => {
    const blocks = [body("x ".repeat(55_000))];
    // 11 entities with 4,546 distinct single-character spans each = 50,006 spans.
    const entities = Array.from({ length: 11 }, (_, e) => ({
      id: `e${String(e + 1)}`,
      class: "ORG",
      precision: "normal",
      spans: Array.from({ length: 4_546 }, (_, i) => [
        0,
        (e * 4_546 + i) * 2,
        (e * 4_546 + i) * 2 + 1,
      ]),
    }));
    await invalid({ ...segmentReply(blocks), entities }, blocks);
  });

  it("test_segment_requisites_unknown_clause_is_invalid_response", () =>
    invalid({ requisites: [{ clause: "c99", lines: [{ span: [0, 0, 5], action: "drop" }] }] }));
  it("test_segment_requisites_bad_action_is_invalid_response", () =>
    invalid({ requisites: [{ clause: "c1", lines: [{ span: [0, 0, 5], action: "delete" }] }] }));
  it("test_segment_requisites_line_outside_block_is_invalid_response", () =>
    invalid({ requisites: [{ clause: "c1", lines: [{ span: [0, 0, 9999], action: "drop" }] }] }));
  it("test_segment_neutralized_span_outside_block_is_invalid_response", () =>
    invalid({ neutralized: [[0, 3, 9999]] }));

  it("test_segment_too_many_identifiers_422_is_mapped", async () => {
    expect(await call({ error: "too_many_identifiers" }, 422)).toEqual({
      ok: false,
      code: "too_many_identifiers",
    });
  });
});
