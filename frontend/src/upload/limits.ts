/**
 * Upload limits (stage 2 limits table in docs/agent/TASKS.md).
 * The browser enforces them before any request; the server is still the
 * source of truth for the file size and type (threat model T4, T6).
 */

/**
 * Largest file in bytes (10 MiB). The server has the same limit.
 * Sizes in the UI are 1024-based: "1 MB" means 1024² bytes (see `format.ts`).
 */
export const MAX_FILE_BYTES = 10 * 1024 * 1024;

/** Files per contract: main text plus annexes. */
export const MAX_FILES_PER_CONTRACT = 5;

/** Contracts per analysis. */
export const MAX_CONTRACTS = 5;

/** A comparison needs at least two contracts. */
export const MIN_CONTRACTS = 2;

/** Total size of all files in one analysis (50 MiB). */
export const MAX_TOTAL_BYTES = 50 * 1024 * 1024;

/** File checks in flight in the whole form. The server allows 2 extractions. */
export const MAX_PARALLEL_REQUESTS = 2;

/** Attempts per file when the server answers `busy` (first try included). */
export const MAX_CHECK_ATTEMPTS = 3;

/** Upper bound for the `Retry-After` delay of a `busy` answer. */
export const MAX_RETRY_DELAY_MS = 10_000;

/** Delay when a `busy` answer has no usable `Retry-After` header. */
export const DEFAULT_RETRY_DELAY_MS = 5_000;

/** Lower bound for the retry delay, so that a `Retry-After: 0` never spins. */
export const MIN_RETRY_DELAY_MS = 1_000;
