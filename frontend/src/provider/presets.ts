/** Provider presets shown in the settings panel (ADR 0016 points 4 and 9). Model IDs are suggestions only. */
export type PresetId =
  "free" | "anthropic" | "openai" | "gemini" | "mistral" | "openrouter" | "custom";

export interface Preset {
  id: PresetId;
  models: readonly string[];
}

export const PRESETS: readonly Preset[] = [
  { id: "free", models: [] },
  { id: "anthropic", models: ["claude-sonnet-4-5", "claude-opus-4-1", "claude-haiku-4-5"] },
  { id: "openai", models: ["gpt-5", "gpt-5-mini", "gpt-4.1"] },
  { id: "gemini", models: ["gemini-2.5-pro", "gemini-2.5-flash"] },
  {
    id: "mistral",
    models: ["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest"],
  },
  {
    id: "openrouter",
    models: ["anthropic/claude-sonnet-4.5", "openai/gpt-5", "google/gemini-2.5-pro"],
  },
  { id: "custom", models: [] },
];

export const DEFAULT_PRESET: PresetId = "free";

export function isPresetId(value: string): value is PresetId {
  return PRESETS.some((p) => p.id === value);
}
