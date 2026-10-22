/**
 * S3-T5 AC3, AC4, AC5, AC7 — `src/ocr/ocrPdf.ts`.
 *
 * Assumed contract:
 *   recognizePages(file: File, pages: readonly number[],
 *     { signal, onProgress }): Promise<{ page: number; text: string; confidence: number }[]>
 * - `onProgress({ current, total, page })` is called before each page starts
 *   (`current` is 1-based, `total` is `pages.length`);
 * - pages are rendered and recognized one after the other, in the given order;
 * - on abort it rejects with an `AbortError` (`name === "AbortError"`);
 * - on any end (done, error, abort) it terminates the Tesseract worker and
 *   destroys the pdf.js document;
 * - `pdfjs-dist` and `tesseract.js` are imported by this module only (lazily).
 *
 * `pdfjs-dist` and `tesseract.js` are mocked. Everything is synthetic.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeFile } from "../test/upload-fakes";
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

interface Hoisted {
  log: string[];
  docParams: Record<string, unknown>[];
  workerOptions: { workerPort: unknown; workerSrc: string };
  createWorkerArgs: unknown[][];
  recognized: unknown[];
  rendered: { page: number; width: number; height: number; annotationMode: unknown }[];
  numPages: number;
  pageSize: Record<number, [number, number]>;
  viewportScales: number[];
  texts: Record<number, { text: string; confidence: number }>;
  pendingRecognize: (() => void) | null;
  holdRecognize: boolean;
  failRecognize: boolean;
  terminate: ReturnType<typeof import("vitest").vi.fn>;
  destroyDoc: ReturnType<typeof import("vitest").vi.fn>;
  getTextContent: ReturnType<typeof import("vitest").vi.fn>;
  getAnnotations: ReturnType<typeof import("vitest").vi.fn>;
  createWorkerSpy: ReturnType<typeof import("vitest").vi.fn>;
  lastRendered: number;
}

const h = vi.hoisted((): Hoisted => {
  return {
    log: [],
    docParams: [],
    workerOptions: { workerPort: null, workerSrc: "" },
    createWorkerArgs: [],
    recognized: [],
    rendered: [],
    numPages: 10,
    pageSize: {},
    viewportScales: [],
    texts: {},
    pendingRecognize: null,
    holdRecognize: false,
    failRecognize: false,
    terminate: undefined as never,
    destroyDoc: undefined as never,
    getTextContent: undefined as never,
    getAnnotations: undefined as never,
    createWorkerSpy: undefined as never,
    lastRendered: 0,
  };
});

vi.mock("pdfjs-dist/legacy/build/pdf.mjs", () => {
  h.destroyDoc = vi.fn(() => Promise.resolve());
  h.getTextContent = vi.fn();
  h.getAnnotations = vi.fn();
  const makePage = (n: number) => ({
    pageNumber: n,
    getViewport: ({ scale }: { scale: number }) => {
      h.viewportScales.push(scale);
      const [w, hh] = h.pageSize[n] ?? [600, 800];
      return { width: w * scale, height: hh * scale, scale };
    },
    render: (params: {
      canvas?: HTMLCanvasElement;
      canvasContext?: { canvas: HTMLCanvasElement };
      viewport: { width: number; height: number };
      annotationMode?: unknown;
    }) => {
      const canvas = params.canvas ?? params.canvasContext?.canvas;
      h.lastRendered = n;
      h.log.push(`render ${String(n)}`);
      h.rendered.push({
        page: n,
        width: canvas?.width ?? -1,
        height: canvas?.height ?? -1,
        annotationMode: params.annotationMode,
      });
      return { promise: Promise.resolve(), cancel: vi.fn() };
    },
    cleanup: vi.fn(),
    getTextContent: h.getTextContent,
    getAnnotations: h.getAnnotations,
  });
  return {
    VerbosityLevel: { ERRORS: 0, WARNINGS: 1, INFOS: 5 },
    AnnotationMode: { DISABLE: 0, ENABLE: 1, ENABLE_FORMS: 2, ENABLE_STORAGE: 3 },
    GlobalWorkerOptions: h.workerOptions,
    getDocument: (params: Record<string, unknown>) => {
      h.docParams.push(params);
      const doc = {
        numPages: h.numPages,
        getPage: (n: number) => Promise.resolve(makePage(n)),
        destroy: h.destroyDoc,
      };
      return { promise: Promise.resolve(doc), destroy: h.destroyDoc };
    },
  };
});

vi.mock("tesseract.js", () => {
  h.terminate = vi.fn(() => Promise.resolve());
  h.createWorkerSpy = vi.fn((...args: unknown[]) => {
    h.createWorkerArgs.push(args);
    return Promise.resolve({
      recognize: (image: unknown) => {
        const n = h.lastRendered;
        h.log.push(`recognize ${String(n)}`);
        h.recognized.push(image);
        if (h.failRecognize) {
          return Promise.reject(new Error("synthetic engine failure"));
        }
        const result = h.texts[n] ?? { text: `text ${String(n)}`, confidence: 90 };
        const done = () => ({ data: { text: result.text, confidence: result.confidence } });
        if (h.holdRecognize) {
          return new Promise((resolve) => {
            h.pendingRecognize = () => {
              resolve(done());
            };
          });
        }
        return Promise.resolve(done());
      },
      terminate: h.terminate,
    });
  });
  return { createWorker: h.createWorkerSpy, OEM: { LSTM_ONLY: 1 }, default: {} };
});

import { PAGE_TIMEOUT_MS, recognizePages } from "./ocrPdf";

class FakeWorker {
  static urls: string[] = [];
  constructor(url: string | URL) {
    FakeWorker.urls.push(String(url));
  }
  postMessage(): void {
    /* no-op */
  }
  terminate(): void {
    /* no-op */
  }
}

function resetHoisted(): void {
  h.log.length = 0;
  h.docParams.length = 0;
  h.createWorkerArgs.length = 0;
  h.recognized.length = 0;
  h.rendered.length = 0;
  h.viewportScales.length = 0;
  h.numPages = 10;
  h.pageSize = {};
  h.texts = {};
  h.pendingRecognize = null;
  h.holdRecognize = false;
  h.failRecognize = false;
  h.workerOptions.workerPort = null;
  h.workerOptions.workerSrc = "";
  h.lastRendered = 0;
  h.terminate.mockClear();
  h.destroyDoc.mockClear();
  h.getTextContent.mockClear();
  h.getAnnotations.mockClear();
  h.createWorkerSpy.mockClear();
  FakeWorker.urls = [];
}

let canvasSpy: { mockRestore: () => void } | undefined;

beforeEach(() => {
  resetHoisted();
  vi.stubGlobal("Worker", FakeWorker);
  canvasSpy = vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(function (
    this: HTMLCanvasElement,
  ) {
    return { canvas: this } as unknown as RenderingContext;
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  canvasSpy?.mockRestore();
});

const file = (): File => makeFile("scan.pdf");
const opts = (extra: Record<string, unknown> = {}) => ({
  signal: new AbortController().signal,
  onProgress: vi.fn(),
  ...extra,
});

function first<T>(items: readonly T[]): T {
  const item = items[0];
  if (item === undefined) {
    throw new Error("expected at least one item");
  }
  return item;
}

describe("pdf.js settings (AC3)", () => {
  it("test_get_document_gets_bytes_and_no_url", async () => {
    await recognizePages(file(), [1], opts());
    const params = first(h.docParams);
    expect(params.data).toBeInstanceOf(Uint8Array);
    expect(params.url).toBeUndefined();
  });

  it("test_get_document_disables_xfa_font_face_and_system_fonts", async () => {
    await recognizePages(file(), [1], opts());
    const params = first(h.docParams);
    expect(params.enableXfa).toBe(false);
    expect(params.disableFontFace).toBe(true);
    expect(params.useSystemFonts).toBe(false);
  });

  it("test_get_document_uses_self_hosted_cmap_font_wasm_and_icc_urls", async () => {
    await recognizePages(file(), [1], opts());
    const params = first(h.docParams);
    expect(params.cMapUrl).toBe(CMAP_URL);
    expect(params.standardFontDataUrl).toBe(STANDARD_FONT_URL);
    expect(params.wasmUrl).toBe(WASM_URL);
    expect(params.iccUrl).toBe(ICC_URL);
  });

  it("test_get_document_does_not_enable_eval", async () => {
    await recognizePages(file(), [1], opts());
    expect(first(h.docParams).isEvalSupported).not.toBe(true);
  });

  it("test_get_document_limits_pdfjs_logging_to_errors", async () => {
    await recognizePages(file(), [1], opts());
    expect(first(h.docParams).verbosity).toBe(0);
  });

  it("test_pdf_worker_port_is_a_worker_with_our_same_origin_url", async () => {
    await recognizePages(file(), [1], opts());
    expect(FakeWorker.urls).toContain(PDF_WORKER_URL);
    const params = first(h.docParams);
    const port = h.workerOptions.workerPort ?? params.workerPort;
    expect(port).toBeInstanceOf(FakeWorker);
  });

  it("test_no_worker_is_created_from_a_blob_or_foreign_url", async () => {
    await recognizePages(file(), [1], opts());
    for (const url of FakeWorker.urls) {
      expect(url).not.toMatch(/^(blob|data|https?):/);
    }
  });

  it("test_render_uses_annotation_mode_enable", async () => {
    await recognizePages(file(), [1], opts());
    expect(first(h.rendered).annotationMode).toBe(1);
  });

  it("test_text_and_annotation_layers_are_never_requested", async () => {
    await recognizePages(file(), [1, 2], opts());
    expect(h.getTextContent).not.toHaveBeenCalled();
    expect(h.getAnnotations).not.toHaveBeenCalled();
  });

  it("test_small_page_is_rendered_at_about_two_times_scale", async () => {
    await recognizePages(file(), [1], opts());
    const { width, height } = first(h.rendered);
    expect(height / 800).toBeGreaterThanOrEqual(1.8);
    expect(height / 800).toBeLessThanOrEqual(2.2);
    expect(width / 600).toBeGreaterThanOrEqual(1.8);
    expect(width / 600).toBeLessThanOrEqual(2.2);
  });

  it("test_huge_page_canvas_longest_side_is_capped_at_4000_px", async () => {
    h.pageSize[1] = [5000, 2000];
    await recognizePages(file(), [1], opts());
    const { width, height } = first(h.rendered);
    expect(Math.max(width, height)).toBeLessThanOrEqual(4000);
    expect(width).toBeGreaterThan(0);
  });

  it("test_huge_page_keeps_aspect_ratio_when_capped", async () => {
    h.pageSize[1] = [2000, 5000];
    await recognizePages(file(), [1], opts());
    const { width, height } = first(h.rendered);
    expect(Math.max(width, height)).toBeLessThanOrEqual(4000);
    expect(height / width).toBeCloseTo(2.5, 1);
  });
});

describe("Tesseract settings (AC4)", () => {
  it("test_create_worker_uses_ukr_rus_eng_and_lstm_only", async () => {
    await recognizePages(file(), [1], opts());
    const [langs, oem] = first(h.createWorkerArgs);
    expect([langs].flat().join("+")).toBe("ukr+rus+eng");
    expect(oem).toBe(1);
  });

  it("test_create_worker_has_no_blob_url_and_no_cache", async () => {
    await recognizePages(file(), [1], opts());
    const options = first(h.createWorkerArgs)[2] as Record<string, unknown>;
    expect(options.workerBlobURL).toBe(false);
    expect(options.cacheMethod).toBe("none");
  });

  it("test_create_worker_paths_are_our_self_hosted_assets", async () => {
    await recognizePages(file(), [1], opts());
    const options = first(h.createWorkerArgs)[2] as Record<string, unknown>;
    expect(options.workerPath).toBe(TESSERACT_WORKER_URL);
    expect(options.corePath).toBe(TESSERACT_CORE_PATH);
    expect(options.langPath).toBe(LANG_PATH);
  });

  it("test_recognize_input_is_a_canvas_or_image_data_never_a_string", async () => {
    await recognizePages(file(), [1, 2], opts());
    expect(h.recognized).toHaveLength(2);
    for (const image of h.recognized) {
      const ok =
        image instanceof HTMLCanvasElement ||
        (typeof ImageData !== "undefined" && image instanceof ImageData);
      expect(ok).toBe(true);
    }
  });
});

describe("flow (AC5)", () => {
  it("test_pages_are_rendered_and_recognized_one_at_a_time_in_order", async () => {
    await recognizePages(file(), [3, 5, 4], opts());
    expect(h.log).toEqual([
      "render 3",
      "recognize 3",
      "render 5",
      "recognize 5",
      "render 4",
      "recognize 4",
    ]);
  });

  it("test_result_has_page_text_and_confidence_per_page", async () => {
    h.texts[2] = { text: "Clause two", confidence: 91.5 };
    h.texts[4] = { text: "Clause four", confidence: 42 };
    const result = await recognizePages(file(), [2, 4], opts());
    expect(result).toEqual([
      { page: 2, text: "Clause two", confidence: 91.5 },
      { page: 4, text: "Clause four", confidence: 42 },
    ]);
  });

  it("test_progress_is_reported_before_each_page", async () => {
    const onProgress = vi.fn();
    await recognizePages(file(), [3, 5], { signal: new AbortController().signal, onProgress });
    expect(onProgress.mock.calls.map((c: unknown[]) => c[0])).toEqual([
      { current: 1, total: 2, page: 3 },
      { current: 2, total: 2, page: 5 },
    ]);
  });

  it("test_worker_and_document_are_released_after_success", async () => {
    await recognizePages(file(), [1], opts());
    expect(h.terminate).toHaveBeenCalledTimes(1);
    expect(h.destroyDoc).toHaveBeenCalled();
  });

  it("test_engine_error_rejects_and_releases_resources", async () => {
    h.failRecognize = true;
    await expect(recognizePages(file(), [1, 2], opts())).rejects.toThrow();
    expect(h.terminate).toHaveBeenCalledTimes(1);
    expect(h.destroyDoc).toHaveBeenCalled();
  });

  it("test_abort_during_recognition_rejects_with_abort_error_and_releases", async () => {
    h.holdRecognize = true;
    const controller = new AbortController();
    const promise = recognizePages(file(), [1, 2, 3], { ...opts(), signal: controller.signal });
    const settled = promise.then(
      () => null,
      (error: unknown) => error,
    );
    await vi.waitFor(() => {
      expect(h.pendingRecognize).not.toBeNull();
    });
    controller.abort();
    const error = await settled;
    expect((error as Error | null)?.name).toBe("AbortError");
    expect(h.terminate).toHaveBeenCalled();
    expect(h.destroyDoc).toHaveBeenCalled();
    expect(h.log).not.toContain("render 2");
  });

  it("test_page_timeout_rejects_and_terminates_the_workers", async () => {
    vi.useFakeTimers();
    try {
      h.holdRecognize = true;
      const promise = recognizePages(file(), [1, 2], opts());
      const settled = promise.then(
        () => null,
        (error: unknown) => error,
      );
      await vi.waitFor(() => {
        expect(h.pendingRecognize).not.toBeNull();
      });
      await vi.advanceTimersByTimeAsync(PAGE_TIMEOUT_MS + 1);
      const error = await settled;
      expect(error).toBeInstanceOf(Error);
      expect((error as Error).name).not.toBe("AbortError");
      expect(h.terminate).toHaveBeenCalled();
      expect(h.destroyDoc).toHaveBeenCalled();
      expect(h.log).not.toContain("render 2");
    } finally {
      vi.useRealTimers();
    }
  });

  it("test_abort_listeners_are_removed_after_the_run", async () => {
    const signal = new AbortController().signal;
    const added = vi.spyOn(signal, "addEventListener");
    const removed = vi.spyOn(signal, "removeEventListener");
    await recognizePages(file(), [1, 2, 3], { signal, onProgress: vi.fn() });
    const count = (calls: unknown[][]): number => calls.filter((c) => c[0] === "abort").length;
    expect(count(added.mock.calls)).toBeGreaterThan(0);
    expect(count(removed.mock.calls)).toBe(count(added.mock.calls));
  });

  it("test_abort_before_start_loads_no_engine", async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(
      recognizePages(file(), [1], { ...opts(), signal: controller.signal }),
    ).rejects.toMatchObject({ name: "AbortError" });
    expect(h.createWorkerSpy).not.toHaveBeenCalled();
    expect(h.log).toEqual([]);
  });
});

describe("lazy loading (AC7)", () => {
  it("test_engine_is_not_started_before_recognize_pages_is_called", () => {
    expect(h.createWorkerSpy).not.toHaveBeenCalled();
    expect(h.docParams).toEqual([]);
    expect(FakeWorker.urls).toEqual([]);
  });
});
