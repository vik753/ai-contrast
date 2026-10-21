/**
 * The `busy` retry policy for one file check (S2-T2 AC4).
 */
import type { ExtractResult } from "../api/extract";
import {
  DEFAULT_RETRY_DELAY_MS,
  MAX_CHECK_ATTEMPTS,
  MAX_RETRY_DELAY_MS,
  MIN_RETRY_DELAY_MS,
} from "./limits";

/** Delay before the next attempt after `busy`: `Retry-After`, kept within 1–10 s. */
export function retryDelayMs(retryAfterSeconds: number | undefined): number {
  const requested =
    retryAfterSeconds === undefined || !Number.isFinite(retryAfterSeconds)
      ? DEFAULT_RETRY_DELAY_MS
      : retryAfterSeconds * 1000;
  return Math.min(MAX_RETRY_DELAY_MS, Math.max(MIN_RETRY_DELAY_MS, requested));
}

/** Resolves `true` after `ms`, or `false` as soon as `signal` aborts. */
function wait(ms: number, signal: AbortSignal): Promise<boolean> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve(false);
      return;
    }
    const onAbort = (): void => {
      clearTimeout(timer);
      resolve(false);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve(true);
    }, ms);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * Runs `attempt` until it gives a result other than `busy`, waiting
 * `Retry-After` (capped) between attempts; at most 3 attempts in total.
 * An abort stops the waiting and gives `aborted`. Never throws if `attempt`
 * never throws.
 */
export async function checkWithRetry(
  attempt: (signal: AbortSignal) => Promise<ExtractResult>,
  signal: AbortSignal,
): Promise<ExtractResult> {
  for (let number = 1; ; number += 1) {
    if (signal.aborted) {
      return { ok: false, code: "aborted" };
    }
    const result = await attempt(signal);
    if (result.ok || result.code !== "busy" || number >= MAX_CHECK_ATTEMPTS) {
      return result;
    }
    const waited = await wait(retryDelayMs(result.retryAfterSeconds), signal);
    if (!waited) {
      return { ok: false, code: "aborted" };
    }
  }
}
