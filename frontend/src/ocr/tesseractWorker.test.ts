// @vitest-environment node
/**
 * The classic Tesseract worker wrapper (`ocr-worker/tesseract-worker.js`):
 * it installs the Trusted Types `default` policy before `importScripts`, and
 * its URL list equals the Tesseract part of `ALLOWED_SCRIPT_URLS`.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { describe, expect, it } from "vitest";
import { ALLOWED_SCRIPT_URLS, PDF_WORKER_URL, TESSERACT_WORKER_SCRIPT_URL } from "./assets";

const SOURCE = readFileSync(
  fileURLToPath(new URL("../../ocr-worker/tesseract-worker.js", import.meta.url)),
  "utf8",
);

type Rules = Record<string, (input: string) => string>;

function run(withTrustedTypes = true) {
  const events: string[] = [];
  const policies: { name: string; rules: Rules }[] = [];
  const scope = {
    location: { origin: "https://app.example" },
    importScripts: (url: string) => {
      events.push(`import ${url}`);
    },
    trustedTypes: withTrustedTypes
      ? {
          createPolicy: (name: string, rules: Rules) => {
            events.push(`policy ${name}`);
            policies.push({ name, rules });
            return rules;
          },
        }
      : undefined,
    self: undefined as unknown,
  };
  scope.self = scope;
  runInNewContext(SOURCE, { ...scope, self: scope });
  return { events, policies };
}

describe("tesseract-worker.js wrapper", () => {
  it("test_installs_the_default_policy_before_loading_the_worker", () => {
    const { events, policies } = run();
    expect(events).toEqual(["policy default", `import ${TESSERACT_WORKER_SCRIPT_URL}`]);
    expect(Object.keys(policies[0]?.rules ?? {})).toEqual(["createScriptURL"]);
  });

  it("test_allows_exactly_the_tesseract_urls_of_the_main_thread_policy", () => {
    const rules = run().policies[0]?.rules;
    const expected = ALLOWED_SCRIPT_URLS.filter((url) => url !== PDF_WORKER_URL);
    for (const url of expected) {
      expect(rules?.createScriptURL?.(url)).toBe(url);
      expect(rules?.createScriptURL?.(`https://app.example${url}`)).toBe(
        `https://app.example${url}`,
      );
    }
    for (const bad of [
      PDF_WORKER_URL,
      "/ocr/evil.js",
      `https://evil.example${expected[0] ?? ""}`,
      "blob:https://app.example/1",
      "",
    ]) {
      expect(() => rules?.createScriptURL?.(bad)).toThrow();
    }
  });

  it("test_still_loads_the_worker_without_trusted_types", () => {
    expect(run(false).events).toEqual([`import ${TESSERACT_WORKER_SCRIPT_URL}`]);
  });
});
