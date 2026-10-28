import { describe, expect, it } from "vitest";
import enJson from "../i18n/locales/en.json";
import ruJson from "../i18n/locales/ru.json";
import ukJson from "../i18n/locales/uk.json";
import { flattenLocale } from "../test/locale-utils";
import { reasonKey } from "./Preview";

const CODES = [
  "control_characters",
  "control_character",
  "default_ignorable",
  "format_character",
  "private_use",
  "unassigned",
  "surrogate",
];

describe("removed-text reasons", () => {
  it.each(CODES)("test_reason_%s_has_its_own_label_in_en_uk_ru", (code) => {
    const key = reasonKey(code);
    expect(key).toBe(`upload.preview.removed.reason.${code}`);
    for (const json of [enJson, ukJson, ruJson]) {
      expect(typeof flattenLocale(json)[key]).toBe("string");
    }
  });

  it("test_unknown_reason_falls_back_to_other", () => {
    expect(reasonKey("something_new")).toBe("upload.preview.removed.reason.other");
  });
});
