/** ADR 0017 point 1: the bundled catalog equals `shared/topics` (the backend's source). */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { bundledCatalog, bundledRawFiles } from "./bundled";

const DIR = join(__dirname, "../../../shared/topics");
const names = readdirSync(DIR).filter((f) => f.endsWith(".json"));

describe("bundled catalog", () => {
  it("test_bundles_every_shared_topics_file_byte_for_byte", () => {
    const bundled = bundledRawFiles();
    expect(Object.keys(bundled).sort()).toEqual([...names].sort());
    for (const n of names) expect(bundled[n]).toBe(readFileSync(join(DIR, n), "utf8"));
  });

  it("test_bundled_catalog_has_every_domain_sorted_and_parses_equal", () => {
    const cat = bundledCatalog();
    expect(cat).not.toBeNull();
    const expected = names
      .map((n) => JSON.parse(readFileSync(join(DIR, n), "utf8")) as { id: string })
      .sort((a, b) => (a.id < b.id ? -1 : 1));
    expect(cat?.domains).toEqual(expected);
  });
});
