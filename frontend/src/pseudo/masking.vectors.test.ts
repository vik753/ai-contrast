/**
 * S5b-T4 AC 1: shared placeholder vectors. The same file (`shared/pseudo-vectors.json`)
 * runs through the Python reference (`backend/tests/canary/test_masking_vectors.py`) and
 * through `masking.ts` here. Both must give the same masked clauses and acknowledged spans.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { clause, segmentReply, type WireBlock, type WireSpan } from "../test/segment-fakes";
import { parsedFixture } from "../test/pseudo-fakes";
import * as masking from "./masking";

interface VectorCase {
  name: string;
  label: string;
  blocks: string[];
  clauses: { id: string; spans: WireSpan[] }[];
  entities: unknown[];
  requisites: unknown[];
  neutralized: WireSpan[];
  unmask: { entities: string[]; occurrences: [string, number][] };
  expected: { masked: { id: string; text: string }[]; acknowledged: [string, number, number][] };
}

// Vitest runs from `frontend/`; the shared file is at the repository root.
const FILE = resolve(process.cwd(), "../shared/pseudo-vectors.json");
const VECTORS = (JSON.parse(readFileSync(FILE, "utf8")) as { cases: VectorCase[] }).cases;

async function review(c: VectorCase): Promise<masking.Review> {
  const blocks: WireBlock[] = c.blocks.map((text) => ({ text, part: "body", page: null }));
  const reply = segmentReply(blocks, {
    clauses: c.clauses.map((item, index) => clause(index + 1, { id: item.id, spans: item.spans })),
    entities: c.entities,
    requisites: c.requisites,
    neutralized: c.neutralized,
  });
  let r = masking.startReview(await parsedFixture({}, blocks, reply), c.label);
  for (const id of c.unmask.entities) r = masking.unmaskEntity(r, id);
  for (const [id, index] of c.unmask.occurrences) r = masking.unmaskOccurrence(r, id, index);
  return r;
}

describe("shared masking vectors", () => {
  it("test_vectors_file_has_cases", () => {
    expect(VECTORS.length).toBeGreaterThanOrEqual(15);
  });

  for (const c of VECTORS) {
    it(`test_vector_masked_clauses_${c.name}`, async () => {
      const r = await review(c);
      expect(masking.maskedClauses(r).map((m) => ({ id: m.id, text: m.text }))).toEqual(
        c.expected.masked,
      );
    });

    it(`test_vector_acknowledged_spans_${c.name}`, async () => {
      const r = await review(c);
      expect(masking.acknowledgedUnmasked(r).map((s) => [...s])).toEqual(c.expected.acknowledged);
    });
  }
});
