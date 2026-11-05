/** S8-T3 AC2/3 — `tagDocument`: wire shape, headers, pinned fetch options, error mapping. */
import { afterEach, expect, it, vi } from "vitest";
import { canary } from "../test/upload-fakes";
import { jsonResponse } from "../test/provider-fakes";
import {
  SELECTION,
  bodyOf,
  maskedDoc,
  stubTagFetch,
  tagCalls,
  tagReply,
} from "../test/tagging-fakes";
import { TAG_ERROR_CODES, tagDocument } from "./tagApi";

afterEach(() => vi.unstubAllGlobals());

const base = () => ({
  provider: "openai",
  model: "gpt-cheap",
  checkModel: "gpt-strong",
  key: "sk-CANARY-abc123",
  domain: "kasko",
  side: "insured",
  document: maskedDoc("A"),
  topics: SELECTION,
});

it("test_tag_document_posts_wire_body_snake_case_without_key_or_digest", async () => {
  const { calls } = stubTagFetch();
  const r = await tagDocument(base());
  expect(r.ok).toBe(true);
  const c = tagCalls(calls)[0];
  expect(c?.method).toBe("POST");
  const b = bodyOf(c as never);
  expect(b.provider).toBe("openai");
  expect(b.model).toBe("gpt-cheap");
  expect(b.check_model).toBe("gpt-strong");
  expect(b.domain).toBe("kasko");
  expect(b.side).toBe("insured");
  expect(b.topics).toEqual(SELECTION);
  const doc = b.document as Record<string, unknown>;
  expect(Object.keys(doc).sort()).toEqual(
    ["acknowledged_unmasked", "clauses", "detector_version", "label"].sort(),
  );
  expect(c?.body).not.toContain("sk-CANARY");
  expect(c?.body).not.toContain("a".repeat(64));
});

it("test_tag_document_sends_key_only_in_header_and_pins_fetch_options", async () => {
  const { calls } = stubTagFetch();
  await tagDocument(base());
  const c = tagCalls(calls)[0];
  expect(c?.headers.get("X-Provider-Key")).toBe("sk-CANARY-abc123");
  expect(c?.headers.get("Content-Type")).toBe("application/json");
  expect(c?.url).not.toContain("sk-CANARY");
  expect(c?.init.credentials).toBe("omit");
  expect(c?.init.redirect).toBe("error");
  expect(c?.init.cache).toBe("no-store");
});

it("test_tag_document_analysis_pass_goes_only_in_its_header", async () => {
  const { calls } = stubTagFetch();
  const { key: _k, model: _m, checkModel: _c, ...free } = base();
  await tagDocument({ ...free, provider: "free", analysisPass: "v1.analysis.pass" });
  const c = tagCalls(calls)[0];
  expect(c?.headers.get("X-Analysis-Pass")).toBe("v1.analysis.pass");
  expect(c?.headers.has("X-Free-Pass")).toBe(false);
  expect(c?.headers.has("X-Provider-Key")).toBe(false);
  expect(c?.body).not.toContain("v1.analysis.pass");
  expect(bodyOf(c as never).turnstile_token).toBeUndefined();
});

it("test_tag_document_turnstile_token_goes_in_body_only", async () => {
  const { calls } = stubTagFetch();
  const { key: _k, model: _m, checkModel: _c, ...free } = base();
  await tagDocument({ ...free, provider: "free", turnstileToken: "tok-1" });
  const c = tagCalls(calls)[0];
  expect(bodyOf(c as never).turnstile_token).toBe("tok-1");
  expect(c?.headers.has("X-Analysis-Pass")).toBe(false);
});

it("test_tag_document_returns_reply_and_analysis_pass_separately", async () => {
  stubTagFetch(() => jsonResponse(200, tagReply({ analysis_pass: "ap-1" })));
  const r = await tagDocument(base());
  expect(r.ok).toBe(true);
  if (!r.ok) return;
  expect(r.analysisPass).toBe("ap-1");
  expect(r.data.signature).toBe("sig-abc");
  expect(r.data.other).toEqual(["c3"]);
  expect("analysis_pass" in r.data).toBe(false);
});

it.each([
  [422, "keyword_budget_exceeded"],
  [422, "document_too_large_for_tagging"],
  [403, "analysis_pass_invalid"],
  [403, "analysis_pass_expired"],
  [403, "analysis_pass_exhausted"],
  [503, "analysis_pass_unavailable"],
  [429, "free_quota_exhausted"],
  [503, "busy"],
  [429, "rate_limited"],
  [422, "too_many_documents"],
  [422, "free_too_large"],
  [403, "turnstile_failed"],
  [401, "provider_auth_failed"],
])("test_tag_document_maps_%s_%s_to_its_code", async (status, code) => {
  stubTagFetch(() => jsonResponse(status, { error: code }));
  const r = await tagDocument(base());
  expect(r).toEqual({ ok: false, code });
  expect(TAG_ERROR_CODES).toContain(code);
});

it("test_tag_document_unlisted_error_code_gives_unknown_and_hides_server_text", async () => {
  const secret = canary("srv");
  stubTagFetch(() => jsonResponse(500, { error: secret }));
  const r = await tagDocument(base());
  expect(r).toEqual({ ok: false, code: "unknown" });
});

it("test_tag_document_malformed_or_extra_key_reply_gives_unknown", async () => {
  stubTagFetch(() => jsonResponse(200, { digest: "x" }));
  expect(await tagDocument(base())).toEqual({ ok: false, code: "unknown" });
  stubTagFetch(() => jsonResponse(200, { ...tagReply(), surprise: 1 }));
  expect(await tagDocument(base())).toEqual({ ok: false, code: "unknown" });
});

it("test_tag_document_fetch_failure_gives_network", async () => {
  vi.stubGlobal("fetch", () => Promise.reject(new TypeError("offline")));
  expect(await tagDocument(base())).toEqual({ ok: false, code: "network" });
});
