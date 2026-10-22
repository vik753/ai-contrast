/**
 * Copies the OCR assets from node_modules into `public/ocr/` (S3-T5 AC1).
 *
 * Run explicitly from the `dev` and `build` scripts (npm lifecycle hooks do
 * not run because of `ignore-scripts`). Threat model T8, T9.
 *
 * - pdf.js comes from the `legacy` build (the modern build needs newer browser
 *   APIs such as `Map.prototype.getOrInsertComputed`).
 * - Only an exact list of files is copied. No `quickjs-eval.*`, no
 *   `pdf.sandbox.*`, no legacy (non-LSTM) Tesseract core.
 * - Language data comes from `4.0.0_best_int` only. Each file is checked
 *   against a SHA-256 manifest before anything is written; a mismatch fails.
 */
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { copyFile, mkdir, readFile, readdir, rm } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const LANGUAGE_SHA256 = {
  eng: "45b4cb346724ac1774f1c36f42f182b887bcdb28ebe63e6fff90ac41f3fcff91",
  ukr: "ea2789a0ad99ff84bfd252a7410a1e8661a7bc5acaa41573d23b54b71446aa4c",
  rus: "f51f5edc992249ff9b70a227b22f242dfa47b2b1bbc7ae0ea74908640c101f6a",
};

const WRAPPER = fileURLToPath(new URL("../ocr-worker/tesseract-worker.js", import.meta.url));
const LANG_DIR = "4.0.0_best_int";

/** Files that must exist: [source under node_modules, target under outDir]. */
const REQUIRED_FILES = [
  ["pdfjs-dist/legacy/build/pdf.worker.min.mjs", "pdf.worker.min.mjs"],
  ["tesseract.js/dist/worker.min.js", "worker.min.js"],
];

const CORE_REQUIRED = ["tesseract-core-lstm.wasm.js", "tesseract-core-simd-lstm.wasm.js"];
/** Newer builds use it on CPUs with relaxed SIMD; older package files may lack it. */
const CORE_OPTIONAL = ["tesseract-core-relaxedsimd-lstm.wasm.js"];

/** Directories copied whole, with a filter on the base name. */
const PDFJS_DIRS = [
  ["cmaps", () => true],
  ["standard_fonts", () => true],
  ["iccs", (name) => name.endsWith(".icc")],
  // WebAssembly decoders only: no quickjs-eval (script sandbox), no JS fallbacks.
  ["wasm", (name) => name.endsWith(".wasm") && !/quickjs/i.test(name)],
];

/** Licence files are copied when present (Apache-2.0 requires them). */
const LICENSES = [
  ["pdfjs-dist/LICENSE", "licenses/pdfjs-dist-LICENSE"],
  ["tesseract.js/LICENSE.md", "licenses/tesseract.js-LICENSE.md"],
  ["tesseract.js-core/LICENSE", "licenses/tesseract.js-core-LICENSE"],
];

const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");

async function copyTo(source, target) {
  await mkdir(dirname(target), { recursive: true });
  await copyFile(source, target);
}

/**
 * @param {{ nodeModulesDir: string, outDir: string, languageSha256?: Record<string, string> }} options
 */
export async function copyOcrAssets({ nodeModulesDir, outDir, languageSha256 = LANGUAGE_SHA256 }) {
  const modules = (...parts) => join(nodeModulesDir, ...parts);

  // 1. Verify all language data first, so a mismatch leaves nothing behind.
  const languages = [];
  for (const lang of Object.keys(languageSha256)) {
    const source = modules("@tesseract.js-data", lang, LANG_DIR, `${lang}.traineddata.gz`);
    const digest = sha256(await readFile(source));
    if (digest !== languageSha256[lang]) {
      throw new Error(`Language data "${lang}" has an unexpected SHA-256 (${digest}).`);
    }
    languages.push([source, join(outDir, "lang", `${lang}.traineddata.gz`)]);
  }

  // 2. Fresh output, then copy the exact list. The directory itself is kept:
  // in Compose it is a volume mount point, and removing it fails with EBUSY.
  await mkdir(outDir, { recursive: true });
  for (const entry of await readdir(outDir)) {
    await rm(join(outDir, entry), { recursive: true, force: true });
  }
  for (const [source, target] of languages) {
    await copyTo(source, target);
  }
  for (const [source, target] of REQUIRED_FILES) {
    await copyTo(modules(source), join(outDir, target));
  }
  for (const name of CORE_REQUIRED) {
    await copyTo(modules("tesseract.js-core", name), join(outDir, "tesseract-core", name));
  }
  for (const name of CORE_OPTIONAL) {
    if (existsSync(modules("tesseract.js-core", name))) {
      await copyTo(modules("tesseract.js-core", name), join(outDir, "tesseract-core", name));
    }
  }
  await copyTo(WRAPPER, join(outDir, "tesseract-worker.js"));
  for (const [dir, accept] of PDFJS_DIRS) {
    const entries = await readdir(modules("pdfjs-dist", dir), { withFileTypes: true });
    for (const entry of entries) {
      if (entry.isFile() && accept(entry.name)) {
        await copyTo(
          modules("pdfjs-dist", dir, entry.name),
          join(outDir, "pdfjs", dir, entry.name),
        );
      }
    }
  }
  for (const [source, target] of LICENSES) {
    if (existsSync(modules(source))) {
      await copyTo(modules(source), join(outDir, target));
    }
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const root = fileURLToPath(new URL("..", import.meta.url));
  copyOcrAssets({
    nodeModulesDir: join(root, "node_modules"),
    outDir: join(root, "public", "ocr"),
  }).catch((error) => {
    console.error(error instanceof Error ? error.message : error);
    process.exit(1);
  });
}
