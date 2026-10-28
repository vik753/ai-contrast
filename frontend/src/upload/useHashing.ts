/**
 * Hashing for the upload form (S4-T1). Hashes stay in memory (state), are never
 * stored, logged, shown or sent.
 *
 * - File bytes: hashed before the first request. The row
 *   stays `queued` until its hash is in the state. A failure (no Web Crypto,
 *   unreadable file) clears the wait without a hash: duplicate detection is a
 *   help, not a gate.
 * - Text: when a row has its clauses (the text is then the cleaned text of the
 *   server, S5-T2), its normalized text is hashed.
 * - A result for a row that left the state is dropped by the reducer.
 */
import { useEffect, useRef, type Dispatch } from "react";
import { sha256Hex } from "../hash/sha256";
import {
  isSegmented,
  textToHash,
  type AcceptedFile,
  type UploadAction,
  type UploadState,
} from "./state";
import type { GetFile } from "./useOcrScheduler";

/** Longest wait for reading and hashing one file. Later rows must not wait longer. */
export const HASH_TIMEOUT_MS = 30_000;

/** Hash of the bytes, or `undefined` on error or timeout (the row goes on without one). */
async function hashFile(blob: File | undefined): Promise<string | undefined> {
  if (blob === undefined) {
    return undefined;
  }
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<undefined>((resolve) => {
    timer = setTimeout(() => {
      resolve(undefined);
    }, HASH_TIMEOUT_MS);
  });
  try {
    return await Promise.race([blob.arrayBuffer().then(sha256Hex), timeout]);
  } catch {
    return undefined;
  } finally {
    clearTimeout(timer);
  }
}

export function useHashing(
  state: UploadState,
  dispatch: Dispatch<UploadAction>,
  getFile: GetFile,
): void {
  const orderRef = useRef<Promise<void>>(Promise.resolve());
  /** Rows whose byte hash was started: never started twice. Dropped with the row. */
  const fileStartedRef = useRef(new Set<string>());
  /**
   * Rows whose text hash was started (or failed): never started twice. A failed text
   * hash is advisory: the row keeps no `textHash`, so `contractTextHash` stays `null`
   * for its contract. Stage 9 must handle that `null`.
   */
  const textStartedRef = useRef(new Set<string>());
  const getFileRef = useRef(getFile);
  const aliveRef = useRef(true);
  const isAlive = (): boolean => aliveRef.current;

  useEffect(() => {
    getFileRef.current = getFile;
  }, [getFile]);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  useEffect(() => {
    const started = fileStartedRef.current;
    const files = state.contracts.flatMap((c) => c.files);
    for (const id of started) {
      if (!files.some((f) => f.id === id)) {
        started.delete(id);
      }
    }
    for (const row of files) {
      if (row.status !== "queued" || row.awaitingHash !== true || started.has(row.id)) {
        continue;
      }
      started.add(row.id);
      // One file at a time (memory): the bytes are read inside the chain, not before it.
      // Results are applied in the order the rows were added, so of two copies the
      // first one is kept.
      orderRef.current = orderRef.current.then(async () => {
        if (!started.has(row.id) || !isAlive()) {
          return; // The row left the state meanwhile: skip the work.
        }
        const hash = await hashFile(getFileRef.current(row.id));
        if (isAlive()) {
          dispatch({ type: "fileHashed", fileId: row.id, ...(hash === undefined ? {} : { hash }) });
        }
      });
    }
  }, [state, dispatch]);

  useEffect(() => {
    const started = textStartedRef.current;
    const present = new Set(state.contracts.flatMap((c) => c.files.map((f) => f.id)));
    for (const id of started) {
      if (!present.has(id)) {
        started.delete(id);
      }
    }
    const rows = state.contracts
      .flatMap((c) => c.files)
      .filter(
        (f): f is AcceptedFile => isSegmented(f) && f.textHash === undefined && !started.has(f.id),
      );
    for (const row of rows) {
      started.add(row.id);
      void sha256Hex(textToHash(row)).then(
        (hash) => {
          if (aliveRef.current) {
            dispatch({ type: "textHashed", fileId: row.id, hash });
          }
        },
        () => undefined,
      );
    }
  }, [state, dispatch]);
}
