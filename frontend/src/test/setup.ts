/**
 * Vitest setup file (runs before every test file).
 *
 * `globals` is off, so Testing Library cannot register its automatic cleanup.
 * We unmount rendered trees after every test here. Test files that run in the
 * `node` environment have no DOM, so the cleanup is skipped for them.
 */
import { afterEach } from "vitest";

afterEach(async () => {
  if (typeof document === "undefined") {
    return;
  }
  const { cleanup } = await import("@testing-library/react");
  cleanup();
});
