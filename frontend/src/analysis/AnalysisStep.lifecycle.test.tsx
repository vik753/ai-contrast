/** S9-T4 AC1 — Clear all aborts streams, drops results, ignores late replies. */
import { afterEach, beforeEach, expect, it } from "vitest";
import { clearAllData } from "../storage/historySetting";
import {
  analyzeCalls,
  controlled,
  evStart,
  frame,
  labelOf,
  runFrames,
  sseResponse,
  stubAnalyzeFetch,
} from "../test/analysis-fakes";
import {
  D,
  act,
  click,
  docsAB,
  fakeCache,
  mountStep,
  noGreen,
  screen,
  setDocs,
  sleep,
  startBtn,
  statusOf,
  t,
  vi,
  waitFor,
} from "../test/analysis-harness";
import { maskedDocsStore } from "../tagging/maskedDocsStore";
import { maskedDoc } from "../test/tagging-fakes";
import { must } from "../test/topics-fakes";
import type { Captured } from "../test/provider-fakes";

beforeEach(() => maskedDocsStore.clearAll());
afterEach(() => {
  maskedDocsStore.clearAll();
  vi.unstubAllGlobals();
});

it("test_clear_all_aborts_the_open_stream_and_sends_nothing_more", async () => {
  const live = controlled();
  const { calls } = stubAnalyzeFetch(() => live.response);
  setDocs(docsAB());
  await mountStep();
  click();
  await waitFor(() => expect(analyzeCalls(calls)).toHaveLength(1));
  await act(async () => {
    await clearAllData();
  });
  expect(analyzeCalls(calls)[0]?.init.signal?.aborted).toBe(true);
  live.push(frame("start", evStart()));
  await sleep(60);
  expect(analyzeCalls(calls)).toHaveLength(1);
});

it("test_clear_all_drops_results_and_status_for_the_same_label_and_digest", async () => {
  stubAnalyzeFetch();
  setDocs(docsAB());
  await mountStep();
  click();
  await screen.findByTestId("analysis-result");
  await waitFor(() => expect(statusOf("B")).toContain(t("analysis.status.done")));
  await act(async () => {
    await clearAllData();
  });
  setDocs(docsAB());
  await screen.findByRole("button", { name: t("analysis.start") });
  expect(screen.queryByTestId("analysis-result")).toBeNull();
  expect(startBtn().disabled).toBe(false);
  const s = screen.queryByTestId("analysis-progress-A")?.textContent ?? "";
  for (const k of ["running", "done", "incomplete", "failed", "stopped"])
    expect(s).not.toContain(t(`analysis.status.${k}`));
});

it("test_reply_that_arrives_after_clear_all_is_ignored_and_not_cached", async () => {
  const { store, puts } = fakeCache();
  let release: (r: Response) => void = () => undefined;
  const { calls } = stubAnalyzeFetch((c: Captured) =>
    c.url === "/api/analyze"
      ? new Promise<Response>((res) => {
          release = res; // the reply is not tied to the abort signal: it arrives late
        })
      : undefined,
  );
  const seen: unknown[][] = [];
  setDocs(docsAB());
  await mountStep({
    cacheStore: store,
    textHashes: { A: "c".repeat(64), B: "d".repeat(64) },
    onResultsChange: (r: readonly unknown[]) => seen.push([...r]),
  });
  click();
  await waitFor(() => expect(analyzeCalls(calls)).toHaveLength(1));
  await act(async () => {
    await clearAllData();
  });
  setDocs(docsAB());
  act(() => release(sseResponse(runFrames())));
  await sleep(80);
  expect(screen.queryByTestId("analysis-result")).toBeNull();
  expect(noGreen()).toBeNull();
  expect(puts).toHaveLength(0);
  expect(analyzeCalls(calls)).toHaveLength(1);
  expect(seen.filter((r) => r.length > 0).length).toBe(0);
});

it("test_events_pushed_after_clear_all_are_not_rendered_or_cached", async () => {
  const live = controlled();
  const { store, puts } = fakeCache();
  stubAnalyzeFetch(() => live.response);
  setDocs(docsAB());
  await mountStep({ cacheStore: store, textHashes: { A: "c".repeat(64) } });
  click();
  live.push(frame("start", evStart()));
  await sleep(30);
  await act(async () => {
    await clearAllData();
  });
  setDocs(docsAB());
  for (const f of runFrames()) live.push(f);
  live.close();
  await sleep(80);
  expect(screen.queryByTestId("analysis-result")).toBeNull();
  expect(puts).toHaveLength(0);
});

it("test_start_after_clear_all_works_without_stale_state", async () => {
  const live = controlled();
  let first = true;
  const { calls } = stubAnalyzeFetch((c) => {
    if (c.url !== "/api/analyze") return undefined;
    if (first) {
      first = false;
      return live.response;
    }
    return sseResponse(runFrames());
  });
  setDocs([maskedDoc("A", D.A)]);
  const { taggingResult } = await import("../test/analysis-fakes");
  await mountStep({ taggingResults: [taggingResult("A", D.A)] });
  click();
  await waitFor(() => expect(analyzeCalls(calls)).toHaveLength(1));
  await act(async () => {
    await clearAllData();
  });
  setDocs([maskedDoc("A", D.A)]);
  await sleep(30);
  click();
  await screen.findByTestId("analysis-result");
  expect(analyzeCalls(calls)).toHaveLength(2);
  expect(labelOf(must(analyzeCalls(calls)[1]))).toBe("A");
});

it("test_removed_document_is_not_sent_after_removal", async () => {
  const live = controlled();
  const { calls } = stubAnalyzeFetch((c) =>
    c.url === "/api/analyze" && labelOf(c) === "A" ? live.response : undefined,
  );
  setDocs(docsAB());
  await mountStep();
  click();
  await waitFor(() => expect(analyzeCalls(calls)).toHaveLength(1));
  act(() => maskedDocsStore.remove("B"));
  for (const f of runFrames()) live.push(f);
  live.close();
  await sleep(80);
  expect(analyzeCalls(calls).map(labelOf)).toEqual(["A"]);
});
