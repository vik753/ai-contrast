/**
 * S4-T2 AC6, AC6a, AC7 — history setting, store factory, start-up delete, clear all.
 *
 * INJECTION POINTS: src/storage/historySetting.ts exports (all use the GLOBAL
 * `indexedDB`, `localStorage`, `sessionStorage`; tests replace the global `indexedDB`
 * with a fresh fake `IDBFactory` through `vi.stubGlobal`):
 *   isHistoryEnabled(): boolean
 *   setHistoryEnabled(enabled: boolean): Promise<void>      // false: remove key, THEN delete database
 *   createCacheStore(): Promise<CacheStore>                 // Disabled or IndexedDb
 *   startupCleanup(): Promise<void>                         // history off -> indexedDB.deleteDatabase("aic-cache")
 *   clearAllData(): Promise<"cleared" | "blocked" | "failed">
 *   subscribeHistoryChanges(onChange: () => void): () => void
 *       // calls onChange when window gets a `storage` event with key "aic.history" or key null;
 *       // returns an unsubscribe function. The app uses it to switch to DisabledCacheStore.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  makeGetItemThrow,
  makeLocalStorageAccessThrow,
  resetBrowserEnv,
} from "../test/browser-env";
import { databaseNames, DB_NAME, freshFactory, openBlockingConnection } from "../test/idb-helpers";
import { DisabledCacheStore } from "./disabledCacheStore";
import { IndexedDbCacheStore } from "./indexedDbCacheStore";
import {
  clearAllData,
  createCacheStore,
  isHistoryEnabled,
  setHistoryEnabled,
  startupCleanup,
  subscribeHistoryChanges,
} from "./historySetting";

const key = (n: number): string => n.toString(16).padStart(64, "0");

function install(factory: IDBFactory = freshFactory()): IDBFactory {
  vi.stubGlobal("indexedDB", factory);
  return factory;
}

/** Proxy that records the order of calls and what storage looked like at deleteDatabase. */
function spyFactory(factory: IDBFactory, log: string[]): IDBFactory {
  return new Proxy(factory, {
    get(target, prop) {
      const value: unknown = Reflect.get(target, prop, target);
      if (prop === "deleteDatabase") {
        return (name: string) => {
          const aic = [...Object.keys(localStorage), ...Object.keys(sessionStorage)].filter(
            (k) => k.startsWith("aic.") && k !== "aic.lang",
          );
          log.push(`delete:${name}|aicKeysLeft=${aic.join(",")}`);
          return target.deleteDatabase(name);
        };
      }
      return typeof value === "function"
        ? (value as (...a: unknown[]) => unknown).bind(target)
        : value;
    },
  });
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});
afterEach(() => {
  resetBrowserEnv();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("isHistoryEnabled (AC6)", () => {
  it("test_history_is_off_when_key_is_missing", () => {
    expect(isHistoryEnabled()).toBe(false);
  });
  it("test_history_is_on_only_for_exact_value_on", () => {
    localStorage.setItem("aic.history", "on");
    expect(isHistoryEnabled()).toBe(true);
    for (const v of ["ON", "true", "1", "off", "", " on"]) {
      localStorage.setItem("aic.history", v);
      expect(isHistoryEnabled()).toBe(false);
    }
  });
  it("test_history_is_off_when_storage_read_throws", () => {
    localStorage.setItem("aic.history", "on");
    makeGetItemThrow();
    expect(isHistoryEnabled()).toBe(false);
  });
  it("test_history_is_off_when_storage_access_throws", () => {
    makeLocalStorageAccessThrow();
    expect(isHistoryEnabled()).toBe(false);
  });
});

describe("setHistoryEnabled (AC6)", () => {
  it("test_enable_writes_on", async () => {
    install();
    await setHistoryEnabled(true);
    expect(localStorage.getItem("aic.history")).toBe("on");
  });

  it("test_disable_removes_key_before_deleting_database", async () => {
    const real = install();
    const log: string[] = [];
    vi.stubGlobal("indexedDB", spyFactory(real, log));
    localStorage.setItem("aic.history", "on");
    await setHistoryEnabled(false);
    expect(localStorage.getItem("aic.history")).toBeNull();
    expect(log).toEqual([`delete:${DB_NAME}|aicKeysLeft=`]);
  });

  it("test_disable_deletes_saved_entries", async () => {
    const factory = install();
    localStorage.setItem("aic.history", "on");
    const store = await createCacheStore();
    await store.put(key(1), "analysis", { v: 1 });
    expect(await databaseNames(factory)).toContain(DB_NAME);
    await setHistoryEnabled(false);
    expect(await databaseNames(factory)).not.toContain(DB_NAME);
  });
});

describe("createCacheStore (AC6)", () => {
  it("test_history_off_returns_disabled_store_and_never_opens_database", async () => {
    const factory = install();
    const open = vi.spyOn(factory, "open");
    expect(await createCacheStore()).toBeInstanceOf(DisabledCacheStore);
    expect(open).not.toHaveBeenCalled();
    expect(await databaseNames(factory)).toEqual([]);
  });

  it("test_history_on_returns_indexeddb_store", async () => {
    install();
    localStorage.setItem("aic.history", "on");
    expect(await createCacheStore()).toBeInstanceOf(IndexedDbCacheStore);
  });

  it("test_history_on_but_indexeddb_null_returns_disabled_store", async () => {
    vi.stubGlobal("indexedDB", null);
    localStorage.setItem("aic.history", "on");
    expect(await createCacheStore()).toBeInstanceOf(DisabledCacheStore);
  });

  it("test_history_on_but_indexeddb_undefined_returns_disabled_store", async () => {
    vi.stubGlobal("indexedDB", undefined);
    localStorage.setItem("aic.history", "on");
    expect(await createCacheStore()).toBeInstanceOf(DisabledCacheStore);
  });

  it("test_history_on_but_open_throws_security_error_returns_disabled_store", async () => {
    const real = freshFactory();
    vi.stubGlobal(
      "indexedDB",
      new Proxy(real, {
        get(target, prop) {
          if (prop === "open") {
            return () => {
              throw new DOMException("denied", "SecurityError");
            };
          }
          const value: unknown = Reflect.get(target, prop, target);
          return typeof value === "function"
            ? (value as (...a: unknown[]) => unknown).bind(target)
            : value;
        },
      }),
    );
    localStorage.setItem("aic.history", "on");
    expect(await createCacheStore()).toBeInstanceOf(DisabledCacheStore);
  });

  it("test_history_on_but_open_request_errors_returns_disabled_store", async () => {
    const real = freshFactory();
    vi.stubGlobal(
      "indexedDB",
      new Proxy(real, {
        get(target, prop) {
          if (prop === "open") {
            return () => {
              const req: {
                error: DOMException | null;
                onerror: ((e: Event) => void) | null;
              } = { error: null, onerror: null };
              queueMicrotask(() => {
                req.error = new DOMException("x", "UnknownError");
                req.onerror?.(new Event("error"));
              });
              return req;
            };
          }
          const value: unknown = Reflect.get(target, prop, target);
          return typeof value === "function"
            ? (value as (...a: unknown[]) => unknown).bind(target)
            : value;
        },
      }),
    );
    localStorage.setItem("aic.history", "on");
    expect(await createCacheStore()).toBeInstanceOf(DisabledCacheStore);
  });
});

describe("start-up delete and storage event (AC6a)", () => {
  async function seedDatabase(factory: IDBFactory): Promise<void> {
    localStorage.setItem("aic.history", "on");
    const store = new IndexedDbCacheStore({ factory, clock: () => 1, storage: localStorage });
    await store.put(key(1), "analysis", { v: 1 });
    localStorage.removeItem("aic.history");
  }

  it("test_startup_with_history_off_deletes_leftover_database", async () => {
    const factory = install();
    await seedDatabase(factory);
    expect(await databaseNames(factory)).toContain(DB_NAME);
    await startupCleanup();
    expect(await databaseNames(factory)).not.toContain(DB_NAME);
  });

  it("test_startup_with_history_on_keeps_database", async () => {
    const factory = install();
    await seedDatabase(factory);
    localStorage.setItem("aic.history", "on");
    const del = vi.spyOn(factory, "deleteDatabase");
    await startupCleanup();
    expect(del).not.toHaveBeenCalled();
    expect(await databaseNames(factory)).toContain(DB_NAME);
  });

  it("test_startup_without_indexeddb_does_not_throw", async () => {
    vi.stubGlobal("indexedDB", null);
    await expect(startupCleanup()).resolves.toBeUndefined();
  });

  it("test_storage_event_for_history_key_notifies_subscriber", () => {
    const cb = vi.fn();
    const off = subscribeHistoryChanges(cb);
    window.dispatchEvent(new StorageEvent("storage", { key: "aic.history", newValue: null }));
    expect(cb).toHaveBeenCalledTimes(1);
    off();
  });

  it("test_storage_event_with_null_key_means_storage_cleared_and_notifies", () => {
    const cb = vi.fn();
    const off = subscribeHistoryChanges(cb);
    window.dispatchEvent(new StorageEvent("storage", { key: null }));
    expect(cb).toHaveBeenCalledTimes(1);
    off();
  });

  it("test_storage_event_for_other_key_is_ignored", () => {
    const cb = vi.fn();
    const off = subscribeHistoryChanges(cb);
    window.dispatchEvent(new StorageEvent("storage", { key: "aic.lang", newValue: "uk" }));
    expect(cb).not.toHaveBeenCalled();
    off();
  });

  it("test_unsubscribe_stops_notifications", () => {
    const cb = vi.fn();
    subscribeHistoryChanges(cb)();
    window.dispatchEvent(new StorageEvent("storage", { key: "aic.history", newValue: null }));
    expect(cb).not.toHaveBeenCalled();
  });
});

describe("clearAllData (AC7)", () => {
  function fillStorage(): void {
    localStorage.setItem("aic.history", "on");
    localStorage.setItem("aic.lang", "uk");
    localStorage.setItem("aic.other", "1");
    localStorage.setItem("unrelated", "keep");
    sessionStorage.setItem("aic.session", "1");
    sessionStorage.setItem("aic.lang", "ru");
    sessionStorage.setItem("unrelated", "keep");
  }

  it("test_clear_all_removes_aic_keys_except_lang_in_both_storages", async () => {
    install();
    fillStorage();
    expect(await clearAllData()).toBe("cleared");
    expect(localStorage.getItem("aic.history")).toBeNull();
    expect(localStorage.getItem("aic.other")).toBeNull();
    expect(sessionStorage.getItem("aic.session")).toBeNull();
    expect(localStorage.getItem("aic.lang")).toBe("uk");
    expect(localStorage.getItem("unrelated")).toBe("keep");
    expect(sessionStorage.getItem("unrelated")).toBe("keep");
  });

  it("test_clear_all_removes_storage_keys_before_deleting_database", async () => {
    const real = install();
    const log: string[] = [];
    vi.stubGlobal("indexedDB", spyFactory(real, log));
    fillStorage();
    await clearAllData();
    expect(log.length).toBeGreaterThan(0);
    for (const line of log) {
      expect(line).toMatch(/\|aicKeysLeft=$/);
    }
    expect(log[0]).toContain(`delete:${DB_NAME}|`);
  });

  it("test_clear_all_deletes_database_with_entries", async () => {
    const factory = install();
    localStorage.setItem("aic.history", "on");
    const store = await createCacheStore();
    await store.put(key(1), "analysis", { v: 1 });
    await clearAllData();
    expect(await databaseNames(factory)).not.toContain(DB_NAME);
  });

  it("test_clear_all_deletes_other_databases_of_the_origin", async () => {
    const factory = install();
    (await openBlockingConnection(factory, "other-db")).close();
    expect(await databaseNames(factory)).toContain("other-db");
    expect(await clearAllData()).toBe("cleared");
    expect(await databaseNames(factory)).toEqual([]);
  });

  it("test_clear_all_works_when_databases_api_is_missing", async () => {
    const real = freshFactory();
    const noList = new Proxy(real, {
      get(target, prop) {
        if (prop === "databases") {
          return undefined;
        }
        const value: unknown = Reflect.get(target, prop, target);
        return typeof value === "function"
          ? (value as (...a: unknown[]) => unknown).bind(target)
          : value;
      },
    });
    vi.stubGlobal("indexedDB", noList);
    localStorage.setItem("aic.history", "on");
    const store = new IndexedDbCacheStore({ factory: real, clock: () => 1, storage: localStorage });
    await store.put(key(1), "analysis", { v: 1 });
    expect(await clearAllData()).toBe("cleared");
    expect(await databaseNames(real)).not.toContain(DB_NAME);
  });

  it("test_clear_all_returns_blocked_when_another_tab_keeps_connection_open", async () => {
    const factory = install();
    fillStorage();
    const other = await openBlockingConnection(factory, DB_NAME); // ignores versionchange
    try {
      expect(await clearAllData()).toBe("blocked");
      // Storage keys are gone even though the deletion is blocked.
      expect(localStorage.getItem("aic.history")).toBeNull();
    } finally {
      other.close();
    }
    // The other tab closed; start-up delete (history off) finishes the job.
    await startupCleanup();
    expect(await databaseNames(factory)).not.toContain(DB_NAME);
  });

  it("test_clear_all_returns_failed_when_delete_database_throws", async () => {
    const real = freshFactory();
    vi.stubGlobal(
      "indexedDB",
      new Proxy(real, {
        get(target, prop) {
          if (prop === "deleteDatabase") {
            return () => {
              throw new DOMException("denied", "SecurityError");
            };
          }
          const value: unknown = Reflect.get(target, prop, target);
          return typeof value === "function"
            ? (value as (...a: unknown[]) => unknown).bind(target)
            : value;
        },
      }),
    );
    expect(await clearAllData()).toBe("failed");
  });
});
