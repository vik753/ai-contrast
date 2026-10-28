/**
 * History setting, store factory, start-up cleanup and "clear all" (ADR 0013 points 1, 2, 2a, 7).
 * History is off by default. Off means nothing is stored. The setting is `localStorage["aic.history"] === "on"`.
 */
import type { CacheStore } from "./cacheStore";
import { DisabledCacheStore } from "./disabledCacheStore";
import { DB_NAME, HISTORY_KEY, IndexedDbCacheStore } from "./indexedDbCacheStore";

export const LANGUAGE_KEY = "aic.lang";
const PREFIX = "aic.";

type DeleteResult = "deleted" | "blocked" | "failed";
export type ClearResult = "cleared" | "blocked" | "failed";

function getFactory(): IDBFactory | null {
  try {
    const factory = (globalThis as { indexedDB?: IDBFactory | null }).indexedDB;
    return factory ?? null;
  } catch {
    return null;
  }
}

/** True when this browser has IndexedDB at all. */
export function isHistoryAvailable(): boolean {
  return getFactory() !== null;
}

export function isHistoryEnabled(): boolean {
  try {
    return localStorage.getItem(HISTORY_KEY) === "on";
  } catch {
    return false;
  }
}

function deleteDatabase(factory: IDBFactory, name: string): Promise<DeleteResult> {
  return new Promise((resolve) => {
    let request: IDBOpenDBRequest;
    try {
      request = factory.deleteDatabase(name);
    } catch {
      resolve("failed");
      return;
    }
    request.onsuccess = () => {
      resolve("deleted");
    };
    request.onerror = () => {
      resolve("failed");
    };
    // The deletion stays pending and finishes when the other tab closes its connection.
    request.onblocked = () => {
      resolve("blocked");
    };
  });
}

/** Turning history off removes the key first, then deletes the database. */
export async function setHistoryEnabled(enabled: boolean): Promise<void> {
  if (enabled) {
    localStorage.setItem(HISTORY_KEY, "on");
    return;
  }
  try {
    localStorage.removeItem(HISTORY_KEY);
  } catch {
    // Blocked storage: history is already off for every read.
  }
  const factory = getFactory();
  if (factory !== null) {
    await deleteDatabase(factory, DB_NAME);
  }
}

function newIndexedDbStore(factory: IDBFactory): IndexedDbCacheStore {
  return new IndexedDbCacheStore({
    factory,
    clock: () => Date.now(),
    storage: {
      getItem: (k: string) => localStorage.getItem(k),
    },
  });
}

export async function createCacheStore(): Promise<CacheStore> {
  const factory = getFactory();
  if (factory === null || !isHistoryEnabled()) {
    return new DisabledCacheStore();
  }
  const store = newIndexedDbStore(factory);
  if (!(await store.ensureOpen())) {
    store.close();
    return new DisabledCacheStore();
  }
  return store;
}

/** Number of saved results, or `null` when it cannot be read. Opens nothing with history off. */
export async function countSavedResults(): Promise<number | null> {
  if (!isHistoryEnabled()) {
    return 0;
  }
  const store = await createCacheStore();
  try {
    if (store instanceof DisabledCacheStore) {
      return null;
    }
    return (await store.list()).length;
  } catch {
    return null;
  } finally {
    (store as { close?: () => void }).close?.();
  }
}

/**
 * Start-up: history off deletes a leftover database (a deletion that was blocked or failed
 * earlier); history on removes expired entries.
 */
export async function startupCleanup(): Promise<void> {
  const factory = getFactory();
  if (factory === null) {
    return;
  }
  try {
    if (isHistoryEnabled()) {
      const store = await createCacheStore();
      await store.purgeExpired();
      (store as { close?: () => void }).close?.();
    } else {
      await deleteDatabase(factory, DB_NAME);
    }
  } catch {
    // Cleanup is best effort.
  }
}

/** Calls `onChange` when another tab changes or clears the history setting. */
export function subscribeHistoryChanges(onChange: () => void): () => void {
  const handler = (event: StorageEvent) => {
    if (event.key === null || event.key === HISTORY_KEY) {
      onChange();
    }
  };
  window.addEventListener("storage", handler);
  return () => {
    window.removeEventListener("storage", handler);
  };
}

function removeAicKeys(storage: () => Storage): void {
  try {
    const s = storage();
    const keys: string[] = [];
    for (let i = 0; i < s.length; i++) {
      const k = s.key(i);
      if (k !== null && k.startsWith(PREFIX) && k !== LANGUAGE_KEY) {
        keys.push(k);
      }
    }
    for (const k of keys) {
      s.removeItem(k);
    }
  } catch {
    // Blocked storage has nothing we can remove.
  }
}

/** Removes `aic.*` keys (not the language), then deletes every IndexedDB database of the origin. */
export async function clearAllData(): Promise<ClearResult> {
  removeAicKeys(() => localStorage);
  removeAicKeys(() => sessionStorage);
  const factory = getFactory();
  if (factory === null) {
    return "cleared";
  }
  const results: DeleteResult[] = [await deleteDatabase(factory, DB_NAME)];
  try {
    if (typeof factory.databases === "function") {
      const list = await factory.databases();
      for (const info of list) {
        if (typeof info.name === "string" && info.name !== DB_NAME) {
          results.push(await deleteDatabase(factory, info.name));
        }
      }
    }
  } catch {
    // The list is not available: the main database is already handled.
  }
  if (results.includes("failed")) {
    return "failed";
  }
  return results.includes("blocked") ? "blocked" : "cleared";
}
