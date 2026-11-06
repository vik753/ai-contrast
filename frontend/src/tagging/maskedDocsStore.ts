/**
 * In-memory store of the confirmed masked documents (S8-T3). Never persisted: no `localStorage`,
 * `sessionStorage` or IndexedDB. "Delete all data" empties it.
 */
import { useSyncExternalStore } from "react";
import type { SafetyDocument } from "../api/safetyCheck";

/** A masked document whose safety check passed, with the `digest` of the safety reply. */
export type MaskedDoc = SafetyDocument & { digest: string };

export interface MaskedDocsStore {
  get: () => readonly MaskedDoc[];
  set: (doc: MaskedDoc) => void;
  remove: (label: string) => void;
  clearAll: () => void;
  subscribe: (listener: () => void) => () => void;
}

export function createMaskedDocsStore(): MaskedDocsStore {
  let docs: readonly MaskedDoc[] = [];
  const listeners = new Set<() => void>();
  const publish = (next: readonly MaskedDoc[]): void => {
    docs = next;
    for (const l of listeners) l();
  };
  return {
    get: () => docs,
    set: (doc) => {
      const rest = docs.filter((d) => d.label !== doc.label);
      publish([...rest, doc].sort((a, b) => (a.label < b.label ? -1 : a.label > b.label ? 1 : 0)));
    },
    remove: (label) => {
      if (docs.some((d) => d.label === label)) publish(docs.filter((d) => d.label !== label));
    },
    clearAll: () => {
      if (docs.length > 0) publish([]);
      else for (const l of listeners) l();
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

export const maskedDocsStore: MaskedDocsStore = createMaskedDocsStore();

export function useMaskedDocs(): readonly MaskedDoc[] {
  return useSyncExternalStore(maskedDocsStore.subscribe, maskedDocsStore.get);
}
