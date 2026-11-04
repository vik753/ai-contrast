/** S6-T5 AC2 — API helper: key only in the header, pinned fetch options. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, stubFetch } from "../test/provider-fakes";
import { checkConnection } from "./checkConnection";

const KEY = "sk-CANARY-77be02";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("checkConnection (S6-T5 AC2)", () => {
  it("test_check_posts_to_provider_check_with_pinned_fetch_options", async () => {
    const { calls } = stubFetch();
    await checkConnection({ provider: "openai", model: "gpt-x", key: KEY });
    expect(calls).toHaveLength(1);
    const c = calls[0];
    expect(c?.url).toBe("/api/provider/check");
    expect(c?.method).toBe("POST");
    expect(c?.init.credentials).toBe("omit");
    expect(c?.init.redirect).toBe("error");
    expect(c?.init.cache).toBe("no-store");
    expect(c?.headers.get("content-type")).toMatch(/^application\/json/);
  });

  it("test_check_sends_key_only_in_x_provider_key_header", async () => {
    const { calls } = stubFetch();
    await checkConnection({ provider: "openai", model: "gpt-x", key: KEY });
    const c = calls[0];
    expect(c?.headers.get("x-provider-key")).toBe(KEY);
    expect(c?.url).not.toContain(KEY);
    expect(c?.body).not.toContain(KEY);
    expect(JSON.parse(c?.body ?? "{}")).toEqual({ provider: "openai", model: "gpt-x" });
  });

  it("test_check_custom_sends_base_url_in_body", async () => {
    const { calls } = stubFetch();
    await checkConnection({
      provider: "custom",
      model: "m1",
      baseUrl: "https://llm.example.test/v1",
      key: KEY,
    });
    expect(JSON.parse(calls[0]?.body ?? "{}")).toEqual({
      provider: "custom",
      model: "m1",
      base_url: "https://llm.example.test/v1",
    });
  });

  it("test_check_free_sends_token_and_no_key_header_and_no_model", async () => {
    const { calls } = stubFetch();
    await checkConnection({ provider: "free", turnstileToken: "tok-1" });
    const c = calls[0];
    expect(c?.headers.has("x-provider-key")).toBe(false);
    expect(JSON.parse(c?.body ?? "{}")).toEqual({ provider: "free", turnstile_token: "tok-1" });
  });

  it("test_check_success_returns_ok", async () => {
    stubFetch(() => jsonResponse(200, { ok: true }));
    expect(await checkConnection({ provider: "openai", model: "m", key: KEY })).toEqual({
      ok: true,
    });
  });

  it("test_check_known_error_code_is_returned", async () => {
    stubFetch(() => jsonResponse(401, { error: "provider_auth_failed" }));
    expect(await checkConnection({ provider: "openai", model: "m", key: KEY })).toEqual({
      ok: false,
      code: "provider_auth_failed",
    });
  });

  it.each([
    ["unknown code", () => jsonResponse(500, { error: "<img src=x onerror=alert(1)>" })],
    ["not json", () => new Response("<html>oops</html>", { status: 502 })],
    ["200 without ok", () => jsonResponse(200, { ok: false })],
    ["200 with extra field", () => jsonResponse(200, { ok: true, text: "model said hi" })],
  ])("test_check_%s_maps_to_unknown", async (_n, reply) => {
    stubFetch(reply);
    expect(await checkConnection({ provider: "openai", model: "m", key: KEY })).toEqual({
      ok: false,
      code: "unknown",
    });
  });

  it("test_check_fetch_failure_maps_to_network_without_the_error_text", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError(`boom ${KEY}`))),
    );
    const r = await checkConnection({ provider: "openai", model: "m", key: KEY });
    expect(r).toEqual({ ok: false, code: "network" });
    expect(JSON.stringify(r)).not.toContain(KEY);
  });
});
