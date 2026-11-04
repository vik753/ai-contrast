// @vitest-environment node
/** S6-T5 AC3 — the second origin is buildable and runnable on its own port. */
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const root = (p: string): string => fileURLToPath(new URL(`../../${p}`, import.meta.url));

describe("turnstile frame build (S6-T5 AC3)", () => {
  it("test_package_json_has_dev_and_build_scripts_for_the_frame", () => {
    const scripts = (
      JSON.parse(readFileSync(root("package.json"), "utf8")) as { scripts: Record<string, string> }
    ).scripts;
    expect(scripts["dev:turnstile"]).toMatch(/vite.*turnstile/);
    expect(scripts["build:turnstile"]).toMatch(/vite.*build.*turnstile/);
  });

  it("test_frame_vite_config_uses_port_5174_and_its_own_root_and_outdir", () => {
    const p = root("vite.turnstile.config.ts");
    expect(existsSync(p)).toBe(true);
    const src = readFileSync(p, "utf8");
    expect(src).toMatch(/5174/);
    expect(src).toMatch(/root:\s*["']turnstile["']|turnstile/);
    expect(src).toMatch(/dist-turnstile/);
    expect(src).not.toMatch(/proxy/);
  });

  it("test_frame_entry_exists", () => {
    expect(existsSync(root("turnstile/turnstile.html"))).toBe(true);
    expect(existsSync(root("turnstile/main.ts"))).toBe(true);
  });

  it("test_frame_code_never_uses_wildcard_target_origin", () => {
    for (const f of ["src/turnstile-frame/frameController.ts", "turnstile/main.ts"]) {
      const src = readFileSync(root(f), "utf8");
      expect(src, f).not.toMatch(/postMessage\([^)]*,\s*["']\*["']/);
      expect(src, f).not.toMatch(/localStorage|sessionStorage|indexedDB/);
    }
  });

  it("test_app_source_never_references_a_cloudflare_script_url", () => {
    for (const f of ["src/provider/TurnstileFrame.tsx", "src/provider/ProviderSettings.tsx"]) {
      const src = readFileSync(root(f), "utf8");
      expect(src, f).not.toMatch(/challenges\.cloudflare\.com/);
      expect(src, f).not.toMatch(/createElement\(\s*["']script["']/);
    }
  });
});
