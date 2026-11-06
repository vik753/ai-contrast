/** Test harness for `TaggingStep` (S8-T3). Not a test file. */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import i18next from "i18next";
import { createElement } from "react";
import { I18nextProvider } from "react-i18next";
import en from "../i18n/locales/en.json";
import { setupI18n } from "../i18n";
import { flattenLocale } from "./locale-utils";
import { NAMES, SELECTION, maskedDoc } from "./tagging-fakes";
import type { MaskedDoc } from "../tagging/maskedDocsStore";
import { TaggingStep } from "../tagging/TaggingStep";

const EN = flattenLocale(en);
export const t = (k: string): string => String(EN[k]);

export interface Opts {
  documents?: readonly MaskedDoc[];
  connection?: Record<string, unknown>;
  selection?: typeof SELECTION;
  turnstileToken?: string;
  onResultsChange?: (r: readonly unknown[]) => void;
}

export async function renderStep(o: Opts = {}) {
  await setupI18n();
  const props = {
    connection: { provider: "openai", model: "gpt-cheap", checkModel: "gpt-strong", key: "sk-x" },
    documents: [maskedDoc("A")],
    selection: SELECTION,
    topicNames: NAMES,
    ...o,
  };
  const view = render(
    createElement(I18nextProvider, { i18n: i18next }, createElement(TaggingStep, props as never)),
  );
  return view;
}

export const start = () =>
  fireEvent.click(screen.getByRole("button", { name: t("tagging.start") }));
export const byId = (id: string) => screen.getByTestId(id);
export const clauseEl = (root: HTMLElement, id: string): HTMLElement => {
  const el = root.querySelector<HTMLElement>(`[data-clause-id="${id}"]`);
  if (!el) throw new Error(`no clause ${id}`);
  return el;
};
export const chips = (root: HTMLElement) =>
  Array.from(root.querySelectorAll<HTMLElement>("[data-topic-id][data-source]"));
export async function done(label = "A") {
  return screen.findByTestId(`tag-result-${label}`);
}
export { act, fireEvent, screen, waitFor, within };
