/**
 * S4-T2 AC2, AC3, AC5, AC6a, AC10 — IndexedDbCacheStore specifics.
 * Injection points: see cacheStore.contract.test.ts. Additionally:
 *   - the store reads `aic.history` from the injected `storage` (getItem only), before it
 *     opens the database, before every put, and inside onupgradeneeded;
 *   - the store calls only `factory.open`, `factory.deleteDatabase` (never globals);
 *   - database `aic-cache`, object store `entries`, key path `key`, index `lastUsedAt`;
 *   - record shape { key, schema: 1, kind: "analysis", createdAt, lastUsedAt, size, json }.
 */
import { IDBObjectStore } from "fake-indexeddb";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IndexedDbCacheStore } from "./indexedDbCacheStore";
import {
  databaseNames,
  DB_NAME,
  freshFactory,
  memoryStorage,
  rawEntries,
  rawPut,
  STORE_NAME,
} from "../test/idb-helpers";

const DAY = 24 * 60 * 60 * 1000;
const T0 = Date.UTC(2026, 9, 22, 12, 0, 0);
const key = (n: number): string => n.toString(16).padStart(64, "0");
const anyData = (d: unknown): d is unknown => d !== undefined;

function setup(history: "on" | null = "on") {
  const factory = freshFactory();
  const storage = memoryStorage(history === null ? {} : { "aic.history": history });
  const time = { now: T0 };
  const make = () => new IndexedDbCacheStore({ factory, clock: () => time.now, storage });
  return { factory, storage, time, make, store: make() };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("record layout (AC1, AC2)", () => {
  it("test_put_writes_record_with_json_string_schema_1_and_size", async () => {
    const { factory, store } = setup();
    await store.put(key(1), "analysis", { v: "é" });
    const [rec] = await rawEntries(factory);
    const json = JSON.stringify({ v: "é" });
    expect(rec).toEqual({
      key: key(1),
      schema: 1,
      kind: "analysis",
      createdAt: T0,
      lastUsedAt: T0,
      size: new TextEncoder().encode(json).length,
      json,
    });
  });

  it("test_database_has_entries_store_with_last_used_at_index", async () => {
    const { factory, store } = setup();
    await store.put(key(1), "analysis", { v: 1 });
    const db = await new Promise<IDBDatabase>((resolve) => {
      const r = factory.open(DB_NAME);
      r.onsuccess = () => {
        resolve(r.result);
      };
    });
    try {
      expect(db.version).toBe(1);
      const os = db.transaction(STORE_NAME, "readonly").objectStore(STORE_NAME);
      expect(os.keyPath).toBe("key");
      expect([...os.indexNames]).toContain("lastUsedAt");
    } finally {
      db.close();
    }
  });
});

describe("validation on read (AC3)", () => {
  const bad: [string, Record<string, unknown>][] = [
    ["unknown_schema", { schema: 2 }],
    ["unknown_kind", { kind: "other" }],
    ["created_at_nan", { createdAt: Number.NaN }],
    ["created_at_string", { createdAt: "x" }],
    ["created_at_infinite", { createdAt: Number.POSITIVE_INFINITY }],
    ["last_used_at_not_number", { lastUsedAt: "x" }],
    ["created_at_more_than_a_day_in_future", { createdAt: T0 + DAY + 1000 }],
    ["last_used_at_more_than_a_day_in_future", { lastUsedAt: T0 + 2 * DAY }],
    ["size_mismatch", { size: 3 }],
    ["json_not_a_string", { json: { v: 1 } }],
    ["json_unparseable", { json: "{not json", size: 9 }],
  ];

  it.each(bad)("test_corrupt_entry_%s_is_deleted_and_get_returns_null", async (_n, patch) => {
    const { factory, store } = setup();
    await store.put(key(1), "analysis", { v: 1 });
    const [rec] = await rawEntries(factory);
    await rawPut(factory, { ...rec, ...patch });
    expect(await store.get(key(1), anyData)).toBeNull();
    expect(await rawEntries(factory)).toEqual([]);
  });

  it("test_timestamp_up_to_one_day_in_future_is_accepted", async () => {
    const { factory, store } = setup();
    await store.put(key(1), "analysis", { v: 1 });
    const [rec] = await rawEntries(factory);
    await rawPut(factory, { ...rec, lastUsedAt: T0 + DAY });
    expect((await store.get(key(1), anyData))?.data).toEqual({ v: 1 });
  });
});

describe("failure handling (AC5)", () => {
  it("test_quota_error_on_put_returns_storage_full_and_leaves_no_entry", async () => {
    const { factory, store } = setup();
    vi.spyOn(IDBObjectStore.prototype, "put").mockImplementation(() => {
      throw new DOMException("quota", "QuotaExceededError");
    });
    expect(await store.put(key(1), "analysis", { v: 1 })).toBe("storage_full");
    vi.restoreAllMocks();
    expect(await rawEntries(factory)).toEqual([]);
  });

  it("test_other_transaction_error_returns_failed_and_leaves_no_entry", async () => {
    const { factory, store } = setup();
    vi.spyOn(IDBObjectStore.prototype, "put").mockImplementation(() => {
      throw new DOMException("boom", "UnknownError");
    });
    expect(await store.put(key(1), "analysis", { v: 1 })).toBe("failed");
    vi.restoreAllMocks();
    expect(await rawEntries(factory)).toEqual([]);
  });

  it("test_failed_put_at_101_entries_does_not_evict_in_separate_transaction", async () => {
    const { factory, store, time } = setup();
    for (let i = 0; i < 100; i++) {
      time.now = T0 + i;
      await store.put(key(i), "analysis", { v: i });
    }
    vi.spyOn(IDBObjectStore.prototype, "put").mockImplementation(() => {
      throw new DOMException("quota", "QuotaExceededError");
    });
    time.now = T0 + 1000;
    expect(await store.put(key(100), "analysis", { v: 100 })).toBe("storage_full");
    vi.restoreAllMocks();
    const keys = (await rawEntries(factory)).map((r) => r.key);
    expect(keys.length).toBe(100);
    expect(keys).toContain(key(0));
    expect(keys).not.toContain(key(100));
  });
});

describe("history off writes nothing (AC6, AC6a)", () => {
  it.each([null, "off", "true", "ON", ""])(
    "test_put_with_history_value_%s_returns_disabled_and_creates_no_database",
    async (value) => {
      const { factory } = setup(null);
      const storage = memoryStorage(value === null ? {} : { "aic.history": value });
      const s = new IndexedDbCacheStore({ factory, clock: () => T0, storage });
      const open = vi.spyOn(factory, "open");
      expect(await s.put(key(1), "analysis", { v: 1 })).toBe("disabled");
      expect(await s.get(key(1), anyData)).toBeNull();
      expect(await s.list()).toEqual([]);
      expect(open).not.toHaveBeenCalled();
      expect(await databaseNames(factory)).toEqual([]);
    },
  );

  it("test_storage_read_error_is_treated_as_off", async () => {
    const factory = freshFactory();
    const storage = {
      getItem: () => {
        throw new DOMException("denied", "SecurityError");
      },
    };
    const s = new IndexedDbCacheStore({ factory, clock: () => T0, storage });
    expect(await s.put(key(1), "analysis", { v: 1 })).toBe("disabled");
    expect(await databaseNames(factory)).toEqual([]);
  });

  it("test_put_does_not_touch_local_or_session_storage", async () => {
    const { store } = setup();
    const before = [localStorage.length, sessionStorage.length];
    await store.put(key(1), "analysis", { v: 1 });
    expect([localStorage.length, sessionStorage.length]).toEqual(before);
  });
});

describe("two tabs on one IDBFactory (AC6a)", () => {
  it("test_tab_b_put_after_tab_a_turned_history_off_returns_disabled_and_no_database", async () => {
    const { factory, storage, make } = setup();
    const tabA = make();
    const tabB = make();
    expect(await tabA.put(key(1), "analysis", { v: 1 })).toBe("stored");
    expect(await tabB.put(key(2), "analysis", { v: 2 })).toBe("stored");
    // Tab A: history off = remove the key first, then delete the database.
    storage.removeItem("aic.history");
    await new Promise<void>((resolve, reject) => {
      const r = factory.deleteDatabase(DB_NAME);
      r.onsuccess = () => {
        resolve();
      };
      r.onerror = () => {
        reject(new Error("delete failed"));
      };
    });
    expect(await tabB.put(key(3), "analysis", { v: 3 })).toBe("disabled");
    expect(await databaseNames(factory)).toEqual([]);
  });

  it("test_connection_closed_by_versionchange_is_never_reopened_by_that_instance", async () => {
    const { factory, storage, make } = setup();
    const tabB = make();
    await tabB.put(key(1), "analysis", { v: 1 });
    storage.removeItem("aic.history");
    await new Promise<void>((resolve) => {
      const r = factory.deleteDatabase(DB_NAME);
      r.onsuccess = () => {
        resolve();
      };
    });
    storage.setItem("aic.history", "on"); // history back on, tab B must still stay closed
    expect(await tabB.put(key(2), "analysis", { v: 2 })).not.toBe("stored");
    expect(await databaseNames(factory)).toEqual([]);
  });

  it("test_open_reaching_upgradeneeded_after_history_off_aborts_and_creates_no_database", async () => {
    const factory = freshFactory();
    const storage = memoryStorage({ "aic.history": "on" });
    // The setting turns off right after `open` was called, before onupgradeneeded runs.
    const racing = new Proxy(factory, {
      get(target, prop) {
        const value: unknown = Reflect.get(target, prop, target);
        if (prop === "open") {
          return (...args: Parameters<IDBFactory["open"]>) => {
            const request = target.open(...args);
            storage.removeItem("aic.history");
            return request;
          };
        }
        return typeof value === "function"
          ? (value as (...a: unknown[]) => unknown).bind(target)
          : value;
      },
    });
    const store = new IndexedDbCacheStore({ factory: racing, clock: () => T0, storage });
    expect(await store.put(key(1), "analysis", { v: 1 })).toBe("disabled");
    expect(await databaseNames(factory)).toEqual([]);
  });
});
