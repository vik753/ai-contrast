/**
 * Unit tests (frontend-dev) for `checkWithRetry` and `retryDelayMs`.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ExtractResult } from "../api/extract";
import { checkWithRetry, retryDelayMs } from "./check";

afterEach(() => {
  vi.useRealTimers();
});

const ok: ExtractResult = { ok: true, kind: "pdf", bytes: 1 };
const busy = (retryAfterSeconds?: number): ExtractResult =>
  retryAfterSeconds === undefined
    ? { ok: false, code: "busy" }
    : { ok: false, code: "busy", retryAfterSeconds };

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

describe("checkWithRetry", () => {
  it("returns the first non-busy result without waiting", async () => {
    const attempt = vi.fn(() => Promise.resolve(ok));
    await expect(checkWithRetry(attempt, new AbortController().signal)).resolves.toEqual(ok);
    expect(attempt).toHaveBeenCalledTimes(1);
  });

  it("uses the default delay when busy has no Retry-After", async () => {
    vi.useFakeTimers();
    const attempt = vi
      .fn<() => Promise<ExtractResult>>()
      .mockResolvedValueOnce(busy())
      .mockResolvedValueOnce(ok);
    const pending = checkWithRetry(attempt, new AbortController().signal);
    await vi.advanceTimersByTimeAsync(4_999);
    expect(attempt).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(attempt).toHaveBeenCalledTimes(2);
    await expect(pending).resolves.toEqual(ok);
  });

  it("stops after three busy answers", async () => {
    vi.useFakeTimers();
    const attempt = vi.fn(() => Promise.resolve(busy(1)));
    const pending = checkWithRetry(attempt, new AbortController().signal);
    await vi.advanceTimersByTimeAsync(60_000);
    await expect(pending).resolves.toMatchObject({ ok: false, code: "busy" });
    expect(attempt).toHaveBeenCalledTimes(3);
  });

  it("abort during the busy wait returns aborted and makes no new attempt", async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const attempt = vi.fn(() => Promise.resolve(busy(5)));
    const pending = checkWithRetry(attempt, controller.signal);
    await vi.advanceTimersByTimeAsync(1_000);
    controller.abort();
    await expect(pending).resolves.toEqual({ ok: false, code: "aborted" });
    await vi.advanceTimersByTimeAsync(10_000);
    expect(attempt).toHaveBeenCalledTimes(1);
  });

  it("already aborted signal makes no attempt", async () => {
    const controller = new AbortController();
    controller.abort();
    const attempt = vi.fn(() => Promise.resolve(ok));
    await expect(checkWithRetry(attempt, controller.signal)).resolves.toEqual({
      ok: false,
      code: "aborted",
    });
    expect(attempt).not.toHaveBeenCalled();
  });
});
