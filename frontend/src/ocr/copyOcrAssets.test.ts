// @vitest-environment node
/**
 * S3-T5 AC1 — `frontend/scripts/copy-ocr-assets.mjs`.
 *
 * Assumed contract (ES module, no side effect on import; runs `main` only
 * when started as a script):
 *   export const LANGUAGE_SHA256: { eng: string; ukr: string; rus: string };
 *   export async function copyOcrAssets(options: {
 *     nodeModulesDir: string;   // contains pdfjs-dist, tesseract.js, tesseract.js-core, @tesseract.js-data/*
 *     outDir: string;           // the `public/ocr` directory
 *     languageSha256?: Record<string, string>; // default LANGUAGE_SHA256
 *   }): Promise<void>;          // rejects with an Error on a hash mismatch
 * Source layout (as in the packages):
 *   pdfjs-dist/build/pdf.worker.min.mjs, pdfjs-dist/build/pdf.sandbox.min.mjs,
 *   pdfjs-dist/cmaps/*, pdfjs-dist/standard_fonts/*, pdfjs-dist/wasm/* (with quickjs-eval.*),
 *   pdfjs-dist/iccs/*, tesseract.js/dist/worker.min.js,
 *   tesseract.js-core/tesseract-core*.wasm.js,
 *   @tesseract.js-data/<lang>/4.0.0_best_int/<lang>.traineddata.gz and /4.0.0/<lang>.traineddata.gz.
 * Output layout is free: tests look at base names anywhere under `outDir`.
 */
import { createHash } from "node:crypto";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

const SCRIPT = fileURLToPath(new URL("../../scripts/copy-ocr-assets.mjs", import.meta.url));

interface ScriptModule {
  LANGUAGE_SHA256: Record<string, string>;
  copyOcrAssets(options: {
    nodeModulesDir: string;
    outDir: string;
    languageSha256?: Record<string, string>;
  }): Promise<void>;
}

async function loadScript(): Promise<ScriptModule> {
  return (await import(/* @vite-ignore */ pathToFileURL(SCRIPT).href)) as ScriptModule;
}

let root: string;
let modules: string;
let out: string;

const sha = (text: string): string => createHash("sha256").update(text).digest("hex");

function put(relative: string, content = `synthetic ${relative}`): void {
  const path = join(modules, relative);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, content);
}

const LANGS = ["eng", "ukr", "rus"] as const;

function seed(): void {
  put("pdfjs-dist/legacy/build/pdf.worker.min.mjs");
  put("pdfjs-dist/build/pdf.worker.min.mjs", "modern worker");
  put("pdfjs-dist/build/pdf.sandbox.min.mjs");
  put("pdfjs-dist/build/pdf.mjs");
  put("pdfjs-dist/cmaps/Adobe-Japan1-0.bcmap");
  put("pdfjs-dist/standard_fonts/FoxitSans.pfb");
  put("pdfjs-dist/wasm/openjpeg.wasm");
  put("pdfjs-dist/wasm/quickjs-eval.js");
  put("pdfjs-dist/wasm/quickjs-eval.wasm");
  put("pdfjs-dist/iccs/CGATS001Compat-v2-micro.icc");
  put("tesseract.js/dist/worker.min.js");
  put("tesseract.js/dist/tesseract.min.js");
  put("tesseract.js-core/tesseract-core-lstm.wasm.js");
  put("tesseract.js-core/tesseract-core-simd-lstm.wasm.js");
  put("tesseract.js-core/tesseract-core.wasm.js");
  put("tesseract.js-core/tesseract-core-simd.wasm.js");
  for (const lang of LANGS) {
    put(`@tesseract.js-data/${lang}/4.0.0_best_int/${lang}.traineddata.gz`, `best_int ${lang}`);
    put(`@tesseract.js-data/${lang}/4.0.0/${lang}.traineddata.gz`, `plain ${lang}`);
    put(`@tesseract.js-data/${lang}/4.0.0_best/${lang}.traineddata.gz`, `best ${lang}`);
  }
}

function goodManifest(): Record<string, string> {
  return Object.fromEntries(LANGS.map((lang) => [lang, sha(`best_int ${lang}`)]));
}

function walk(dir: string, prefix = ""): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory()
      ? walk(join(dir, entry.name), `${prefix}${entry.name}/`)
      : [`${prefix}${entry.name}`],
  );
}

const names = (): string[] => walk(out).map((p) => p.split("/").at(-1) ?? p);

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "ocr-assets-"));
  modules = join(root, "node_modules");
  out = join(root, "public", "ocr");
  mkdirSync(modules, { recursive: true });
  seed();
});

afterEach(() => {
  rmSync(root, { recursive: true, force: true });
});

describe("copy-ocr-assets manifest", () => {
  it("test_language_manifest_has_the_approved_sha256_values", async () => {
    const script = await loadScript();
    expect(script.LANGUAGE_SHA256).toEqual({
      eng: "45b4cb346724ac1774f1c36f42f182b887bcdb28ebe63e6fff90ac41f3fcff91",
      ukr: "ea2789a0ad99ff84bfd252a7410a1e8661a7bc5acaa41573d23b54b71446aa4c",
      rus: "f51f5edc992249ff9b70a227b22f242dfa47b2b1bbc7ae0ea74908640c101f6a",
    });
  });

  it("test_import_has_no_side_effects", async () => {
    await loadScript();
    expect(() => readdirSync(out)).toThrow();
  });
});

describe("copy-ocr-assets copy", () => {
  async function run(): Promise<void> {
    const script = await loadScript();
    await script.copyOcrAssets({
      nodeModulesDir: modules,
      outDir: out,
      languageSha256: goodManifest(),
    });
  }

  it("test_copies_the_workers_and_the_language_data", async () => {
    await run();
    const copied = names();
    expect(copied).toContain("pdf.worker.min.mjs");
    expect(copied).toContain("worker.min.js");
    for (const lang of LANGS) {
      expect(copied).toContain(`${lang}.traineddata.gz`);
    }
  });

  it("test_copies_pdfjs_cmaps_fonts_wasm_and_icc_data", async () => {
    await run();
    const copied = names();
    expect(copied).toContain("Adobe-Japan1-0.bcmap");
    expect(copied).toContain("FoxitSans.pfb");
    expect(copied).toContain("openjpeg.wasm");
    expect(copied).toContain("CGATS001Compat-v2-micro.icc");
  });

  it("test_copies_only_lstm_core_files", async () => {
    await run();
    const cores = names().filter((n) => n.startsWith("tesseract-core"));
    expect(cores.sort()).toEqual([
      "tesseract-core-lstm.wasm.js",
      "tesseract-core-simd-lstm.wasm.js",
    ]);
  });

  it("test_does_not_copy_quickjs_or_pdf_sandbox", async () => {
    await run();
    for (const name of names()) {
      expect(name).not.toMatch(/quickjs|sandbox/i);
    }
  });

  it("test_does_not_copy_unrelated_package_files", async () => {
    await run();
    const copied = names();
    expect(copied).not.toContain("tesseract.min.js");
    expect(copied).not.toContain("pdf.mjs");
  });

  it("test_language_data_comes_from_the_best_int_directory_only", async () => {
    await run();
    const langFiles = walk(out).filter((p) => p.endsWith(".traineddata.gz"));
    expect(langFiles).toHaveLength(3);
    for (const path of langFiles) {
      expect(readFileSync(join(out, path), "utf8")).toMatch(/^best_int /);
    }
  });

  it("test_copied_files_are_byte_equal_to_the_sources", async () => {
    await run();
    const target = walk(out).find((p) => p.endsWith("pdf.worker.min.mjs"));
    expect(readFileSync(join(out, target ?? "missing"), "utf8")).toBe(
      "synthetic pdfjs-dist/legacy/build/pdf.worker.min.mjs",
    );
  });
});

describe("copy-ocr-assets hash check", () => {
  it("test_hash_mismatch_rejects_and_names_the_language", async () => {
    const script = await loadScript();
    const manifest = { ...goodManifest(), ukr: "0".repeat(64) };
    await expect(
      script.copyOcrAssets({ nodeModulesDir: modules, outDir: out, languageSha256: manifest }),
    ).rejects.toThrow(/ukr/);
  });

  it("test_hash_mismatch_leaves_no_language_file_in_the_output", async () => {
    const script = await loadScript();
    const manifest = { ...goodManifest(), rus: "f".repeat(64) };
    await script
      .copyOcrAssets({ nodeModulesDir: modules, outDir: out, languageSha256: manifest })
      .catch(() => undefined);
    let leftovers: string[] = [];
    try {
      leftovers = walk(out).filter((p) => p.endsWith("rus.traineddata.gz"));
    } catch {
      leftovers = [];
    }
    expect(leftovers).toEqual([]);
  });

  it("test_default_manifest_rejects_synthetic_language_files", async () => {
    const script = await loadScript();
    await expect(script.copyOcrAssets({ nodeModulesDir: modules, outDir: out })).rejects.toThrow();
  });

  it("test_missing_language_file_rejects", async () => {
    rmSync(join(modules, "@tesseract.js-data/eng/4.0.0_best_int"), { recursive: true });
    const script = await loadScript();
    await expect(
      script.copyOcrAssets({
        nodeModulesDir: modules,
        outDir: out,
        languageSha256: goodManifest(),
      }),
    ).rejects.toThrow();
  });
});

describe("copy-ocr-assets output directory", () => {
  it("test_keeps_the_output_directory_and_removes_only_its_contents", async () => {
    mkdirSync(out, { recursive: true });
    writeFileSync(join(out, "stale.txt"), "old");
    mkdirSync(join(out, "old-dir"));
    writeFileSync(join(out, "old-dir", "x"), "old");
    const before = statSync(out).ino;
    const script = await loadScript();
    await script.copyOcrAssets({
      nodeModulesDir: modules,
      outDir: out,
      languageSha256: goodManifest(),
    });
    expect(statSync(out).ino).toBe(before);
    expect(names()).not.toContain("stale.txt");
    expect(names()).not.toContain("x");
    expect(names()).toContain("pdf.worker.min.mjs");
  });

  it("test_copies_the_legacy_pdfjs_worker_not_the_modern_one", async () => {
    const script = await loadScript();
    await script.copyOcrAssets({
      nodeModulesDir: modules,
      outDir: out,
      languageSha256: goodManifest(),
    });
    expect(readFileSync(join(out, "pdf.worker.min.mjs"), "utf8")).toContain("legacy");
  });
});

describe("pdf.js legacy build in node_modules", () => {
  const real = fileURLToPath(
    new URL("../../node_modules/pdfjs-dist/legacy/build/", import.meta.url),
  );

  it.each(["pdf.worker.min.mjs", "pdf.mjs"])("test_%s_has_no_eval_and_no_new_function", (name) => {
    const code = readFileSync(join(real, name), "utf8");
    expect(code).not.toMatch(/\beval\s*\(/);
    expect(code).not.toMatch(/new\s+Function\s*\(/);
  });
});
