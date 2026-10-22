/**
 * S4-T2 AC1, AC2, AC4, AC5 — CacheStore contract suite.
 *
 * INJECTION POINTS (the developer must follow these module paths and shapes):
 *   src/storage/cacheStore.ts          types: CacheStore, CacheKey (string), CacheKind ("analysis"),
 *                                      PutResult, CacheHit<T> ({ data: T; createdAt: number; lastUsedAt: number }),
 *                                      CacheEntryMeta
 *   src/storage/memoryCacheStore.ts    export class MemoryCacheStore { constructor(opts: { clock: () => number }) }
 *   src/storage/disabledCacheStore.ts  export class DisabledCacheStore { constructor() }
 *   src/storage/indexedDbCacheStore.ts export class IndexedDbCacheStore {
 *                                        constructor(opts: { factory: IDBFactory; clock: () => number;
 *                                                            storage: Pick<Storage, "getItem"> }) }
 *     `clock` returns epoch milliseconds. `storage` is where `aic.history` is read.
 *   The same contract runs on Memory and IndexedDb. Time never comes from Date.now() directly.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { DisabledCacheStore } from "./disabledCacheStore";
import { IndexedDbCacheStore } from "./indexedDbCacheStore";
import { MemoryCacheStore } from "./memoryCacheStore";
import type { CacheStore } from "./cacheStore";
import { freshFactory, memoryStorage } from "../test/idb-helpers";

const DAY = 24 * 60 * 60 * 1000;
const T0 = Date.UTC(2026, 9, 22, 12, 0, 0);
const MIB2 = 2 * 1024 * 1024;

const key = (n: number): string => n.toString(16).padStart(64, "0");
const anyData = (d: unknown): d is unknown => d === d || true;
const isObj = (d: unknown): d is { v: number } =>
  typeof d === "object" && d !== null && typeof (d as { v?: unknown }).v === "number";

interface Env {
  store: CacheStore;
  time: { now: number };
}

const makers: [string, () => Env][] = [
  [
    "MemoryCacheStore",
    () => {
      const time = { now: T0 };
      return { time, store: new MemoryCacheStore({ clock: () => time.now }) };
    },
  ],
  [
    "IndexedDbCacheStore",
    () => {
      const time = { now: T0 };
      const store = new IndexedDbCacheStore({
        factory: freshFactory(),
        clock: () => time.now,
        storage: memoryStorage({ "aic.history": "on" }),
      });
      return { time, store };
    },
  ],
];

describe.each(makers)("CacheStore contract: %s", (_name, make) => {
  let env: Env;
  beforeEach(() => {
    env = make();
  });

  it("test_get_unknown_key_returns_null", async () => {
    expect(await env.store.get(key(1), anyData)).toBeNull();
  });

  it("test_put_then_get_returns_equal_data", async () => {
    expect(await env.store.put(key(1), "analysis", { v: 7, s: "ä" })).toBe("stored");
    const hit = await env.store.get(key(1), anyData);
    expect(hit?.data).toEqual({ v: 7, s: "ä" });
  });

  it("test_get_updates_last_used_at_on_hit", async () => {
    await env.store.put(key(1), "analysis", { v: 1 });
    env.time.now = T0 + 5 * DAY;
    await env.store.get(key(1), anyData);
    const [meta] = await env.store.list();
    expect(meta?.createdAt).toBe(T0);
    expect(meta?.lastUsedAt).toBe(T0 + 5 * DAY);
  });

  it("test_put_same_key_replaces_entry", async () => {
    await env.store.put(key(1), "analysis", { v: 1 });
    await env.store.put(key(1), "analysis", { v: 2 });
    expect((await env.store.list()).length).toBe(1);
    expect((await env.store.get(key(1), isObj))?.data).toEqual({ v: 2 });
  });

  it("test_list_returns_newest_first_with_meta_fields", async () => {
    await env.store.put(key(1), "analysis", { v: 1 });
    env.time.now = T0 + DAY;
    await env.store.put(key(2), "analysis", { v: 2 });
    const list = await env.store.list();
    expect(list.map((m) => m.key)).toEqual([key(2), key(1)]);
    expect(list[0]).toMatchObject({ kind: "analysis", createdAt: T0 + DAY, lastUsedAt: T0 + DAY });
    expect(list[0]?.size).toBe(new TextEncoder().encode(JSON.stringify({ v: 2 })).length);
  });

  it("test_get_validator_false_deletes_entry_and_returns_null", async () => {
    await env.store.put(key(1), "analysis", { v: 1 });
    const never = (d: unknown): d is never => typeof d === "symbol";
    expect(await env.store.get(key(1), never)).toBeNull();
    expect(await env.store.list()).toEqual([]);
  });

  it("test_delete_removes_only_that_key", async () => {
    await env.store.put(key(1), "analysis", { v: 1 });
    await env.store.put(key(2), "analysis", { v: 2 });
    await env.store.delete(key(1));
    expect((await env.store.list()).map((m) => m.key)).toEqual([key(2)]);
  });

  it("test_clear_removes_all_entries", async () => {
    await env.store.put(key(1), "analysis", { v: 1 });
    await env.store.put(key(2), "analysis", { v: 2 });
    await env.store.clear();
    expect(await env.store.list()).toEqual([]);
  });

  it("test_entry_one_ms_before_90_days_is_returned", async () => {
    await env.store.put(key(1), "analysis", { v: 1 });
    env.time.now = T0 + 90 * DAY - 1;
    expect((await env.store.get(key(1), isObj))?.data).toEqual({ v: 1 });
  });

  it("test_entry_exactly_90_days_old_is_expired_and_deleted", async () => {
    await env.store.put(key(1), "analysis", { v: 1 });
    env.time.now = T0 + 90 * DAY;
    expect(await env.store.get(key(1), isObj)).toBeNull();
    env.time.now = T0;
    expect(await env.store.list()).toEqual([]);
  });

  it("test_use_does_not_extend_retention", async () => {
    await env.store.put(key(1), "analysis", { v: 1 });
    env.time.now = T0 + 60 * DAY;
    await env.store.get(key(1), isObj);
    env.time.now = T0 + 90 * DAY;
    expect(await env.store.get(key(1), isObj)).toBeNull();
  });

  it("test_list_never_returns_expired_entries", async () => {
    await env.store.put(key(1), "analysis", { v: 1 });
    env.time.now = T0 + 91 * DAY;
    expect(await env.store.list()).toEqual([]);
  });

  it("test_purge_expired_returns_count_and_keeps_fresh", async () => {
    await env.store.put(key(1), "analysis", { v: 1 });
    await env.store.put(key(2), "analysis", { v: 2 });
    env.time.now = T0 + 89 * DAY;
    await env.store.put(key(3), "analysis", { v: 3 });
    env.time.now = T0 + 90 * DAY;
    expect(await env.store.purgeExpired()).toBe(2);
    expect((await env.store.list()).map((m) => m.key)).toEqual([key(3)]);
  });

  it("test_put_exactly_2_mib_json_is_stored", async () => {
    const data = "a".repeat(MIB2 - 2); // JSON adds two quote characters
    expect(await env.store.put(key(1), "analysis", data)).toBe("stored");
    expect((await env.store.list())[0]?.size).toBe(MIB2);
  });

  it("test_put_one_byte_over_2_mib_is_too_large_and_not_stored", async () => {
    expect(await env.store.put(key(1), "analysis", "a".repeat(MIB2 - 1))).toBe("too_large");
    expect(await env.store.list()).toEqual([]);
  });

  it("test_put_limit_counts_utf8_bytes_not_characters", async () => {
    // 1 048 576 two-byte characters are below 2 MiB in characters but above in bytes.
    expect(await env.store.put(key(1), "analysis", "é".repeat(1024 * 1024))).toBe("too_large");
    expect(await env.store.put(key(2), "analysis", "é".repeat(1024 * 1024 - 1))).toBe("stored");
  });

  it("test_too_large_put_keeps_existing_entry_for_same_key", async () => {
    await env.store.put(key(1), "analysis", { v: 1 });
    expect(await env.store.put(key(1), "analysis", "a".repeat(MIB2))).toBe("too_large");
    expect((await env.store.get(key(1), isObj))?.data).toEqual({ v: 1 });
  });

  it("test_put_unserializable_data_returns_failed", async () => {
    const circular: Record<string, unknown> = {};
    circular.self = circular;
    expect(await env.store.put(key(1), "analysis", circular)).toBe("failed");
    expect(await env.store.put(key(2), "analysis", { n: 10n })).toBe("failed");
    expect(await env.store.list()).toEqual([]);
  });

  it("test_put_101st_entry_evicts_least_recently_used", async () => {
    for (let i = 0; i < 100; i++) {
      env.time.now = T0 + i * 1000;
      await env.store.put(key(i), "analysis", { v: i });
    }
    // Use the oldest entry: key(1) becomes the least recently used one.
    env.time.now = T0 + 200_000;
    await env.store.get(key(0), isObj);
    env.time.now = T0 + 300_000;
    expect(await env.store.put(key(100), "analysis", { v: 100 })).toBe("stored");
    const keys = (await env.store.list()).map((m) => m.key);
    expect(keys.length).toBe(100);
    expect(keys).not.toContain(key(1));
    expect(keys).toContain(key(0));
    expect(keys).toContain(key(100));
  });

  it("test_put_over_existing_key_at_100_entries_evicts_nothing", async () => {
    for (let i = 0; i < 100; i++) {
      await env.store.put(key(i), "analysis", { v: i });
    }
    await env.store.put(key(5), "analysis", { v: 555 });
    expect((await env.store.list()).length).toBe(100);
  });
});

describe("DisabledCacheStore", () => {
  it("test_disabled_store_keeps_nothing_and_misses", async () => {
    const store = new DisabledCacheStore();
    expect(await store.put(key(1), "analysis", { v: 1 })).toBe("disabled");
    expect(await store.get(key(1), anyData)).toBeNull();
    expect(await store.list()).toEqual([]);
    expect(await store.purgeExpired()).toBe(0);
    await expect(store.delete(key(1))).resolves.toBeUndefined();
    await expect(store.clear()).resolves.toBeUndefined();
  });
});
