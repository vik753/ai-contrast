/**
 * `POST /api/tag` helper (ADR 0018). The key goes only into `X-Provider-Key`, the analysis pass
 * only into `X-Analysis-Pass`. Server text is never returned: only closed codes and parsed ids,
 * enums, counts and offsets.
 */
import type { SafetyDocument } from "../api/safetyCheck";
import type { TopicSelection } from "../topics/types";

export const TAG_ERROR_CODES: readonly string[] = [
  "request_too_large",
  "invalid_request",
  "invalid_provider",
  "invalid_model",
  "unexpected_model",
  "unexpected_base_url",
  "invalid_base_url",
  "unexpected_turnstile_token",
  "invalid_provider_key",
  "unexpected_provider_key",
  "unexpected_analysis_pass",
  "unmasked_identifier",
  "detector_version_mismatch",
  "too_many_topics",
  "unknown_topic",
  "no_topics",
  "catalog_version_mismatch",
  "topic_flagged",
  "keyword_budget_exceeded",
  "document_too_large_for_tagging",
  "too_many_documents",
  "free_too_large",
  "analysis_pass_invalid",
  "analysis_pass_expired",
  "analysis_pass_exhausted",
  "analysis_pass_unavailable",
  "turnstile_failed",
  "free_quota_exhausted",
  "free_mode_unavailable",
  "rate_limited",
  "busy",
  "provider_auth_failed",
  "provider_model_not_found",
  "provider_bad_request",
  "provider_blocked_host",
];

const KNOWN: ReadonlySet<string> = new Set(TAG_ERROR_CODES);

export type TagSource = "keyword" | "model" | "check";
export type Layer2Class = "heuristic" | "high";
export type IncompleteReason = "bad_output" | "timeout" | "quota" | "check_failed" | "clause_cap";

export interface TopicStats {
  keyword_clauses: number;
  model_clauses: number;
  model_asserted: number;
  model_tags_dropped: boolean;
  not_analyzed: "too_many_clauses" | null;
}

export type Span = readonly [number, number];
export type Layer2Hit = readonly [number, number, Layer2Class];

/** The wire reply (snake_case) without `analysis_pass`. */
export interface TagReply {
  digest: string;
  tagging_version: string;
  signature: string;
  tags: Record<string, { topic_id: string; source: TagSource }[]>;
  other: string[];
  risk: Record<string, Span[]>;
  topics: Record<string, TopicStats>;
  missing_topics: string[];
  layer2: Record<string, { text: Layer2Hit[]; heading: Layer2Hit[] }>;
  model_tagging_incomplete: boolean;
  incomplete_reasons: IncompleteReason[];
}

export type TagResult =
  { ok: true; data: TagReply; analysisPass?: string } | { ok: false; code: string };

export interface TagRequest {
  provider: string;
  model?: string;
  checkModel?: string;
  baseUrl?: string;
  key?: string;
  turnstileToken?: string;
  analysisPass?: string;
  domain: string;
  side: string;
  document: SafetyDocument;
  topics: TopicSelection;
}

const UNKNOWN = { ok: false, code: "unknown" } as const;
const NETWORK = { ok: false, code: "network" } as const;
const PINNED = { credentials: "omit", redirect: "error", cache: "no-store" } as const;

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isCount = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v) && v >= 0;
const isBool = (v: unknown): v is boolean => typeof v === "boolean";
const ID_RE = /^[A-Za-z0-9_]{1,64}$/;
const REASONS: readonly string[] = ["bad_output", "timeout", "quota", "check_failed", "clause_cap"];

function idList(v: unknown): v is string[] {
  return Array.isArray(v) && v.every((x) => isStr(x) && ID_RE.test(x));
}
function spanOk(v: unknown, n: number): boolean {
  return (
    Array.isArray(v) &&
    v.length === n &&
    isCount(v[0]) &&
    isCount(v[1]) &&
    v[0] <= v[1] &&
    (n === 2 || v[2] === "heuristic" || v[2] === "high")
  );
}
function mapOf(v: unknown, ok: (x: unknown) => boolean): v is Record<string, unknown> {
  return isRecord(v) && Object.entries(v).every(([k, x]) => ID_RE.test(k) && ok(x));
}
function onlyKeys(o: Record<string, unknown>, keys: readonly string[]): boolean {
  const k = Object.keys(o);
  return k.length === keys.length && keys.every((x) => x in o);
}

const REPLY_KEYS = [
  "digest",
  "tagging_version",
  "signature",
  "tags",
  "other",
  "risk",
  "topics",
  "missing_topics",
  "layer2",
  "model_tagging_incomplete",
  "incomplete_reasons",
];

function parseReply(o: Record<string, unknown>): TagReply | null {
  if (!onlyKeys(o, REPLY_KEYS)) return null;
  if (!isStr(o.digest) || !/^[0-9a-f]{64}$/.test(o.digest)) return null;
  if (!isStr(o.tagging_version) || o.tagging_version.length > 256) return null;
  if (!isStr(o.signature) || o.signature.length > 1024) return null;
  const tagOk = (x: unknown): boolean =>
    Array.isArray(x) &&
    x.every(
      (p) =>
        isRecord(p) &&
        onlyKeys(p, ["topic_id", "source"]) &&
        isStr(p.topic_id) &&
        ID_RE.test(p.topic_id) &&
        (p.source === "keyword" || p.source === "model" || p.source === "check"),
    );
  if (!mapOf(o.tags, tagOk)) return null;
  if (!idList(o.other) || !idList(o.missing_topics)) return null;
  if (!mapOf(o.risk, (x) => Array.isArray(x) && x.every((s) => spanOk(s, 2)))) return null;
  const topicOk = (x: unknown): boolean =>
    isRecord(x) &&
    onlyKeys(x, [
      "keyword_clauses",
      "model_clauses",
      "model_asserted",
      "model_tags_dropped",
      "not_analyzed",
    ]) &&
    isCount(x.keyword_clauses) &&
    isCount(x.model_clauses) &&
    isCount(x.model_asserted) &&
    isBool(x.model_tags_dropped) &&
    (x.not_analyzed === null || x.not_analyzed === "too_many_clauses");
  if (!mapOf(o.topics, topicOk)) return null;
  const hits = (v: unknown): boolean => Array.isArray(v) && v.every((s) => spanOk(s, 3));
  const layerOk = (x: unknown): boolean =>
    isRecord(x) && onlyKeys(x, ["text", "heading"]) && hits(x.text) && hits(x.heading);
  if (!mapOf(o.layer2, layerOk)) return null;
  if (!isBool(o.model_tagging_incomplete)) return null;
  if (
    !Array.isArray(o.incomplete_reasons) ||
    !o.incomplete_reasons.every((r) => REASONS.includes(r as string))
  ) {
    return null;
  }
  return o as unknown as TagReply;
}

export async function tagDocument(req: TagRequest, signal?: AbortSignal): Promise<TagResult> {
  const d = req.document;
  const payload: Record<string, unknown> = { provider: req.provider };
  if (req.model !== undefined) payload.model = req.model;
  if (req.checkModel !== undefined) payload.check_model = req.checkModel;
  if (req.baseUrl !== undefined) payload.base_url = req.baseUrl;
  if (req.turnstileToken !== undefined) payload.turnstile_token = req.turnstileToken;
  payload.domain = req.domain;
  payload.side = req.side;
  payload.document = {
    label: d.label,
    detector_version: d.detectorVersion,
    clauses: d.clauses.map(({ id, text }) => ({ id, text })),
    acknowledged_unmasked: d.acknowledgedUnmasked.map((s) => [...s]),
  };
  payload.topics = req.topics;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (req.key !== undefined) headers["X-Provider-Key"] = req.key;
  if (req.analysisPass !== undefined) headers["X-Analysis-Pass"] = req.analysisPass;

  let response: Response;
  try {
    response = await fetch("/api/tag", {
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
  if (!isRecord(data)) return UNKNOWN;
  if (!response.ok) {
    return isStr(data.error) && KNOWN.has(data.error) ? { ok: false, code: data.error } : UNKNOWN;
  }
  const { analysis_pass: pass, ...rest } = data;
  if (pass !== undefined && !(isStr(pass) && pass.length >= 1 && pass.length <= 512)) {
    return UNKNOWN;
  }
  const parsed = parseReply(rest);
  if (parsed === null) return UNKNOWN;
  return pass === undefined
    ? { ok: true, data: parsed }
    : { ok: true, data: parsed, analysisPass: pass };
}
