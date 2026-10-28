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

/** In-memory adapter for tests. Same rules as the IndexedDB adapter. */
export class MemoryCacheStore implements CacheStore {
  private readonly records = new Map<string, CacheRecord>();
  private readonly clock: () => number;

  constructor(options: { clock: () => number }) {
    this.clock = options.clock;
  }

  get<T>(key: CacheKey, validate: (data: unknown) => data is T): Promise<CacheHit<T> | null> {
    this.purge();
    const raw = this.records.get(key);
    if (raw === undefined) {
      return Promise.resolve(null);
    }
    const now = this.clock();
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
      this.records.delete(key);
      return Promise.resolve(null);
    }
    raw.lastUsedAt = now;
    return Promise.resolve({ data: read.data as T, createdAt: raw.createdAt, lastUsedAt: now });
  }

  put(key: CacheKey, kind: CacheKind, data: unknown): Promise<PutResult> {
    const json = serialize(data);
    if (json === null) {
      return Promise.resolve("failed");
    }
    const size = utf8Length(json);
    if (size > MAX_ENTRY_BYTES) {
      return Promise.resolve("too_large");
    }
    this.purge();
    const now = this.clock();
    this.records.set(key, {
      key,
      schema: RECORD_SCHEMA,
      kind,
      createdAt: now,
      lastUsedAt: now,
      size,
      json,
    });
    const others = [...this.records.values()]
      .filter((r) => r.key !== key)
      .sort((a, b) => a.lastUsedAt - b.lastUsedAt);
    const excess = this.records.size - MAX_ENTRIES;
    for (const r of others.slice(0, Math.max(0, excess))) {
      this.records.delete(r.key);
    }
    return Promise.resolve("stored");
  }

  list(): Promise<CacheEntryMeta[]> {
    this.purge();
    const now = this.clock();
    const metas = [...this.records.values()]
      .map((r) => toMeta(r, now))
      .filter((m): m is CacheEntryMeta => m !== null);
    return Promise.resolve(sortNewestFirst(metas));
  }

  delete(key: CacheKey): Promise<void> {
    this.records.delete(key);
    return Promise.resolve();
  }

  clear(): Promise<void> {
    this.records.clear();
    return Promise.resolve();
  }

  purgeExpired(): Promise<number> {
    return Promise.resolve(this.purge());
  }

  close(): void {
    // Nothing is open.
  }

  private purge(): number {
    const now = this.clock();
    let count = 0;
    for (const r of [...this.records.values()]) {
      if (isExpired(r.createdAt, now)) {
        this.records.delete(r.key);
        count++;
      }
    }
    return count;
  }
}
