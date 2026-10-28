/**
 * Check scheduler for the upload form (S2-T2 AC4, AC8).
 *
 * - At most `MAX_PARALLEL_REQUESTS` requests in flight, counting the clause splits too
 *   (`RequestBudget`); the rest stay `queued`.
 * - `check` makes one attempt; this hook retries `busy` (see `checkWithRetry`).
 * - A file that waits for its hash (`awaitingHash`) is not sent yet, and holds back
 *   the files after it (display order).
 * - A file that leaves the state (file or contract removed) has its check
 *   aborted and its slot freed. Unmounting aborts every check.
 * - When the effect starts again (remount, StrictMode), `checking` files
 *   without a request in flight go back to `queued`, so no file is stuck.
 */
import { useEffect, useRef, useState, type Dispatch } from "react";
import type { ExtractResult } from "../api/extract";
import { checkWithRetry } from "./check";
import { createRequestBudget, freeSlots, released, type RequestBudget } from "./budget";
import { filesWithStatus, isPending, type UploadAction, type UploadState } from "./state";

/** One check attempt for one file. Must not throw. */
export type CheckFile = (file: { id: string }, signal: AbortSignal) => Promise<ExtractResult>;

export function useCheckScheduler(
  state: UploadState,
  dispatch: Dispatch<UploadAction>,
  check: CheckFile,
  budget?: RequestBudget,
): void {
  /** The budget is shared with the clause splits when the form passes one. */
  const [shared] = useState(() => budget ?? createRequestBudget());
  /** Bumped when the other scheduler frees a slot, so this effect runs again. */
  const [wakeCount, setWakeCount] = useState(0);

  useEffect(() => {
    const wake = (): void => {
      setWakeCount((count) => count + 1);
    };
    shared.wake.add(wake);
    return () => {
      shared.wake.delete(wake);
    };
  }, [shared]);
  const checkRef = useRef(check);

  useEffect(() => {
    checkRef.current = check;
  }, [check]);

  useEffect(() => {
    const inFlight = shared.checks;
    let freed = false;
    const pending = new Set(
      state.contracts.flatMap((c) => c.files.filter(isPending).map((f) => f.id)),
    );

    // Files removed from the state: abort their checks and free the slots.
    for (const [id, controller] of inFlight) {
      if (!pending.has(id)) {
        inFlight.delete(id);
        controller.abort();
        freed = true;
      }
    }
    if (freed) {
      // No state change follows an abort: wake the other scheduler to use the slot.
      released(shared);
    }

    // `checking` files that lost their request: queue them again.
    const orphans = filesWithStatus(state, "checking")
      .filter((file) => !inFlight.has(file.id))
      .map((file) => file.id);
    if (orphans.length > 0) {
      dispatch({ type: "checksRequeued", fileIds: orphans });
      return;
    }

    const free = freeSlots(shared);
    if (free <= 0) {
      return;
    }
    // Display order is kept: the first file still being hashed holds back those after it.
    const queued = filesWithStatus(state, "queued").filter((file) => !inFlight.has(file.id));
    const blocked = queued.findIndex((file) => file.awaitingHash === true);
    const next = (blocked === -1 ? queued : queued.slice(0, blocked)).slice(0, free);
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
  }, [state, dispatch, shared, wakeCount]);

  // Unmount: abort every check. A new mount starts with an empty map.
  useEffect(() => {
    const inFlight = shared.checks;
    return () => {
      for (const controller of inFlight.values()) {
        controller.abort();
      }
      inFlight.clear();
    };
  }, [shared]);
}
