// @vitest-environment node
/**
 * S1-T2b AC10 — npm version is pinned through `packageManager`, not through
 * `engines.npm` (npm 10 crashed on this project; see PROGRESS.md).
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const PACKAGE_JSON_PATH = fileURLToPath(new URL("../../package.json", import.meta.url));

interface Manifest {
  packageManager?: unknown;
  engines?: Record<string, unknown>;
}

function manifest(): Manifest {
  return JSON.parse(readFileSync(PACKAGE_JSON_PATH, "utf8")) as Manifest;
}

describe("package.json npm pin (S1-T2b AC10)", () => {
  it("test_package_manager_is_npm_11_6_2", () => {
    expect(manifest().packageManager).toBe("npm@11.6.2");
  });

  it("test_engines_has_no_npm_entry", () => {
    expect(manifest().engines?.npm).toBeUndefined();
  });
});
