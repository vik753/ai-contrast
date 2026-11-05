/**
 * Topic API helpers (ADR 0017 point 7). The key goes only into `X-Provider-Key`, the free pass
 * only into `X-Free-Pass`. Server text is never returned: only closed codes and numbers.
 */
import type { SafetyDocument } from "../api/safetyCheck";
import { isCatalog } from "./catalogShape";
import {
  ATTRIBUTE_TYPES,
  type AttributeDefinition,
  type Catalog,
  type TopicDefinition,
} from "./types";

export const TOPIC_ERROR_CODES: ReadonlySet<string> = new Set([
  "topic_contains_identifier",
  "topic_flagged",
  "invalid_topic_text",
  "ai_bad_output",
  "free_quota_exhausted",
  "busy",
  "catalog_version_mismatch",
  "rate_limited",
  "free_pass_invalid",
  "free_pass_expired",
  "free_pass_exhausted",
  "turnstile_failed",
]);

const TEXT_ERRORS: ReadonlySet<string> = new Set([
  "topic_contains_identifier",
  "topic_flagged",
  "invalid_topic_text",
]);

export interface CommonRequest {
  provider: string;
  model?: string;
  baseUrl?: string;
  key?: string;
  turnstileToken?: string;
  freePass?: string;
}

export interface TopicFailure {
  ok: false;
  code: string;
  field?: string;
  spans?: [number, number][];
}
export type TopicResult<T> = { ok: true; data: T; freePass?: string } | TopicFailure;

export interface Suggestion {
  id: string;
  name: string;
  description: string;
}
export interface SuggestData {
  suggestions: Suggestion[];
  dropped: number;
}
export interface ProposeData {
  attributes: AttributeDefinition[];
  dropped: number;
}
export interface ExpandData {
  synonyms_en: string[];
  synonyms_uk: string[];
  synonyms_ru: string[];
  dropped: number;
}

const UNKNOWN: TopicFailure = { ok: false, code: "unknown" };
const NETWORK: TopicFailure = { ok: false, code: "network" };

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isStrArray = (v: unknown): v is string[] => Array.isArray(v) && v.every(isStr);
const isCount = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v) && v >= 0;

const PINNED = { credentials: "omit", redirect: "error", cache: "no-store" } as const;

function failure(data: unknown): TopicFailure {
  if (!isRecord(data) || !isStr(data.error) || !TOPIC_ERROR_CODES.has(data.error)) return UNKNOWN;
  const code = data.error;
  const out: TopicFailure = { ok: false, code };
  if (TEXT_ERRORS.has(code)) {
    if (isStr(data.field) && /^[a-z_]{1,32}$/.test(data.field)) out.field = data.field;
    const s = data.spans;
    if (
      Array.isArray(s) &&
      s.length <= 100 &&
      s.every(
        (p) => Array.isArray(p) && p.length === 2 && isCount(p[0]) && isCount(p[1]) && p[0] <= p[1],
      )
    ) {
      out.spans = s.map((p: [number, number]) => [p[0], p[1]] as [number, number]);
    }
  }
  return out;
}

/** Reads the reply; `parse` checks the success body (without `free_pass`). */
async function send<T>(
  path: string,
  body: Record<string, unknown>,
  common: CommonRequest,
  parse: (data: Record<string, unknown>) => T | null,
  signal?: AbortSignal,
): Promise<TopicResult<T>> {
  const payload: Record<string, unknown> = { provider: common.provider };
  if (common.model !== undefined) payload.model = common.model;
  if (common.baseUrl !== undefined) payload.base_url = common.baseUrl;
  if (common.turnstileToken !== undefined) payload.turnstile_token = common.turnstileToken;
  Object.assign(payload, body);
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (common.key !== undefined) headers["X-Provider-Key"] = common.key;
  if (common.freePass !== undefined) headers["X-Free-Pass"] = common.freePass;

  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      ...PINNED,
      ...(signal ? { signal } : {}),
    });
  } catch {
    return NETWORK;
  }
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    return UNKNOWN;
  }
  if (!response.ok) return failure(data);
  if (!isRecord(data)) return UNKNOWN;
  const { free_pass: pass, ...rest } = data;
  if (pass !== undefined && !(isStr(pass) && pass.length >= 1 && pass.length <= 256)) {
    return UNKNOWN;
  }
  const parsed = parse(rest);
  if (parsed === null) return UNKNOWN;
  return pass === undefined
    ? { ok: true, data: parsed }
    : { ok: true, data: parsed, freePass: pass };
}

function onlyKeys(o: Record<string, unknown>, keys: string[]): boolean {
  const k = Object.keys(o);
  return k.length === keys.length && keys.every((x) => x in o);
}

function parseSuggest(o: Record<string, unknown>): SuggestData | null {
  if (!onlyKeys(o, ["suggestions", "dropped"]) || !isCount(o.dropped)) return null;
  const list = o.suggestions;
  if (!Array.isArray(list) || list.length > 8) return null;
  const out: Suggestion[] = [];
  for (const s of list) {
    if (!isRecord(s) || !onlyKeys(s, ["id", "name", "description"])) return null;
    if (!isStr(s.id) || !isStr(s.name) || !isStr(s.description)) return null;
    out.push({ id: s.id, name: s.name, description: s.description });
  }
  return { suggestions: out, dropped: o.dropped };
}

function parsePropose(o: Record<string, unknown>): ProposeData | null {
  if (!onlyKeys(o, ["attributes", "dropped"]) || !isCount(o.dropped)) return null;
  const list = o.attributes;
  if (!Array.isArray(list) || list.length > 12) return null;
  const out: AttributeDefinition[] = [];
  for (const a of list) {
    if (!isRecord(a) || !isStr(a.id) || !isStr(a.label) || !isStr(a.type)) return null;
    if (!(ATTRIBUTE_TYPES as readonly string[]).includes(a.type)) return null;
    const units = a.units ?? [];
    const values = a.values ?? [];
    if (!isStrArray(units) || !isStrArray(values) || values.length > 30) return null;
    out.push({
      id: a.id,
      label: a.label,
      type: a.type as AttributeDefinition["type"],
      units,
      direction: "none",
      order: [],
      values,
      direction_source: "client",
    });
  }
  return { attributes: out, dropped: o.dropped };
}

function parseExpand(o: Record<string, unknown>): ExpandData | null {
  if (!onlyKeys(o, ["synonyms_en", "synonyms_uk", "synonyms_ru", "dropped"])) return null;
  if (!isCount(o.dropped)) return null;
  const { synonyms_en: en, synonyms_uk: uk, synonyms_ru: ru } = o;
  if (!isStrArray(en) || !isStrArray(uk) || !isStrArray(ru)) return null;
  if (en.length > 40 || uk.length > 40 || ru.length > 40) return null;
  return { synonyms_en: en, synonyms_uk: uk, synonyms_ru: ru, dropped: o.dropped };
}

export interface SuggestRequest extends CommonRequest {
  domain: string;
  side: string;
  document: SafetyDocument;
}

export function suggestTopics(req: SuggestRequest, signal?: AbortSignal) {
  const d = req.document;
  return send(
    "/api/topics/suggest",
    {
      domain: req.domain,
      side: req.side,
      document: {
        label: d.label,
        detector_version: d.detectorVersion,
        clauses: d.clauses.map(({ id, text }) => ({ id, text })),
        acknowledged_unmasked: d.acknowledgedUnmasked.map((s) => [...s]),
      },
    },
    req,
    parseSuggest,
    signal,
  );
}

export interface TopicRequest extends CommonRequest {
  /** A topic definition; the server validates every field. */
  topic: TopicDefinition | Record<string, unknown>;
}

export function proposeAttributes(req: TopicRequest, signal?: AbortSignal) {
  return send("/api/topics/propose-attributes", { topic: req.topic }, req, parsePropose, signal);
}

export function expandSynonyms(req: TopicRequest, signal?: AbortSignal) {
  return send("/api/topics/expand-synonyms", { topic: req.topic }, req, parseExpand, signal);
}

export async function fetchCatalog(
  signal?: AbortSignal,
): Promise<{ ok: true; data: Catalog } | TopicFailure> {
  let response: Response;
  try {
    response = await fetch("/api/topics/catalog", {
      method: "GET",
      ...PINNED,
      ...(signal ? { signal } : {}),
    });
  } catch {
    return NETWORK;
  }
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    return UNKNOWN;
  }
  if (!response.ok) return failure(data);
  return isCatalog(data) ? { ok: true, data } : UNKNOWN;
}
