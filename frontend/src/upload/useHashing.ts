/**
 * Hashing for the upload form (S4-T1). Hashes stay in memory (state), are never
 * stored, logged, shown or sent.
 *
 * - File bytes: hashed before the first request. The row
 *   stays `queued` until its hash is in the state. A failure (no Web Crypto,
 *   unreadable file) clears the wait without a hash: duplicate detection is a
 *   help, not a gate.
 * - Text: when a row is accepted and has no OCR pages left, its normalized text
 *   is hashed.
 * - A result for a row that left the state is dropped by the reducer.
 */
import { useEffect, useRef, type Dispatch } from "react";
import { sha256Hex } from "../hash/sha256";
import {
  needsOcr,
  textToHash,
  type AcceptedFile,
  type UploadAction,
  type UploadState,
} from "./state";
import type { GetFile } from "./useOcrScheduler";

export function useHashing(
  state: UploadState,
  dispatch: Dispatch<UploadAction>,
  getFile: GetFile,
): void {
  /** Rows whose byte hash was started: never started twice. */
  const orderRef = useRef<Promise<void>>(Promise.resolve());
  const fileStartedRef = useRef(new Set<string>());
  /** Rows whose text hash was started (or failed): never started twice. */
  const textStartedRef = useRef(new Set<string>());
  const getFileRef = useRef(getFile);
  const aliveRef = useRef(true);

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
      const blob = getFileRef.current(row.id);
      const work = (async () => {
        try {
          return blob === undefined ? undefined : await sha256Hex(await blob.arrayBuffer());
        } catch {
          return undefined;
        }
      })();
      // Results are applied in the order the rows were added, so of two copies the
      // first one is kept, whatever hash finishes first.
      const previous = orderRef.current;
      orderRef.current = (async () => {
        const hash = await work;
        await previous;
        if (aliveRef.current) {
          dispatch({ type: "fileHashed", fileId: row.id, ...(hash === undefined ? {} : { hash }) });
        }
      })();
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
        (f): f is AcceptedFile =>
          f.status === "accepted" && !needsOcr(f) && f.textHash === undefined && !started.has(f.id),
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
