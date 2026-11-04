/** S6-T5 AC1 — preset list (ADR 0016 points 4 and 9). */
import { describe, expect, it } from "vitest";
import { DEFAULT_PRESET, PRESETS } from "./presets";

describe("provider presets (S6-T5 AC1)", () => {
  it("test_presets_list_has_seven_ids_in_order", () => {
    expect(PRESETS.map((p) => p.id)).toEqual([
      "free",
      "anthropic",
      "openai",
      "gemini",
      "mistral",
      "openrouter",
      "custom",
    ]);
  });

  it("test_default_preset_is_free", () => {
    expect(DEFAULT_PRESET).toBe("free");
  });

  it("test_free_has_no_model_suggestions_because_the_model_is_fixed", () => {
    expect(PRESETS.find((p) => p.id === "free")?.models).toEqual([]);
  });

  it("test_every_keyed_preset_except_custom_has_suggestions_in_the_model_grammar", () => {
    const grammar = /^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}$/;
    for (const p of PRESETS.filter((x) => x.id !== "free" && x.id !== "custom")) {
      expect(p.models.length, p.id).toBeGreaterThan(0);
      for (const m of p.models) expect(m, `${p.id}:${m}`).toMatch(grammar);
    }
  });
});
