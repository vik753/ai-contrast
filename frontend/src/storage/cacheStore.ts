/**
 * `CacheStore` port (ADR 0013). Application code depends only on this file;
 * adapters live next to it. The cache holds analysis results with placeholders,
 * never contract text, file bytes or the placeholder mapping.
 */

/** Lower-case hex SHA-256 string built by the hash module. */
export type CacheKey = string;

/** What an entry is. Only `"analysis"` exists for now. */
export type CacheKind = "analysis";

export type PutResult = "stored" | "disabled" | "too_large" | "storage_full" | "failed";

export interface CacheHit<T> {
  data: T;
  createdAt: number;
  lastUsedAt: number;
}

export interface CacheEntryMeta {
  key: CacheKey;
  kind: CacheKind;
  createdAt: number;
  lastUsedAt: number;
  size: number;
}

export interface CacheStore {
  /** Returns the entry and updates `lastUsedAt`, or `null` (miss, expired, invalid). */
  get<T>(key: CacheKey, validate: (data: unknown) => data is T): Promise<CacheHit<T> | null>;
  put(key: CacheKey, kind: CacheKind, data: unknown): Promise<PutResult>;
  /** Newest first. */
  list(): Promise<CacheEntryMeta[]>;
  delete(key: CacheKey): Promise<void>;
  clear(): Promise<void>;
  /** Deletes expired entries and returns how many were deleted. */
  purgeExpired(): Promise<number>;
  /** Releases a held connection. Optional: adapters without one omit it. */
  close?(): void;
}
