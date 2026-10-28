import type { CacheStore } from "./cacheStore";

/** History is off or IndexedDB is not available: nothing is kept, every `get` misses. */
export class DisabledCacheStore implements CacheStore {
  readonly get: CacheStore["get"] = () => Promise.resolve(null);
  readonly put: CacheStore["put"] = () => Promise.resolve("disabled");
  readonly list: CacheStore["list"] = () => Promise.resolve([]);
  readonly delete: CacheStore["delete"] = () => Promise.resolve();
  readonly clear: CacheStore["clear"] = () => Promise.resolve();
  readonly purgeExpired: CacheStore["purgeExpired"] = () => Promise.resolve(0);
  close(): void {
    // Nothing is open.
  }
}
