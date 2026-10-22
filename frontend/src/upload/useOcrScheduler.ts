/**
 * OCR scheduler for the upload form (S3-T5 AC5, AC7).
 *
 * - At most one OCR job in the whole form. Other scans wait, in display order.
 * - The OCR module (pdf.js, Tesseract) is imported only when a job starts.
 * - A file that leaves the state (removed, rejected, finished) has its job
 *   aborted. Unmounting aborts the running job. A result that arrives after an
 *   abort is ignored.
 * - A failure rejects the file with `ocr_failed`. The error itself is dropped:
 *   it may contain document data (threat model T1).
 */
import { useEffect, useRef, type Dispatch } from "react";
import { needsOcr, type AcceptedFile, type UploadAction, type UploadState } from "./state";

/** The original `File` of an accepted file, or `undefined` if it is gone. */
export type GetFile = (fileId: string) => File | undefined;

interface Job {
  readonly fileId: string;
  readonly controller: AbortController;
}

function scans(state: UploadState): AcceptedFile[] {
  return state.contracts.flatMap((c) =>
    c.files.filter((f): f is AcceptedFile => f.status === "accepted" && needsOcr(f)),
  );
}

export function useOcrScheduler(
  state: UploadState,
  dispatch: Dispatch<UploadAction>,
  getFile: GetFile,
): void {
  const jobRef = useRef<Job | null>(null);
  const getFileRef = useRef(getFile);

  useEffect(() => {
    getFileRef.current = getFile;
  }, [getFile]);

  useEffect(() => {
    const waiting = scans(state);
    const running = jobRef.current;
    if (running !== null && !waiting.some((f) => f.id === running.fileId)) {
      jobRef.current = null;
      running.controller.abort();
    }
    if (jobRef.current !== null) {
      return;
    }
    const next = waiting[0];
    if (next === undefined) {
      return;
    }
    const file = getFileRef.current(next.id);
    if (file === undefined) {
      dispatch({ type: "ocrFailed", fileId: next.id });
      return;
    }
    const job: Job = { fileId: next.id, controller: new AbortController() };
    jobRef.current = job;
    const current = (): boolean => jobRef.current === job;
    void (async () => {
      try {
        const { recognizePages } = await import("../ocr/ocrPdf");
        const pages = await recognizePages(file, next.extraction.ocrPages, {
          signal: job.controller.signal,
          onProgress: ({ current: done, total }) => {
            if (current()) {
              dispatch({ type: "ocrProgress", fileId: job.fileId, current: done, total });
            }
          },
        });
        if (current()) {
          jobRef.current = null;
          dispatch({ type: "ocrFinished", fileId: job.fileId, pages });
        }
      } catch {
        if (current()) {
          jobRef.current = null;
          dispatch({ type: "ocrFailed", fileId: job.fileId });
        }
      }
    })();
  }, [state, dispatch]);

  // Unmount: abort the running job. A new mount starts with no job.
  useEffect(() => {
    return () => {
      const running = jobRef.current;
      jobRef.current = null;
      running?.controller.abort();
    };
  }, []);
}
