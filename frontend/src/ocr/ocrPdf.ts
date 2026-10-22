/**
 * OCR of scanned PDF pages in the browser (S3-T5 AC3, AC4, AC5, AC7).
 *
 * This is the only module that imports `pdfjs-dist` and `tesseract.js`. The
 * form loads this module with a dynamic `import()` only when a file needs OCR,
 * so no OCR code or data is fetched before that. Everything is self-hosted (`assets.ts`). Threat model T1, T5, T8, T9.
 *
 * - pdf.js: same-origin module worker as `workerPort`, no XFA, no font face,
 *   no system fonts, no eval (pdf.js 6 has no eval path), self-hosted cMaps, fonts, wasm and ICC data.
 *   Only `page.render` is used: no text layer, no annotation layer.
 *   Annotations and form values are drawn (`AnnotationMode.ENABLE`).
 * - Tesseract: LSTM only, `ukr+rus+eng`, our classic worker wrapper, no blob
 *   worker, no cache. The input is always a canvas, never a URL string.
 * - One page at a time. Aborting terminates both workers and frees the canvas.
 */
import * as pdfjs from "pdfjs-dist";
import * as tesseractNamespace from "tesseract.js";
import {
  CMAP_URL,
  ICC_URL,
  LANG_PATH,
  PDF_WORKER_URL,
  STANDARD_FONT_URL,
  TESSERACT_CORE_PATH,
  TESSERACT_WORKER_URL,
  WASM_URL,
} from "./assets";
import { installTrustedTypesPolicy } from "./trustedTypes";

/** Longest canvas side in pixels. */
const MAX_CANVAS_SIDE = 4000;
/** Render scale for OCR (about 150 to 200 dpi for A4). */
const OCR_SCALE = 2;
/** CommonJS interop: the API is on the namespace, or on `default`. */
const tesseract =
  "createWorker" in tesseractNamespace
    ? tesseractNamespace
    : (tesseractNamespace as { default: typeof tesseractNamespace }).default;
const LANGUAGES = "ukr+rus+eng";

export interface RecognizedPage {
  readonly page: number;
  readonly text: string;
  /** Mean confidence of the engine, 0-100. */
  readonly confidence: number;
}

export interface OcrProgress {
  readonly current: number;
  readonly total: number;
  readonly page: number;
}

export interface RecognizeOptions {
  readonly signal: AbortSignal;
  /** Called before each page starts. */
  readonly onProgress: (progress: OcrProgress) => void;
}

interface EngineWorker {
  recognize(image: HTMLCanvasElement): Promise<{ data: { text: string; confidence: number } }>;
  terminate(): Promise<unknown>;
}

function abortError(): DOMException {
  return new DOMException("OCR was cancelled.", "AbortError");
}

/** Render scale: about 2x, never more than `MAX_CANVAS_SIDE` pixels on the longest side. */
function scaleFor(width: number, height: number): number {
  return Math.min(OCR_SCALE, MAX_CANVAS_SIDE / Math.max(width, height));
}

export async function recognizePages(
  file: File,
  pages: readonly number[],
  { signal, onProgress }: RecognizeOptions,
): Promise<RecognizedPage[]> {
  if (signal.aborted) {
    throw abortError();
  }

  let onAbort: (() => void) | undefined;
  const aborted = new Promise<never>((_, reject) => {
    onAbort = () => {
      reject(abortError());
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
  aborted.catch(() => undefined);
  const isAborted = (): boolean => signal.aborted;
  const guard = <T>(work: Promise<T>): Promise<T> => Promise.race([work, aborted]);

  let pdfWorker: Worker | undefined;
  let loadingTask: { destroy(): Promise<void> } | undefined;
  let engine: EngineWorker | undefined;
  let enginePromise: Promise<EngineWorker> | undefined;

  try {
    installTrustedTypesPolicy();
    const bytes = new Uint8Array(await guard(file.arrayBuffer()));
    pdfWorker = new Worker(PDF_WORKER_URL, { type: "module" });
    pdfjs.GlobalWorkerOptions.workerPort = pdfWorker;
    const task = pdfjs.getDocument({
      data: bytes,
      enableXfa: false,
      disableFontFace: true,
      useSystemFonts: false,
      cMapUrl: CMAP_URL,
      cMapPacked: true,
      standardFontDataUrl: STANDARD_FONT_URL,
      wasmUrl: WASM_URL,
      iccUrl: ICC_URL,
    });
    loadingTask = task;
    const doc = await guard(task.promise);

    enginePromise = tesseract.createWorker(LANGUAGES, tesseract.OEM.LSTM_ONLY, {
      workerPath: TESSERACT_WORKER_URL,
      corePath: TESSERACT_CORE_PATH,
      langPath: LANG_PATH,
      workerBlobURL: false,
      cacheMethod: "none",
    });
    engine = await guard(enginePromise);

    const results: RecognizedPage[] = [];
    for (const [index, pageNumber] of pages.entries()) {
      onProgress({ current: index + 1, total: pages.length, page: pageNumber });
      const page = await guard(doc.getPage(pageNumber));
      const base = page.getViewport({ scale: 1 });
      const viewport = page.getViewport({ scale: scaleFor(base.width, base.height) });
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.floor(viewport.width));
      canvas.height = Math.max(1, Math.floor(viewport.height));
      try {
        const render = page.render({
          canvas,
          viewport,
          background: "white",
          annotationMode: pdfjs.AnnotationMode.ENABLE,
        });
        signal.addEventListener(
          "abort",
          () => {
            render.cancel();
          },
          { once: true },
        );
        await guard(render.promise);
        const { data } = await guard(engine.recognize(canvas));
        results.push({ page: pageNumber, text: data.text, confidence: data.confidence });
      } finally {
        // Free the bitmap now, not when the garbage collector runs.
        canvas.width = 0;
        canvas.height = 0;
        page.cleanup();
      }
    }
    return results;
  } catch (error) {
    if (isAborted()) {
      throw abortError();
    }
    throw error;
  } finally {
    if (onAbort !== undefined) {
      signal.removeEventListener("abort", onAbort);
    }
    if (engine !== undefined) {
      void engine.terminate().catch(() => undefined);
    } else if (enginePromise !== undefined) {
      // Still starting: stop it as soon as it exists.
      void enginePromise.then((late) => late.terminate()).catch(() => undefined);
    }
    void loadingTask?.destroy().catch(() => undefined);
    pdfWorker?.terminate();
  }
}
