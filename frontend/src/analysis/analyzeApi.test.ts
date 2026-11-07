/** S9-T4 AC1 — `analyzeDocument`: request shape, refusals before the stream, outcomes. */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  analyzeCalls,
  controlled,
  evDone,
  evStart,
  frame,
  runFrames,
  sseResponse,
  stubAnalyzeFetch,
  taggingResult,
} from "../test/analysis-fakes";
import { jsonResponse } from "../test/provider-fakes";
import { maskedDoc, SELECTION } from "../test/tagging-fakes";
import { must } from "../test/topics-fakes";
import { ANALYZE_ERROR_CODES, analyzeDocument, type AnalyzeRequest } from "./analyzeApi";

afterEach(() => vi.unstubAllGlobals());

const CANARY = "sk-CANARY-91ac33";
const req = (over: Partial<AnalyzeRequest> = {}): AnalyzeRequest =>
  ({
    provider: "openai",
    model: "gpt-strong",
    key: CANARY,
    domain: "kasko",
    side: "insured",
    language: "en",
    document: maskedDoc("A"),
    topics: SELECTION,
    tagging: taggingResult("A"),
    ...over,
  }) as AnalyzeRequest;
const noop = () => undefined;
const bodyOf = (c: { body: string | undefined }) =>
  JSON.parse(c.body ?? "{}") as Record<string, unknown>;

describe("request", () => {
  it("test_posts_json_to_api_analyze_and_asks_for_an_event_stream", async () => {
    const { calls } = stubAnalyzeFetch();
    await analyzeDocument(req(), noop);
    const c = must(analyzeCalls(calls)[0]);
    expect(c.method).toBe("POST");
    expect(c.headers.get("Content-Type")).toBe("application/json");
    expect(c.headers.get("Accept")).toBe("text/event-stream");
  });

  it("test_fetch_options_are_pinned_and_the_signal_is_passed", async () => {
    const { calls } = stubAnalyzeFetch();
    const ac = new AbortController();
    await analyzeDocument(req(), noop, ac.signal);
    const i = must(analyzeCalls(calls)[0]).init;
    expect(i.credentials).toBe("omit");
    expect(i.redirect).toBe("error");
    expect(i.cache).toBe("no-store");
    expect(i.signal).toBeDefined();
  });

  it("test_key_is_only_in_x_provider_key_header", async () => {
    const { calls } = stubAnalyzeFetch();
    await analyzeDocument(req(), noop);
    const c = must(analyzeCalls(calls)[0]);
    expect(c.headers.get("X-Provider-Key")).toBe(CANARY);
    expect(c.url).not.toContain(CANARY);
    expect(c.body ?? "").not.toContain(CANARY);
    expect(c.headers.get("X-Free-Pass")).toBeNull();
    expect(c.headers.get("X-Analysis-Pass")).toBeNull();
  });

  it("test_body_has_the_contract_keys_and_the_seven_tagging_keys", async () => {
    const { calls } = stubAnalyzeFetch();
    await analyzeDocument(
      req({
        baseUrl: "https://llm.example.test/v1",
        flags: ["not_read_material"],
        annexLinks: ["c2"],
      }),
      noop,
    );
    const b = bodyOf(must(analyzeCalls(calls)[0]));
    expect(Object.keys(b).sort()).toEqual(
      [
        "annex_links",
        "base_url",
        "document",
        "domain",
        "flags",
        "language",
        "model",
        "provider",
        "side",
        "tagging",
        "topics",
      ].sort(),
    );
    expect(b.document).toEqual({
      label: "A",
      detector_version: "pseudo-1",
      clauses: maskedDoc("A").clauses,
      acknowledged_unmasked: [],
    });
    expect(Object.keys(b.tagging as object).sort()).toEqual(
      [
        "client_tags",
        "digest",
        "incomplete_reasons",
        "signature",
        "tags",
        "tagging_version",
        "topics",
      ].sort(),
    );
    expect((b.tagging as { signature: string }).signature).toBe("sig-A");
  });

  it("test_optional_keys_are_absent_when_not_given", async () => {
    const { calls } = stubAnalyzeFetch();
    await analyzeDocument(req({ model: undefined, flags: undefined, annexLinks: undefined }), noop);
    const b = bodyOf(must(analyzeCalls(calls)[0]));
    for (const k of [
      "model",
      "flags",
      "annex_links",
      "base_url",
      "check_model",
      "turnstile_token",
      "key",
    ])
      expect(b).not.toHaveProperty(k);
  });

  it("test_free_mode_sends_the_pass_header_and_no_key_or_token", async () => {
    const { calls } = stubAnalyzeFetch();
    await analyzeDocument(
      req({ provider: "free", model: undefined, key: undefined, analysisPass: "ap-1" }),
      noop,
    );
    const c = must(analyzeCalls(calls)[0]);
    expect(c.headers.get("X-Analysis-Pass")).toBe("ap-1");
    expect(c.headers.get("X-Provider-Key")).toBeNull();
    expect(bodyOf(c)).not.toHaveProperty("analysis_pass");
    expect(bodyOf(c)).not.toHaveProperty("turnstile_token");
  });
});

describe("outcome", () => {
  it("test_events_are_delivered_in_order_and_done_is_returned", async () => {
    stubAnalyzeFetch(() => sseResponse(runFrames()));
    const seen: string[] = [];
    const r = await analyzeDocument(req(), (e: { event: string }) => seen.push(e.event));
    expect(seen).toEqual(["start", "topic", "topic", "other", "progress", "done"]);
    expect(r).toMatchObject({ ok: true, error: null });
    expect(r.ok && r.done?.analysis_version).toBe("av-1");
  });

  it("test_stream_without_done_returns_done_null", async () => {
    stubAnalyzeFetch(() => sseResponse(runFrames({ deductible: {} }, { done: null })));
    const r = await analyzeDocument(req(), noop);
    expect(r).toEqual({ ok: true, done: null, error: null });
  });

  it("test_error_event_returns_its_code_and_no_done", async () => {
    stubAnalyzeFetch(() =>
      sseResponse([frame("start", evStart()), frame("error", { error: "provider_auth_failed" })]),
    );
    const r = await analyzeDocument(req(), noop);
    expect(r).toEqual({ ok: true, done: null, error: "provider_auth_failed" });
  });

  it("test_parser_error_returns_stream_invalid", async () => {
    stubAnalyzeFetch(() => sseResponse([frame("start", evStart()), frame("nope", {})]));
    expect(await analyzeDocument(req(), noop)).toEqual({ ok: false, code: "stream_invalid" });
  });

  it("test_stream_caps_are_passed_to_the_parser", async () => {
    stubAnalyzeFetch(() => sseResponse(runFrames()));
    const r = await analyzeDocument(req(), noop, undefined, { maxStreamBytes: 200 });
    expect(r).toEqual({ ok: false, code: "stream_invalid" });
  });

  it.each(ANALYZE_ERROR_CODES.map((c) => [c]))(
    "test_refusal_%s_is_returned_as_a_code",
    async (code) => {
      stubAnalyzeFetch(() => jsonResponse(code === "busy" ? 503 : 422, { error: code }));
      expect(await analyzeDocument(req(), noop)).toEqual({ ok: false, code });
    },
  );

  it("test_refusal_is_a_json_reply_and_onEvent_is_never_called", async () => {
    stubAnalyzeFetch(() => jsonResponse(429, { error: "rate_limited" }));
    const spy = vi.fn();
    await analyzeDocument(req(), spy);
    expect(spy).not.toHaveBeenCalled();
  });

  it("test_unknown_refusal_code_and_extra_text_give_unknown", async () => {
    stubAnalyzeFetch(() =>
      jsonResponse(500, { error: "<img src=x onerror=alert(1)>", detail: "secret" }),
    );
    expect(await analyzeDocument(req(), noop)).toEqual({ ok: false, code: "unknown" });
  });

  it("test_non_json_error_body_gives_unknown", async () => {
    stubAnalyzeFetch(() => new Response("boom", { status: 502 }));
    expect(await analyzeDocument(req(), noop)).toEqual({ ok: false, code: "unknown" });
  });

  it("test_200_with_wrong_content_type_gives_unknown", async () => {
    stubAnalyzeFetch(() => jsonResponse(200, evDone()));
    expect(await analyzeDocument(req(), noop)).toEqual({ ok: false, code: "unknown" });
  });

  it("test_fetch_failure_gives_network", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("down"))),
    );
    expect(await analyzeDocument(req(), noop)).toEqual({ ok: false, code: "network" });
  });

  it("test_abort_during_the_stream_gives_aborted_and_cancels_the_body", async () => {
    const live = controlled();
    stubAnalyzeFetch(() => live.response);
    const ac = new AbortController();
    const p = analyzeDocument(req(), noop, ac.signal);
    live.push(frame("start", evStart()));
    await new Promise((r) => setTimeout(r, 10));
    ac.abort();
    expect(await p).toEqual({ ok: false, code: "aborted" });
    expect(live.cancelled()).toBe(true);
  });

  it("test_abort_before_the_reply_gives_aborted", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_u: string, i: RequestInit) =>
          new Promise((_res, rej) => {
            i.signal?.addEventListener("abort", () => rej(new DOMException("x", "AbortError")));
          }),
      ),
    );
    const ac = new AbortController();
    const p = analyzeDocument(req(), noop, ac.signal);
    ac.abort();
    expect(await p).toEqual({ ok: false, code: "aborted" });
  });
});
