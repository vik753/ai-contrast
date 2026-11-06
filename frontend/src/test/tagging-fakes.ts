/** Helpers for S8-T3 tests: synthetic masked documents, tag replies, a routing fake fetch. */
import { vi } from "vitest";
import type { MaskedDoc } from "../tagging/maskedDocsStore";
import type { TopicSelection } from "../topics/types";
import { jsonResponse, type Captured } from "./provider-fakes";

export const DIGEST_A = "a".repeat(64);
export const DIGEST_B = "b".repeat(64);

export function maskedDoc(label: string, digest = DIGEST_A, texts?: string[]): MaskedDoc {
  const list = texts ?? [
    "1.1. The deductible is 5 percent.",
    "1.2. Theft is covered.",
    "1.3. The insurer may terminate the contract unilaterally.",
  ];
  return {
    label,
    detectorVersion: "pseudo-1",
    clauses: list.map((text, i) => ({ id: `c${i + 1}`, text })),
    acknowledgedUnmasked: [],
    digest,
  };
}

export const SELECTION: TopicSelection = {
  catalog: [
    { domain: "kasko", topic_id: "deductible", side: "insured", lang: "en", catalog_version: "v1" },
    {
      domain: "kasko",
      topic_id: "theft_cover",
      side: "insured",
      lang: "en",
      catalog_version: "v1",
    },
  ],
  suggested: [],
  custom: [],
};

export const NAMES = { deductible: "Deductible", theft_cover: "Theft cover" };

/** A full 200 reply for `maskedDoc` (three clauses). */
export function tagReply(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    digest: DIGEST_A,
    tagging_version: "tv-1",
    signature: "sig-abc",
    tags: {
      c1: [{ topic_id: "deductible", source: "keyword" }],
      c2: [{ topic_id: "theft_cover", source: "model" }],
      c3: [],
    },
    other: ["c3"],
    risk: { c3: [[9, 18]] },
    topics: {
      deductible: {
        keyword_clauses: 1,
        model_clauses: 0,
        model_asserted: 0,
        model_tags_dropped: false,
        not_analyzed: null,
      },
      theft_cover: {
        keyword_clauses: 0,
        model_clauses: 1,
        model_asserted: 1,
        model_tags_dropped: false,
        not_analyzed: null,
      },
    },
    missing_topics: [],
    layer2: {},
    model_tagging_incomplete: false,
    incomplete_reasons: [],
    ...over,
  };
}

export type Router = (c: Captured) => Response | Promise<Response> | undefined;

/** Routes `/api/tag`; default reply is `tagReply()`. Records every call. */
export function stubTagFetch(route: Router = () => undefined): { calls: Captured[] } {
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
      if (c.url === "/api/tag") return Promise.resolve(jsonResponse(200, tagReply()));
      return Promise.resolve(jsonResponse(500, { error: "unknown" }));
    }),
  );
  return { calls };
}

export const tagCalls = (calls: Captured[]): Captured[] =>
  calls.filter((c) => c.url === "/api/tag");
export const bodyOf = (c: Captured): Record<string, unknown> =>
  JSON.parse(c.body ?? "{}") as Record<string, unknown>;
