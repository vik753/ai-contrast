/**
 * IndexedDB adapter for the `CacheStore` port (ADR 0013). Own small wrapper, no library.
 * Database `aic-cache` version 1, object store `entries` (key path `key`), index `lastUsedAt`.
 * Fail closed: the setting `aic.history` is re-read before the database is opened, before
 * every `put` and inside `onupgradeneeded`. A connection closed by `versionchange` is never
 * reopened by the same instance.
 */
import {
  isExpired,
  MAX_ENTRIES,
  MAX_ENTRY_BYTES,
  RECORD_SCHEMA,
  readRecord,
  serialize,
  sortNewestFirst,
  toMeta,
  utf8Length,
  type CacheRecord,
} from "./cacheRules";
import type {
  CacheEntryMeta,
  CacheHit,
  CacheKey,
  CacheKind,
  CacheStore,
  PutResult,
} from "./cacheStore";

export const DB_NAME = "aic-cache";
export const STORE_NAME = "entries";
export const HISTORY_KEY = "aic.history";

export interface IndexedDbCacheStoreOptions {
  factory: IDBFactory;
  /** Epoch milliseconds. */
  clock: () => number;
  /** Where `aic.history` is read. */
  storage: Pick<Storage, "getItem">;
}

export class IndexedDbCacheStore implements CacheStore {
  private readonly factory: IDBFactory;
  private readonly clock: () => number;
  private readonly storage: Pick<Storage, "getItem">;
  private db: IDBDatabase | null = null;
  private opening: Promise<IDBDatabase | null> | null = null;
  private dead = false;

  constructor(options: IndexedDbCacheStoreOptions) {
    this.factory = options.factory;
    this.clock = options.clock;
    this.storage = options.storage;
  }

  /** Opens the database. `false` when history is off or the database cannot be used. */
  async ensureOpen(): Promise<boolean> {
    try {
      return (await this.connection()) !== null;
    } catch {
      return false;
    }
  }

  close(): void {
    this.dead = true;
    this.db?.close();
    this.db = null;
  }

  async get<T>(key: CacheKey, validate: (data: unknown) => data is T): Promise<CacheHit<T> | null> {
    try {
      const db = await this.connection();
      if (db === null) {
        return null;
      }
      await this.purge(db);
      const now = this.clock();
      return await this.run(db, (store, setResult) => {
        const request = store.get(key);
        request.onsuccess = () => {
          const raw: unknown = request.result;
          if (raw === undefined) {
            return;
          }
          const read = readRecord(raw, key, now);
          let valid = false;
          if (read !== null) {
            try {
              valid = validate(read.data);
            } catch {
              valid = false;
            }
          }
          if (read === null || !valid) {
            store.delete(key);
            return;
          }
          const updated: CacheRecord = { ...read.record, lastUsedAt: now };
          store.put(updated);
          setResult({ data: read.data as T, createdAt: updated.createdAt, lastUsedAt: now });
        };
      });
    } catch {
      return null;
    }
  }

  async put(key: CacheKey, kind: CacheKind, data: unknown): Promise<PutResult> {
    if (!this.isOn()) {
      return "disabled";
    }
    const json = serialize(data);
    if (json === null) {
      return "failed";
    }
    const size = utf8Length(json);
    if (size > MAX_ENTRY_BYTES) {
      return "too_large";
    }
    try {
      const db = await this.connection();
      if (db === null || !this.isOn()) {
        return "disabled";
      }
      await this.purge(db);
      const now = this.clock();
      const record: CacheRecord = {
        key,
        schema: RECORD_SCHEMA,
        kind,
        createdAt: now,
        lastUsedAt: now,
        size,
        json,
      };
      await this.run<true>(db, (store, setResult, fail) => {
        // Count every record, valid or not. A key cursor reads no values.
        const all: string[] = [];
        const ordered: string[] = [];
        const allCursor = store.openKeyCursor();
        allCursor.onsuccess = () => {
          const c = allCursor.result;
          if (c !== null) {
            all.push(c.primaryKey as string);
            c.continue();
            return;
          }
          const indexCursor = store.index("lastUsedAt").openKeyCursor();
          indexCursor.onsuccess = () => {
            const ic = indexCursor.result;
            if (ic !== null) {
              if (typeof ic.key === "number") {
                ordered.push(ic.primaryKey as string);
              }
              ic.continue();
              return;
            }
            try {
              store.put(record);
            } catch (error) {
              fail(error);
              return;
            }
            // Records without a valid numeric lastUsedAt count as the oldest.
            const valid = new Set(ordered);
            const oldestFirst = [...all.filter((k) => !valid.has(k)), ...ordered].filter(
              (k) => k !== key,
            );
            const excess = new Set(all).add(key).size - MAX_ENTRIES;
            for (const old of oldestFirst.slice(0, Math.max(0, excess))) {
              store.delete(old);
            }
            setResult(true);
          };
        };
      });
      return "stored";
    } catch (error) {
      return isQuota(error) ? "storage_full" : "failed";
    }
  }

  async list(): Promise<CacheEntryMeta[]> {
    try {
      const db = await this.connection();
      if (db === null) {
        return [];
      }
      await this.purge(db);
      const now = this.clock();
      const metas =
        (await this.run<CacheEntryMeta[]>(db, (store, setResult) => {
          const found: CacheEntryMeta[] = [];
          const cursor = store.openCursor();
          cursor.onsuccess = () => {
            const c = cursor.result;
            if (c === null) {
              setResult(found);
              return;
            }
            const value: unknown = c.value;
            const meta = toMeta(value, now);
            if (meta !== null && readRecord(value, meta.key, now) !== null) {
              found.push(meta);
            } else {
              c.delete();
            }
            c.continue();
          };
        })) ?? [];
      return sortNewestFirst(metas);
    } catch {
      return [];
    }
  }

  async delete(key: CacheKey): Promise<void> {
    try {
      const db = await this.connection();
      if (db !== null) {
        await this.run(db, (store) => {
          store.delete(key);
        });
      }
    } catch {
      // Nothing to delete or storage blocked.
    }
  }

  async clear(): Promise<void> {
    try {
      const db = await this.connection();
      if (db !== null) {
        await this.run(db, (store) => {
          store.clear();
        });
      }
    } catch {
      // Nothing to clear or storage blocked.
    }
  }

  async purgeExpired(): Promise<number> {
    try {
      const db = await this.connection();
      return db === null ? 0 : await this.purge(db);
    } catch {
      return 0;
    }
  }

  private isOn(): boolean {
    try {
      return this.storage.getItem(HISTORY_KEY) === "on";
    } catch {
      return false;
    }
  }

  private connection(): Promise<IDBDatabase | null> {
    if (this.dead || !this.isOn()) {
      return Promise.resolve(null);
    }
    if (this.db !== null) {
      return Promise.resolve(this.db);
    }
    this.opening ??= this.open().finally(() => {
      this.opening = null;
    });
    return this.opening;
  }

  private open(): Promise<IDBDatabase | null> {
    return new Promise((resolve, reject) => {
      let aborted = false;
      let request: IDBOpenDBRequest;
      try {
        request = this.factory.open(DB_NAME, 1);
      } catch (error) {
        reject(asError(error));
        return;
      }
      request.onupgradeneeded = () => {
        if (!this.isOn() || this.dead) {
          aborted = true;
          request.transaction?.abort();
          return;
        }
        const store = request.result.createObjectStore(STORE_NAME, { keyPath: "key" });
        store.createIndex("lastUsedAt", "lastUsedAt");
      };
      request.onsuccess = () => {
        const db = request.result;
        if (this.dead) {
          db.close();
          resolve(null);
          return;
        }
        db.onversionchange = () => {
          db.close();
          this.dead = true;
          this.db = null;
        };
        db.onclose = () => {
          this.db = null;
          this.dead = true;
        };
        this.db = db;
        resolve(db);
      };
      request.onerror = () => {
        if (aborted) {
          resolve(null);
        } else {
          reject(request.error ?? new Error("open failed"));
        }
      };
    });
  }

  /** Deletes expired and unusable records in one transaction. Returns the count. */
  private purge(db: IDBDatabase): Promise<number> {
    const now = this.clock();
    return this.run<number>(db, (store, setResult) => {
      let count = 0;
      const cursor = store.openCursor();
      cursor.onsuccess = () => {
        const c = cursor.result;
        if (c === null) {
          setResult(count);
          return;
        }
        const value: unknown = c.value;
        const created =
          typeof value === "object" && value !== null
            ? (value as Record<string, unknown>).createdAt
            : undefined;
        if (isExpired(created, now)) {
          c.delete();
          count++;
        }
        c.continue();
      };
    }).then((n) => n ?? 0);
  }

  /** One readwrite (or readonly) transaction. Any error aborts it; nothing partial stays. */
  private run<R>(
    db: IDBDatabase,
    work: (
      store: IDBObjectStore,
      setResult: (value: R) => void,
      fail: (error: unknown) => void,
    ) => void,
    mode: IDBTransactionMode = "readwrite",
  ): Promise<R | null> {
    return new Promise((resolve, reject) => {
      let result: R | null = null;
      let error: unknown = null;
      const tx = db.transaction(STORE_NAME, mode);
      const abort = (e: unknown) => {
        error ??= e;
        try {
          tx.abort();
        } catch {
          // Already finished.
        }
      };
      tx.oncomplete = () => {
        resolve(result);
      };
      tx.onabort = () => {
        reject(asError(error ?? tx.error ?? new Error("aborted")));
      };
      tx.onerror = () => {
        error ??= tx.error;
      };
      try {
        work(
          tx.objectStore(STORE_NAME),
          (value) => {
            result = value;
          },
          abort,
        );
      } catch (e) {
        abort(e);
      }
    });
  }
}

function isQuota(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    (error as { name?: unknown }).name === "QuotaExceededError"
  );
}

function asError(error: unknown): Error {
  if (error instanceof Error) {
    return error;
  }
  const result = new Error("indexeddb error");
  if (typeof error === "object" && error !== null) {
    const name = (error as { name?: unknown }).name;
    if (typeof name === "string") {
      result.name = name;
    }
  }
  return result;
}
