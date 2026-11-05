/**
 * Own topics (ADR 0017 point 7). Memory by default. `localStorage` key `aic.topics.v1` only
 * after the opt-in. Blocked storage never throws.
 */
import { exportTopics, importTopics } from "./transfer";
import { MAX_OWN_TOPICS, type TopicDefinition } from "./types";

export const TOPICS_STORAGE_KEY = "aic.topics.v1";

export interface TopicStore {
  getTopics: () => readonly TopicDefinition[];
  add: (topic: TopicDefinition) => void;
  update: (topicId: string, topic: TopicDefinition) => void;
  remove: (topicId: string) => void;
  replaceAll: (list: readonly TopicDefinition[]) => void;
  subscribe: (fn: () => void) => () => void;
  isPersisted: () => boolean;
  setPersist: (on: boolean) => void;
  clearAll: () => void;
}

export function createTopicStore({ storage }: { storage?: Storage } = {}): TopicStore {
  let topics: readonly TopicDefinition[] = [];
  let persisted = false;
  const listeners = new Set<() => void>();

  const attempt = (fn: (s: Storage) => void): void => {
    try {
      if (storage) fn(storage);
    } catch {
      // Blocked or full storage: the topics stay in memory.
    }
  };
  const write = (): void => {
    if (persisted)
      attempt((s) => {
        s.setItem(TOPICS_STORAGE_KEY, exportTopics(topics));
      });
  };
  const notify = (): void => {
    for (const fn of [...listeners]) fn();
  };
  const set = (next: readonly TopicDefinition[]): void => {
    topics = next;
    write();
    notify();
  };

  attempt((s) => {
    const raw = s.getItem(TOPICS_STORAGE_KEY);
    if (raw === null) return;
    const result = importTopics(raw);
    if (result.ok) {
      topics = result.topics;
      persisted = true;
    } else {
      s.removeItem(TOPICS_STORAGE_KEY);
    }
  });

  return {
    getTopics: () => topics,
    add(topic) {
      if (topics.length >= MAX_OWN_TOPICS) return;
      set([...topics, topic]);
    },
    update(topicId, topic) {
      set(topics.map((t) => (t.topic_id === topicId ? topic : t)));
    },
    remove(topicId) {
      set(topics.filter((t) => t.topic_id !== topicId));
    },
    replaceAll(list) {
      set(list.slice(0, MAX_OWN_TOPICS));
    },
    subscribe(fn) {
      listeners.add(fn);
      return () => {
        listeners.delete(fn);
      };
    },
    isPersisted: () => persisted,
    setPersist(on) {
      persisted = on;
      if (on) write();
      else {
        attempt((s) => {
          s.removeItem(TOPICS_STORAGE_KEY);
        });
      }
      notify();
    },
    clearAll() {
      topics = [];
      persisted = false;
      attempt((s) => {
        s.removeItem(TOPICS_STORAGE_KEY);
      });
      notify();
    },
  };
}

function browserStorage(): Storage | undefined {
  try {
    return localStorage;
  } catch {
    return undefined;
  }
}

export const topicStore: TopicStore = createTopicStore(
  (() => {
    const storage = browserStorage();
    return storage ? { storage } : {};
  })(),
);
