/** S7-T3 AC2 — own topics: memory by default, opt-in localStorage `aic.topics.v1`. */
import { beforeEach, describe, expect, it } from "vitest";
import { topic } from "../test/topics-fakes";
import { createTopicStore } from "./topicStore";
import type { TopicDefinition } from "./types";

const KEY = "aic.topics.v1";
const t = (over: Record<string, unknown> = {}) => topic(over) as unknown as TopicDefinition;
beforeEach(() => localStorage.clear());

describe("topicStore", () => {
  it("test_default_is_memory_only_nothing_written", () => {
    const s = createTopicStore({ storage: localStorage });
    s.add(t());
    expect(s.getTopics()).toHaveLength(1);
    expect(s.isPersisted()).toBe(false);
    expect(localStorage.length).toBe(0);
  });

  it("test_opt_in_writes_topics_only_and_follows_changes", () => {
    const s = createTopicStore({ storage: localStorage });
    s.add(t());
    s.setPersist(true);
    const saved = JSON.parse(localStorage.getItem(KEY) ?? "null") as {
      version: number;
      topics: { title: string }[];
    };
    expect(saved.version).toBe(1);
    expect(saved.topics.map((x) => x.title)).toEqual(["My topic"]);
    s.add(t({ topic_id: "custom_2", title: "Second" }));
    expect(localStorage.getItem(KEY)).toContain("Second");
    s.remove("custom_1");
    expect(localStorage.getItem(KEY)).not.toContain("My topic");
  });

  it("test_opt_out_removes_key_but_keeps_memory", () => {
    const s = createTopicStore({ storage: localStorage });
    s.setPersist(true);
    s.add(t());
    s.setPersist(false);
    expect(localStorage.getItem(KEY)).toBeNull();
    expect(s.getTopics()).toHaveLength(1);
  });

  it("test_clearAll_removes_key_and_memory", () => {
    const s = createTopicStore({ storage: localStorage });
    s.setPersist(true);
    s.add(t());
    s.clearAll();
    expect(localStorage.getItem(KEY)).toBeNull();
    expect(s.getTopics()).toHaveLength(0);
    expect(s.isPersisted()).toBe(false);
  });

  it("test_new_store_loads_valid_saved_topics_and_is_persisted", () => {
    const a = createTopicStore({ storage: localStorage });
    a.setPersist(true);
    a.add(t());
    const b = createTopicStore({ storage: localStorage });
    expect(b.isPersisted()).toBe(true);
    expect(b.getTopics().map((x) => x.title)).toEqual(["My topic"]);
  });

  it("test_corrupt_saved_data_is_ignored_and_removed", () => {
    localStorage.setItem(KEY, '{"version":1,"topics":[{"__proto__":{},"x":1}]}');
    const s = createTopicStore({ storage: localStorage });
    expect(s.getTopics()).toHaveLength(0);
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("test_blocked_storage_never_throws", () => {
    const blocked = {
      getItem: () => {
        throw new Error("x");
      },
      setItem: () => {
        throw new Error("x");
      },
      removeItem: () => {
        throw new Error("x");
      },
    } as unknown as Storage;
    const s = createTopicStore({ storage: blocked });
    expect(() => {
      s.add(t());
      s.setPersist(true);
      s.clearAll();
    }).not.toThrow();
  });

  it("test_subscribe_notifies_on_change", () => {
    const s = createTopicStore({ storage: localStorage });
    let n = 0;
    const off = s.subscribe(() => n++);
    s.add(t());
    off();
    s.add(t({ topic_id: "custom_2" }));
    expect(n).toBe(1);
  });
});
