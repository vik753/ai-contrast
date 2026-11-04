/** S6-T5 review MAJOR — "Clear all" empties the open key field; token expiry. */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import en from "../i18n/locales/en.json";
import { flattenLocale } from "../test/locale-utils";
import { FRAME_ORIGIN, stubFetch } from "../test/provider-fakes";
import { MAX_TOKEN_AGE_MS, isExpiredMessage, isTokenFresh } from "./turnstileProtocol";

const EN = flattenLocale(en);
const text = (k: string): string => String(EN[k]);
const KEY = "sk-CANARY-clearall";

async function renderApp(): Promise<HTMLElement> {
  vi.resetModules();
  vi.stubEnv("VITE_TURNSTILE_FRAME_ORIGIN", FRAME_ORIGIN);
  const i18n = await import("../i18n/index");
  await i18n.setupI18n();
  const mod: { default: ComponentType } = await import("../App");
  const { container } = render(<mod.default />);
  await screen.findByRole("main");
  return container;
}

const select = () => screen.getByLabelText<HTMLSelectElement>(/^provider$/i);
const keyInput = () => screen.getByLabelText<HTMLInputElement>(/api key/i);
const remember = () =>
  screen.getByRole<HTMLInputElement>("checkbox", { name: /remember on this device/i });
const testBtn = () => screen.getByRole("button", { name: /test connection/i });

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

async function clearAll(): Promise<void> {
  fireEvent.click(screen.getByRole("button", { name: /data and history/i }));
  fireEvent.click(await screen.findByRole("button", { name: /delete all data in this browser/i }));
  const dialogs = await waitFor(() => {
    const d = [...screen.queryAllByRole("dialog"), ...screen.queryAllByRole("alertdialog")];
    if (d.length === 0) throw new Error("no dialog");
    return d;
  });
  const dialog = dialogs[dialogs.length - 1];
  if (!dialog) throw new Error("no dialog");
  const confirm = within(dialog)
    .getAllByRole("button")
    .find((b) => !/cancel/i.test(b.textContent));
  if (!confirm) throw new Error("no confirm");
  fireEvent.click(confirm);
  await waitFor(() => {
    expect(localStorage.getItem("aic.history")).toBeNull();
    expect(screen.queryAllByRole("dialog")).toHaveLength(0);
  });
}

describe("Clear all with the provider panel open (S6-T5 review)", () => {
  it("test_clear_all_empties_key_field_and_unchecks_remember", async () => {
    await renderApp();
    fireEvent.change(select(), { target: { value: "openai" } });
    fireEvent.change(keyInput(), { target: { value: KEY } });
    fireEvent.click(remember());
    expect(localStorage.getItem("aic.key.openai")).toBe(KEY);
    await clearAll();
    await waitFor(() => {
      expect(keyInput().value).toBe("");
    });
    expect(remember().checked).toBe(false);
    expect(localStorage.getItem("aic.key.openai")).toBeNull();
    expect(sessionStorage.getItem("aic.key.openai")).toBeNull();
  });

  it("test_clear_all_empties_a_session_only_key_too", async () => {
    await renderApp();
    fireEvent.change(select(), { target: { value: "openai" } });
    fireEvent.change(keyInput(), { target: { value: KEY } });
    await clearAll();
    await waitFor(() => {
      expect(keyInput().value).toBe("");
    });
  });

  it("test_test_connection_after_clear_all_sends_no_key_and_shows_missing_key", async () => {
    const { fetchMock } = stubFetch();
    await renderApp();
    fireEvent.change(select(), { target: { value: "openai" } });
    fireEvent.change(screen.getByLabelText(/^model$/i), { target: { value: "gpt-x" } });
    fireEvent.change(keyInput(), { target: { value: KEY } });
    await clearAll();
    fireEvent.click(testBtn());
    expect((await screen.findByRole("alert")).textContent).toContain(
      text("provider.error.invalid_provider_key"),
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("token expiry helpers (S6-T5 review)", () => {
  it("test_max_token_age_is_240_seconds", () => {
    expect(MAX_TOKEN_AGE_MS).toBe(240_000);
  });

  it("test_is_token_fresh_boundary", () => {
    expect(isTokenFresh(1000, 1000 + 240_000)).toBe(true);
    expect(isTokenFresh(1000, 1000 + 240_001)).toBe(false);
    expect(isTokenFresh(1000, 999)).toBe(false);
  });

  it("test_expired_message_shape_is_strict", () => {
    expect(isExpiredMessage({ type: "turnstile-expired" })).toBe(true);
    expect(isExpiredMessage({ type: "turnstile-expired", token: "t" })).toBe(false);
    expect(isExpiredMessage({ type: "expired" })).toBe(false);
    expect(isExpiredMessage("turnstile-expired")).toBe(false);
    expect(isExpiredMessage(null)).toBe(false);
  });
});

describe("expired message in the panel (S6-T5 review)", () => {
  async function mounted() {
    const stub = stubFetch();
    const container = await renderApp();
    fireEvent.click(testBtn());
    const f = await waitFor(() => {
      const el = container.ownerDocument.querySelector("iframe");
      if (!el?.contentWindow) throw new Error("no iframe");
      return el;
    });
    const win = f.contentWindow;
    if (!win) throw new Error("no window");
    const spy = vi.spyOn(win, "postMessage").mockImplementation(() => undefined);
    const send = (data: unknown, origin: string, source: MessageEventSource | null) =>
      act(() => {
        window.dispatchEvent(new MessageEvent("message", { data, origin, source }));
      });
    return { ...stub, win, spy, send };
  }

  it("test_valid_expired_message_requests_a_new_challenge", async () => {
    const { spy, win, send, fetchMock } = await mounted();
    send({ type: "turnstile-expired" }, FRAME_ORIGIN, win);
    await waitFor(() => {
      expect(spy).toHaveBeenCalled();
    });
    expect(spy.mock.calls.at(-1)?.[0]).toEqual({ type: "reset" });
    expect(spy.mock.calls.at(-1)?.[1]).toBe(FRAME_ORIGIN);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ["wrong origin", { type: "turnstile-expired" }, "https://evil.example.test", "frame"],
    ["wrong source", { type: "turnstile-expired" }, FRAME_ORIGIN, "window"],
    ["extra key", { type: "turnstile-expired", x: 1 }, FRAME_ORIGIN, "frame"],
  ])("test_expired_message_with_%s_is_ignored", async (_n, data, origin, src) => {
    const { spy, win, send } = await mounted();
    send(data, origin, src === "frame" ? win : window);
    await new Promise((r) => setTimeout(r, 20));
    expect(spy).not.toHaveBeenCalled();
  });

  it("test_fresh_token_after_an_expired_message_is_used", async () => {
    const { calls, win, send } = await mounted();
    send({ type: "turnstile-expired" }, FRAME_ORIGIN, win);
    send({ type: "turnstile-token", token: "tok-new" }, FRAME_ORIGIN, win);
    await waitFor(() => {
      expect(calls).toHaveLength(1);
    });
    expect(
      (JSON.parse(calls[0]?.body ?? "{}") as { turnstile_token?: string }).turnstile_token,
    ).toBe("tok-new");
  });
});
