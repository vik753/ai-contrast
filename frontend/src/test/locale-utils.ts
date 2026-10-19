/**
 * Test helpers for locale files.
 *
 * Locale files may be nested (`{ "app": { "title": "..." } }`) or flat
 * (`{ "app.title": "..." }`). Both are flattened to dotted keys so that tests
 * do not depend on the chosen layout.
 */

export type FlatLocale = Readonly<Record<string, unknown>>;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function flattenLocale(value: unknown, prefix = ""): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (!isPlainObject(value)) {
    if (prefix !== "") {
      out[prefix] = value;
    }
    return out;
  }
  for (const [key, child] of Object.entries(value)) {
    const path = prefix === "" ? key : `${prefix}.${key}`;
    if (isPlainObject(child)) {
      Object.assign(out, flattenLocale(child, path));
    } else {
      out[path] = child;
    }
  }
  return out;
}

/** Returns the string value of `key`, or throws a readable error. */
export function text(locale: FlatLocale, key: string): string {
  const value = locale[key];
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`Locale key "${key}" is missing or not a non-empty string`);
  }
  return value;
}

/** All non-empty string values of a flattened locale. */
export function allStrings(locale: FlatLocale): string[] {
  return Object.values(locale).filter(
    (v): v is string => typeof v === "string" && v.trim() !== "",
  );
}
