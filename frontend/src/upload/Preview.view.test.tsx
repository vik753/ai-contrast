/**
 * S3-T4 (developer tests, review findings): character cap of the default
 * view, focus after "Show all", collapsed text not in the DOM.
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import i18next from "i18next";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setupI18n } from "../i18n";
import enJson from "../i18n/locales/en.json";
import { resetBrowserEnv } from "../test/browser-env";
import { FakeFetch, fileList, makeFile, okResponse } from "../test/upload-fakes";
import { routeFetch } from "../test/segment-router";
import { PREVIEW_CHAR_LIMIT } from "./Preview";
import { UploadForm } from "./UploadForm";

let blocksForNextFile: { text: string; part: "body"; page: null }[] = [];

beforeEach(() => {
  resetBrowserEnv();
  const server = new FakeFetch();
  server.autoRespond = (body) =>
    okResponse("text", (body as Blob).size, { blocks: blocksForNextFile });
  routeFetch(server);
});

afterEach(() => {
  vi.unstubAllGlobals();
  resetBrowserEnv();
});

function region(): HTMLElement {
  return screen.getByRole("region", { name: "Contract A" });
}

async function renderWith(texts: string[]): Promise<HTMLElement> {
  blocksForNextFile = texts.map((text) => ({ text, part: "body", page: null }));
  await setupI18n();
  render(
    <I18nextProvider i18n={i18next}>
      <UploadForm />
    </I18nextProvider>,
  );
  const input = (await screen.findByRole("region", { name: "Contract A" })).querySelector(
    'input[type="file"]',
  );
  if (input === null) {
    throw new Error("no input");
  }
  act(() => {
    fireEvent.change(input, { target: { files: fileList([makeFile("main.txt")]) } });
  });
  await waitFor(() => within(region()).getByRole("button", { name: "Preview" }));
  return region();
}

function click(element: HTMLElement): void {
  act(() => {
    fireEvent.click(element);
  });
}

describe("collapsed preview", () => {
  it("test_collapsed_preview_text_is_not_in_the_dom", async () => {
    const container = await renderWith(["Collapsed clause."]);
    expect(within(container).queryByText("Collapsed clause.")).toBeNull();
    click(within(container).getByRole("button", { name: "Preview" }));
    expect(within(container).getByText("Collapsed clause.")).toBeTruthy();
  });
});

describe("character cap and Show all", () => {
  it("test_1000000_character_block_is_shortened_with_marker", async () => {
    const container = await renderWith(["a".repeat(1_000_000)]);
    click(within(container).getByRole("button", { name: "Preview" }));
    const text = container.querySelector(".preview-block__text");
    expect(text?.textContent.length).toBe(PREVIEW_CHAR_LIMIT);
    expect(within(container).getByText(enJson.upload.preview.shortened)).toBeTruthy();

    click(within(container).getByRole("button", { name: /^Show all/ }));
    expect(container.querySelector(".preview-block__text")?.textContent.length).toBe(1_000_000);
    expect(within(container).queryByText(enJson.upload.preview.shortened)).toBeNull();
    // The shortened block is the first one not shown in full: focus goes there.
    expect(document.activeElement).toBe(container.querySelector(".preview-block"));
  });

  it("test_show_all_moves_focus_to_block_201", async () => {
    const container = await renderWith(Array.from({ length: 250 }, (_, i) => `Block ${i + 1}.`));
    click(within(container).getByRole("button", { name: "Preview" }));
    click(within(container).getByRole("button", { name: /^Show all/ }));
    const target = within(container).getByText("Block 201.").closest("li");
    expect(document.activeElement).toBe(target);
    expect(target?.getAttribute("tabindex")).toBe("-1");
  });
});
