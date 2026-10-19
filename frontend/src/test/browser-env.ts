/**
 * Test helpers that change and restore browser state:
 * localStorage, navigator.language and <html lang>.
 *
 * Every test must call `resetBrowserEnv()` in `afterEach` (and may call it in
 * `beforeEach`) so that no state leaks between tests.
 */
import { vi } from "vitest";

const STORAGE_TARGETS: object[] = [globalThis];
if (typeof window !== "undefined" && (window as object) !== globalThis) {
  STORAGE_TARGETS.push(window);
}

const originalStorageDescriptors = new Map<object, PropertyDescriptor | undefined>(
  STORAGE_TARGETS.map((target) => [
    target,
    Object.getOwnPropertyDescriptor(target, "localStorage"),
  ]),
);

function securityError(): DOMException {
  return new DOMException("The operation is insecure.", "SecurityError");
}

/** Makes `localStorage.getItem` throw, as in a browser with blocked storage. */
export function makeGetItemThrow(): void {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw securityError();
  });
}

/** Makes `localStorage.setItem` throw, as with a full quota or blocked storage. */
export function makeSetItemThrow(): void {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw securityError();
  });
}

/** Makes reading the `localStorage` property itself throw (Safari / sandboxed iframes). */
export function makeLocalStorageAccessThrow(): void {
  for (const target of STORAGE_TARGETS) {
    Object.defineProperty(target, "localStorage", {
      configurable: true,
      get() {
        throw securityError();
      },
    });
  }
}

function restoreLocalStorageProperty(): void {
  for (const target of STORAGE_TARGETS) {
    const original = originalStorageDescriptors.get(target);
    if (original) {
      Object.defineProperty(target, "localStorage", original);
    } else {
      Reflect.deleteProperty(target, "localStorage");
    }
  }
}

/** Pretends that the browser prefers another language. */
export function setBrowserLanguage(language: string): void {
  Object.defineProperty(navigator, "language", {
    configurable: true,
    get: () => language,
  });
  Object.defineProperty(navigator, "languages", {
    configurable: true,
    get: () => [language, language.split("-")[0]],
  });
}

function restoreBrowserLanguage(): void {
  Reflect.deleteProperty(navigator, "language");
  Reflect.deleteProperty(navigator, "languages");
}

export function resetBrowserEnv(): void {
  vi.restoreAllMocks();
  restoreLocalStorageProperty();
  restoreBrowserLanguage();
  globalThis.localStorage.clear();
  document.documentElement.removeAttribute("lang");
}
