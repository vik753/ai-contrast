// @vitest-environment node
/** S6-T5 AC3 / T9 — app CSP and frame page headers. */
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const APP = fileURLToPath(new URL("../../public/_headers", import.meta.url));
const FRAME = fileURLToPath(new URL("../../turnstile/public/_headers", import.meta.url));
const FRAME_HTML = fileURLToPath(new URL("../../turnstile/turnstile.html", import.meta.url));
const PLACEHOLDER = "__TURNSTILE_FRAME_ORIGIN__";

function header(path: string, name: string): string[] {
  const out: string[] = [];
  for (const line of readFileSync(path, "utf8").split(/\r?\n/)) {
    const t = line.trim();
    if (t.startsWith("#") || !/^\s/.test(line)) continue;
    const i = t.indexOf(":");
    if (i > 0 && t.slice(0, i).trim().toLowerCase() === name.toLowerCase())
      out.push(t.slice(i + 1).trim());
  }
  return out;
}

function directive(csp: string, name: string): string[] | undefined {
  for (const part of csp.split(";")) {
    const [n, ...rest] = part.trim().split(/\s+/);
    if (n === name) return rest;
  }
  return undefined;
}

const appCsp = (): string => header(APP, "content-security-policy")[0] ?? "";
const frameCsp = (): string => header(FRAME, "content-security-policy")[0] ?? "";

describe("app CSP (S6-T5 AC3)", () => {
  it("test_frame_src_is_exactly_one_https_origin_or_the_placeholder", () => {
    const src = directive(appCsp(), "frame-src");
    expect(src).toBeDefined();
    expect(src).toHaveLength(1);
    expect(src?.[0]).toMatch(new RegExp(`^(https://[a-z0-9.-]+|${PLACEHOLDER})$`));
  });

  it("test_frame_src_is_not_cloudflare_and_has_no_wildcard_or_self", () => {
    const joined = (directive(appCsp(), "frame-src") ?? []).join(" ");
    expect(joined).not.toMatch(/cloudflare|\*|'self'|'none'|data:|blob:/);
  });

  it("test_script_src_is_unchanged_and_has_no_cloudflare", () => {
    expect(directive(appCsp(), "script-src")).toEqual(["'self'", "'wasm-unsafe-eval'"]);
    expect(appCsp()).not.toContain("challenges.cloudflare.com");
  });

  it("test_other_app_csp_directives_are_unchanged", () => {
    const csp = appCsp();
    expect(directive(csp, "default-src")).toEqual(["'self'"]);
    expect(directive(csp, "connect-src")).toEqual(["'self'"]);
    expect(directive(csp, "frame-ancestors")).toEqual(["'none'"]);
    expect(directive(csp, "object-src")).toEqual(["'none'"]);
    expect(directive(csp, "require-trusted-types-for")).toEqual(["'script'"]);
    expect(header(APP, "x-frame-options")).toEqual(["DENY"]);
  });
});

describe("frame page headers (S6-T5 AC3)", () => {
  it("test_frame_headers_file_exists", () => {
    expect(existsSync(FRAME)).toBe(true);
  });

  it("test_frame_ancestors_is_one_exact_app_origin_or_placeholder", () => {
    const fa = directive(frameCsp(), "frame-ancestors");
    expect(fa).toHaveLength(1);
    expect(fa?.[0]).toMatch(/^(https:\/\/[a-z0-9.-]+|__APP_ORIGIN__)$/);
    expect(fa?.[0]).not.toContain("*");
  });

  it("test_referrer_policy_is_no_referrer", () => {
    expect(header(FRAME, "referrer-policy")).toEqual(["no-referrer"]);
  });

  it("test_script_and_frame_sources_allow_only_self_and_challenges_cloudflare", () => {
    const csp = frameCsp();
    for (const d of ["script-src", "frame-src"]) {
      const src = directive(csp, d) ?? [];
      expect(src, d).toContain("https://challenges.cloudflare.com");
      const allowed = d === "frame-src" ? [] : ["'self'"];
      for (const s of src)
        expect([...allowed, "https://challenges.cloudflare.com"], `${d} ${s}`).toContain(s);
    }
    expect(directive(csp, "default-src")).toEqual(["'none'"]);
    expect(csp).not.toMatch(/unsafe-eval|script-src[^;]*unsafe-inline|\*/);
    expect(directive(csp, "base-uri")).toEqual(["'none'"]);
    expect(directive(csp, "form-action")).toEqual(["'none'"]);
  });

  it("test_frame_does_not_send_x_frame_options_or_cors_headers", () => {
    expect(header(FRAME, "x-frame-options")).toEqual([]);
    expect(header(FRAME, "access-control-allow-origin")).toEqual([]);
    expect(header(FRAME, "x-content-type-options")).toEqual(["nosniff"]);
  });

  it("test_frame_page_has_no_inline_script_and_no_foreign_url", () => {
    const html = readFileSync(FRAME_HTML, "utf8");
    const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script\s*>/gi)];
    expect(scripts.length).toBeGreaterThan(0);
    for (const s of scripts) {
      expect(s[1]).toMatch(/\bsrc=/);
      expect((s[2] ?? "").trim()).toBe("");
    }
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
    expect(html).not.toMatch(/https?:\/\//i);
  });
});
