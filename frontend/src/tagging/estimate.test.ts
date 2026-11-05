/** S8-T3 AC2 — cost estimate and the model pair shown before the step. */
import { expect, it } from "vitest";
import { maskedDoc } from "../test/tagging-fakes";
import { FREE_MODEL, estimateTagging, modelPairOf } from "./estimate";

it("test_estimate_one_small_document_is_one_batch", () => {
  const doc = maskedDoc("A", undefined, ["x".repeat(30)]);
  expect(estimateTagging([doc], 2)).toEqual({
    calls: 1,
    maxCheckCalls: 1,
    inputTokens: 10 + (200 + 120),
  });
});

it("test_estimate_batches_by_characters", () => {
  const doc = maskedDoc("A", undefined, ["x".repeat(6000), "y".repeat(6001)]);
  expect(estimateTagging([doc], 1).calls).toBe(2);
});

it("test_estimate_batches_by_clause_count", () => {
  const doc = maskedDoc(
    "A",
    undefined,
    Array.from({ length: 41 }, () => "ab"),
  );
  expect(estimateTagging([doc], 1).calls).toBe(2);
});

it("test_estimate_sums_over_documents_and_empty_is_zero", () => {
  const a = maskedDoc("A", undefined, ["x".repeat(30)]);
  const b = maskedDoc("B", undefined, ["x".repeat(30)]);
  expect(estimateTagging([a, b], 2).calls).toBe(2);
  expect(estimateTagging([], 2)).toEqual({ calls: 0, maxCheckCalls: 0, inputTokens: 0 });
});

it("test_model_pair_free_is_the_free_model_twice", () => {
  expect(FREE_MODEL).toBe("@cf/openai/gpt-oss-120b");
  expect(modelPairOf({ provider: "free" })).toEqual({ cheap: FREE_MODEL, strong: FREE_MODEL });
});

it("test_model_pair_uses_model_and_check_model_else_model_twice", () => {
  expect(modelPairOf({ provider: "openai", model: "m1", checkModel: "m2" })).toEqual({
    cheap: "m1",
    strong: "m2",
  });
  expect(modelPairOf({ provider: "custom", model: "m1" })).toEqual({ cheap: "m1", strong: "m1" });
});
