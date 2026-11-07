// @vitest-environment node
/** S9-T4 AC2 — `compareValues` (ADR 0019 point 5): pure comparison by code. */
import { describe, expect, it } from "vitest";
import { compareValues, type CompareInput, type Direction } from "./compare";

const amt = (number: number, currency = "UAH"): CompareInput => ({
  status: "verified",
  value: { type: "amount", number, currency },
});
const dur = (number: number, unit = "days"): CompareInput => ({
  status: "verified",
  value: { type: "duration", number, unit },
});
const pct = (number: number): CompareInput => ({
  status: "verified",
  value: { type: "percentage", number },
});
const en = (value: string): CompareInput => ({
  status: "verified",
  value: { type: "enum", value },
});
const cat = (...values: string[]): CompareInput => ({
  status: "verified",
  value: { type: "categories", values },
});
const txt = (text: string): CompareInput => ({ status: "verified", value: { type: "text", text } });
const NOT_STATED: CompareInput = { status: "verified", value: { type: "not_stated" } };
const NOT_CONFIRMED: CompareInput = {
  status: "not_confirmed",
  value: { type: "amount", number: 1, currency: "UAH" },
};
const NOT_ANALYZED: CompareInput = { status: "not_analyzed" };
const run = (type: string, direction: Direction, ...inputs: CompareInput[]) =>
  compareValues({ type, direction }, inputs);

describe("numbers", () => {
  it("test_equal_amounts_are_same", () => {
    expect(run("amount", "lower_better", amt(5000), amt(5000))).toEqual({
      status: "compared",
      marks: ["same", "same"],
    });
  });
  it("test_lower_better_marks_the_smaller_better", () => {
    expect(run("amount", "lower_better", amt(5000), amt(8000)).marks).toEqual(["better", "worse"]);
  });
  it("test_higher_better_marks_the_larger_better", () => {
    expect(run("amount", "higher_better", amt(5000), amt(8000)).marks).toEqual(["worse", "better"]);
  });
  it("test_no_direction_gives_different_not_better", () => {
    expect(run("amount", "none", amt(5000), amt(8000)).marks).toEqual(["different", "different"]);
  });
  it("test_percentage_and_duration_follow_direction", () => {
    expect(run("percentage", "lower_better", pct(5), pct(10)).marks).toEqual(["better", "worse"]);
    expect(run("duration", "higher_better", dur(10), dur(30)).marks).toEqual(["worse", "better"]);
  });
  it("test_three_documents_best_is_better_and_the_rest_worse", () => {
    expect(run("amount", "lower_better", amt(9000), amt(5000), amt(7000)).marks).toEqual([
      "worse",
      "better",
      "worse",
    ]);
  });
});

describe("units", () => {
  it("test_different_currencies_are_not_comparable_and_not_converted", () => {
    const r = run("amount", "lower_better", amt(100, "USD"), amt(4000, "UAH"));
    expect(r).toMatchObject({ status: "not_comparable", reason: "unit" });
    expect(r.marks).toEqual(["not_compared", "not_compared"]);
  });
  it("test_percent_of_sum_and_uah_are_not_comparable", () => {
    expect(run("amount", "none", amt(5, "percent_of_sum"), amt(5, "UAH")).reason).toBe("unit");
  });
  it("test_different_duration_units_are_not_comparable", () => {
    const r = run("duration", "lower_better", dur(10, "days"), dur(10, "working_days"));
    expect(r).toMatchObject({ status: "not_comparable", reason: "unit" });
  });
  it("test_different_value_types_are_not_comparable", () => {
    expect(run("amount", "none", amt(5), pct(5))).toMatchObject({
      status: "not_comparable",
      reason: "type",
    });
  });
});

describe("enums and categories", () => {
  it("test_equal_enum_ids_are_same_and_text_is_never_read", () => {
    expect(run("enum", "none", en("covered"), en("covered")).marks).toEqual(["same", "same"]);
  });
  it("test_different_enum_ids_without_direction_are_different", () => {
    expect(run("enum", "none", en("covered"), en("conditional")).marks).toEqual([
      "different",
      "different",
    ]);
  });
  it("test_enum_list_direction_ranks_by_index_best_first", () => {
    const dir = ["covered", "conditional", "not_covered"];
    expect(run("enum", dir, en("not_covered"), en("covered")).marks).toEqual(["worse", "better"]);
  });
  it("test_categories_equal_sets_in_any_order_are_same", () => {
    expect(run("categories", "none", cat("a", "b"), cat("b", "a")).marks).toEqual(["same", "same"]);
  });
  it("test_categories_different_sets_without_direction_are_different", () => {
    expect(run("categories", "none", cat("a"), cat("b")).marks).toEqual(["different", "different"]);
  });
  it("test_categories_more_better_ranks_by_set_size", () => {
    expect(run("categories", "more_better", cat("a"), cat("a", "b")).marks).toEqual([
      "worse",
      "better",
    ]);
    expect(run("categories", "fewer_better", cat("a"), cat("a", "b")).marks).toEqual([
      "better",
      "worse",
    ]);
  });
  it("test_categories_same_size_different_sets_are_different_even_with_direction", () => {
    expect(run("categories", "more_better", cat("a"), cat("b")).marks).toEqual([
      "different",
      "different",
    ]);
  });
});

describe("text and values that cannot be compared", () => {
  it("test_text_is_never_compared", () => {
    const r = run("text", "none", txt("Within 10 days"), txt("Within 10 days"));
    expect(r.status).toBe("text");
    expect(r.marks).toEqual(["not_compared", "not_compared"]);
  });
  it("test_not_confirmed_value_is_never_compared_even_if_the_number_matches", () => {
    const r = run("amount", "lower_better", { ...NOT_CONFIRMED }, amt(1));
    expect(r.marks).toEqual(["not_compared", "not_compared"]);
    expect(r).toMatchObject({ status: "not_comparable", reason: "too_few" });
  });
  it("test_two_not_stated_values_are_not_same", () => {
    const r = run("amount", "none", NOT_STATED, NOT_STATED);
    expect(r.marks).toEqual(["not_compared", "not_compared"]);
  });
  it("test_two_not_analyzed_values_are_not_same", () => {
    expect(run("enum", "none", NOT_ANALYZED, NOT_ANALYZED).marks).toEqual([
      "not_compared",
      "not_compared",
    ]);
  });
  it("test_not_stated_against_a_value_is_not_compared", () => {
    expect(run("amount", "lower_better", NOT_STATED, amt(5)).marks).toEqual([
      "not_compared",
      "not_compared",
    ]);
  });
  it("test_third_document_without_value_does_not_block_the_other_two", () => {
    const r = run("amount", "lower_better", amt(5), NOT_CONFIRMED, amt(9));
    expect(r.status).toBe("compared");
    expect(r.marks).toEqual(["better", "not_compared", "worse"]);
  });
  it("test_single_input_is_not_comparable", () => {
    expect(run("amount", "lower_better", amt(5))).toMatchObject({
      status: "not_comparable",
      reason: "too_few",
      marks: ["not_compared"],
    });
  });
});

describe("capped values", () => {
  it("test_better_is_never_shown_for_a_capped_value", () => {
    const r = run("amount", "lower_better", { ...amt(5), capped: true }, amt(8));
    expect(r.marks).not.toContain("better");
    expect(r.marks).not.toContain("worse");
    expect(r.marks).toEqual(["different", "different"]);
  });
  it("test_capped_equal_values_may_still_be_same", () => {
    expect(run("amount", "lower_better", { ...amt(5), capped: true }, amt(5)).marks).toEqual([
      "same",
      "same",
    ]);
  });
});
