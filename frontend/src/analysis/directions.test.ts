// @vitest-environment node
/** S9-T4 AC2 — directions from the selection and the catalog. */
import { describe, expect, it } from "vitest";
import { CATALOG } from "../test/topics-fakes";
import { directionsFromSelection } from "./directions";

const ref = (topic_id: string, side: string) => ({
  domain: "kasko",
  topic_id,
  side,
  lang: "en",
  catalog_version: "v-test-1",
});
const def = (over: Record<string, unknown>) => ({
  origin: "custom",
  domain: "kasko",
  topic_id: "mine",
  title: "Mine",
  description: "d",
  side: "insured",
  attributes: [],
  synonyms_en: [],
  synonyms_uk: [],
  synonyms_ru: [],
  ...over,
});
const attr = (over: Record<string, unknown>) => ({
  id: "a1",
  label: "A",
  type: "amount",
  units: [],
  direction: "none",
  order: [],
  values: [],
  direction_source: "client",
  ...over,
});

describe("directionsFromSelection", () => {
  it("test_catalog_ref_reads_the_direction_of_the_chosen_side", () => {
    const sel = { catalog: [ref("deductible", "insured")], suggested: [], custom: [] };
    expect(directionsFromSelection(sel as never, CATALOG as never)["deductible/amount"]).toBe(
      "lower_better",
    );
    const sel2 = { catalog: [ref("deductible", "insurer")], suggested: [], custom: [] };
    expect(directionsFromSelection(sel2 as never, CATALOG as never)["deductible/amount"]).toBe(
      "higher_better",
    );
  });
  it("test_custom_definition_uses_its_attribute_direction", () => {
    const sel = {
      catalog: [],
      suggested: [],
      custom: [def({ attributes: [attr({ direction: "higher_better" })] })],
    };
    expect(directionsFromSelection(sel as never, CATALOG as never)["mine/a1"]).toBe(
      "higher_better",
    );
  });
  it("test_custom_enum_with_an_order_gives_that_list", () => {
    const sel = {
      catalog: [],
      suggested: [
        def({
          origin: "suggested",
          attributes: [attr({ type: "enum", order: ["x", "y"], values: ["x", "y"] })],
        }),
      ],
      custom: [],
    };
    expect(directionsFromSelection(sel as never, CATALOG as never)["mine/a1"]).toEqual(["x", "y"]);
  });
  it("test_unknown_topic_gives_no_entry", () => {
    const sel = { catalog: [ref("nope", "insured")], suggested: [], custom: [] };
    expect(directionsFromSelection(sel as never, CATALOG as never)).toEqual({});
  });
});
