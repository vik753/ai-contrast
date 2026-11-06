import { expect, it } from "vitest";
import { setClientTags } from "./clientTags";
import type { TagReply } from "./tagApi";

const topic = (kw: number) => ({
  keyword_clauses: kw,
  model_clauses: 0,
  model_asserted: 0,
  model_tags_dropped: false,
  not_analyzed: null,
});
const reply = (tags: TagReply["tags"], kw = 0): TagReply =>
  ({ tags, topics: { a: topic(kw), b: topic(0) } }) as unknown as TagReply;
const allowed = new Set(["a", "b"]);
const clauses = new Set(["c1", "c2"]);

it("test_set_client_tags_adds_a_selected_topic", () => {
  expect(setClientTags(reply({ c1: [] }), {}, "c1", ["a"], allowed, clauses)).toEqual({
    c1: ["a"],
  });
});
it("test_set_client_tags_refuses_unknown_topic_or_clause", () => {
  expect(setClientTags(reply({}), {}, "c1", ["zzz"], allowed, clauses)).toBeNull();
  expect(setClientTags(reply({}), {}, "c9", ["a"], allowed, clauses)).toBeNull();
});
it("test_set_client_tags_refuses_a_sixth_non_keyword_tag", () => {
  const model = ["t1", "t2", "t3", "t4", "t5"].map((topic_id) => ({
    topic_id,
    source: "model" as const,
  }));
  expect(setClientTags(reply({ c1: model }), {}, "c1", ["a"], allowed, clauses)).toBeNull();
  const four = model.slice(0, 4);
  expect(setClientTags(reply({ c1: four }), {}, "c1", ["a"], allowed, clauses)).toEqual({
    c1: ["a"],
  });
});
it("test_set_client_tags_counts_keyword_clauses_towards_120", () => {
  expect(setClientTags(reply({ c1: [] }, 120), {}, "c1", ["a"], allowed, clauses)).toBeNull();
  expect(setClientTags(reply({ c1: [] }, 119), {}, "c1", ["a"], allowed, clauses)).toEqual({
    c1: ["a"],
  });
  expect(
    setClientTags(reply({ c1: [] }, 119), { c2: ["a"] }, "c1", ["a"], allowed, clauses),
  ).toBeNull();
});
it("test_set_client_tags_always_allows_removal", () => {
  expect(setClientTags(reply({ c1: [] }, 500), { c1: ["a"] }, "c1", [], allowed, clauses)).toEqual(
    {},
  );
});
