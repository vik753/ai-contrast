/**
 * Self-hosted OCR assets (S3-T5 AC1, AC2). Threat model T8, T9.
 *
 * Every file lives under `/ocr/` on our own origin. `scripts/copy-ocr-assets.mjs`
 * puts them there at `dev` and `build` time. No CDN. The list of script URLs is
 * exact: the Trusted Types `default` policy lets nothing else through.
 */

/** The pdf.js worker (module worker). */
export const PDF_WORKER_URL = "/ocr/pdf.worker.min.mjs";

/** Our classic wrapper around the Tesseract worker. It installs the same policy. */
export const TESSERACT_WORKER_URL = "/ocr/tesseract-worker.js";

/** The real Tesseract worker, loaded by the wrapper with `importScripts`. */
export const TESSERACT_WORKER_SCRIPT_URL = "/ocr/worker.min.js";

/** Directory of the LSTM-only core files. Tesseract picks one by CPU features. */
export const TESSERACT_CORE_PATH = "/ocr/tesseract-core/";

/** Directory of `<lang>.traineddata.gz` (`4.0.0_best_int`, hash-checked at copy time). */
export const LANG_PATH = "/ocr/lang/";

export const CMAP_URL = "/ocr/pdfjs/cmaps/";
export const STANDARD_FONT_URL = "/ocr/pdfjs/standard_fonts/";
export const WASM_URL = "/ocr/pdfjs/wasm/";
export const ICC_URL = "/ocr/pdfjs/iccs/";

/** Core files by CPU features. LSTM only (no legacy engine). */
export const TESSERACT_CORE_URLS: readonly string[] = [
  `${TESSERACT_CORE_PATH}tesseract-core-lstm.wasm.js`,
  `${TESSERACT_CORE_PATH}tesseract-core-simd-lstm.wasm.js`,
  `${TESSERACT_CORE_PATH}tesseract-core-relaxedsimd-lstm.wasm.js`,
];

/** Every URL that may be loaded as a script or a worker. Exact match only. */
export const ALLOWED_SCRIPT_URLS: readonly string[] = [
  PDF_WORKER_URL,
  TESSERACT_WORKER_URL,
  TESSERACT_WORKER_SCRIPT_URL,
  ...TESSERACT_CORE_URLS,
];
