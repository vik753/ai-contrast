/** S6-T5 AC2 — the key never reaches URL, IndexedDB, console, the DOM text or error messages. */
import { fireEvent, render, screen } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, stubFetch } from "../test/provider-fakes";

const CANARY = `sk-CANARY-${Math.random().toString(16).slice(2, 10)}`;

async function renderPanel(): Promise<HTMLElement> {
  vi.resetModules();
  const i18n = await import("../i18n/index");
  await i18n.setupI18n();
  const mod = (await import("./ProviderSettings")) as { ProviderSettings: ComponentType };
  return render(<mod.ProviderSettings />).container;
}

function fill(): void {
  fireEvent.change(screen.getByLabelText(/^provider$/i), { target: { value: "openai" } });
  fireEvent.change(screen.getByLabelText(/^model$/i), { target: { value: "gpt-x" } });
  fireEvent.change(screen.getByLabelText(/api key/i), { target: { value: CANARY } });
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("key leak canary (S6-T5 AC2)", () => {
  it("test_key_not_in_url_console_idb_or_dom_after_success", async () => {
    const parts: string[] = [];
    for (const m of ["log", "info", "warn", "error", "debug", "trace"] as const) {
      vi.spyOn(console, m).mockImplementation((...a: unknown[]) => {
        parts.push(a.map(String).join(" "));
      });
    }
    const idbOpen = vi.fn();
    vi.stubGlobal("indexedDB", { open: idbOpen, databases: vi.fn(() => Promise.resolve([])) });
    const { calls } = stubFetch();
    const container = await renderPanel();
    fill();
    fireEvent.click(screen.getByRole("button", { name: /test connection/i }));
    await screen.findByRole("status");
    expect(calls[0]?.url).not.toContain(CANARY);
    expect(calls[0]?.body).not.toContain(CANARY);
    expect(idbOpen).not.toHaveBeenCalled();
    expect(parts.join("\n")).not.toContain(CANARY);
    expect(container.innerHTML).not.toContain(CANARY);
    expect(document.title).not.toContain(CANARY);
    expect(location.href).not.toContain(CANARY);
  });

  it("test_key_not_in_console_or_dom_when_fetch_throws_with_the_key_in_the_error", async () => {
    const parts: string[] = [];
    for (const m of ["log", "info", "warn", "error", "debug", "trace"] as const) {
      vi.spyOn(console, m).mockImplementation((...a: unknown[]) => {
        parts.push(a.map((x) => (x instanceof Error ? x.message : String(x))).join(" "));
      });
    }
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError(`failed ${CANARY}`))),
    );
    const container = await renderPanel();
    fill();
    fireEvent.click(screen.getByRole("button", { name: /test connection/i }));
    await screen.findByRole("alert");
    expect(parts.join("\n")).not.toContain(CANARY);
    expect(container.innerHTML).not.toContain(CANARY);
  });

  it("test_key_not_in_dom_when_server_echoes_it_in_an_error", async () => {
    stubFetch(() => jsonResponse(400, { error: `bad ${CANARY}` }));
    const container = await renderPanel();
    fill();
    fireEvent.click(screen.getByRole("button", { name: /test connection/i }));
    await screen.findByRole("alert");
    expect(container.innerHTML).not.toContain(CANARY);
  });

  it("test_key_stays_out_of_local_storage_unless_remember_is_chosen", async () => {
    stubFetch();
    await renderPanel();
    fill();
    fireEvent.click(screen.getByRole("button", { name: /test connection/i }));
    await screen.findByRole("status");
    expect(JSON.stringify(Object.entries(localStorage))).not.toContain(CANARY);
  });
});
