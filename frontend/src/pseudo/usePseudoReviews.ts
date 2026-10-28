/**
 * Replacement reviews of the contracts in the upload form (S5b-T3).
 *
 * - One review per contract, created when the client opens "Check replacements". It holds the
 *   original values and the mapping: in memory only, here, never in storage, the URL, the
 *   console, an announcement or a request (ADR 0013 point 9a).
 * - A review is dropped when its contract leaves the form or when any of its rows changes
 *   (removed, added, split again). Its in-flight safety check is aborted with it.
 * - A contract is ready for analysis only after the safety check answered `ok`; every edit
 *   resets it. The review follows the contract, not its label: a contract that moves up after
 *   another one was removed keeps its review and its readiness (the label is only a prefix).
 * - The safety check shares the request budget of the form.
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type Dispatch,
} from "react";
import { checkSafety } from "../api/safetyCheck";
import { freeSlots, released, type RequestBudget } from "../upload/budget";
import {
  contractLabel,
  isActive,
  type AcceptedFile,
  type UploadAction,
  type UploadState,
} from "../upload/state";
import {
  acknowledgedUnmasked,
  applyUnmaskedIdentifiers,
  maskedClauses,
  mergeSegmentations,
  relabel,
  startReview,
  type Review,
} from "./masking";

export type Phase = "editing" | "checking" | "ready" | "confirmAgain";

export interface Entry {
  /** The segmentations the review was made from; a change drops the review. */
  readonly sources: readonly object[] | null;
  readonly review: Review | null;
  readonly phase: Phase;
  /** An error code (ours, never server text) shown next to the status. */
  readonly error: string | null;
}

export interface ContractSection {
  /** Every row has its clauses: the review can start. */
  readonly available: boolean;
  readonly entry: Entry | undefined;
  readonly open: () => void;
  readonly edit: (review: Review) => void;
  readonly confirm: () => void;
}

export interface PseudoReviews {
  readonly forContract: (contractId: string, index: number) => ContractSection;
}

interface Sources {
  readonly parts: readonly object[];
  readonly files: readonly AcceptedFile[];
}

/** The done rows of a contract, or `null` while a row has no clauses yet. */
function sourcesOf(state: UploadState, contractId: string): Sources | null {
  const contract = state.contracts.find((c) => c.id === contractId);
  const files = contract?.files.filter(isActive) ?? [];
  const parts: object[] = [];
  const accepted: AcceptedFile[] = [];
  for (const file of files) {
    if (file.status !== "accepted" || file.segment?.status !== "done") {
      return null;
    }
    parts.push(file.segment);
    accepted.push(file);
  }
  return parts.length === 0 ? null : { parts, files: accepted };
}

function sameSources(a: readonly object[] | null, b: readonly object[]): boolean {
  return a !== null && a.length === b.length && a.every((item, i) => item === b[i]);
}

function reviewOf(sources: Sources, label: string): Review | null {
  const merged = mergeSegmentations(
    sources.files.flatMap((file) =>
      file.segment?.status === "done"
        ? [
            {
              clauses: file.segment.clauses,
              blocks: file.extraction.blocks,
              removed: [],
              warnings: file.segment.warnings,
              ...file.segment.detection,
            },
          ]
        : [],
    ),
  );
  return merged === null ? null : startReview(merged, label);
}

/** The entries live in a small store, so that dropping one from an effect is not a state update. */
class EntryStore {
  private entries: ReadonlyMap<string, Entry> = new Map();
  private readonly listeners = new Set<() => void>();

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  readonly get = (): ReadonlyMap<string, Entry> => this.entries;

  update(change: (current: ReadonlyMap<string, Entry>) => ReadonlyMap<string, Entry>): void {
    this.entries = change(this.entries);
    for (const listener of this.listeners) {
      listener();
    }
  }
}

export function usePseudoReviews(
  state: UploadState,
  dispatch: Dispatch<UploadAction>,
  budget: RequestBudget,
): PseudoReviews {
  const [store] = useState(() => new EntryStore());
  const entries = useSyncExternalStore(store.subscribe, store.get);
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  });

  const abort = useCallback(
    (contractId: string): void => {
      const controller = budget.safety.get(contractId);
      if (controller !== undefined) {
        budget.safety.delete(contractId);
        controller.abort();
        released(budget);
      }
    },
    [budget],
  );

  const put = useCallback(
    (contractId: string, entry: Entry | null): void => {
      store.update((current) => {
        const next = new Map(current);
        if (entry === null) {
          next.delete(contractId);
        } else {
          next.set(contractId, entry);
        }
        return next;
      });
    },
    [store],
  );

  // Drop a review whose contract left or whose rows changed. Its request ends with it.
  useEffect(() => {
    const stale: string[] = [];
    for (const [id, entry] of entries) {
      const sources = sourcesOf(state, id);
      const gone = !state.contracts.some((c) => c.id === id);
      if (
        gone ||
        (entry.review !== null && (sources === null || !sameSources(entry.sources, sources.parts)))
      ) {
        stale.push(id);
      }
    }
    if (stale.length === 0) {
      return;
    }
    for (const id of stale) {
      abort(id);
    }
    store.update((current) => {
      const next = new Map(current);
      for (const id of stale) {
        next.delete(id);
      }
      return next;
    });
  }, [state, entries, abort, store]);

  // Unmount: abort every request.
  useEffect(() => {
    const running = budget.safety;
    return () => {
      for (const controller of running.values()) {
        controller.abort();
      }
      running.clear();
    };
  }, [budget]);

  const labelOf = (contractId: string): string =>
    contractLabel(stateRef.current.contracts.findIndex((c) => c.id === contractId));

  const confirm = (contractId: string): void => {
    const entry = store.get().get(contractId);
    if (entry?.review === undefined || entry.review === null || budget.safety.has(contractId)) {
      return;
    }
    const review = relabel(entry.review, labelOf(contractId));
    if (freeSlots(budget) <= 0) {
      put(contractId, { ...entry, review, phase: "editing", error: "busy" });
      return;
    }
    const controller = new AbortController();
    budget.safety.set(contractId, controller);
    put(contractId, { ...entry, review, phase: "checking", error: null });
    void checkSafety(
      {
        label: review.label,
        detectorVersion: review.detectorVersion,
        clauses: maskedClauses(review),
        acknowledgedUnmasked: acknowledgedUnmasked(review),
      },
      { signal: controller.signal },
    ).then((result) => {
      if (budget.safety.get(contractId) !== controller) {
        return;
      }
      budget.safety.delete(contractId);
      released(budget);
      const current = store.get().get(contractId);
      if (current?.review === undefined || current.review === null) {
        return;
      }
      if (result.ok) {
        put(contractId, { ...current, phase: "ready", error: null });
      } else if (result.code === "unmasked_identifier" && result.spans !== undefined) {
        put(contractId, {
          ...current,
          review: applyUnmaskedIdentifiers(current.review, result.spans),
          phase: "confirmAgain",
          error: "unmasked_identifier",
        });
      } else if (result.code === "detector_version_mismatch") {
        const sources = sourcesOf(stateRef.current, contractId);
        dispatch({
          type: "segmentsRestarted",
          fileIds: sources?.files.map((file) => file.id) ?? [],
        });
        put(contractId, { sources: null, review: null, phase: "editing", error: result.code });
      } else if (result.code !== "aborted") {
        put(contractId, { ...current, phase: "editing", error: result.code });
      }
    });
  };

  const forContract = (contractId: string, index: number): ContractSection => {
    const sources = sourcesOf(state, contractId);
    const found = entries.get(contractId);
    const entry =
      found !== undefined &&
      (found.review === null || (sources !== null && sameSources(found.sources, sources.parts)))
        ? found
        : undefined;
    return {
      available: sources !== null,
      entry,
      open: () => {
        const now = sourcesOf(stateRef.current, contractId);
        const review = now === null ? null : reviewOf(now, contractLabel(index));
        if (now !== null && review !== null) {
          put(contractId, { sources: now.parts, review, phase: "editing", error: null });
        }
      },
      edit: (review) => {
        const current = store.get().get(contractId);
        if (current === undefined) {
          return;
        }
        abort(contractId);
        put(contractId, { ...current, review, phase: "editing", error: null });
      },
      confirm: () => {
        confirm(contractId);
      },
    };
  };

  return { forContract };
}
