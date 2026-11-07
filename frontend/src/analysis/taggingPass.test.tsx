/** S9-T4 — TaggingStep passes the free analysis pass on to the analysis step. */
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { jsonResponse } from "../test/provider-fakes";
import { maskedDoc, stubTagFetch, tagReply } from "../test/tagging-fakes";
import { done, renderStep, start } from "../test/tagging-step-harness";
import { maskedDocsStore } from "../tagging/maskedDocsStore";

beforeEach(() => maskedDocsStore.clearAll());
afterEach(() => vi.unstubAllGlobals());

it("test_tagging_result_carries_the_analysis_pass_in_free_mode", async () => {
  stubTagFetch((c) =>
    c.url === "/api/tag" ? jsonResponse(200, tagReply({ analysis_pass: "ap-9" })) : undefined,
  );
  const seen: { analysisPass?: string }[][] = [];
  await renderStep({
    connection: { provider: "free" },
    turnstileToken: "tok",
    documents: [maskedDoc("A")],
    onResultsChange: (r) => seen.push([...(r as { analysisPass?: string }[])]),
  });
  start();
  await done("A");
  const last = seen[seen.length - 1] ?? [];
  expect(last[0]?.analysisPass).toBe("ap-9");
});
