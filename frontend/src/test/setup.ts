/**
 * Vitest setup file (runs before every test file).
 *
 * `globals` is off, so Testing Library cannot register its automatic cleanup.
 * We unmount rendered trees after every test here. Test files that run in the
 * `node` environment have no DOM, so the cleanup is skipped for them.
 */
import { createHash } from "node:crypto";
import { configure } from "@testing-library/dom";
import { afterEach } from "vitest";

// Forms chain several fake requests; with the whole suite running in parallel a step can
// take over the 1 s default of `waitFor` and `findBy*` (and the stale-ref race fixed in usePseudoReviews).
configure({ asyncUtilTimeout: 3000 });

/**
 * SHA-256 through Web Crypto runs on a thread pool, so its result arrives after
 * an unpredictable real delay. Tests with fake timers cannot wait for that. Here
 * the digest is computed at once and resolved in a microtask: same bytes, same
 * result, no timing. Tests still see `crypto.subtle.digest` (and may spy on it).
 */
const subtle = (globalThis.crypto as Crypto | undefined)?.subtle;
if (subtle !== undefined) {
  const real = subtle.digest.bind(subtle);
  subtle.digest = (algorithm: AlgorithmIdentifier, data: BufferSource): Promise<ArrayBuffer> => {
    const name = typeof algorithm === "string" ? algorithm : algorithm.name;
    if (name !== "SHA-256") {
      return real(algorithm, data);
    }
    const bytes = ArrayBuffer.isView(data)
      ? new Uint8Array(data.buffer, data.byteOffset, data.byteLength)
      : new Uint8Array(data);
    const out = createHash("sha256").update(bytes).digest();
    return Promise.resolve(out.buffer.slice(out.byteOffset, out.byteOffset + out.byteLength));
  };
}

afterEach(async () => {
  if (typeof document === "undefined") {
    return;
  }
  const { cleanup } = await import("@testing-library/react");
  cleanup();
});
