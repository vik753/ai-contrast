/** S8-T3 AC1 — confirmed masked documents reach App, TaggingStep and TopicPanel (Suggest). */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import en from "../i18n/locales/en.json";
import { resetBrowserEnv } from "../test/browser-env";
import { flattenLocale } from "../test/locale-utils";
import { BLOCKS, DETECTOR_VERSION, fixtureReply, installRouter } from "../test/pseudo-fakes";
import { jsonResponse as provJson } from "../test/provider-fakes";
import { CATALOG, must } from "../test/topics-fakes";
import { Servers, addFile, region, settle } from "../test/segment-fakes";
import { jsonResponse, makeFile } from "../test/upload-fakes";

const EN = flattenLocale(en);
const t = (k: string): string => String(EN[k]);
const DIGEST = "d".repeat(64);

let servers: Servers;
let safetyOk = true;

beforeEach(() => {
  resetBrowserEnv();
  sessionStorage.clear();
  safetyOk = true;
  servers = new Servers();
  installRouter({
    extract: (b) => {
      const auto = servers.extract.autoRespond;
      if (auto === null) throw new Error("no extract fake");
      return auto(b);
    },
    segment: () => jsonResponse(200, fixtureReply()),
    safety: () =>
      safetyOk
        ? jsonResponse(200, { ok: true, detector_version: DETECTOR_VERSION, digest: DIGEST })
        : jsonResponse(409, { error: "detector_version_mismatch" }),
  });
  const routed = globalThis.fetch;
  vi.stubGlobal("fetch", (input: unknown, init?: RequestInit) =>
    String(input) === "/api/topics/catalog"
      ? Promise.resolve(provJson(200, CATALOG))
      : routed(input as never, init),
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
  resetBrowserEnv();
});

async function mountApp() {
  vi.resetModules();
  const i18n = await import("../i18n/index");
  await i18n.setupI18n();
  const mod: { default: ComponentType } = await import("../App");
  const store = await import("./maskedDocsStore");
  render(<mod.default />);
  await screen.findByRole("main");
  return store.maskedDocsStore;
}

async function confirmContract() {
  addFile(servers, "A", makeFile("a.docx", { content: "x" }), BLOCKS);
  const open = await waitFor(() =>
    within(region("A")).getByRole("button", { name: t("pseudo.checkReplacements") }),
  );
  fireEvent.click(open);
  const ok = await screen.findByRole("button", { name: t("pseudo.everythingCorrect") });
  fireEvent.click(ok);
  await settle(40);
}

it("test_app_confirmed_document_lands_in_the_store_with_masked_text_and_digest", async () => {
  const store = await mountApp();
  expect(store.get()).toHaveLength(0);
  await confirmContract();
  await waitFor(() => expect(store.get()).toHaveLength(1));
  const doc = store.get()[0];
  expect(doc?.label).toBe("A");
  expect(doc?.digest).toBe(DIGEST);
  expect(doc?.detectorVersion).toBe(DETECTOR_VERSION);
  expect(doc?.clauses.length).toBeGreaterThan(0);
});

it("test_app_unconfirmed_document_is_not_in_the_store", async () => {
  const store = await mountApp();
  addFile(servers, "A", makeFile("a.docx", { content: "x" }), BLOCKS);
  await waitFor(() =>
    within(region("A")).getByRole("button", { name: t("pseudo.checkReplacements") }),
  );
  await settle(40);
  expect(store.get()).toHaveLength(0);
});

it("test_app_suggest_button_enabled_once_a_document_is_confirmed", async () => {
  await mountApp();
  fireEvent.click(screen.getByRole("button", { name: t("topics.open") }));
  await screen.findByRole("option", { name: "Car insurance" });
  fireEvent.change(screen.getByLabelText(t("topics.domain.label")), { target: { value: "kasko" } });
  const suggest = () => screen.getByRole("button", { name: t("topics.suggest.button") });
  expect((suggest() as HTMLButtonElement).disabled).toBe(true);
  await confirmContract();
  await waitFor(() => expect((suggest() as HTMLButtonElement).disabled).toBe(false));
});

it("test_app_shows_tagging_region_only_when_a_document_is_confirmed", async () => {
  await mountApp();
  expect(screen.queryByRole("region", { name: t("tagging.title") })).toBeNull();
  await confirmContract();
  await screen.findByRole("region", { name: t("tagging.title") });
});

it("test_app_clear_all_empties_the_store_and_hides_the_tagging_step", async () => {
  const store = await mountApp();
  await confirmContract();
  await waitFor(() => expect(store.get()).toHaveLength(1));
  fireEvent.click(screen.getByRole("button", { name: /data and history/i }));
  fireEvent.click(await screen.findByRole("button", { name: /delete all data in this browser/i }));
  const dialogs = await screen
    .findAllByRole("dialog")
    .catch(() => screen.findAllByRole("alertdialog"));
  const dialog = must(dialogs[dialogs.length - 1]);
  const go = must(
    within(dialog)
      .getAllByRole("button")
      .find((b) => !/cancel/i.test(b.textContent)),
  );
  act(() => {
    fireEvent.click(go);
  });
  await waitFor(() => expect(store.get()).toHaveLength(0));
  await waitFor(() =>
    expect(screen.queryByRole("region", { name: t("tagging.title") })).toBeNull(),
  );
});

it("test_app_does_not_write_masked_text_to_browser_storage", async () => {
  await mountApp();
  await confirmContract();
  const dump = [localStorage, sessionStorage]
    .flatMap((s) => Array.from({ length: s.length }, (_, i) => must(s.key(i))))
    .join("|");
  const values = [localStorage, sessionStorage]
    .flatMap((s) => Array.from({ length: s.length }, (_, i) => s.getItem(must(s.key(i))) ?? ""))
    .join("|");
  expect(dump + values).not.toContain("[A.");
  expect(dump + values).not.toContain(DIGEST);
});
