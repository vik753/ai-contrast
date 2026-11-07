/** S9-T4 AC1 (stage 7 follow-up) — a free-pass reply that started before Clear all is ignored. */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import en from "../i18n/locales/en.json";
import { clearAllData } from "../storage/historySetting";
import { flattenLocale } from "../test/locale-utils";
import { FRAME_ORIGIN, jsonResponse } from "../test/provider-fakes";
import { attr, stubTopicsFetch } from "../test/topics-fakes";

const EN = flattenLocale(en);
const text = (k: string): string => String(EN[k]);

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

it("test_free_pass_from_a_reply_that_started_before_clear_all_is_not_used_afterwards", async () => {
  let release: (r: Response) => void = () => undefined;
  let n = 0;
  const { calls } = stubTopicsFetch((c) => {
    if (c.url !== "/api/topics/propose-attributes") return undefined;
    n += 1;
    if (n === 1)
      return new Promise<Response>((res) => {
        release = res; // not tied to the abort signal: the reply arrives after Clear all
      });
    return jsonResponse(200, { attributes: [attr()], dropped: 0, free_pass: "pass-2" });
  });
  vi.resetModules();
  vi.stubEnv("VITE_TURNSTILE_FRAME_ORIGIN", FRAME_ORIGIN);
  const i18n = await import("../i18n/index");
  await i18n.setupI18n();
  const mod: { default: ComponentType } = await import("../App");
  const { container } = render(<mod.default />);
  await screen.findByRole("main");
  fireEvent.click(screen.getByRole("button", { name: text("topics.open") }));
  await screen.findByRole("option", { name: "Car insurance" });
  fireEvent.change(screen.getByLabelText(text("topics.domain.label")), {
    target: { value: "kasko" },
  });
  fireEvent.change(screen.getByLabelText(text("topics.own.name")), { target: { value: "T" } });
  const propose = () => screen.getByRole("button", { name: text("topics.own.propose") });
  const frameEl = () =>
    waitFor(() => {
      const el = container.ownerDocument.querySelector("iframe");
      if (!el) throw new Error("no iframe");
      return el;
    });
  const token = (f: HTMLIFrameElement, tok: string) =>
    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { type: "turnstile-token", token: tok },
          origin: FRAME_ORIGIN,
          source: f.contentWindow,
        }),
      );
    });

  fireEvent.click(propose());
  token(await frameEl(), "tok-1");
  await waitFor(() => expect(n).toBe(1));

  await act(async () => {
    await clearAllData();
  });
  await act(async () => {
    release(jsonResponse(200, { attributes: [attr()], dropped: 0, free_pass: "pass-late" }));
    await new Promise((r) => setTimeout(r, 40));
  });

  fireEvent.click(propose());
  // the late pass was dropped: the next call needs a new token
  token(await frameEl(), "tok-2");
  await waitFor(() => expect(n).toBe(2));
  const second = calls.filter((c) => c.url === "/api/topics/propose-attributes")[1];
  expect(second?.headers.get("X-Free-Pass")).toBeNull();
  expect(JSON.parse(second?.body ?? "{}")).toHaveProperty("turnstile_token", "tok-2");
});
