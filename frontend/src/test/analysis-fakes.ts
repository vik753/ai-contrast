/** Helpers for S9-T4 tests: SSE responses, wire events, a routing fake fetch. Not a test file. */
import { vi } from "vitest";
import type { TaggingResult } from "../tagging/TaggingStep";
import { DIGEST_A, tagReply } from "./tagging-fakes";
import { jsonResponse, type Captured } from "./provider-fakes";

export const SIG = "f".repeat(64);
export const enc = new TextEncoder();

export const frame = (name: string, data: unknown): string =>
  `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;

export function streamOf(chunks: readonly (string | Uint8Array)[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(c) {
      for (const x of chunks) c.enqueue(typeof x === "string" ? enc.encode(x) : x);
      c.close();
    },
  });
}

export const sseResponse = (chunks: readonly (string | Uint8Array)[], status = 200): Response =>
  new Response(streamOf(chunks), {
    status,
    headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-store" },
  });

/** A stream the test feeds by hand. */
export function controlled() {
  let ctl!: ReadableStreamDefaultController<Uint8Array>;
  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      ctl = c;
    },
    cancel() {
      cancelled = true;
    },
  });
  return {
    response: new Response(body, {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    }),
    push: (s: string) => {
      try {
        ctl.enqueue(enc.encode(s));
      } catch {
        // closed or cancelled: a late push is dropped, as on a real socket
      }
    },
    close: () => {
      try {
        ctl.close();
      } catch {
        // already closed
      }
    },
    cancelled: () => cancelled,
  };
}

export const evStart = (over: Record<string, unknown> = {}) => ({
  digest: DIGEST_A,
  topics: 2,
  other_batches: 1,
  reserved_calls: 6,
  ...over,
});

export const finding = (over: Record<string, unknown> = {}) => ({
  rating: "green",
  attribute: null,
  explanation: "Fine for the client.",
  reasons: [],
  unverified: false,
  evidence: [["c1", 0, 10]],
  attached: [],
  ...over,
});

export const value = (over: Record<string, unknown> = {}) => ({
  attribute: "amount",
  value: { type: "amount", number: 5000, currency: "UAH" },
  status: "verified",
  reasons: [],
  evidence: [["c1", 20, 31]],
  ...over,
});

export const evTopic = (topicId: string, over: Record<string, unknown> = {}) => ({
  topic_id: topicId,
  state: "ok",
  reason: null,
  clauses: ["c1"],
  missing: null,
  values: [],
  findings: [],
  ...over,
});

export const evOther = (over: Record<string, unknown> = {}) => ({
  batch: 0,
  part: 0,
  clauses: ["c3"],
  rated: true,
  reason: null,
  no_issue: [],
  findings: [],
  ...over,
});

export const evDone = (over: Record<string, unknown> = {}) => ({
  digest: DIGEST_A,
  incomplete: false,
  unrated_other: 0,
  greens_allowed: true,
  not_analyzed: [],
  flags: [],
  result_signature: SIG,
  analysis_version: "av-1",
  ...over,
});

/** Frames of a normal run: start, topics, other, progress, done. */
export function runFrames(
  topics: Record<string, Record<string, unknown>> = { deductible: {}, theft_cover: {} },
  opts: { done?: Record<string, unknown> | null; other?: Record<string, unknown> } = {},
): string[] {
  const out = [frame("start", evStart({ topics: Object.keys(topics).length }))];
  for (const [id, over] of Object.entries(topics)) out.push(frame("topic", evTopic(id, over)));
  out.push(frame("other", evOther(opts.other)));
  out.push(frame("progress", { done: 6, total: 6 }));
  if (opts.done !== null) out.push(frame("done", evDone(opts.done)));
  return out;
}

export function taggingResult(label: string, digest = DIGEST_A, pass?: string): TaggingResult {
  return {
    label,
    digest,
    taggingVersion: "tv-1",
    signature: `sig-${label}`,
    reply: tagReply({ digest }) as never,
    clientTags: {},
    ...(pass === undefined ? {} : { analysisPass: pass }),
  };
}

export type Router = (c: Captured) => Response | Promise<Response> | undefined;

/** Routes `/api/analyze` (default: a normal run with the document's digest). Records every call. */
export function stubAnalyzeFetch(route: Router = () => undefined): { calls: Captured[] } {
  const calls: Captured[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const i = init ?? {};
      const c: Captured = {
        url: typeof input === "string" ? input : input instanceof URL ? input.href : input.url,
        method: i.method,
        headers: new Headers(i.headers),
        body: typeof i.body === "string" ? i.body : undefined,
        init: i,
      };
      calls.push(c);
      const r = route(c);
      if (r) return Promise.resolve(r);
      if (c.url === "/api/analyze") return Promise.resolve(sseResponse(runFrames()));
      return Promise.resolve(jsonResponse(500, { error: "unknown" }));
    }),
  );
  return { calls };
}

export const analyzeCalls = (calls: Captured[]): Captured[] =>
  calls.filter((c) => c.url === "/api/analyze");
export const labelOf = (c: Captured): string =>
  (JSON.parse(c.body ?? "{}") as { document: { label: string } }).document.label;
