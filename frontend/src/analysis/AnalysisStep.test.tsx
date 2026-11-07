/** S9-T4 AC1, AC1a, AC3, AC4 — the analysis step: sequence, progress, stop, provisional results, cache. */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  analyzeCalls,
  controlled,
  evDone,
  evStart,
  evTopic,
  finding,
  frame,
  labelOf,
  runFrames,
  sseResponse,
  stubAnalyzeFetch,
  value,
} from "../test/analysis-fakes";
import {
  D,
  act,
  click,
  docsAB,
  fakeCache,
  marks,
  mountStep,
  noGreen,
  screen,
  setDocs,
  sleep,
  startBtn,
  statusOf,
  stopBtn,
  t,
  vi,
  waitFor,
} from "../test/analysis-harness";
import { jsonResponse } from "../test/provider-fakes";
import { maskedDocsStore } from "../tagging/maskedDocsStore";
import { FREE_MODEL } from "../tagging/estimate";
import { SELECTION } from "../test/tagging-fakes";
import { must } from "../test/topics-fakes";
import { buildAnalysisKey, flagsHash, selectionSignature } from "./cacheKey";

const bodyOf = (c: { body: string | undefined }) =>
  JSON.parse(c.body ?? "{}") as Record<string, unknown>;

beforeEach(() => maskedDocsStore.clearAll());
afterEach(() => {
  maskedDocsStore.clearAll();
  vi.unstubAllGlobals();
});

describe("start and request", () => {
  it("test_region_is_absent_without_tagging_results", async () => {
    await mountStep({ taggingResults: [] });
    expect(screen.queryByRole("region", { name: t("analysis.title") })).toBeNull();
  });

  it("test_start_sends_one_post_per_document_in_order_with_own_tagging_signature", async () => {
    const { calls } = stubAnalyzeFetch();
    setDocs(docsAB());
    await mountStep();
    click();
    await screen.findByTestId("analysis-result");
    await waitFor(() => expect(analyzeCalls(calls)).toHaveLength(2));
    const sent = analyzeCalls(calls);
    expect(sent.map(labelOf)).toEqual(["A", "B"]);
    expect((bodyOf(must(sent[1])).tagging as { signature: string }).signature).toBe("sig-B");
    expect(sent.every((c) => c.method === "POST")).toBe(true);
  });

  it("test_request_uses_the_strong_model_domain_side_and_language", async () => {
    const { calls } = stubAnalyzeFetch();
    setDocs(docsAB());
    await mountStep({
      language: "uk",
      flags: { A: ["not_read_material"] },
      annexLinks: { A: ["c2"] },
    });
    click();
    await waitFor(() => expect(analyzeCalls(calls)).toHaveLength(2));
    const a = bodyOf(must(analyzeCalls(calls)[0]));
    const b = bodyOf(must(analyzeCalls(calls)[1]));
    expect(a).toMatchObject({
      provider: "openai",
      model: "gpt-strong",
      domain: "kasko",
      side: "insured",
      language: "uk",
      flags: ["not_read_material"],
      annex_links: ["c2"],
    });
    expect(b).not.toHaveProperty("flags");
    expect(must(analyzeCalls(calls)[0]).headers.get("X-Provider-Key")).toBe("sk-x");
    expect(JSON.stringify(a)).not.toContain("sk-x");
  });

  it("test_free_mode_sends_the_last_tagging_pass_and_no_model_or_key", async () => {
    const { calls } = stubAnalyzeFetch();
    setDocs(docsAB());
    const { taggingResult } = await import("../test/analysis-fakes");
    await mountStep({
      connection: { provider: "free" },
      taggingResults: [taggingResult("A", D.A, "ap-1"), taggingResult("B", D.B, "ap-2")],
    });
    click();
    await waitFor(() => expect(analyzeCalls(calls).length).toBeGreaterThan(0));
    const c = must(analyzeCalls(calls)[0]);
    expect(c.headers.get("X-Analysis-Pass")).toBe("ap-2");
    expect(c.headers.get("X-Provider-Key")).toBeNull();
    expect(bodyOf(c)).not.toHaveProperty("model");
    expect(bodyOf(c)).not.toHaveProperty("turnstile_token");
  });

  it("test_free_mode_without_a_pass_sends_nothing_and_shows_the_error", async () => {
    const { calls } = stubAnalyzeFetch();
    setDocs(docsAB());
    await mountStep({ connection: { provider: "free" } });
    click();
    expect((await screen.findByRole("alert")).textContent).toContain(
      t("analysis.error.analysis_pass_invalid"),
    );
    expect(analyzeCalls(calls)).toHaveLength(0);
  });

  it("test_tagging_result_with_another_digest_is_not_analyzed", async () => {
    const { calls } = stubAnalyzeFetch();
    setDocs([docsAB()[0] as never]);
    const { taggingResult } = await import("../test/analysis-fakes");
    await mountStep({ taggingResults: [taggingResult("A", "9".repeat(64))] });
    click();
    await sleep(60);
    expect(analyzeCalls(calls)).toHaveLength(0);
  });
});

describe("sequence, progress, stop", () => {
  it("test_second_document_starts_only_after_the_first_stream_ended", async () => {
    const first = controlled();
    const { calls } = stubAnalyzeFetch((c) =>
      c.url === "/api/analyze" && labelOf(c) === "A" ? first.response : undefined,
    );
    setDocs(docsAB());
    await mountStep();
    click();
    await waitFor(() => expect(analyzeCalls(calls)).toHaveLength(1));
    await sleep(60);
    expect(analyzeCalls(calls)).toHaveLength(1);
    expect(statusOf("A")).toContain(t("analysis.status.running"));
    expect(statusOf("B")).toContain(t("analysis.status.pending"));
    for (const f of runFrames()) first.push(f);
    first.close();
    await waitFor(() => expect(analyzeCalls(calls)).toHaveLength(2));
  });

  it("test_progress_events_drive_the_bar_and_topic_status_shows_per_topic", async () => {
    const live = controlled();
    stubAnalyzeFetch(() => live.response);
    setDocs([docsAB()[0] as never]);
    await mountStep({
      taggingResults: [(await import("../test/analysis-fakes")).taggingResult("A", D.A)],
    });
    click();
    live.push(frame("start", evStart()));
    live.push(frame("topic", evTopic("deductible")));
    live.push(frame("topic", evTopic("theft_cover", { state: "not_analyzed", reason: "timeout" })));
    live.push(frame("progress", { done: 3, total: 6 }));
    const bar = await screen.findByRole("progressbar");
    await waitFor(() => expect(bar.getAttribute("aria-valuenow")).toBe("3"));
    expect(bar.getAttribute("aria-valuemax")).toBe("6");
    expect(screen.getByTestId("analysis-bar-A")).toBe(bar);
    expect(screen.getByTestId("analysis-topic-progress-A-deductible").textContent).toContain(
      t("analysis.topic.state.ok"),
    );
    expect(screen.getByTestId("analysis-topic-progress-A-theft_cover").textContent).toContain(
      t("analysis.topic.state.not_analyzed"),
    );
    live.push(frame("done", evDone()));
    live.close();
    await waitFor(() => expect(statusOf("A")).toContain(t("analysis.status.done")));
  });

  it("test_stop_aborts_the_stream_and_sends_no_later_document", async () => {
    const live = controlled();
    const { calls } = stubAnalyzeFetch(() => live.response);
    setDocs(docsAB());
    await mountStep();
    click();
    await waitFor(() => expect(analyzeCalls(calls)).toHaveLength(1));
    live.push(frame("start", evStart()));
    act(() => stopBtn().click());
    expect(must(analyzeCalls(calls)[0]).init.signal?.aborted).toBe(true);
    await sleep(60);
    expect(analyzeCalls(calls)).toHaveLength(1);
    expect(statusOf("A")).toContain(t("analysis.status.stopped"));
    expect(startBtn().disabled).toBe(false);
  });

  it("test_stopped_document_has_no_greens_no_marks_and_no_cache_write", async () => {
    const live = controlled();
    const { store, puts } = fakeCache();
    stubAnalyzeFetch(() => live.response);
    setDocs(docsAB());
    await mountStep({ cacheStore: store, textHashes: { A: "c".repeat(64), B: "d".repeat(64) } });
    click();
    live.push(frame("start", evStart()));
    live.push(frame("topic", evTopic("deductible", { findings: [finding()] })));
    await sleep(30);
    act(() => stopBtn().click());
    live.push(frame("done", evDone()));
    await sleep(60);
    expect(noGreen()).toBeNull();
    expect(marks()).toHaveLength(0);
    expect(puts).toHaveLength(0);
  });

  it("test_refusal_shows_a_translated_alert_and_marks_the_document_failed", async () => {
    stubAnalyzeFetch(() => jsonResponse(422, { error: "tagging_signature_invalid" }));
    setDocs([docsAB()[0] as never]);
    await mountStep({
      taggingResults: [(await import("../test/analysis-fakes")).taggingResult("A", D.A)],
    });
    click();
    expect((await screen.findByRole("alert")).textContent).toBe(
      t("analysis.error.tagging_signature_invalid"),
    );
    expect(statusOf("A")).toContain(t("analysis.status.failed"));
    expect(screen.queryByTestId("analysis-result")).toBeNull();
  });

  it("test_server_text_in_a_refusal_is_never_shown", async () => {
    stubAnalyzeFetch(() => jsonResponse(500, { error: "<b>boom</b>", detail: "SECRET-DETAIL" }));
    setDocs([docsAB()[0] as never]);
    await mountStep({
      taggingResults: [(await import("../test/analysis-fakes")).taggingResult("A", D.A)],
    });
    click();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(t("analysis.error.unknown"));
    expect(document.body.textContent).not.toContain("SECRET-DETAIL");
  });

  it("test_error_event_makes_the_document_failed_with_no_greens_and_no_cache", async () => {
    const { store, puts } = fakeCache();
    stubAnalyzeFetch(() =>
      sseResponse([
        frame("start", evStart()),
        frame("topic", evTopic("deductible", { findings: [finding()] })),
        frame("error", { error: "provider_auth_failed" }),
      ]),
    );
    setDocs([docsAB()[0] as never]);
    await mountStep({
      cacheStore: store,
      textHashes: { A: "c".repeat(64) },
      taggingResults: [(await import("../test/analysis-fakes")).taggingResult("A", D.A)],
    });
    click();
    expect((await screen.findByRole("alert")).textContent).toBe(
      t("analysis.error.provider_auth_failed"),
    );
    expect(noGreen()).toBeNull();
    expect(puts).toHaveLength(0);
  });
});

describe("provisional events (1a)", () => {
  it("test_no_green_and_no_comparison_before_done", async () => {
    const live = controlled();
    stubAnalyzeFetch(() => live.response);
    setDocs([docsAB()[0] as never]);
    await mountStep({
      taggingResults: [(await import("../test/analysis-fakes")).taggingResult("A", D.A)],
    });
    click();
    live.push(frame("start", evStart()));
    live.push(
      frame(
        "topic",
        evTopic("deductible", { findings: [finding({ rating: "green" })], values: [value()] }),
      ),
    );
    live.push(
      frame("other", {
        batch: 0,
        part: 0,
        clauses: ["c3"],
        rated: true,
        reason: null,
        no_issue: ["c3"],
        findings: [],
      }),
    );
    live.push(frame("progress", { done: 2, total: 4 }));
    await screen.findByTestId("analysis-topic-progress-A-deductible");
    await sleep(30);
    expect(noGreen()).toBeNull();
    expect(marks()).toHaveLength(0);
    expect(screen.queryByTestId("analysis-result")).toBeNull();
    expect(statusOf("A")).toContain(t("analysis.status.running"));
  });

  it("test_done_with_signature_shows_the_final_result_and_the_green", async () => {
    stubAnalyzeFetch(() =>
      sseResponse(
        runFrames({ deductible: { findings: [finding({ rating: "green" })] }, theft_cover: {} }),
      ),
    );
    setDocs([docsAB()[0] as never]);
    await mountStep({
      taggingResults: [(await import("../test/analysis-fakes")).taggingResult("A", D.A)],
    });
    click();
    await screen.findByTestId("analysis-result");
    expect(document.querySelector('[data-rating="green"]')).not.toBeNull();
    expect(statusOf("A")).toContain(t("analysis.status.done"));
  });

  it("test_stream_without_done_is_incomplete_no_green_no_marks_no_cache", async () => {
    const { store, puts } = fakeCache();
    stubAnalyzeFetch((c) =>
      c.url === "/api/analyze"
        ? sseResponse(
            runFrames(
              { deductible: { findings: [finding({ rating: "green" })], values: [value()] } },
              { done: null },
            ),
          )
        : undefined,
    );
    setDocs(docsAB());
    await mountStep({ cacheStore: store, textHashes: { A: "c".repeat(64), B: "d".repeat(64) } });
    click();
    await waitFor(() => expect(statusOf("B")).toContain(t("analysis.status.incomplete")));
    expect(statusOf("A")).toContain(t("analysis.status.incomplete"));
    expect(noGreen()).toBeNull();
    expect(marks()).toHaveLength(0);
    expect(puts).toHaveLength(0);
  });

  it("test_one_document_without_done_blocks_comparison_but_the_other_keeps_its_result", async () => {
    const { store, puts } = fakeCache();
    stubAnalyzeFetch((c) =>
      c.url === "/api/analyze"
        ? sseResponse(
            runFrames(
              { deductible: { values: [value()] } },
              { done: labelOf(c) === "A" ? {} : null },
            ),
          )
        : undefined,
    );
    setDocs(docsAB());
    await mountStep({
      cacheStore: store,
      textHashes: { A: "c".repeat(64), B: "d".repeat(64) },
      directions: { "deductible/amount": "lower_better" },
    });
    click();
    await waitFor(() => expect(statusOf("B")).toContain(t("analysis.status.incomplete")));
    expect(statusOf("A")).toContain(t("analysis.status.done"));
    expect(marks()).toHaveLength(0);
    expect(puts).toHaveLength(1);
  });

  it("test_parser_error_mid_stream_gives_failed_and_no_greens", async () => {
    stubAnalyzeFetch(() =>
      sseResponse([
        frame("start", evStart()),
        frame("topic", evTopic("deductible", { findings: [finding()] })),
        frame("bogus", {}),
      ]),
    );
    setDocs([docsAB()[0] as never]);
    await mountStep({
      taggingResults: [(await import("../test/analysis-fakes")).taggingResult("A", D.A)],
    });
    click();
    expect((await screen.findByRole("alert")).textContent).toBe(t("analysis.error.stream_invalid"));
    expect(noGreen()).toBeNull();
  });

  it("test_comparison_marks_show_after_both_documents_are_done", async () => {
    stubAnalyzeFetch((c) =>
      c.url === "/api/analyze"
        ? sseResponse(
            runFrames({
              deductible: {
                values: [
                  value({
                    value: {
                      type: "amount",
                      number: labelOf(c) === "A" ? 5000 : 8000,
                      currency: "UAH",
                    },
                  }),
                ],
              },
            }),
          )
        : undefined,
    );
    setDocs(docsAB());
    await mountStep({ directions: { "deductible/amount": "lower_better" } });
    click();
    await waitFor(() => expect(document.querySelectorAll("[data-mark]")).toHaveLength(2));
    expect(Array.from(marks()).map((m) => m.getAttribute("data-mark"))).toEqual([
      "better",
      "worse",
    ]);
  });

  it("test_onResultsChange_reports_results_only_with_the_complete_flag_set_by_done", async () => {
    const seen: unknown[][] = [];
    stubAnalyzeFetch((c) =>
      c.url === "/api/analyze"
        ? sseResponse(runFrames({ deductible: {} }, { done: labelOf(c) === "A" ? {} : null }))
        : undefined,
    );
    setDocs(docsAB());
    await mountStep({ onResultsChange: (r: readonly unknown[]) => seen.push([...r]) });
    click();
    await waitFor(() => expect(statusOf("B")).toContain(t("analysis.status.incomplete")));
    const last = (seen[seen.length - 1] ?? []) as { label: string; complete: boolean }[];
    expect(last.map((r) => [r.label, r.complete])).toEqual([
      ["A", true],
      ["B", false],
    ]);
  });
});

describe("cache (AC4)", () => {
  async function expectedKey(label: "A" | "B", over: Record<string, unknown> = {}) {
    return buildAnalysisKey({
      documentDigest: D[label],
      contractTextHash: label === "A" ? "c".repeat(64) : "d".repeat(64),
      selectionSignature: await selectionSignature(SELECTION),
      analysisVersion: "av-1",
      domain: "kasko",
      side: "insured",
      model: "gpt-strong",
      language: "en",
      flagsHash: await flagsHash([]),
      ...over,
    });
  }

  it("test_result_is_written_once_per_document_after_done_with_the_full_key", async () => {
    const { store, puts } = fakeCache();
    stubAnalyzeFetch();
    setDocs(docsAB());
    await mountStep({ cacheStore: store, textHashes: { A: "c".repeat(64), B: "d".repeat(64) } });
    click();
    await waitFor(() => expect(puts).toHaveLength(2));
    expect(puts.map((p) => p.kind)).toEqual(["analysis", "analysis"]);
    expect(puts[0]?.key).toBe(await expectedKey("A"));
    expect(puts[1]?.key).toBe(await expectedKey("B"));
  });

  it("test_key_includes_flags_language_and_free_model", async () => {
    const { store, puts } = fakeCache();
    stubAnalyzeFetch();
    setDocs([docsAB()[0] as never]);
    await mountStep({
      cacheStore: store,
      language: "ru",
      connection: { provider: "free" },
      flags: { A: ["hidden_text_removed"] },
      textHashes: { A: "c".repeat(64) },
      taggingResults: [(await import("../test/analysis-fakes")).taggingResult("A", D.A, "ap-1")],
    });
    click();
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]?.key).toBe(
      await expectedKey("A", {
        language: "ru",
        model: FREE_MODEL,
        flagsHash: await flagsHash(["hidden_text_removed"]),
      }),
    );
  });

  it("test_null_contract_text_hash_skips_the_write_but_shows_the_result", async () => {
    const { store, puts } = fakeCache();
    stubAnalyzeFetch();
    setDocs(docsAB());
    await mountStep({ cacheStore: store, textHashes: { A: null } });
    click();
    await screen.findByTestId("analysis-result");
    await waitFor(() => expect(statusOf("B")).toContain(t("analysis.status.done")));
    expect(puts).toHaveLength(0);
  });

  it("test_cached_data_holds_no_clause_text_or_key", async () => {
    const { store, puts } = fakeCache();
    stubAnalyzeFetch();
    setDocs([docsAB()[0] as never]);
    await mountStep({
      cacheStore: store,
      textHashes: { A: "c".repeat(64) },
      taggingResults: [(await import("../test/analysis-fakes")).taggingResult("A", D.A)],
    });
    click();
    await waitFor(() => expect(puts).toHaveLength(1));
    const json = JSON.stringify(puts[0]?.data);
    expect(json).not.toContain("The deductible is 5 percent");
    expect(json).not.toContain("sk-x");
  });

  it("test_refusal_writes_nothing", async () => {
    const { store, puts } = fakeCache();
    stubAnalyzeFetch(() => jsonResponse(429, { error: "rate_limited" }));
    setDocs(docsAB());
    await mountStep({ cacheStore: store, textHashes: { A: "c".repeat(64), B: "d".repeat(64) } });
    click();
    await screen.findByRole("alert");
    await sleep(40);
    expect(puts).toHaveLength(0);
  });
});
