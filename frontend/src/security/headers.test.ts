// @vitest-environment node
/**
 * S1-T2 AC8 / threat model T9 — `frontend/public/_headers` (Cloudflare Pages).
 *
 * File format: a URL pattern line (no indentation) followed by indented
 * `Name: value` lines. `#` starts a comment.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const HEADERS_PATH = fileURLToPath(new URL("../../public/_headers", import.meta.url));

type HeaderBlock = Map<string, string[]>;

function parseHeadersFile(source: string): Map<string, HeaderBlock> {
  const blocks = new Map<string, HeaderBlock>();
  let current: HeaderBlock | undefined;
  for (const rawLine of source.split(/\r?\n/)) {
    if (rawLine.trim() === "" || rawLine.trim().startsWith("#")) {
      continue;
    }
    if (!/^\s/.test(rawLine)) {
      const pattern = rawLine.trim();
      current = blocks.get(pattern) ?? new Map<string, string[]>();
      blocks.set(pattern, current);
      continue;
    }
    if (!current) {
      throw new Error(`Header line before any URL pattern: ${rawLine}`);
    }
    const line = rawLine.trim();
    const colon = line.indexOf(":");
    if (colon <= 0) {
      throw new Error(`Malformed header line: ${line}`);
    }
    const name = line.slice(0, colon).trim().toLowerCase();
    const value = line.slice(colon + 1).trim();
    current.set(name, [...(current.get(name) ?? []), value]);
  }
  return blocks;
}

function loadAllPathsBlock(): HeaderBlock {
  const blocks = parseHeadersFile(readFileSync(HEADERS_PATH, "utf8"));
  const block = blocks.get("/*");
  if (!block) {
    throw new Error("_headers has no `/*` rule");
  }
  return block;
}

function singleHeader(name: string): string {
  const values = loadAllPathsBlock().get(name.toLowerCase()) ?? [];
  expect(values, `header ${name}`).toHaveLength(1);
  return values[0] ?? "";
}

function parseCsp(value: string): Map<string, string[]> {
  const directives = new Map<string, string[]>();
  for (const part of value.split(";")) {
    const tokens = part.trim().split(/\s+/).filter((t) => t !== "");
    const [name, ...sources] = tokens;
    if (name === undefined) {
      continue;
    }
    const key = name.toLowerCase();
    if (directives.has(key)) {
      throw new Error(`Duplicate CSP directive: ${key}`);
    }
    directives.set(key, sources);
  }
  return directives;
}

function csp(): Map<string, string[]> {
  return parseCsp(singleHeader("Content-Security-Policy"));
}

function directive(name: string): string[] {
  const sources = csp().get(name);
  if (sources === undefined) {
    throw new Error(`CSP has no ${name} directive`);
  }
  return sources;
}

describe("_headers file (AC8)", () => {
  it("test_headers_file_has_rule_for_all_paths", () => {
    expect(() => loadAllPathsBlock()).not.toThrow();
  });

  it("test_headers_file_has_single_content_security_policy", () => {
    expect(singleHeader("Content-Security-Policy")).not.toBe("");
  });
});

describe("Content-Security-Policy (AC8, T9)", () => {
  it("test_csp_default_src_is_self", () => {
    expect(directive("default-src")).toEqual(["'self'"]);
  });

  it("test_csp_script_src_contains_self", () => {
    expect(directive("script-src")).toContain("'self'");
  });

  it("test_csp_script_src_has_no_unsafe_inline", () => {
    expect(directive("script-src")).not.toContain("'unsafe-inline'");
  });

  it("test_csp_script_src_has_no_unsafe_eval", () => {
    expect(directive("script-src")).not.toContain("'unsafe-eval'");
  });

  it("test_csp_script_src_allows_no_external_hosts", () => {
    // Rule 8: no third-party scripts or CDNs. Only keyword sources ('self', ...).
    const hosts = directive("script-src").filter((s) => !s.startsWith("'"));
    expect(hosts).toEqual([]);
  });

  it("test_csp_object_src_is_none", () => {
    expect(directive("object-src")).toEqual(["'none'"]);
  });

  it("test_csp_base_uri_is_none", () => {
    expect(directive("base-uri")).toEqual(["'none'"]);
  });

  it("test_csp_frame_ancestors_is_none", () => {
    expect(directive("frame-ancestors")).toEqual(["'none'"]);
  });

  it("test_csp_connect_src_is_self_only", () => {
    expect(directive("connect-src")).toEqual(["'self'"]);
  });

  it("test_csp_form_action_is_none", () => {
    expect(directive("form-action")).toEqual(["'none'"]);
  });

  it("test_csp_style_src_has_no_unsafe_inline", () => {
    const styleSrc = csp().get("style-src") ?? directive("default-src");
    expect(styleSrc).not.toContain("'unsafe-inline'");
  });

  it("test_csp_has_no_wildcard_sources", () => {
    const wildcards = [...csp().entries()].filter(([, sources]) => sources.includes("*"));
    expect(wildcards).toEqual([]);
  });
});

describe("other security headers (AC8, T9)", () => {
  it("test_hsts_has_max_age_at_least_one_year", () => {
    const value = singleHeader("Strict-Transport-Security");
    const match = /max-age=(\d+)/i.exec(value);
    expect(match).not.toBeNull();
    expect(Number(match?.[1])).toBeGreaterThanOrEqual(31_536_000);
  });

  it("test_hsts_includes_subdomains", () => {
    expect(singleHeader("Strict-Transport-Security").toLowerCase()).toContain(
      "includesubdomains",
    );
  });

  it("test_x_content_type_options_is_nosniff", () => {
    expect(singleHeader("X-Content-Type-Options")).toBe("nosniff");
  });

  it("test_referrer_policy_is_no_referrer", () => {
    expect(singleHeader("Referrer-Policy")).toBe("no-referrer");
  });

  it("test_permissions_policy_disables_camera_microphone_geolocation", () => {
    const value = singleHeader("Permissions-Policy").replace(/\s+/g, "");
    expect(value).toContain("camera=()");
    expect(value).toContain("microphone=()");
    expect(value).toContain("geolocation=()");
  });

  it("test_cross_origin_opener_policy_is_same_origin", () => {
    expect(singleHeader("Cross-Origin-Opener-Policy")).toBe("same-origin");
  });
});
