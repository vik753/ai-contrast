/**
 * API key storage (threat model T1, browser controls; ADR 0016 point 9).
 * `sessionStorage` by default. `localStorage` only after the user opts in. One key per provider
 * under `aic.key.<provider>`. Blocked storage never throws: the key is then simply not kept.
 */
const PREFIX = "aic.key.";

function area(kind: "session" | "local"): Storage | null {
  try {
    return kind === "session" ? sessionStorage : localStorage;
  } catch {
    return null;
  }
}

function read(kind: "session" | "local", provider: string): string | null {
  try {
    return area(kind)?.getItem(PREFIX + provider) ?? null;
  } catch {
    return null;
  }
}

function remove(kind: "session" | "local", provider: string): void {
  try {
    area(kind)?.removeItem(PREFIX + provider);
  } catch {
    // Blocked storage has nothing to remove.
  }
}

/** The stored key: session first, then local. */
export function getKey(provider: string): string | null {
  return read("session", provider) ?? read("local", provider);
}

export function isRemembered(provider: string): boolean {
  return read("session", provider) === null && read("local", provider) !== null;
}

/** Writes to the chosen storage only and removes the copy in the other one. */
export function setKey(provider: string, key: string, options: { remember: boolean }): void {
  const [target, other] = options.remember
    ? (["local", "session"] as const)
    : (["session", "local"] as const);
  remove(other, provider);
  try {
    area(target)?.setItem(PREFIX + provider, key);
  } catch {
    // Blocked or full storage: the key is not kept.
  }
}

export function forgetKey(provider: string): void {
  remove("session", provider);
  remove("local", provider);
}

export function forgetAllKeys(): void {
  for (const kind of ["session", "local"] as const) {
    try {
      const s = area(kind);
      if (s === null) continue;
      const names: string[] = [];
      for (let i = 0; i < s.length; i++) {
        const name = s.key(i);
        if (name?.startsWith(PREFIX) === true) names.push(name);
      }
      for (const name of names) s.removeItem(name);
    } catch {
      // Blocked storage has nothing to remove.
    }
  }
}
