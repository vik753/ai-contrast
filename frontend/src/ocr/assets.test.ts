/**
 * S3-T5 AC1/AC2 — `src/ocr/assets.ts`: the exact, self-hosted OCR URLs.
 *
 * Assumed exports (see the report):
 * - `ALLOWED_SCRIPT_URLS: readonly string[]` — every URL that may be loaded as
 *   a script or worker (exact, same-origin paths under `/ocr/`);
 * - `PDF_WORKER_URL`, `TESSERACT_WORKER_URL` (our classic wrapper) — both in the list;
 * - `TESSERACT_CORE_PATH`, `LANG_PATH`, `CMAP_URL`, `STANDARD_FONT_URL`,
 *   `WASM_URL`, `ICC_URL` — same-origin paths under `/ocr/`, directories end with `/`.
 */
import { describe, expect, it } from "vitest";
import * as assets from "./assets";

describe("OCR asset URLs", () => {
  it("test_allowed_script_urls_are_exact_same_origin_paths_under_ocr", () => {
    expect(assets.ALLOWED_SCRIPT_URLS.length).toBeGreaterThan(0);
    for (const url of assets.ALLOWED_SCRIPT_URLS) {
      expect(url).toMatch(/^\/ocr\/[A-Za-z0-9._\-/]+$/);
      expect(url).not.toContain("..");
      expect(url).not.toContain("//");
    }
  });

  it("test_allowed_script_urls_have_no_duplicates", () => {
    expect(new Set(assets.ALLOWED_SCRIPT_URLS).size).toBe(assets.ALLOWED_SCRIPT_URLS.length);
  });

  it("test_allowed_script_urls_exclude_sandbox_quickjs_and_non_lstm_cores", () => {
    for (const url of assets.ALLOWED_SCRIPT_URLS) {
      expect(url).not.toMatch(/quickjs|sandbox/i);
      if (/tesseract-core/.test(url)) {
        expect(url).toMatch(/-lstm\.wasm\.js$/);
      }
    }
  });

  it("test_both_workers_are_in_the_allowed_list", () => {
    expect(assets.ALLOWED_SCRIPT_URLS).toContain(assets.PDF_WORKER_URL);
    expect(assets.ALLOWED_SCRIPT_URLS).toContain(assets.TESSERACT_WORKER_URL);
  });

  it("test_asset_locations_are_same_origin_paths_under_ocr", () => {
    const locations = [
      assets.TESSERACT_CORE_PATH,
      assets.LANG_PATH,
      assets.CMAP_URL,
      assets.STANDARD_FONT_URL,
      assets.WASM_URL,
      assets.ICC_URL,
    ];
    for (const location of locations) {
      expect(location).toMatch(/^\/ocr\//);
      expect(location).not.toMatch(/^[a-z]+:/i);
      expect(location.endsWith("/")).toBe(true);
    }
  });
});
