/**
 * Unit tests (frontend-dev) for `checkFile` and `retryDelayMs`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeFetch, acceptAsPdf, busyResponse, makeFile } from "../test/upload-fakes";
import type { ExtractResult } from "../api/extract";
import { checkFile, retryDelayMs } from "./check";

let server: FakeFetch;

beforeEach(() => {
  server = new FakeFetch();
  vi.stubGlobal("fetch", server.fetch);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("retryDelayMs", () => {
  it.each([
    [undefined, 5_000],
    [0, 1_000],
    [1, 1_000],
    [5, 5_000],
    [10, 10_000],
    [11, 10_000],
    [999_999, 10_000],
    [Number.NaN, 5_000],
    [Number.POSITIVE_INFINITY, 5_000],
  ])("retry after %s s waits %i ms", (seconds, expected) => {
    expect(retryDelayMs(seconds)).toBe(expected);
  });
});

describe("checkFile", () => {
  it("returns the first non-busy result without waiting", async () => {
    server.autoRespond = acceptAsPdf;
    const file = makeFile("a.pdf");
    const result = await checkFile(file, new AbortController().signal);
    expect(result).toEqual({ ok: true, kind: "pdf", bytes: file.size });
    expect(server.calls).toHaveLength(1);
  });

  it("uses the default delay when busy has no Retry-After", async () => {
    vi.useFakeTimers();
    const pending = checkFile(makeFile("a.pdf"), new AbortController().signal);
    await vi.advanceTimersByTimeAsync(0);
    server.calls[0]?.respond(busyResponse(null));
    await vi.advanceTimersByTimeAsync(4_999);
    expect(server.calls).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(server.calls).toHaveLength(2);
    const second = server.calls[1];
    second?.respond(acceptAsPdf(second.body));
    await expect(pending).resolves.toMatchObject({ ok: true });
  });

  it("abort during the busy wait returns aborted and sends nothing more", async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    let result: ExtractResult | undefined;
    void checkFile(makeFile("a.pdf"), controller.signal).then((r) => {
      result = r;
    });
    await vi.advanceTimersByTimeAsync(0);
    server.calls[0]?.respond(busyResponse("5"));
    await vi.advanceTimersByTimeAsync(1_000);
    controller.abort();
    await vi.advanceTimersByTimeAsync(0);
    expect(result).toEqual({ ok: false, code: "aborted" });
    await vi.advanceTimersByTimeAsync(10_000);
    expect(server.calls).toHaveLength(1);
  });

  it("already aborted signal sends no request", async () => {
    const controller = new AbortController();
    controller.abort();
    const result = await checkFile(makeFile("a.pdf"), controller.signal);
    expect(result).toEqual({ ok: false, code: "aborted" });
    expect(server.calls).toHaveLength(0);
  });
});
