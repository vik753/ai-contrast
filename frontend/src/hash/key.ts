/** Canonical JSON and cache keys (ADR 0013 point 8). Keys never leave the browser. */
import { sha256Hex } from "./sha256";

export type KeyPart =
  string | number | boolean | null | readonly KeyPart[] | { readonly [key: string]: KeyPart };

export type CacheKey = string & { readonly __brand: "CacheKey" };

/** JSON with sorted keys and no spaces. Throws for anything that is not plain data. */
export function canonicalJson(value: unknown): string {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new TypeError("Not a finite number");
    }
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  }
  if (typeof value === "object") {
    const proto = Object.getPrototypeOf(value) as unknown;
    if (proto !== Object.prototype && proto !== null) {
      throw new TypeError("Not a plain object");
    }
    const entries = Object.entries(value).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${canonicalJson(v)}`).join(",")}}`;
  }
  throw new TypeError("Unsupported value");
}

export async function buildKey(parts: Record<string, KeyPart>): Promise<CacheKey> {
  return (await sha256Hex(canonicalJson({ v: 1, ...parts }))) as CacheKey;
}
