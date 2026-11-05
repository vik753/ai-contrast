/** S8-T3 AC3 — free mode: one Turnstile per analysis, the analysis pass for the next document. */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import i18next from "i18next";
import { createElement } from "react";
import { I18nextProvider } from "react-i18next";
import { afterEach, expect, it, vi } from "vitest";
import { FRAME_ORIGIN, jsonResponse } from "../test/provider-fakes";
import {
  DIGEST_B,
  NAMES,
  SELECTION,
  bodyOf,
  maskedDoc,
  stubTagFetch,
  tagCalls,
  tagReply,
} from "../test/tagging-fakes";
import { t } from "./stepHarness";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

async function mount(documents = [maskedDoc("A"), maskedDoc("B", DIGEST_B)]) {
  vi.resetModules();
  vi.stubEnv("VITE_TURNSTILE_FRAME_ORIGIN", FRAME_ORIGIN);
  const { setupI18n } = await import("../i18n");
  await setupI18n();
  const { TaggingStep } = await import("./TaggingStep");
  return render(
    createElement(
      I18nextProvider,
      { i18n: i18next },
      createElement(TaggingStep, {
        connection: { provider: "free" },
        documents,
        selection: SELECTION,
        topicNames: NAMES,
      } as never),
    ),
  );
}

const frame = (c: { container: HTMLElement }) =>
  waitFor(() => {
    const el = c.container.ownerDocument.querySelector("iframe");
    if (!el) throw new Error("no iframe");
    return el;
  });

function token(f: HTMLIFrameElement, tok: string) {
  act(() => {
    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "turnstile-token", token: tok },
        origin: FRAME_ORIGIN,
        source: f.contentWindow,
      }),
    );
  });
}

const route = () =>
  stubTagFetch((c) => {
    if (c.url !== "/api/tag") return undefined;
    const b = bodyOf(c);
    const first = b.turnstile_token !== undefined;
    const label = (b.document as { label: string }).label;
    return jsonResponse(
      200,
      tagReply({
        digest: label === "A" ? "a".repeat(64) : DIGEST_B,
        ...(first ? { analysis_pass: "ap-1" } : {}),
      }),
    );
  });

it("test_free_no_iframe_and_no_call_before_start", async () => {
  const { calls } = route();
  const view = await mount();
  expect(view.container.ownerDocument.querySelector("iframe")).toBeNull();
  expect(tagCalls(calls)).toHaveLength(0);
});

it("test_free_first_document_waits_for_token_then_sends_it_in_body_only", async () => {
  const { calls } = route();
  const view = await mount();
  fireEvent.click(screen.getByRole("button", { name: t("tagging.start") }));
  const f = await frame(view);
  expect(tagCalls(calls)).toHaveLength(0);
  token(f, "tok-1");
  await waitFor(() => expect(tagCalls(calls).length).toBeGreaterThanOrEqual(1));
  const first = tagCalls(calls)[0];
  expect(bodyOf(first as never).turnstile_token).toBe("tok-1");
  expect(first?.headers.has("X-Analysis-Pass")).toBe(false);
  expect(first?.headers.has("X-Provider-Key")).toBe(false);
});

it("test_free_second_document_reuses_the_analysis_pass_without_turnstile", async () => {
  const { calls } = route();
  const view = await mount();
  fireEvent.click(screen.getByRole("button", { name: t("tagging.start") }));
  token(await frame(view), "tok-1");
  await screen.findByTestId("tag-result-B");
  const c = tagCalls(calls);
  expect(c).toHaveLength(2);
  expect(c[1]?.headers.get("X-Analysis-Pass")).toBe("ap-1");
  expect(bodyOf(c[1] as never).turnstile_token).toBeUndefined();
  expect(c[1]?.body).not.toContain("ap-1");
  expect(c[1]?.headers.has("X-Free-Pass")).toBe(false);
});

it("test_free_new_analysis_needs_a_new_turnstile_token_and_drops_the_old_pass", async () => {
  const { calls } = route();
  const view = await mount();
  fireEvent.click(screen.getByRole("button", { name: t("tagging.start") }));
  const f = await frame(view);
  token(f, "tok-1");
  await screen.findByTestId("tag-result-B");
  fireEvent.click(screen.getByRole("button", { name: t("tagging.start") }));
  await new Promise((r) => setTimeout(r, 30));
  expect(tagCalls(calls)).toHaveLength(2);
  token(await frame(view), "tok-2");
  await waitFor(() => expect(tagCalls(calls).length).toBeGreaterThanOrEqual(3));
  const third = tagCalls(calls)[2];
  expect(bodyOf(third as never).turnstile_token).toBe("tok-2");
  expect(third?.headers.has("X-Analysis-Pass")).toBe(false);
});

it("test_free_analysis_pass_error_drops_the_pass_and_shows_message", async () => {
  stubTagFetch((c) => {
    if (c.url !== "/api/tag") return undefined;
    const b = bodyOf(c);
    if (b.turnstile_token !== undefined) {
      return jsonResponse(200, tagReply({ analysis_pass: "ap-1" }));
    }
    return jsonResponse(403, { error: "analysis_pass_expired" });
  });
  const view = await mount();
  fireEvent.click(screen.getByRole("button", { name: t("tagging.start") }));
  token(await frame(view), "tok-1");
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain(t("tagging.error.analysis_pass_expired"));
  expect(screen.getByTestId("tag-progress-B").textContent).toContain(t("tagging.status.failed"));
});

it("test_free_turnstile_failed_is_an_i18n_message", async () => {
  stubTagFetch(() => jsonResponse(403, { error: "turnstile_failed" }));
  const view = await mount([maskedDoc("A")]);
  fireEvent.click(screen.getByRole("button", { name: t("tagging.start") }));
  token(await frame(view), "tok-1");
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain(t("tagging.error.turnstile_failed"));
});
