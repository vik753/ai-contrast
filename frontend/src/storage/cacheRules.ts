/** Rules shared by the cache adapters (ADR 0013 points 4 to 6). Pure functions, no I/O. */
import type { CacheEntryMeta } from "./cacheStore";

export const DAY_MS = 24 * 60 * 60 * 1000;
export const RETENTION_MS = 90 * DAY_MS;
export const MAX_ENTRIES = 100;
export const MAX_ENTRY_BYTES = 2 * 1024 * 1024;
export const RECORD_SCHEMA = 1;
const FUTURE_TOLERANCE_MS = DAY_MS;

/** The stored record. `json` is the data as a JSON string. */
export interface CacheRecord {
  key: string;
  schema: number;
  kind: string;
  createdAt: number;
  lastUsedAt: number;
  size: number;
  json: string;
}

const encoder = new TextEncoder();

export function utf8Length(text: string): number {
  return encoder.encode(text).length;
}

/** Returns the JSON text or `null` when the data cannot be serialized. */
export function serialize(data: unknown): string | null {
  try {
    const json = JSON.stringify(data) as string | undefined;
    return typeof json === "string" ? json : null;
  } catch {
    return null;
  }
}

/** An entry exactly 90 days old is expired. */
export function isExpired(createdAt: unknown, now: number): boolean {
  return (
    typeof createdAt !== "number" || !Number.isFinite(createdAt) || now - createdAt >= RETENTION_MS
  );
}

function isTime(value: unknown, now: number): value is number {
  return typeof value === "number" && Number.isFinite(value) && value <= now + FUTURE_TOLERANCE_MS;
}

/** Checks everything except the caller's validator. Returns the parsed data or `null`. */
export function readRecord(
  record: unknown,
  key: string,
  now: number,
): { data: unknown; record: CacheRecord } | null {
  if (typeof record !== "object" || record === null) {
    return null;
  }
  const r = record as Record<string, unknown>;
  if (
    r.key !== key ||
    r.schema !== RECORD_SCHEMA ||
    r.kind !== "analysis" ||
    !isTime(r.createdAt, now) ||
    !isTime(r.lastUsedAt, now) ||
    typeof r.json !== "string" ||
    r.size !== utf8Length(r.json)
  ) {
    return null;
  }
  try {
    const data: unknown = JSON.parse(r.json);
    return { data, record: r as unknown as CacheRecord };
  } catch {
    return null;
  }
}

/** Metadata of a record, or `null` when its shape is not valid. */
export function toMeta(record: unknown, now: number): CacheEntryMeta | null {
  if (typeof record !== "object" || record === null) {
    return null;
  }
  const r = record as Record<string, unknown>;
  if (
    typeof r.key !== "string" ||
    r.kind !== "analysis" ||
    !isTime(r.createdAt, now) ||
    !isTime(r.lastUsedAt, now) ||
    typeof r.size !== "number"
  ) {
    return null;
  }
  return {
    key: r.key,
    kind: r.kind,
    createdAt: r.createdAt,
    lastUsedAt: r.lastUsedAt,
    size: r.size,
  };
}

/** Newest first. */
export function sortNewestFirst(list: CacheEntryMeta[]): CacheEntryMeta[] {
  return [...list].sort((a, b) => b.createdAt - a.createdAt || b.lastUsedAt - a.lastUsedAt);
}
