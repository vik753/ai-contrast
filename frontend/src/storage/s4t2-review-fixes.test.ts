/** S4-T2 review fixes: cap with corrupt records, list validation, clear all, lifecycle. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { IndexedDbCacheStore } from "./indexedDbCacheStore";
import { clearAllData, countSavedResults, setHistoryEnabled } from "./historySetting";
import {
  DB_NAME,
  freshFactory,
  memoryStorage,
  openBlockingConnection,
  rawEntries,
  rawPut,
} from "../test/idb-helpers";
import { resetBrowserEnv } from "../test/browser-env";

const T0 = Date.UTC(2026, 9, 22, 12, 0, 0);
const key = (n: number): string => n.toString(16).padStart(64, "0");

function setup() {
  const factory = freshFactory();
  const storage = memoryStorage({ "aic.history": "on" });
  const store = new IndexedDbCacheStore({ factory, clock: () => T0, storage });
  return { factory, store };
}

afterEach(() => {
  resetBrowserEnv();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("review fixes", () => {
  it("test_corrupt_record_counts_toward_cap_and_is_evicted_first", async () => {
    const { factory, store } = setup();
    for (let i = 0; i < 100; i++) {
      await store.put(key(i), "analysis", { v: i });
    }
    const [rec] = await rawEntries(factory);
    await rawPut(factory, { ...rec, key: "corrupt", lastUsedAt: "x" });
    await store.put(key(500), "analysis", { v: 1 });
    const keys = (await rawEntries(factory)).map((r) => r.key);
    expect(keys.length).toBeLessThanOrEqual(100);
    expect(keys).not.toContain("corrupt");
    expect(keys).toContain(key(500));
  });

  it("test_list_deletes_records_with_unknown_schema", async () => {
    const { factory, store } = setup();
    await store.put(key(1), "analysis", { v: 1 });
    await store.put(key(2), "analysis", { v: 2 });
    const [rec] = await rawEntries(factory);
    await rawPut(factory, { ...rec, schema: 2 });
    expect((await store.list()).length).toBe(1);
    expect((await rawEntries(factory)).length).toBe(1);
  });

  it("test_set_history_disabled_returns_blocked_when_another_tab_holds_database", async () => {
    const factory = freshFactory();
    vi.stubGlobal("indexedDB", factory);
    localStorage.setItem("aic.history", "on");
    const other = await openBlockingConnection(factory, DB_NAME);
    try {
      expect(await setHistoryEnabled(false)).toBe("blocked");
    } finally {
      other.close();
    }
  });

  it("test_clear_all_returns_failed_when_removing_an_aic_key_throws", async () => {
    vi.stubGlobal("indexedDB", freshFactory());
    sessionStorage.setItem("aic.x", "1");
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    expect(await clearAllData()).toBe("failed");
  });

  it("test_count_is_null_when_history_is_on_but_open_fails", async () => {
    vi.stubGlobal("indexedDB", null);
    localStorage.setItem("aic.history", "on");
    expect(await countSavedResults()).toBeNull();
  });
});
