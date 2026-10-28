/**
 * Clause split scheduler for the upload form (S5-T2 AC1, AC5).
 *
 * Same rules as `useCheckScheduler`:
 * - At most `MAX_PARALLEL_REQUESTS` requests in flight; `busy` is retried with a
 *   capped delay (`checkWithRetry`).
 * - A row starts when it is accepted and has no OCR pages left, so the request
 *   carries the OCR blocks in page order.
 * - A row that leaves the state (row or contract removed) has its request
 *   aborted and its slot freed. Unmounting aborts every request.
 * - When the effect starts again (remount, StrictMode), `running` rows without a
 *   request in flight go back to waiting, so no row is stuck.
 */
import { useEffect, useRef, type Dispatch } from "react";
import type { SegmentResult } from "../api/segment";
import { checkWithRetry } from "./check";
import { MAX_PARALLEL_REQUESTS } from "./limits";
import { awaitsSegment, type AcceptedFile, type UploadAction, type UploadState } from "./state";

/** One attempt to split one row. Must not throw. */
export type SegmentRow = (file: AcceptedFile, signal: AbortSignal) => Promise<SegmentResult>;

export function useSegmentScheduler(
  state: UploadState,
  dispatch: Dispatch<UploadAction>,
  segment: SegmentRow,
): void {
  /** Requests in flight (also during a `busy` wait), by file id. */
  const inFlightRef = useRef(new Map<string, AbortController>());
  const segmentRef = useRef(segment);

  useEffect(() => {
    segmentRef.current = segment;
  }, [segment]);

  useEffect(() => {
    const inFlight = inFlightRef.current;
    const waiting = state.contracts.flatMap((c) => c.files.filter(awaitsSegment));
    const waitingIds = new Set(waiting.map((f) => f.id));

    for (const [id, controller] of inFlight) {
      if (!waitingIds.has(id)) {
        inFlight.delete(id);
        controller.abort();
      }
    }

    const orphans = waiting
      .filter((file) => file.segment?.status === "running" && !inFlight.has(file.id))
      .map((file) => file.id);
    if (orphans.length > 0) {
      dispatch({ type: "segmentsRequeued", fileIds: orphans });
      return;
    }

    const free = MAX_PARALLEL_REQUESTS - inFlight.size;
    if (free <= 0) {
      return;
    }
    const next = waiting
      .filter((file) => file.segment === undefined && !inFlight.has(file.id))
      .slice(0, free);
    for (const file of next) {
      const controller = new AbortController();
      inFlight.set(file.id, controller);
      dispatch({ type: "segmentStarted", fileId: file.id });
      void checkWithRetry((signal) => segmentRef.current(file, signal), controller.signal).then(
        (result) => {
          if (inFlight.get(file.id) !== controller) {
            // Removed or unmounted meanwhile: the slot is already free.
            return;
          }
          inFlight.delete(file.id);
          dispatch({ type: "segmentFinished", fileId: file.id, result });
        },
      );
    }
  }, [state, dispatch]);

  // Unmount: abort every request. A new mount starts with an empty map.
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
