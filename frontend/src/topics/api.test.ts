/** S7-T3 AC1, AC3 — API helpers: key and pass channels, pinned options, strict replies. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse } from "../test/provider-fakes";
import { CATALOG, DOC, bodyOf, must, stubTopicsFetch, topic } from "../test/topics-fakes";
import { expandSynonyms, fetchCatalog, proposeAttributes, suggestTopics } from "./api";

const KEY = "sk-CANARY-topics-1234";
afterEach(() => vi.unstubAllGlobals());

const base = { provider: "anthropic", model: "m1", key: KEY } as const;

describe("topic API helpers", () => {
  it("test_fetchCatalog_get_pinned_options_no_body_no_key", async () => {
    const { calls } = stubTopicsFetch();
    const r = await fetchCatalog();
    expect(r).toEqual({ ok: true, data: CATALOG });
    const c = must(calls[0]);
    expect(c.url).toBe("/api/topics/catalog");
    expect(c.method ?? "GET").toBe("GET");
    expect(c.body).toBeUndefined();
    expect(c.init).toMatchObject({ credentials: "omit", redirect: "error", cache: "no-store" });
  });

  it("test_suggestTopics_key_only_in_header_and_snake_case_body", async () => {
    const { calls } = stubTopicsFetch(() => jsonResponse(200, { suggestions: [], dropped: 0 }));
    await suggestTopics({ ...base, domain: "kasko", side: "insured", document: DOC("A") });
    const c = must(calls[0]);
    expect(c.url).toBe("/api/topics/suggest");
    expect(c.method).toBe("POST");
    expect(c.headers.get("X-Provider-Key")).toBe(KEY);
    expect(c.headers.get("X-Free-Pass")).toBeNull();
    expect(c.body).not.toContain(KEY);
    expect(c.url).not.toContain(KEY);
    expect(c.init).toMatchObject({ credentials: "omit", redirect: "error", cache: "no-store" });
    expect(bodyOf(c)).toEqual({
      provider: "anthropic",
      model: "m1",
      domain: "kasko",
      side: "insured",
      document: {
        label: "A",
        detector_version: "pseudo-1",
        clauses: [{ id: "c1", text: "1. Text" }],
        acknowledged_unmasked: [],
      },
    });
  });

  it("test_free_pass_only_in_header", async () => {
    const { calls } = stubTopicsFetch(() => jsonResponse(200, { attributes: [], dropped: 0 }));
    await proposeAttributes({ provider: "free", freePass: "v1.topics.pass", topic: topic() });
    const c = must(calls[0]);
    expect(c.url).toBe("/api/topics/propose-attributes");
    expect(c.headers.get("X-Free-Pass")).toBe("v1.topics.pass");
    expect(c.headers.get("X-Provider-Key")).toBeNull();
    expect(c.body).not.toContain("v1.topics.pass");
    expect(bodyOf(c)).not.toHaveProperty("turnstile_token");
    expect(bodyOf(c)).toHaveProperty("topic");
  });

  it("test_turnstile_token_goes_in_body_for_first_call", async () => {
    const { calls } = stubTopicsFetch(() =>
      jsonResponse(200, { synonyms_en: [], synonyms_uk: [], synonyms_ru: [], dropped: 0 }),
    );
    await expandSynonyms({ provider: "free", turnstileToken: "tok", topic: topic() });
    expect(must(calls[0]).url).toBe("/api/topics/expand-synonyms");
    expect(bodyOf(must(calls[0])).turnstile_token).toBe("tok");
  });

  it("test_reply_free_pass_is_returned", async () => {
    stubTopicsFetch(() => jsonResponse(200, { suggestions: [], dropped: 2, free_pass: "p-new" }));
    const r = await suggestTopics({ provider: "free", domain: "k", side: "s", document: DOC("A") });
    expect(r).toEqual({ ok: true, data: { suggestions: [], dropped: 2 }, freePass: "p-new" });
  });

  it("test_free_pass_over_256_chars_is_unknown", async () => {
    stubTopicsFetch(() =>
      jsonResponse(200, { suggestions: [], dropped: 0, free_pass: "x".repeat(257) }),
    );
    const r = await suggestTopics({ provider: "free", domain: "k", side: "s", document: DOC("A") });
    expect(r).toEqual({ ok: false, code: "unknown" });
  });

  it("test_error_identifier_keeps_field_and_numeric_spans", async () => {
    stubTopicsFetch(() =>
      jsonResponse(422, { error: "topic_contains_identifier", field: "title", spans: [[5, 18]] }),
    );
    const r = await proposeAttributes({ ...base, topic: topic() });
    expect(r).toEqual({
      ok: false,
      code: "topic_contains_identifier",
      field: "title",
      spans: [[5, 18]],
    });
  });

  it.each([
    "topic_flagged",
    "invalid_topic_text",
    "ai_bad_output",
    "free_quota_exhausted",
    "busy",
    "catalog_version_mismatch",
    "rate_limited",
    "free_pass_invalid",
    "free_pass_expired",
    "free_pass_exhausted",
    "turnstile_failed",
  ])("test_known_error_code_%s_passes_through", async (code) => {
    stubTopicsFetch(() => jsonResponse(429, { error: code }));
    const r = await proposeAttributes({ ...base, topic: topic() });
    expect(r).toMatchObject({ ok: false, code });
  });

  it("test_unknown_error_code_and_server_text_become_unknown", async () => {
    stubTopicsFetch(() => jsonResponse(500, { error: "<img src=x onerror=1>", detail: "boom" }));
    expect(await proposeAttributes({ ...base, topic: topic() })).toEqual({
      ok: false,
      code: "unknown",
    });
  });

  it("test_malformed_success_bodies_are_unknown", async () => {
    for (const bad of [{ suggestions: "x", dropped: 0 }, { dropped: 0 }, [], null, "ok"]) {
      stubTopicsFetch(() => jsonResponse(200, bad));
      const r = await suggestTopics({ ...base, domain: "k", side: "s", document: DOC("A") });
      expect(r).toEqual({ ok: false, code: "unknown" });
    }
  });

  it("test_network_failure_gives_network_code", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("down")));
    expect(await fetchCatalog()).toEqual({ ok: false, code: "network" });
    expect(await proposeAttributes({ ...base, topic: topic() })).toEqual({
      ok: false,
      code: "network",
    });
  });
});
