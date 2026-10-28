// @vitest-environment node
/**
 * S4-T2 AC10 — `fake-indexeddb` is a dev dependency, imported only in tests, never in the bundle.
 */
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const SRC = join(ROOT, "src");
const DIST = join(ROOT, "dist");

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

const isTestSupport = (p: string): boolean =>
  /\.test\.(ts|tsx)$/.test(p) || p.startsWith(join(SRC, "test") + "/");

describe("fake-indexeddb isolation (AC10)", () => {
  it("test_manifest_pins_fake_indexeddb_6_2_5_as_dev_dependency_only", () => {
    const pkg = JSON.parse(readFileSync(join(ROOT, "package.json"), "utf8")) as {
      dependencies?: Record<string, string>;
      devDependencies?: Record<string, string>;
    };
    expect(pkg.devDependencies?.["fake-indexeddb"]).toBe("6.2.5");
    expect(pkg.dependencies?.["fake-indexeddb"]).toBeUndefined();
  });

  it("test_production_sources_do_not_mention_fake_indexeddb", () => {
    const offenders = walk(SRC)
      .filter((p) => /\.(ts|tsx|js|jsx|mjs|css)$/.test(p) && !isTestSupport(p))
      .filter((p) => readFileSync(p, "utf8").includes("fake-indexeddb"));
    expect(offenders).toEqual([]);
  });

  it("test_production_sources_do_not_import_test_helpers", () => {
    const offenders = walk(SRC)
      .filter((p) => /\.(ts|tsx)$/.test(p) && !isTestSupport(p))
      .filter((p) => /from\s+["'][^"']*\/test\/[^"']*["']/.test(readFileSync(p, "utf8")));
    expect(offenders).toEqual([]);
  });

  it("test_no_global_auto_import_of_fake_indexeddb_anywhere", () => {
    const offenders = walk(SRC)
      .filter((p) => /\.(ts|tsx)$/.test(p) && !p.endsWith("no-fake-indexeddb.test.ts"))
      .filter((p) => readFileSync(p, "utf8").includes("fake-indexeddb/auto"));
    expect(offenders).toEqual([]);
    expect(readFileSync(join(ROOT, "vite.config.ts"), "utf8")).not.toMatch(/fake-indexeddb/);
  });

  it.skipIf(!existsSync(DIST))("test_dist_bundle_does_not_contain_fake_indexeddb", () => {
    const hits = walk(DIST)
      .filter((p) => /\.(js|mjs|css|html|map)$/.test(p))
      .filter((p) => /fake-indexeddb|FDBFactory|fakeIndexedDB/i.test(readFileSync(p, "utf8")));
    expect(hits).toEqual([]);
  });
});
