/**
 * Check scheduler for the upload form (S2-T2 AC4, AC8).
 *
 * - At most `MAX_PARALLEL_REQUESTS` checks in flight; the rest stay `queued`.
 * - `check` makes one attempt; this hook retries `busy` (see `checkWithRetry`).
 * - A file that leaves the state (file or contract removed) has its check
 *   aborted and its slot freed. Unmounting aborts every check.
 * - When the effect starts again (remount, StrictMode), `checking` files
 *   without a request in flight go back to `queued`, so no file is stuck.
 */
import { useEffect, useRef, type Dispatch } from "react";
import type { ExtractResult } from "../api/extract";
import { checkWithRetry } from "./check";
import { MAX_PARALLEL_REQUESTS } from "./limits";
import { filesWithStatus, isPending, type UploadAction, type UploadState } from "./state";

/** One check attempt for one file. Must not throw. */
export type CheckFile = (file: { id: string }, signal: AbortSignal) => Promise<ExtractResult>;

export function useCheckScheduler(
  state: UploadState,
  dispatch: Dispatch<UploadAction>,
  check: CheckFile,
): void {
  /** Requests in flight (also during a `busy` wait), by file id. */
  const inFlightRef = useRef(new Map<string, AbortController>());
  const checkRef = useRef(check);

  useEffect(() => {
    checkRef.current = check;
  }, [check]);

  useEffect(() => {
    const inFlight = inFlightRef.current;
    const pending = new Set(
      state.contracts.flatMap((c) => c.files.filter(isPending).map((f) => f.id)),
    );

    // Files removed from the state: abort their checks and free the slots.
    for (const [id, controller] of inFlight) {
      if (!pending.has(id)) {
        inFlight.delete(id);
        controller.abort();
      }
    }

    // `checking` files that lost their request: queue them again.
    const orphans = filesWithStatus(state, "checking")
      .filter((file) => !inFlight.has(file.id))
      .map((file) => file.id);
    if (orphans.length > 0) {
      dispatch({ type: "checksRequeued", fileIds: orphans });
      return;
    }

    const free = MAX_PARALLEL_REQUESTS - inFlight.size;
    if (free <= 0) {
      return;
    }
    const next = filesWithStatus(state, "queued")
      .filter((file) => !inFlight.has(file.id))
      .slice(0, free);
    for (const { id } of next) {
      const controller = new AbortController();
      inFlight.set(id, controller);
      dispatch({ type: "fileCheckStarted", fileId: id });
      void checkWithRetry((signal) => checkRef.current({ id }, signal), controller.signal).then(
        (result) => {
          if (inFlight.get(id) !== controller) {
            // Removed or unmounted meanwhile: the slot is already free.
            return;
          }
          inFlight.delete(id);
          dispatch({ type: "fileChecked", fileId: id, result });
        },
      );
    }
  }, [state, dispatch]);

  // Unmount: abort every check. A new mount starts with an empty map.
  useEffect(() => {
    const inFlight = inFlightRef.current;
    return () => {
      for (const controller of inFlight.values()) {
        controller.abort();
      }
      inFlight.clear();
    };
  }, []);
}
