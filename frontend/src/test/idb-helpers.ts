/**
 * S4-T2 test helpers for IndexedDB. TEST-ONLY: this is the only place (with the
 * S4-T2 test files) that imports `fake-indexeddb`. Production code must never
 * import this file (a build test checks it).
 */
import { IDBFactory } from "fake-indexeddb";

export const DB_NAME = "aic-cache";
export const STORE_NAME = "entries";

export function freshFactory(): IDBFactory {
  return new IDBFactory();
}

export function reqDone<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => {
      resolve(request.result);
    };
    request.onerror = () => {
      reject(request.error ?? new Error("request failed"));
    };
  });
}

function openExisting(factory: IDBFactory): Promise<IDBDatabase | null> {
  return new Promise((resolve, reject) => {
    const request = factory.open(DB_NAME);
    let existed = true;
    request.onupgradeneeded = () => {
      existed = false;
      request.transaction?.abort();
    };
    request.onsuccess = () => {
      resolve(request.result);
    };
    request.onerror = () => {
      if (existed) {
        reject(request.error ?? new Error("open failed"));
      } else {
        resolve(null);
      }
    };
  });
}

/** Names of all databases on the factory. */
export async function databaseNames(factory: IDBFactory): Promise<string[]> {
  const list = await factory.databases();
  return list.map((d) => d.name ?? "");
}

/** All raw records of `entries`; `[]` when the database does not exist. Never creates it. */
export async function rawEntries(factory: IDBFactory): Promise<Record<string, unknown>[]> {
  if (!(await databaseNames(factory)).includes(DB_NAME)) {
    return [];
  }
  const db = await openExisting(factory);
  if (db === null) {
    return [];
  }
  try {
    const tx = db.transaction(STORE_NAME, "readonly");
    return (await reqDone(tx.objectStore(STORE_NAME).getAll())) as Record<string, unknown>[];
  } finally {
    db.close();
  }
}

/** Overwrites one raw record (the database must already exist). */
export async function rawPut(factory: IDBFactory, record: Record<string, unknown>): Promise<void> {
  const db = await openExisting(factory);
  if (db === null) {
    throw new Error("database does not exist");
  }
  try {
    const tx = db.transaction(STORE_NAME, "readwrite");
    await reqDone(tx.objectStore(STORE_NAME).put(record));
  } finally {
    db.close();
  }
}

/** Opens a connection that ignores `versionchange` (a second tab that blocks deletion). */
export function openBlockingConnection(factory: IDBFactory, name: string): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = factory.open(name, 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore("x");
    };
    request.onsuccess = () => {
      resolve(request.result);
    };
    request.onerror = () => {
      reject(request.error ?? new Error("open failed"));
    };
  });
}

/** In-memory `Storage` shared by "tabs" in one test. */
export function memoryStorage(initial: Record<string, string> = {}): Storage {
  const map = new Map(Object.entries(initial));
  return {
    get length() {
      return map.size;
    },
    clear: () => {
      map.clear();
    },
    getItem: (k: string) => map.get(k) ?? null,
    key: (i: number) => [...map.keys()][i] ?? null,
    removeItem: (k: string) => {
      map.delete(k);
    },
    setItem: (k: string, v: string) => {
      map.set(k, v);
    },
  };
}
