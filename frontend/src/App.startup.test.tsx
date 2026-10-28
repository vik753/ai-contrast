/** S4-T2: the app calls `startupCleanup()` once at start-up. */
import { render, screen, waitFor } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IndexedDbCacheStore } from "./storage/indexedDbCacheStore";
import { databaseNames, DB_NAME, freshFactory } from "./test/idb-helpers";
import { resetBrowserEnv } from "./test/browser-env";

async function renderApp(): Promise<void> {
  vi.resetModules();
  const i18n = await import("./i18n/index");
  await i18n.setupI18n();
  const mod: { default: ComponentType } = await import("./App");
  const App = mod.default;
  render(<App />);
  await screen.findByRole("main");
}

async function seedDatabase(factory: IDBFactory): Promise<void> {
  const seed = new IndexedDbCacheStore({
    factory,
    clock: () => Date.now(),
    storage: { getItem: () => "on" },
  });
  await seed.put("0".repeat(64), "analysis", { v: 1 });
  seed.close();
}

beforeEach(() => {
  localStorage.clear();
});
afterEach(() => {
  resetBrowserEnv();
  vi.unstubAllGlobals();
});

describe("App start-up cleanup", () => {
  it("test_app_deletes_leftover_database_at_startup_when_history_is_off", async () => {
    const factory = freshFactory();
    vi.stubGlobal("indexedDB", factory);
    await seedDatabase(factory);
    expect(await databaseNames(factory)).toContain(DB_NAME);
    await renderApp();
    await waitFor(async () => {
      expect(await databaseNames(factory)).not.toContain(DB_NAME);
    });
  });

  it("test_app_keeps_database_at_startup_when_history_is_on", async () => {
    const factory = freshFactory();
    vi.stubGlobal("indexedDB", factory);
    localStorage.setItem("aic.history", "on");
    await seedDatabase(factory);
    const del = vi.spyOn(factory, "deleteDatabase");
    await renderApp();
    await new Promise((r) => setTimeout(r, 50));
    expect(del).not.toHaveBeenCalled();
    expect(await databaseNames(factory)).toContain(DB_NAME);
  });
});
