/** Import and export of own topics. An imported file is untrusted input (ADR 0017 point 7). */
import {
  ATTRIBUTE_TYPES,
  MAX_OWN_TOPICS,
  directionOptions,
  type AttributeDefinition,
  type TopicDefinition,
} from "./types";

export const MAX_IMPORT_BYTES = 262144;

export type ImportError =
  "too_large" | "invalid_json" | "forbidden_key" | "invalid_shape" | "too_many";
export type ImportResult =
  { ok: true; topics: TopicDefinition[] } | { ok: false; code: ImportError };

const FORBIDDEN = new Set(["__proto__", "constructor", "prototype"]);
const MAX_ATTRIBUTES = 12;
const MAX_VALUES = 30;
const MAX_SYNONYMS = 40;
const MAX_UNITS = 10;
const MAX_ID = 64;

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const len = (s: string): number => Array.from(s).length;

class Shape extends Error {}

function hasForbiddenKey(root: unknown): boolean {
  const stack: unknown[] = [root];
  while (stack.length > 0) {
    const v = stack.pop();
    if (Array.isArray(v)) for (const x of v as unknown[]) stack.push(x);
    else if (isRecord(v)) {
      for (const k of Object.keys(v)) {
        if (FORBIDDEN.has(k)) return true;
        stack.push(v[k]);
      }
    }
  }
  return false;
}

function exactKeys(o: Record<string, unknown>, keys: readonly string[]): void {
  const have = Object.keys(o);
  if (have.length !== keys.length || !keys.every((k) => Object.hasOwn(o, k))) throw new Shape();
}

/** Mutable flag: set when a count or length cap is exceeded (shape errors win over it). */
interface Ctx {
  over: boolean;
}

function text(v: unknown, min: number, max: number, ctx: Ctx): string {
  if (typeof v !== "string") throw new Shape();
  const n = len(v);
  if (n < min) throw new Shape();
  if (n > max) ctx.over = true;
  return v;
}

function strList(v: unknown, max: number, itemMax: number, ctx: Ctx, items = 1): string[] {
  if (!Array.isArray(v)) throw new Shape();
  if (v.length > max) ctx.over = true;
  return v.map((x) => text(x, items, itemMax, ctx));
}

function attribute(v: unknown, ctx: Ctx): AttributeDefinition {
  if (!isRecord(v)) throw new Shape();
  exactKeys(v, [
    "id",
    "label",
    "type",
    "units",
    "direction",
    "order",
    "values",
    "direction_source",
  ]);
  const type = v.type;
  if (typeof type !== "string" || !(ATTRIBUTE_TYPES as readonly string[]).includes(type)) {
    throw new Shape();
  }
  const t = type as AttributeDefinition["type"];
  const direction = v.direction;
  if (typeof direction !== "string" || !directionOptions(t).includes(direction)) throw new Shape();
  if (v.direction_source !== "client") throw new Shape();
  if (!Array.isArray(v.order) || v.order.length !== 0) throw new Shape();
  return {
    id: text(v.id, 1, MAX_ID, ctx),
    label: text(v.label, 1, 200, ctx),
    type: t,
    units: strList(v.units, MAX_UNITS, 32, ctx),
    direction,
    order: [],
    values: strList(v.values, MAX_VALUES, 60, ctx),
    direction_source: "client",
  };
}

function topic(v: unknown, ctx: Ctx): TopicDefinition {
  if (!isRecord(v)) throw new Shape();
  exactKeys(v, [
    "origin",
    "domain",
    "topic_id",
    "title",
    "description",
    "side",
    "attributes",
    "synonyms_en",
    "synonyms_uk",
    "synonyms_ru",
  ]);
  const origin = v.origin;
  if (origin !== "suggested" && origin !== "custom") throw new Shape();
  const domain = v.domain === null ? null : text(v.domain, 1, MAX_ID, ctx);
  const description = text(v.description, 0, 200, ctx);
  if (origin === "suggested" && description !== "") throw new Shape();
  if (!Array.isArray(v.attributes)) throw new Shape();
  if (v.attributes.length > MAX_ATTRIBUTES) ctx.over = true;
  return {
    origin,
    domain,
    topic_id: text(v.topic_id, 1, MAX_ID, ctx),
    title: text(v.title, 1, 80, ctx),
    description,
    side: text(v.side, 1, MAX_ID, ctx),
    attributes: v.attributes.map((a) => attribute(a, ctx)),
    synonyms_en: strList(v.synonyms_en, MAX_SYNONYMS, 60, ctx),
    synonyms_uk: strList(v.synonyms_uk, MAX_SYNONYMS, 60, ctx),
    synonyms_ru: strList(v.synonyms_ru, MAX_SYNONYMS, 60, ctx),
  };
}

export function exportTopics(topics: readonly TopicDefinition[]): string {
  return JSON.stringify({ version: 1, topics }, null, 2);
}

/** Never throws; no partial result. */
export function importTopics(raw: string): ImportResult {
  try {
    if (new TextEncoder().encode(raw).length > MAX_IMPORT_BYTES) {
      return { ok: false, code: "too_large" };
    }
    let data: unknown;
    try {
      data = JSON.parse(raw);
    } catch {
      return { ok: false, code: "invalid_json" };
    }
    if (hasForbiddenKey(data)) return { ok: false, code: "forbidden_key" };
    if (!isRecord(data)) return { ok: false, code: "invalid_shape" };
    exactKeys(data, ["version", "topics"]);
    if (data.version !== 1 || !Array.isArray(data.topics)) throw new Shape();
    const ctx: Ctx = { over: data.topics.length > MAX_OWN_TOPICS };
    const topics = data.topics.map((t) => topic(t, ctx));
    if (ctx.over) return { ok: false, code: "too_many" };
    return { ok: true, topics };
  } catch {
    return { ok: false, code: "invalid_shape" };
  }
}
