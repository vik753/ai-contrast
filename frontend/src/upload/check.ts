/**
 * One file check with the `busy` retry policy (stage 2, S2-T2 AC4).
 */
import { extractFile, type ExtractResult } from "../api/extract";
import {
  DEFAULT_RETRY_DELAY_MS,
  MAX_CHECK_ATTEMPTS,
  MAX_RETRY_DELAY_MS,
  MIN_RETRY_DELAY_MS,
} from "./limits";

/** Delay before the next attempt after `busy`: `Retry-After`, capped. */
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
 * Checks one file. A `busy` answer is retried after its `Retry-After`
 * (at most 10 s), with at most 3 attempts in total. Never throws.
 */
export async function checkFile(file: Blob, signal: AbortSignal): Promise<ExtractResult> {
  for (let attempt = 1; ; attempt += 1) {
    const result = await extractFile(file, { signal });
    if (result.ok || result.code !== "busy" || attempt >= MAX_CHECK_ATTEMPTS) {
      return result;
    }
    const waited = await wait(retryDelayMs(result.retryAfterSeconds), signal);
    if (!waited) {
      return { ok: false, code: "aborted" };
    }
  }
}
