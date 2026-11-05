/**
 * Offline fallback for the catalog (ADR 0017 point 1): the files of `shared/topics` are bundled
 * at build time, so the panel works before the backend wakes. A test checks they equal the repo.
 */
import type { Catalog, CatalogDomain } from "./types";
import { isCatalogDomain } from "./catalogShape";

const files = import.meta.glob<string>("../../../shared/topics/*.json", {
  eager: true,
  query: "?raw",
  import: "default",
});

export const BUNDLED_CATALOG_VERSION = "bundled";

export function bundledCatalog(): Catalog | null {
  const domains: CatalogDomain[] = [];
  for (const raw of Object.values(files)) {
    try {
      const parsed: unknown = JSON.parse(raw);
      if (isCatalogDomain(parsed)) domains.push(parsed);
    } catch {
      return null;
    }
  }
  if (domains.length === 0) return null;
  domains.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return { catalog_version: BUNDLED_CATALOG_VERSION, domains };
}

/** For tests: the raw bundled files by file name. */
export function bundledRawFiles(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [path, raw] of Object.entries(files)) out[path.split("/").pop() ?? path] = raw;
  return out;
}
