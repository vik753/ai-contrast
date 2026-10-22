/**
 * Trusted Types `default` policy (S3-T5 AC2, threat model T9).
 *
 * The CSP says `trusted-types default`, so this is the only policy. It has
 * `createScriptURL` only, and it passes an exact list of our own worker and
 * core URLs. Every other script URL throws. There is no `createHTML` and no
 * `createScript`: those sinks still throw.
 *
 * `ocr-worker/tesseract-worker.js` carries the same rule for the worker scope
 * (a test keeps the two lists equal).
 */
import { ALLOWED_SCRIPT_URLS } from "./assets";

interface PolicyFactory {
  createPolicy(name: string, rules: Record<string, (input: string) => string>): unknown;
}

let installed = false;

/** Whether `input` is an allowed URL: a listed path, or the same path on our origin. */
function isAllowed(input: string): boolean {
  const allowed = ALLOWED_SCRIPT_URLS;
  if (allowed.includes(input)) {
    return true;
  }
  const origin = globalThis.location.origin;
  return input.startsWith(origin) && allowed.includes(input.slice(origin.length));
}

export function installTrustedTypesPolicy(): void {
  const factory = (globalThis as { trustedTypes?: PolicyFactory }).trustedTypes;
  if (installed || factory === undefined) {
    return;
  }
  installed = true;
  factory.createPolicy("default", {
    createScriptURL: (input: string): string => {
      if (!isAllowed(input)) {
        throw new TypeError("Script URL is not allowed.");
      }
      return input;
    },
  });
}
