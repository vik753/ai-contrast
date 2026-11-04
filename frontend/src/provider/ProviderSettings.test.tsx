/** S6-T5 AC1, AC3, AC4 — settings panel behaviour (English UI). */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import en from "../i18n/locales/en.json";
import { flattenLocale } from "../test/locale-utils";
import { FRAME_ORIGIN, jsonResponse, stubFetch } from "../test/provider-fakes";

const EN = flattenLocale(en);
const text = (k: string): string => String(EN[k]);

async function renderPanel(): Promise<{ container: HTMLElement }> {
  vi.resetModules();
  vi.stubEnv("VITE_TURNSTILE_FRAME_ORIGIN", FRAME_ORIGIN);
  const i18n = await import("../i18n/index");
  await i18n.setupI18n();
  const mod = (await import("./ProviderSettings")) as { ProviderSettings: ComponentType };
  const { container } = render(<mod.ProviderSettings />);
  return { container };
}

const select = () => screen.getByLabelText<HTMLSelectElement>(/^provider$/i);
const choose = (id: string) => fireEvent.change(select(), { target: { value: id } });
const testBtn = () => screen.getByRole("button", { name: /test connection/i });
const keyInput = () => screen.getByLabelText<HTMLInputElement>(/api key/i);
const modelInput = () => screen.getByLabelText<HTMLInputElement>(/^model$/i);
function winOf(f: HTMLIFrameElement): Window {
  if (!f.contentWindow) throw new Error("no contentWindow");
  return f.contentWindow;
}
const iframe = (c: HTMLElement) => c.ownerDocument.querySelector("iframe");

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("ProviderSettings fields (S6-T5 AC1)", () => {
  it("test_panel_lists_presets_with_free_selected", async () => {
    await renderPanel();
    expect([...select().options].map((o) => o.value)).toEqual([
      "free",
      "anthropic",
      "openai",
      "gemini",
      "mistral",
      "openrouter",
      "custom",
    ]);
    expect(select().value).toBe("free");
  });

  it("test_free_has_no_model_and_no_key_field", async () => {
    await renderPanel();
    expect(screen.queryByLabelText(/^model$/i)).toBeNull();
    expect(screen.queryByLabelText(/api key/i)).toBeNull();
  });

  it("test_model_field_offers_the_preset_suggestions", async () => {
    const { container } = await renderPanel();
    choose("openai");
    const list = modelInput().getAttribute("list");
    expect(list).toBeTruthy();
    const options = [...container.querySelectorAll(`datalist#${CSS.escape(list ?? "")} option`)];
    const presets: typeof import("./presets") = await import("./presets");
    expect(options.map((o) => o.getAttribute("value"))).toEqual(
      presets.PRESETS.find((p) => p.id === "openai")?.models,
    );
    expect(options.length).toBeGreaterThan(0);
  });

  it("test_base_url_is_hidden_for_non_custom_presets", async () => {
    await renderPanel();
    for (const id of ["free", "anthropic", "openai", "gemini", "mistral", "openrouter"]) {
      choose(id);
      expect(screen.queryByLabelText(/base url/i), id).toBeNull();
      expect(screen.queryByText(/^advanced$/i), id).toBeNull();
    }
  });

  it("test_base_url_for_custom_is_under_an_advanced_details_element", async () => {
    await renderPanel();
    choose("custom");
    const input = screen.getByLabelText(/base url/i);
    const details = input.closest("details");
    expect(details).not.toBeNull();
    expect(within(details as HTMLElement).getByText(/^advanced$/i)).toBeTruthy();
  });

  it("test_key_field_is_password_with_autocomplete_off", async () => {
    await renderPanel();
    choose("openai");
    expect(keyInput().type).toBe("password");
    expect(keyInput().getAttribute("autocomplete")).toBe("off");
  });

  it("test_key_field_is_empty_not_prefilled_in_dom_value_attribute", async () => {
    sessionStorage.setItem("aic.key.openai", "sk-CANARY-stored");
    const { container } = await renderPanel();
    choose("openai");
    expect(container.innerHTML).not.toContain("sk-CANARY-stored");
  });
});

describe("ProviderSettings key storage UI (S6-T5 AC2)", () => {
  it("test_typing_a_key_stores_it_in_session_storage_only", async () => {
    await renderPanel();
    choose("openai");
    fireEvent.change(keyInput(), { target: { value: "sk-CANARY-1" } });
    expect(sessionStorage.getItem("aic.key.openai")).toBe("sk-CANARY-1");
    expect(localStorage.getItem("aic.key.openai")).toBeNull();
  });

  it("test_remember_shows_a_warning_and_moves_the_key_to_local_storage", async () => {
    await renderPanel();
    choose("openai");
    fireEvent.change(keyInput(), { target: { value: "sk-CANARY-1" } });
    expect(screen.queryByRole("note")).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: /remember on this device/i }));
    expect(screen.getByRole("note").textContent).toContain(text("provider.remember.warning"));
    expect(localStorage.getItem("aic.key.openai")).toBe("sk-CANARY-1");
    expect(sessionStorage.getItem("aic.key.openai")).toBeNull();
  });

  it("test_forget_key_clears_storage_and_the_field", async () => {
    await renderPanel();
    choose("openai");
    fireEvent.change(keyInput(), { target: { value: "sk-CANARY-1" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /remember on this device/i }));
    fireEvent.click(screen.getByRole("button", { name: /forget key/i }));
    expect(localStorage.getItem("aic.key.openai")).toBeNull();
    expect(sessionStorage.getItem("aic.key.openai")).toBeNull();
    expect(keyInput().value).toBe("");
  });

  it("test_each_provider_shows_its_own_key", async () => {
    await renderPanel();
    choose("openai");
    fireEvent.change(keyInput(), { target: { value: "k-openai" } });
    choose("anthropic");
    expect(keyInput().value).toBe("");
    fireEvent.change(keyInput(), { target: { value: "k-anthropic" } });
    choose("openai");
    expect(keyInput().value).toBe("k-openai");
  });
});

describe("ProviderSettings test connection (S6-T5 AC2)", () => {
  it("test_connection_sends_key_in_header_and_model_in_body", async () => {
    const { calls } = stubFetch();
    await renderPanel();
    choose("openai");
    fireEvent.change(modelInput(), { target: { value: "gpt-x" } });
    fireEvent.change(keyInput(), { target: { value: "sk-CANARY-2" } });
    fireEvent.click(testBtn());
    await screen.findByRole("status");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.url).toBe("/api/provider/check");
    expect(calls[0]?.headers.get("x-provider-key")).toBe("sk-CANARY-2");
    expect(JSON.parse(calls[0]?.body ?? "{}")).toEqual({ provider: "openai", model: "gpt-x" });
    expect(calls[0]?.init.credentials).toBe("omit");
    expect(calls[0]?.init.redirect).toBe("error");
    expect(calls[0]?.init.cache).toBe("no-store");
  });

  it("test_connection_custom_includes_base_url", async () => {
    const { calls } = stubFetch();
    await renderPanel();
    choose("custom");
    fireEvent.change(modelInput(), { target: { value: "m1" } });
    fireEvent.change(screen.getByLabelText(/base url/i), {
      target: { value: "https://llm.example.test/v1" },
    });
    fireEvent.change(keyInput(), { target: { value: "k" } });
    fireEvent.click(testBtn());
    await screen.findByRole("status");
    expect(JSON.parse(calls[0]?.body ?? "{}")).toEqual({
      provider: "custom",
      model: "m1",
      base_url: "https://llm.example.test/v1",
    });
  });

  it("test_connection_success_shows_the_ok_message", async () => {
    stubFetch();
    await renderPanel();
    choose("openai");
    fireEvent.change(modelInput(), { target: { value: "gpt-x" } });
    fireEvent.change(keyInput(), { target: { value: "k" } });
    fireEvent.click(testBtn());
    expect((await screen.findByRole("status")).textContent).toContain(text("provider.test.ok"));
  });

  it("test_connection_without_key_does_not_call_the_api_and_shows_invalid_key_message", async () => {
    const { fetchMock } = stubFetch();
    await renderPanel();
    choose("openai");
    fireEvent.change(modelInput(), { target: { value: "gpt-x" } });
    fireEvent.click(testBtn());
    expect((await screen.findByRole("alert")).textContent).toContain(
      text("provider.error.invalid_provider_key"),
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("test_connection_without_model_does_not_call_the_api_and_shows_invalid_model_message", async () => {
    const { fetchMock } = stubFetch();
    await renderPanel();
    choose("openai");
    fireEvent.change(keyInput(), { target: { value: "k" } });
    fireEvent.click(testBtn());
    expect((await screen.findByRole("alert")).textContent).toContain(
      text("provider.error.invalid_model"),
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ["provider_auth_failed", 401],
    ["rate_limited", 429],
    ["provider_unavailable", 502],
    ["busy", 503],
  ])("test_connection_error_%s_shows_the_mapped_message", async (code, status) => {
    stubFetch(() => jsonResponse(status, { error: code }));
    await renderPanel();
    choose("openai");
    fireEvent.change(modelInput(), { target: { value: "gpt-x" } });
    fireEvent.change(keyInput(), { target: { value: "k" } });
    fireEvent.click(testBtn());
    expect((await screen.findByRole("alert")).textContent).toContain(
      text(`provider.error.${code}`),
    );
  });

  it("test_connection_hostile_server_text_is_not_rendered", async () => {
    stubFetch(() => jsonResponse(500, { error: "<img src=x onerror=alert(1)>" }));
    const { container } = await renderPanel();
    choose("openai");
    fireEvent.change(modelInput(), { target: { value: "gpt-x" } });
    fireEvent.change(keyInput(), { target: { value: "k" } });
    fireEvent.click(testBtn());
    expect((await screen.findByRole("alert")).textContent).toContain(
      text("provider.error.unknown"),
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).not.toContain("onerror");
  });
});

describe("ProviderSettings notices (S6-T5 AC4)", () => {
  it("test_free_mode_shows_provider_notice_and_cloudflare_check_notice", async () => {
    await renderPanel();
    expect(screen.getByText(text("provider.free.notice"))).toBeTruthy();
    expect(screen.getByText(text("provider.free.turnstileNotice"))).toBeTruthy();
    expect(text("provider.free.notice")).toMatch(/cloudflare/i);
  });

  it("test_free_notice_is_hidden_for_other_presets", async () => {
    await renderPanel();
    choose("openai");
    expect(screen.queryByText(text("provider.free.notice"))).toBeNull();
  });

  it("test_gemini_shows_hint_and_data_use_warning_only_for_gemini", async () => {
    await renderPanel();
    choose("gemini");
    expect(screen.getByText(text("provider.gemini.hint"))).toBeTruthy();
    expect(screen.getByText(text("provider.gemini.dataUse"))).toBeTruthy();
    choose("openai");
    expect(screen.queryByText(text("provider.gemini.hint"))).toBeNull();
    expect(screen.queryByText(text("provider.gemini.dataUse"))).toBeNull();
  });
});

describe("ProviderSettings Turnstile flow (S6-T5 AC3)", () => {
  it("test_no_iframe_and_no_cloudflare_script_on_page_load_in_free_mode", async () => {
    const { container } = await renderPanel();
    expect(iframe(container)).toBeNull();
    expect(document.querySelector("script[src*='cloudflare']")).toBeNull();
    expect(document.querySelector("script[src*='turnstile']")).toBeNull();
  });

  it.each(["anthropic", "openai", "gemini", "mistral", "openrouter", "custom"])(
    "test_no_iframe_for_%s_even_after_test_connection",
    async (id) => {
      stubFetch();
      const { container } = await renderPanel();
      choose(id);
      fireEvent.change(modelInput(), { target: { value: "m" } });
      fireEvent.change(keyInput(), { target: { value: "k" } });
      if (id === "custom") {
        fireEvent.change(screen.getByLabelText(/base url/i), {
          target: { value: "https://llm.example.test/v1" },
        });
      }
      fireEvent.click(testBtn());
      await screen.findByRole("status");
      expect(iframe(container)).toBeNull();
    },
  );

  it("test_free_test_connection_mounts_the_frame_and_waits_for_the_token", async () => {
    const { fetchMock } = stubFetch();
    const { container } = await renderPanel();
    fireEvent.click(testBtn());
    const f = await waitFor(() => {
      const el = iframe(container);
      if (!el) throw new Error("no iframe");
      return el;
    });
    expect(f.getAttribute("src")).toBe(`${FRAME_ORIGIN}/turnstile.html`);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("test_valid_token_message_triggers_the_check_with_the_token", async () => {
    const { calls } = stubFetch();
    const { container } = await renderPanel();
    fireEvent.click(testBtn());
    const f = await waitFor(() => {
      const el = iframe(container);
      if (!el) throw new Error("no iframe");
      return el;
    });
    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { type: "turnstile-token", token: "tok-77" },
          origin: FRAME_ORIGIN,
          source: f.contentWindow,
        }),
      );
    });
    await screen.findByRole("status");
    expect(calls).toHaveLength(1);
    expect(JSON.parse(calls[0]?.body ?? "{}")).toEqual({
      provider: "free",
      turnstile_token: "tok-77",
    });
    expect(calls[0]?.headers.has("x-provider-key")).toBe(false);
    expect(calls[0]?.url).not.toContain("tok-77");
  });

  it.each([
    ["wrong origin", { type: "turnstile-token", token: "t" }, "https://evil.example.test", "frame"],
    ["wrong shape", { type: "turnstile-token", token: "t", x: 1 }, FRAME_ORIGIN, "frame"],
    ["wrong source", { type: "turnstile-token", token: "t" }, FRAME_ORIGIN, "window"],
  ])("test_token_message_with_%s_does_not_trigger_the_check", async (_n, data, origin, src) => {
    const { fetchMock } = stubFetch();
    const { container } = await renderPanel();
    fireEvent.click(testBtn());
    const f = await waitFor(() => {
      const el = iframe(container);
      if (!el) throw new Error("no iframe");
      return el;
    });
    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          data,
          origin,
          source: src === "frame" ? f.contentWindow : window,
        }),
      );
    });
    await new Promise((r) => setTimeout(r, 20));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("test_token_is_single_use_and_the_frame_is_reset_after_the_check", async () => {
    const { calls } = stubFetch();
    const { container } = await renderPanel();
    fireEvent.click(testBtn());
    const f = await waitFor(() => {
      const el = iframe(container);
      if (!el) throw new Error("no iframe");
      return el;
    });
    const spy = vi.spyOn(winOf(f), "postMessage").mockImplementation(() => undefined);
    const send = (token: string) =>
      act(() => {
        window.dispatchEvent(
          new MessageEvent("message", {
            data: { type: "turnstile-token", token },
            origin: FRAME_ORIGIN,
            source: f.contentWindow,
          }),
        );
      });
    send("tok-1");
    await screen.findByRole("status");
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(spy.mock.calls.at(-1)?.[0]).toEqual({ type: "reset" });
    expect(spy.mock.calls.at(-1)?.[1]).toBe(FRAME_ORIGIN);
    // A second click needs a fresh token: no request until the frame sends one.
    fireEvent.click(testBtn());
    await new Promise((r) => setTimeout(r, 20));
    expect(calls).toHaveLength(1);
    send("tok-2");
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(
      (JSON.parse(calls[1]?.body ?? "{}") as { turnstile_token?: string }).turnstile_token,
    ).toBe("tok-2");
  });

  it("test_leaving_free_mode_removes_the_frame", async () => {
    stubFetch();
    const { container } = await renderPanel();
    fireEvent.click(testBtn());
    await waitFor(() => expect(iframe(container)).not.toBeNull());
    choose("openai");
    expect(iframe(container)).toBeNull();
  });
});
