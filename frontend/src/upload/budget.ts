/**
 * One in-flight budget for every request of the upload form (S5-T2 review): file
 * checks and clause splits together never exceed `MAX_PARALLEL_REQUESTS`.
 * Each scheduler owns its map (to abort its own requests); the free slots are
 * counted over both.
 */
import { MAX_PARALLEL_REQUESTS } from "./limits";

export interface RequestBudget {
  /** Checks in flight (also during a `busy` wait), by file id. */
  readonly checks: Map<string, AbortController>;
  /** Clause splits in flight, by file id. */
  readonly splits: Map<string, AbortController>;
  /** Safety checks in flight, by contract id. */
  readonly safety: Map<string, AbortController>;
  /** Called after a slot was freed outside a state change (an abort), to wake the schedulers. */
  readonly wake: Set<() => void>;
}

export function createRequestBudget(): RequestBudget {
  return { checks: new Map(), splits: new Map(), safety: new Map(), wake: new Set() };
}

export function freeSlots(budget: RequestBudget): number {
  return MAX_PARALLEL_REQUESTS - budget.checks.size - budget.splits.size - budget.safety.size;
}

/** A slot was freed by an abort: no state changed, so the schedulers must look again. */
export function released(budget: RequestBudget): void {
  for (const wake of budget.wake) {
    wake();
  }
}
