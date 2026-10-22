/**
 * S3-T5 AC2 — `src/ocr/trustedTypes.ts`: `installTrustedTypesPolicy()`.
 *
 * Assumed contract:
 * - creates the Trusted Types policy named `default` once, with the single
 *   rule `createScriptURL` (no `createHTML`, no `createScript`);
 * - `createScriptURL(url)` returns `url` for an exact URL of
 *   `ALLOWED_SCRIPT_URLS` (as a path or as an absolute same-origin URL) and
 *   throws for everything else;
 * - without `trustedTypes` in the browser it does nothing and does not throw.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ALLOWED_SCRIPT_URLS } from "./assets";

type Rules = Record<string, (input: string) => string>;
let createPolicy: ReturnType<typeof vi.fn>;

/** A fresh module per test, so that a module-level "installed" flag cannot leak. */
async function install(): Promise<void> {
  vi.resetModules();
  const fresh = await import("./trustedTypes");
  fresh.installTrustedTypesPolicy();
}

beforeEach(() => {
  createPolicy = vi.fn((_name: string, rules: Rules) => rules);
  vi.stubGlobal("trustedTypes", { createPolicy });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function rules(): Promise<Rules> {
  await install();
  const call = createPolicy.mock.calls[0] as [string, Rules] | undefined;
  if (call === undefined) {
    throw new Error("no policy was created");
  }
  return call[1];
}

const origin = (): string => globalThis.location.origin;

describe("Trusted Types default policy", () => {
  it("test_install_creates_policy_named_default", async () => {
    await install();
    expect(createPolicy).toHaveBeenCalledTimes(1);
    expect(createPolicy.mock.calls[0]?.[0]).toBe("default");
  });

  it("test_install_policy_has_only_create_script_url", async () => {
    expect(Object.keys(await rules())).toEqual(["createScriptURL"]);
  });

  it("test_install_twice_creates_the_policy_once", async () => {
    vi.resetModules();
    const fresh = await import("./trustedTypes");
    fresh.installTrustedTypesPolicy();
    fresh.installTrustedTypesPolicy();
    expect(createPolicy).toHaveBeenCalledTimes(1);
  });

  it("test_install_without_trusted_types_does_not_throw", async () => {
    vi.stubGlobal("trustedTypes", undefined);
    await expect(install()).resolves.toBeUndefined();
  });

  it("test_create_script_url_allows_every_listed_url_as_path", async () => {
    const { createScriptURL } = await rules();
    for (const url of ALLOWED_SCRIPT_URLS) {
      expect(createScriptURL?.(url)).toBe(url);
    }
  });

  it("test_create_script_url_allows_every_listed_url_as_absolute_same_origin", async () => {
    const { createScriptURL } = await rules();
    for (const url of ALLOWED_SCRIPT_URLS) {
      expect(createScriptURL?.(origin() + url)).toBe(origin() + url);
    }
  });

  const FIRST = (): string => ALLOWED_SCRIPT_URLS[0] ?? "/ocr/x.js";

  it.each([
    ["other file under ocr", () => "/ocr/evil.js"],
    ["other origin, same path", () => `https://evil.example${FIRST()}`],
    ["protocol relative", () => `//evil.example${FIRST()}`],
    ["blob url", () => "blob:http://localhost/1234"],
    ["data url", () => "data:text/javascript,alert(1)"],
    ["javascript url", () => "java" + "script:alert(1)"],
    ["path traversal", () => "/ocr/pdfjs/../../assets/evil.js"],
    ["allowed url with query", () => `${FIRST()}?x=1`],
    ["allowed url with fragment", () => `${FIRST()}#x`],
    ["allowed url with suffix", () => `${FIRST()}.evil`],
    ["allowed url in upper case", () => FIRST().toUpperCase()],
    ["empty string", () => ""],
    ["sandbox script", () => "/ocr/pdfjs/pdf.sandbox.min.mjs"],
  ])("test_create_script_url_rejects_%s", async (_label, make) => {
    const { createScriptURL } = await rules();
    expect(() => createScriptURL?.(make())).toThrow();
  });
});
