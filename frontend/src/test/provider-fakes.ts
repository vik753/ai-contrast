/** Helpers for S6-T5 tests: a fake fetch and a check-response builder. */
import { vi, type Mock } from "vitest";

export interface Captured {
  url: string;
  method: string | undefined;
  headers: Headers;
  body: string | undefined;
  init: RequestInit;
}

export function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Replaces global fetch; every call is recorded. `reply` builds the answer. */
export function stubFetch(
  reply: () => Response | Promise<Response> = () => jsonResponse(200, { ok: true }),
): {
  fetchMock: Mock;
  calls: Captured[];
} {
  const calls: Captured[] = [];
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const i = init ?? {};
    calls.push({
      url: typeof input === "string" ? input : input instanceof URL ? input.href : input.url,
      method: i.method,
      headers: new Headers(i.headers),
      body: typeof i.body === "string" ? i.body : undefined,
      init: i,
    });
    return Promise.resolve(reply());
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}

export const FRAME_ORIGIN = "https://turnstile.example.test";
