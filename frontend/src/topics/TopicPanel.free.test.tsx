/** S7-T3 — in the app, free mode gives the topic calls a Turnstile token, then a free pass. */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import en from "../i18n/locales/en.json";
import { flattenLocale } from "../test/locale-utils";
import { FRAME_ORIGIN, jsonResponse } from "../test/provider-fakes";
import { attr, bodyOf, must, stubTopicsFetch } from "../test/topics-fakes";

const EN = flattenLocale(en);
const text = (k: string): string => String(EN[k]);

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

it("test_free_mode_first_topic_call_uses_token_then_pass_without_turnstile_failed", async () => {
  let n = 0;
  const { calls } = stubTopicsFetch((c) => {
    if (c.url !== "/api/topics/propose-attributes") return undefined;
    n += 1;
    if (!c.headers.has("X-Free-Pass") && bodyOf(c).turnstile_token === undefined)
      return jsonResponse(403, { error: "turnstile_failed" });
    return jsonResponse(200, { attributes: [attr()], dropped: 0, free_pass: `pass-${n}` });
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

  const proposeCalls = () => calls.filter((c) => c.url.includes("propose"));
  fireEvent.click(screen.getByRole("button", { name: text("topics.own.propose") }));
  const frame = await waitFor(() => {
    const el = container.ownerDocument.querySelector("iframe");
    if (!el) throw new Error("no iframe");
    return el;
  });
  act(() => {
    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "turnstile-token", token: "tok-app" },
        origin: FRAME_ORIGIN,
        source: frame.contentWindow,
      }),
    );
  });
  await screen.findByRole("list", { name: text("topics.attr.list") });
  expect(proposeCalls()).toHaveLength(1);
  const first = must(proposeCalls()[0]);
  expect(bodyOf(first).turnstile_token).toBe("tok-app");
  expect(first.headers.get("X-Free-Pass")).toBeNull();
  expect(first.headers.get("X-Provider-Key")).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: text("topics.own.propose") }));
  await waitFor(() => expect(proposeCalls()).toHaveLength(2));
  const second = must(proposeCalls()[1]);
  expect(second.headers.get("X-Free-Pass")).toBe("pass-1");
  expect(bodyOf(second)).not.toHaveProperty("turnstile_token");
});
