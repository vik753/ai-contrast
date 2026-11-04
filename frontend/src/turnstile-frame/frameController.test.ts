/** S6-T5 AC3 — frame side: exact-origin postMessage both ways (ADR 0016 point 7). */
import { describe, expect, it, vi } from "vitest";
import { createFrameController } from "./frameController";
import { resolveSiteKey } from "./siteKey";

const APP = "https://app.example.test";

function setup() {
  const parent = { postMessage: vi.fn() };
  const widget = { reset: vi.fn() };
  const c = createFrameController({ appOrigin: APP, parent, widget });
  return { parent, widget, c };
}

describe("frame controller (S6-T5 AC3)", () => {
  it("test_widget_token_is_posted_to_the_exact_app_origin", () => {
    const { parent, c } = setup();
    c.onWidgetToken("tok-1");
    expect(parent.postMessage).toHaveBeenCalledTimes(1);
    expect(parent.postMessage).toHaveBeenCalledWith(
      { type: "turnstile-token", token: "tok-1" },
      APP,
    );
  });

  it("test_widget_token_over_2048_is_not_posted", () => {
    const { parent, c } = setup();
    c.onWidgetToken("a".repeat(2049));
    expect(parent.postMessage).not.toHaveBeenCalled();
  });

  it("test_reset_from_app_origin_and_parent_source_resets_the_widget", () => {
    const { parent, widget, c } = setup();
    c.onMessage({ origin: APP, source: parent, data: { type: "reset" } });
    expect(widget.reset).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["wrong origin", { origin: "https://evil.example.test", data: { type: "reset" } }],
    ["origin with path-like suffix", { origin: `${APP}.evil.test`, data: { type: "reset" } }],
    ["null origin", { origin: "null", data: { type: "reset" } }],
    ["other type", { origin: APP, data: { type: "render" } }],
    ["extra key", { origin: APP, data: { type: "reset", sitekey: "x" } }],
    ["string data", { origin: APP, data: "reset" }],
  ])("test_message_with_%s_is_ignored", (_n, ev) => {
    const { parent, widget, c } = setup();
    c.onMessage({ source: parent, ...ev });
    expect(widget.reset).not.toHaveBeenCalled();
  });

  it("test_message_from_other_source_is_ignored", () => {
    const { widget, c } = setup();
    c.onMessage({ origin: APP, source: { postMessage: vi.fn() }, data: { type: "reset" } });
    expect(widget.reset).not.toHaveBeenCalled();
  });
});

describe("site key (S6-T5 AC3, Cloudflare test key in development)", () => {
  it("test_dev_without_key_uses_cloudflare_test_key", () => {
    expect(resolveSiteKey({ DEV: true })).toBe("1x00000000000000000000AA");
  });

  it("test_production_uses_the_configured_key", () => {
    expect(resolveSiteKey({ DEV: false, VITE_TURNSTILE_SITE_KEY: "0xREAL" })).toBe("0xREAL");
  });

  it("test_production_without_key_throws", () => {
    expect(() => resolveSiteKey({ DEV: false })).toThrow();
    expect(() => resolveSiteKey({ DEV: false, VITE_TURNSTILE_SITE_KEY: "" })).toThrow();
  });

  it("test_production_refuses_a_cloudflare_test_key", () => {
    expect(() =>
      resolveSiteKey({ DEV: false, VITE_TURNSTILE_SITE_KEY: "1x00000000000000000000AA" }),
    ).toThrow();
  });
});

describe("frame controller expiry and error messages", () => {
  it("test_expired_and_error_are_posted_to_the_exact_app_origin", () => {
    const { parent, c } = setup();
    c.onWidgetExpired();
    c.onWidgetError();
    expect(parent.postMessage).toHaveBeenNthCalledWith(1, { type: "turnstile-expired" }, APP);
    expect(parent.postMessage).toHaveBeenNthCalledWith(2, { type: "turnstile-error" }, APP);
  });
});
