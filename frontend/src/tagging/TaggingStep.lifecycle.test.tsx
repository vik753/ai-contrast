/** S8-T3 review MAJOR — Clear all, removed documents, one-time tokens and stale results. */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import i18next from "i18next";
import { createElement } from "react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { clearAllData } from "../storage/historySetting";
import { FRAME_ORIGIN, jsonResponse, type Captured } from "../test/provider-fakes";
import {
  NAMES,
  SELECTION,
  bodyOf,
  maskedDoc,
  stubTagFetch,
  tagCalls,
  tagReply,
} from "../test/tagging-fakes";
import { t } from "../test/tagging-step-harness";
import { must } from "../test/topics-fakes";
import type { TopicSelection } from "../topics/types";
import { maskedDocsStore, useMaskedDocs } from "./maskedDocsStore";
import { TaggingStep } from "./TaggingStep";

const D = { A: "a".repeat(64), B: "b".repeat(64), C: "c".repeat(64) };
const docs = () => (["A", "B", "C"] as const).map((l) => maskedDoc(l, D[l]));
const labelOf = (c: Captured): string => (bodyOf(c).document as { label: string }).label;
const replyFor = (c: Captured, extra: Record<string, unknown> = {}) =>
  jsonResponse(200, tagReply({ digest: D[labelOf(c) as keyof typeof D], ...extra }));

interface Held {
  signal: AbortSignal | null | undefined;
  release: () => void;
}
/** The first /api/tag call hangs until released or aborted; later calls answer at once. */
function holdFirst() {
  const held: Held[] = [];
  const stub = stubTagFetch((c) => {
    if (c.url !== "/api/tag") return undefined;
    if (held.length > 0) return replyFor(c);
    return new Promise<Response>((resolve, reject) => {
      const h: Held = { signal: c.init.signal, release: () => resolve(replyFor(c)) };
      held.push(h);
      c.init.signal?.addEventListener("abort", () => {
        reject(new DOMException("aborted", "AbortError"));
      });
    });
  });
  return { ...stub, held };
}

function Host(p: {
  connection?: Record<string, unknown>;
  selection?: TopicSelection;
  turnstileToken?: string;
}) {
  const documents = useMaskedDocs();
  return createElement(TaggingStep, {
    connection: { provider: "openai", model: "m1", key: "sk-x" },
    selection: SELECTION,
    topicNames: NAMES,
    documents,
    ...p,
  } as never);
}

async function mount(props: Parameters<typeof Host>[0] = {}) {
  vi.stubEnv("VITE_TURNSTILE_FRAME_ORIGIN", FRAME_ORIGIN);
  const { setupI18n } = await import("../i18n");
  await setupI18n();
  const ui = (p: Parameters<typeof Host>[0]) =>
    createElement(I18nextProvider, { i18n: i18next }, createElement(Host, p));
  const view = render(ui(props));
  return { ...view, again: (p: Parameters<typeof Host>[0]) => view.rerender(ui(p)) };
}

const startBtn = () => screen.getByRole<HTMLButtonElement>("button", { name: t("tagging.start") });
const click = () => fireEvent.click(startBtn());
const sleep = (ms = 40) => act(() => new Promise<void>((r) => setTimeout(r, ms)));
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
const frame = (c: HTMLElement) =>
  waitFor(() => {
    const el = c.ownerDocument.querySelector("iframe");
    if (!el) throw new Error("no iframe");
    return el;
  });

beforeEach(() => maskedDocsStore.clearAll());
afterEach(() => {
  maskedDocsStore.clearAll();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

it("test_clear_all_during_run_aborts_the_request_and_sends_nothing_more", async () => {
  const { calls, held } = holdFirst();
  for (const d of docs()) maskedDocsStore.set(d);
  await mount();
  click();
  await waitFor(() => expect(held).toHaveLength(1));
  await act(async () => {
    await clearAllData();
  });
  expect(held[0]?.signal?.aborted).toBe(true);
  await sleep();
  expect(tagCalls(calls)).toHaveLength(1);
});

it("test_clear_all_during_run_then_new_documents_start_works_without_stale_state", async () => {
  const { calls, held } = holdFirst();
  for (const d of docs()) maskedDocsStore.set(d);
  await mount();
  click();
  await waitFor(() => expect(held).toHaveLength(1));
  await act(async () => {
    await clearAllData();
  });
  await sleep();
  act(() => maskedDocsStore.set(maskedDoc("A", D.A)));
  await screen.findByRole("button", { name: t("tagging.start") });
  expect(startBtn().disabled).toBe(false);
  expect(screen.queryByTestId("tag-result-A")).toBeNull();
  const status = screen.queryByTestId("tag-progress-A")?.textContent ?? "";
  for (const k of ["running", "done", "failed"])
    expect(status).not.toContain(t(`tagging.status.${k}`));
  expect(screen.queryByRole("alert")).toBeNull();
  click();
  await screen.findByTestId("tag-result-A");
  expect(tagCalls(calls)).toHaveLength(2);
});

it("test_clear_all_while_waiting_for_turnstile_sends_no_call_when_a_token_arrives_later", async () => {
  const { calls } = stubTagFetch((c) => (c.url === "/api/tag" ? replyFor(c) : undefined));
  maskedDocsStore.set(maskedDoc("A", D.A));
  const view = await mount({ connection: { provider: "free" } });
  click();
  const f = await frame(view.container);
  await act(async () => {
    await clearAllData();
  });
  token(f, "tok-late");
  await sleep();
  expect(tagCalls(calls)).toHaveLength(0);
});

it("test_removed_document_is_never_sent_after_removal", async () => {
  const { calls, held } = holdFirst();
  for (const d of docs()) maskedDocsStore.set(d);
  await mount();
  click();
  await waitFor(() => expect(held).toHaveLength(1));
  act(() => maskedDocsStore.remove("B"));
  act(() => held[0]?.release());
  await sleep(80);
  const sent = tagCalls(calls).map(labelOf);
  expect(sent).not.toContain("B");
  expect(sent[0]).toBe("A");
});

it("test_clear_all_empties_results_and_status_for_the_same_label_and_digest", async () => {
  stubTagFetch((c) => (c.url === "/api/tag" ? replyFor(c) : undefined));
  maskedDocsStore.set(maskedDoc("A", D.A));
  await mount();
  click();
  await screen.findByTestId("tag-result-A");
  await act(async () => {
    await clearAllData();
  });
  act(() => maskedDocsStore.set(maskedDoc("A", D.A)));
  await screen.findByRole("button", { name: t("tagging.start") });
  expect(screen.queryByTestId("tag-result-A")).toBeNull();
  const status = screen.queryByTestId("tag-progress-A")?.textContent ?? "";
  expect(status).not.toContain(t("tagging.status.done"));
});

it("test_free_second_start_does_not_reuse_the_one_time_turnstile_prop", async () => {
  const { calls } = stubTagFetch((c) =>
    c.url === "/api/tag" ? replyFor(c, { analysis_pass: "ap-1" }) : undefined,
  );
  maskedDocsStore.set(maskedDoc("A", D.A));
  const view = await mount({ connection: { provider: "free" }, turnstileToken: "tok-prop" });
  click();
  await screen.findByTestId("tag-result-A");
  expect(bodyOf(must(tagCalls(calls)[0])).turnstile_token).toBe("tok-prop");
  click();
  const f = await frame(view.container);
  await sleep();
  expect(tagCalls(calls)).toHaveLength(1);
  token(f, "tok-2");
  await waitFor(() => expect(tagCalls(calls)).toHaveLength(2));
  const second = must(tagCalls(calls)[1]);
  expect(bodyOf(second).turnstile_token).toBe("tok-2");
  expect(second.headers.has("X-Analysis-Pass")).toBe(false);
});

it("test_changing_the_topic_selection_marks_the_old_result_stale", async () => {
  stubTagFetch((c) => (c.url === "/api/tag" ? replyFor(c) : undefined));
  maskedDocsStore.set(maskedDoc("A", D.A));
  const view = await mount();
  click();
  await screen.findByTestId("tag-result-A");
  expect(screen.queryByText(t("tagging.stale"))).toBeNull();
  view.again({ selection: { ...SELECTION, catalog: SELECTION.catalog.slice(0, 1) } });
  await waitFor(() => {
    const result = screen.queryByTestId("tag-result-A");
    expect(result === null || result.textContent.includes(t("tagging.stale"))).toBe(true);
  });
  if (screen.queryByTestId("tag-result-A") === null) return;
  expect(screen.getAllByText(t("tagging.stale")).length).toBeGreaterThan(0);
});
