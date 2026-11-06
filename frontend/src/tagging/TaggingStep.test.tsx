/** S8-T3 AC2 — the "Tag clauses" step: pair, cost, progress, chips, Other, flags, Layer 2. */
import { afterEach, expect, it, vi } from "vitest";
import { jsonResponse } from "../test/provider-fakes";
import { must } from "../test/topics-fakes";
import {
  DIGEST_B,
  SELECTION,
  bodyOf,
  maskedDoc,
  stubTagFetch,
  tagCalls,
  tagReply,
} from "../test/tagging-fakes";
import {
  byId,
  chips,
  clauseEl,
  done,
  renderStep,
  screen,
  start,
  t,
  waitFor,
  within,
} from "../test/tagging-step-harness";

afterEach(() => vi.unstubAllGlobals());

it("test_step_shows_model_pair_and_cost_before_start_and_no_call", async () => {
  const { calls } = stubTagFetch();
  await renderStep();
  const pair = byId("tag-pair").textContent;
  expect(pair).toContain("gpt-cheap");
  expect(pair).toContain("gpt-strong");
  expect(byId("tag-cost").textContent).toMatch(/\d/);
  expect(tagCalls(calls)).toHaveLength(0);
});

it("test_step_free_mode_pair_shows_the_free_model", async () => {
  stubTagFetch();
  await renderStep({ connection: { provider: "free" } });
  expect(byId("tag-pair").textContent).toContain("@cf/openai/gpt-oss-120b");
});

it("test_step_without_selected_topics_disables_start_and_says_why", async () => {
  stubTagFetch();
  await renderStep({ selection: { catalog: [], suggested: [], custom: [] } });
  expect(screen.getByRole<HTMLButtonElement>("button", { name: t("tagging.start") }).disabled).toBe(
    true,
  );
  expect(screen.getByText(t("tagging.noTopics"))).toBeTruthy();
});

it("test_step_sends_domain_and_side_of_the_first_selected_topic", async () => {
  const { calls } = stubTagFetch();
  await renderStep();
  start();
  await done();
  const b = bodyOf(tagCalls(calls)[0] as never);
  expect(b.domain).toBe("kasko");
  expect(b.side).toBe("insured");
  expect(b.topics).toEqual(SELECTION);
});

it("test_step_progress_per_document_pending_running_done", async () => {
  let release: (r: Response) => void = () => undefined;
  stubTagFetch(
    () =>
      new Promise<Response>((r) => {
        release = r;
      }),
  );
  await renderStep({ documents: [maskedDoc("A"), maskedDoc("B", DIGEST_B)] });
  start();
  await waitFor(() =>
    expect(byId("tag-progress-A").textContent).toContain(t("tagging.status.running")),
  );
  expect(byId("tag-progress-B").textContent).toContain(t("tagging.status.pending"));
  release(jsonResponse(200, tagReply()));
  await waitFor(() =>
    expect(byId("tag-progress-A").textContent).toContain(t("tagging.status.done")),
  );
});

it("test_step_tags_documents_one_after_another_one_call_each", async () => {
  const { calls } = stubTagFetch((c) =>
    c.url === "/api/tag" && c.body?.includes('"label":"B"')
      ? jsonResponse(200, tagReply({ digest: DIGEST_B }))
      : undefined,
  );
  await renderStep({ documents: [maskedDoc("A"), maskedDoc("B", DIGEST_B)] });
  start();
  await done("B");
  const labels = tagCalls(calls).map((c) => (bodyOf(c).document as { label: string }).label);
  expect(labels).toEqual(["A", "B"]);
});

it("test_step_chips_show_source_with_icon_and_text_for_each_source", async () => {
  stubTagFetch(() =>
    jsonResponse(
      200,
      tagReply({
        tags: {
          c1: [
            { topic_id: "deductible", source: "keyword" },
            { topic_id: "theft_cover", source: "check" },
          ],
          c2: [{ topic_id: "theft_cover", source: "model" }],
          c3: [],
        },
      }),
    ),
  );
  await renderStep();
  start();
  const root = await done();
  const c1 = chips(clauseEl(root, "c1"));
  expect(c1.map((c) => c.dataset.source).sort()).toEqual(["check", "keyword"]);
  for (const chip of [...c1, ...chips(clauseEl(root, "c2"))]) {
    const source = must(chip.dataset.source);
    expect(chip.querySelector(`[data-source-icon="${source}"]`)).not.toBeNull();
    expect(chip.textContent).toContain(t(`tagging.source.${source}`));
  }
  expect(chips(clauseEl(root, "c1"))[0]?.textContent).toMatch(/Deductible|Theft cover/);
});

it("test_step_other_lists_clauses_with_risk_marks_on_the_span", async () => {
  stubTagFetch();
  await renderStep();
  start();
  await done();
  const other = byId("tag-other-A");
  expect(other.textContent).toContain(t("tagging.other.heading"));
  const c3 = clauseEl(other, "c3");
  const mark = c3.querySelector("mark[data-risk]");
  expect(mark?.textContent).toBe(
    "1.3. The insurer may terminate the contract unilaterally.".slice(9, 18),
  );
  expect(c3.textContent).toContain(t("tagging.risk.label"));
  expect(other.querySelector('[data-clause-id="c1"]')).toBeNull();
});

it("test_step_topic_counts_and_dropped_flag_are_shown_as_messages", async () => {
  stubTagFetch(() =>
    jsonResponse(
      200,
      tagReply({
        topics: {
          deductible: {
            keyword_clauses: 1,
            model_clauses: 0,
            model_asserted: 61,
            model_tags_dropped: true,
            not_analyzed: null,
          },
          theft_cover: {
            keyword_clauses: 121,
            model_clauses: 0,
            model_asserted: 0,
            model_tags_dropped: false,
            not_analyzed: "too_many_clauses",
          },
        },
      }),
    ),
  );
  await renderStep();
  start();
  await done();
  expect(byId("tag-topic-A-deductible").textContent).toContain(
    t("tagging.flag.model_tags_dropped"),
  );
  expect(byId("tag-topic-A-theft_cover").textContent).toContain(
    t("tagging.flag.not_analyzed.too_many_clauses"),
  );
  expect(byId("tag-topic-A-theft_cover").textContent).not.toContain("too_many_clauses");
  expect(byId("tag-topic-A-theft_cover").textContent).toContain("121");
});

it("test_step_unflagged_topic_shows_no_flag_message", async () => {
  stubTagFetch();
  await renderStep();
  start();
  await done();
  expect(byId("tag-topic-A-deductible").textContent).not.toContain(
    t("tagging.flag.model_tags_dropped"),
  );
});

it.each(["bad_output", "timeout", "quota", "check_failed", "clause_cap"])(
  "test_step_incomplete_reason_%s_is_a_message_not_a_code",
  async (reason) => {
    stubTagFetch(() =>
      jsonResponse(200, tagReply({ model_tagging_incomplete: true, incomplete_reasons: [reason] })),
    );
    await renderStep();
    start();
    await done();
    const el = byId("tag-incomplete-A");
    expect(el.textContent).toContain(t(`tagging.incomplete.${reason}`));
    expect(el.textContent).not.toContain(reason);
  },
);

it("test_step_complete_tagging_shows_no_incomplete_notice", async () => {
  stubTagFetch();
  await renderStep();
  start();
  await done();
  expect(screen.queryByTestId("tag-incomplete-A")).toBeNull();
});

it("test_step_missing_topics_are_listed_by_name", async () => {
  stubTagFetch(() => jsonResponse(200, tagReply({ missing_topics: ["theft_cover"] })));
  await renderStep();
  start();
  await done();
  const el = byId("tag-missing-A");
  expect(el.textContent).toContain(t("tagging.missing.heading"));
  expect(el.textContent).toContain("Theft cover");
});

it("test_step_layer2_hits_shown_per_clause_as_text_labels", async () => {
  stubTagFetch(() =>
    jsonResponse(
      200,
      tagReply({
        layer2: {
          c1: { text: [[0, 4, "heuristic"]], heading: [] },
          c2: { text: [], heading: [[0, 4, "high"]] },
        },
      }),
    ),
  );
  await renderStep();
  start();
  const root = await done();
  const h = clauseEl(root, "c1").querySelector('[data-layer2="heuristic"]');
  const hi = clauseEl(root, "c2").querySelector('[data-layer2="high"]');
  expect(h?.textContent).toContain(t("tagging.layer2.heuristic"));
  expect(hi?.textContent).toContain(t("tagging.layer2.high"));
  expect(clauseEl(root, "c3").querySelector("[data-layer2]")).toBeNull();
});

it("test_step_signature_and_version_are_kept_with_the_result", async () => {
  stubTagFetch();
  const onResultsChange = vi.fn();
  await renderStep({ onResultsChange });
  start();
  await done();
  const last = onResultsChange.mock.calls.at(-1)?.[0] as Record<string, unknown>[];
  expect(last[0]).toMatchObject({
    label: "A",
    digest: "a".repeat(64),
    taggingVersion: "tv-1",
    signature: "sig-abc",
    clientTags: {},
  });
});

it("test_step_digest_mismatch_shows_error_and_no_result", async () => {
  stubTagFetch(() => jsonResponse(200, tagReply({ digest: DIGEST_B })));
  await renderStep();
  start();
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain(t("tagging.error.digest_mismatch"));
  expect(screen.queryByTestId("tag-result-A")).toBeNull();
});

it.each([
  [422, "keyword_budget_exceeded"],
  [422, "document_too_large_for_tagging"],
  [403, "analysis_pass_expired"],
  [403, "analysis_pass_exhausted"],
  [429, "free_quota_exhausted"],
  [503, "busy"],
  [429, "rate_limited"],
  [401, "provider_auth_failed"],
])("test_step_error_%s_%s_is_an_i18n_message", async (status, code) => {
  stubTagFetch(() => jsonResponse(status, { error: code }));
  await renderStep();
  start();
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain(t(`tagging.error.${code}`));
  expect(alert.textContent).not.toContain(code);
  expect(byId("tag-progress-A").textContent).toContain(t("tagging.status.failed"));
});

it("test_step_keyword_budget_error_shows_no_chips_and_no_result", async () => {
  stubTagFetch(() => jsonResponse(422, { error: "keyword_budget_exceeded" }));
  await renderStep();
  start();
  await screen.findByRole("alert");
  expect(screen.queryByTestId("tag-result-A")).toBeNull();
  expect(document.querySelectorAll("[data-source]")).toHaveLength(0);
});

it("test_step_renders_clause_and_reply_text_as_plain_text", async () => {
  const evil = "<img src=x onerror=alert(1)> <script>alert(2)</script> [link](https://evil.test)";
  stubTagFetch(() => jsonResponse(200, tagReply({ risk: {} })));
  await renderStep({ documents: [maskedDoc("A", undefined, [evil, "ok", "ok"])] });
  start();
  const root = await done();
  expect(root.querySelector("img, script, a, iframe")).toBeNull();
  expect(clauseEl(root, "c1").textContent).toContain(evil);
});

it("test_step_with_no_documents_renders_no_region", async () => {
  stubTagFetch();
  await renderStep({ documents: [] });
  expect(screen.queryByRole("region", { name: t("tagging.title") })).toBeNull();
  expect(within(document.body).queryByTestId("tag-pair")).toBeNull();
});
