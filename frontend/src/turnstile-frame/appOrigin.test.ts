import { describe, expect, it } from "vitest";
import { resolveAppOrigin } from "./appOrigin";

describe("resolveAppOrigin", () => {
  it("test_dev_fallback", () => {
    expect(resolveAppOrigin({ DEV: true })).toBe("http://localhost:5173");
  });
  it("test_production_accepts_exact_https_origin", () => {
    expect(
      resolveAppOrigin({ DEV: false, VITE_TURNSTILE_APP_ORIGIN: "https://app.example.test" }),
    ).toBe("https://app.example.test");
  });
  it.each([
    ["missing", undefined],
    ["http", "http://app.example.test"],
    ["path", "https://app.example.test/x"],
    ["trailing slash", "https://app.example.test/"],
    ["default port spelled out", "https://app.example.test:443"],
    ["not a url", "app"],
  ])("test_production_rejects_%s", (_n, raw) => {
    expect(() =>
      resolveAppOrigin({
        DEV: false,
        ...(raw === undefined ? {} : { VITE_TURNSTILE_APP_ORIGIN: raw }),
      }),
    ).toThrow();
  });
});
