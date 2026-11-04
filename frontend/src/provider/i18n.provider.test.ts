// @vitest-environment node
/** S6-T5 AC1 — provider strings exist in en, uk and ru; no hard-coded UI text. */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import en from "../i18n/locales/en.json";
import ru from "../i18n/locales/ru.json";
import uk from "../i18n/locales/uk.json";
import { flattenLocale } from "../test/locale-utils";

const L = { en: flattenLocale(en), uk: flattenLocale(uk), ru: flattenLocale(ru) } as const;

const CODES = [
  "request_too_large",
  "invalid_request",
  "invalid_provider",
  "invalid_model",
  "unexpected_model",
  "unexpected_base_url",
  "invalid_base_url",
  "unexpected_turnstile_token",
  "invalid_provider_key",
  "unexpected_provider_key",
  "free_mode_unavailable",
  "turnstile_failed",
  "free_quota_exhausted",
  "rate_limited",
  "busy",
  "provider_auth_failed",
  "provider_model_not_found",
  "provider_rate_limited",
  "provider_bad_request",
  "provider_blocked_host",
  "provider_unavailable",
  "provider_bad_response",
  "network",
  "unknown",
];
const KEYS = [
  "provider.test.ok",
  "provider.free.notice",
  "provider.free.turnstileNotice",
  "provider.gemini.hint",
  "provider.gemini.dataUse",
  "provider.remember.warning",
  ...CODES.map((c) => `provider.error.${c}`),
];

describe("provider i18n (S6-T5 AC1)", () => {
  it.each(["en", "uk", "ru"] as const)("test_%s_has_every_provider_key_non_empty", (lang) => {
    for (const k of KEYS) {
      const v = L[lang][k];
      expect(typeof v, `${lang}:${k}`).toBe("string");
      expect((v as string).trim().length, `${lang}:${k}`).toBeGreaterThan(0);
    }
  });

  it.each(["uk", "ru"] as const)("test_%s_provider_strings_are_translated_not_copied", (lang) => {
    for (const k of KEYS) {
      expect(L[lang][k], `${lang}:${k}`).not.toBe(L.en[k]);
    }
  });

  it("test_every_provider_key_in_en_exists_in_uk_and_ru", () => {
    const pick = (o: Record<string, unknown>) =>
      Object.keys(o)
        .filter((k) => k.startsWith("provider."))
        .sort();
    expect(pick(L.uk)).toEqual(pick(L.en));
    expect(pick(L.ru)).toEqual(pick(L.en));
  });

  it("test_data_use_and_free_notices_name_the_processor", () => {
    expect(String(L.en["provider.free.notice"])).toMatch(/cloudflare/i);
    expect(String(L.en["provider.gemini.dataUse"])).toMatch(/google/i);
  });

  it("test_provider_settings_source_has_no_jsx_text_literals", () => {
    const src = readFileSync(
      fileURLToPath(new URL("./ProviderSettings.tsx", import.meta.url)),
      "utf8",
    );
    // Text between tags that is not an expression: ">Some words<".
    expect(src).not.toMatch(/>\s*[A-Za-z][A-Za-z ,.'-]{2,}\s*</);
    expect(src).not.toMatch(/dangerouslySetInnerHTML|innerHTML|insertAdjacentHTML/);
  });
});
