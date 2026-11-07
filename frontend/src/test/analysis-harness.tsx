/** Test harness for `AnalysisStep` (S9-T4). Not a test file. */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import i18next from "i18next";
import { createElement } from "react";
import { I18nextProvider } from "react-i18next";
import { vi } from "vitest";
import { setupI18n } from "../i18n";
import en from "../i18n/locales/en.json";
import type { CacheStore } from "../storage/cacheStore";
import { AnalysisStep } from "../analysis/AnalysisStep";
import { maskedDocsStore, useMaskedDocs, type MaskedDoc } from "../tagging/maskedDocsStore";
import type { TaggingResult } from "../tagging/TaggingStep";
import { taggingResult } from "./analysis-fakes";
import { flattenLocale } from "./locale-utils";
import { NAMES, SELECTION, maskedDoc } from "./tagging-fakes";

const EN = flattenLocale(en);
export const t = (k: string): string => String(EN[k]);
export const D = { A: "a".repeat(64), B: "b".repeat(64) };

export interface Opts {
  connection?: Record<string, unknown>;
  documents?: readonly MaskedDoc[];
  taggingResults?: readonly TaggingResult[];
  cacheStore?: CacheStore;
  onResultsChange?: (r: readonly unknown[]) => void;
  [k: string]: unknown;
}

export const docsAB = (): MaskedDoc[] => [maskedDoc("A", D.A), maskedDoc("B", D.B)];
export const tagsAB = (): TaggingResult[] => [taggingResult("A", D.A), taggingResult("B", D.B)];

/** Reads the documents from the store, as `App` does, so Clear all reaches the step. */
function Host(p: Opts) {
  const stored = useMaskedDocs();
  return createElement(AnalysisStep, {
    connection: { provider: "openai", model: "gpt-cheap", checkModel: "gpt-strong", key: "sk-x" },
    selection: SELECTION,
    topicNames: NAMES,
    language: "en",
    taggingResults: tagsAB(),
    ...p,
    documents: p.documents ?? stored,
  } as never);
}

export async function mountStep(o: Opts = {}) {
  await setupI18n();
  const ui = (p: Opts) => createElement(I18nextProvider, { i18n: i18next }, createElement(Host, p));
  const view = render(ui(o));
  return { ...view, again: (p: Opts) => view.rerender(ui(p)) };
}

export function fakeCache() {
  const puts: { key: string; kind: string; data: unknown }[] = [];
  const store: CacheStore = {
    get: () => Promise.resolve(null),
    put: (key, kind, data) => {
      puts.push({ key, kind, data });
      return Promise.resolve("stored");
    },
    list: () => Promise.resolve([]),
    delete: () => Promise.resolve(),
    clear: () => Promise.resolve(),
    purgeExpired: () => Promise.resolve(0),
  };
  return { store, puts };
}

export const startBtn = () =>
  screen.getByRole<HTMLButtonElement>("button", { name: t("analysis.start") });
export const stopBtn = () =>
  screen.getByRole<HTMLButtonElement>("button", { name: t("analysis.stop") });
export const click = () => fireEvent.click(startBtn());
export const sleep = (ms = 40) => act(() => new Promise<void>((r) => setTimeout(r, ms)));
export const statusOf = (l: string) =>
  screen.getByTestId(`analysis-progress-${l}`).textContent ?? "";
export const noGreen = () => document.querySelector('[data-rating="green"]');
export const marks = () => document.querySelectorAll("[data-mark]");
export const setDocs = (docs: readonly MaskedDoc[]) =>
  act(() => {
    for (const d of docs) maskedDocsStore.set(d);
  });
export { act, fireEvent, screen, waitFor, vi };
