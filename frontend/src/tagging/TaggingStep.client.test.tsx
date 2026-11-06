/** S8-T3 AC2 — the client may add a tag, never remove a keyword tag; caps and ids are checked. */
import { afterEach, expect, it, vi } from "vitest";
import { jsonResponse } from "../test/provider-fakes";
import { must } from "../test/topics-fakes";
import { stubTagFetch, tagReply } from "../test/tagging-fakes";
import {
  chips,
  clauseEl,
  done,
  fireEvent,
  renderStep,
  start,
  t,
  within,
} from "../test/tagging-step-harness";

afterEach(() => vi.unstubAllGlobals());

const removeName = (topic: string): string => t("tagging.removeTag").replace("{{topic}}", topic);

const addSelect = (c: HTMLElement) =>
  within(c).getByLabelText<HTMLSelectElement>(t("tagging.add.label"));

it("test_client_tag_add_creates_a_client_chip_with_icon_and_text", async () => {
  stubTagFetch();
  const onResultsChange = vi.fn();
  await renderStep({ onResultsChange });
  start();
  const root = await done();
  const c1 = clauseEl(root, "c3");
  fireEvent.change(addSelect(c1), { target: { value: "theft_cover" } });
  fireEvent.click(within(c1).getByRole("button", { name: t("tagging.add.button") }));
  const chip = chips(clauseEl(root, "c3")).find((c) => c.dataset.source === "client");
  expect(chip?.dataset.topicId).toBe("theft_cover");
  expect(chip?.querySelector('[data-source-icon="client"]')).not.toBeNull();
  expect(chip?.textContent).toContain(t("tagging.source.client"));
  const last = onResultsChange.mock.calls.at(-1)?.[0] as { clientTags: unknown }[];
  expect(last[0]?.clientTags).toEqual({ c3: ["theft_cover"] });
});

it("test_client_tag_options_exclude_topics_the_clause_already_has", async () => {
  stubTagFetch();
  await renderStep();
  start();
  const root = await done();
  const values = Array.from(addSelect(clauseEl(root, "c1")).options).map((o) => o.value);
  expect(values).not.toContain("deductible");
  expect(values).toContain("theft_cover");
});

it("test_client_tag_options_offer_only_selected_topic_ids", async () => {
  stubTagFetch();
  await renderStep();
  start();
  const root = await done();
  const values = Array.from(addSelect(clauseEl(root, "c3")).options)
    .map((o) => o.value)
    .filter((v) => v !== "");
  expect(values.sort()).toEqual(["deductible", "theft_cover"]);
});

it("test_keyword_chip_has_no_remove_button", async () => {
  stubTagFetch();
  await renderStep();
  start();
  const root = await done();
  const kw = chips(clauseEl(root, "c1")).find((c) => c.dataset.source === "keyword");
  expect(kw).toBeTruthy();
  expect(within(must(kw)).queryByRole("button")).toBeNull();
  expect(
    within(clauseEl(root, "c1")).queryByRole("button", { name: removeName("Deductible") }),
  ).toBeNull();
});

it("test_model_and_check_chips_have_no_remove_button", async () => {
  stubTagFetch();
  await renderStep();
  start();
  const root = await done();
  const m = chips(clauseEl(root, "c2")).find((c) => c.dataset.source === "model");
  expect(within(must(m)).queryByRole("button")).toBeNull();
});

it("test_client_chip_can_be_removed_again", async () => {
  stubTagFetch();
  await renderStep();
  start();
  const root = await done();
  const c3 = clauseEl(root, "c3");
  fireEvent.change(addSelect(c3), { target: { value: "deductible" } });
  fireEvent.click(within(c3).getByRole("button", { name: t("tagging.add.button") }));
  fireEvent.click(
    within(clauseEl(root, "c3")).getByRole("button", { name: removeName("Deductible") }),
  );
  expect(chips(clauseEl(root, "c3"))).toHaveLength(0);
});

it("test_client_tag_not_offered_for_topic_at_120_keyword_clauses", async () => {
  stubTagFetch(() =>
    jsonResponse(
      200,
      tagReply({
        topics: {
          deductible: {
            keyword_clauses: 120,
            model_clauses: 0,
            model_asserted: 0,
            model_tags_dropped: false,
            not_analyzed: null,
          },
          theft_cover: {
            keyword_clauses: 0,
            model_clauses: 1,
            model_asserted: 1,
            model_tags_dropped: false,
            not_analyzed: null,
          },
        },
      }),
    ),
  );
  await renderStep();
  start();
  const root = await done();
  const values = Array.from(addSelect(clauseEl(root, "c3")).options).map((o) => o.value);
  expect(values).not.toContain("deductible");
  expect(values).toContain("theft_cover");
});

it("test_client_tag_disabled_when_clause_has_five_non_keyword_tags", async () => {
  const many = ["t1", "t2", "t3", "t4", "t5"];
  stubTagFetch(() =>
    jsonResponse(
      200,
      tagReply({
        tags: {
          c1: [{ topic_id: "deductible", source: "keyword" }],
          c2: many.map((id) => ({ topic_id: id, source: "model" })),
          c3: [],
        },
        other: [],
        risk: {},
      }),
    ),
  );
  await renderStep();
  start();
  const root = await done();
  const c2 = clauseEl(root, "c2");
  expect(addSelect(c2).disabled).toBe(true);
  expect(c2.textContent).toContain(t("tagging.add.clauseCap"));
  expect(addSelect(clauseEl(root, "c1")).disabled).toBe(false);
});

it("test_client_chip_remove_button_names_its_topic", async () => {
  stubTagFetch();
  await renderStep();
  start();
  const root = await done();
  const c3 = clauseEl(root, "c3");
  for (const id of ["deductible", "theft_cover"]) {
    fireEvent.change(addSelect(clauseEl(root, "c3")), { target: { value: id } });
    fireEvent.click(within(c3).getByRole("button", { name: t("tagging.add.button") }));
  }
  expect(within(c3).getByRole("button", { name: removeName("Deductible") })).toBeTruthy();
  expect(within(c3).getByRole("button", { name: removeName("Theft cover") })).toBeTruthy();
  expect(within(c3).queryByRole("button", { name: /^remove$/i })).toBeNull();
});
