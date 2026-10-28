/** S3-T6b review fix: Enter that confirms an IME composition must not add the link. */
import { fireEvent, render, screen, within } from "@testing-library/react";
import i18next from "i18next";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setupI18n } from "../i18n";
import { resetBrowserEnv } from "../test/browser-env";
import { FakeFetch } from "../test/upload-fakes";
import { routeFetch } from "../test/segment-router";
import { UploadForm } from "./UploadForm";

const LINK = "https://docs.google.com/document/d/DocIdAAAAAAAAAAAAAAAAAAAAabc123/edit";
let server: FakeFetch;

beforeEach(() => {
  resetBrowserEnv();
  server = new FakeFetch();
  routeFetch(server);
});

afterEach(() => {
  vi.unstubAllGlobals();
  resetBrowserEnv();
});

async function field(): Promise<HTMLInputElement> {
  await setupI18n();
  render(
    <I18nextProvider i18n={i18next}>
      <UploadForm />
    </I18nextProvider>,
  );
  const region = await screen.findByRole("region", { name: "Contract A" });
  return within(region).getByLabelText("Google Docs link");
}

describe("Enter in the link field", () => {
  it("test_enter_during_ime_composition_does_not_add_the_link", async () => {
    const input = await field();
    fireEvent.change(input, { target: { value: LINK } });
    fireEvent.keyDown(input, { key: "Enter", isComposing: true });
    expect(server.fetch).not.toHaveBeenCalled();
    expect(input.value).toBe(LINK);
  });

  it("test_plain_enter_adds_the_link", async () => {
    const input = await field();
    fireEvent.change(input, { target: { value: LINK } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(server.fetch).toHaveBeenCalledTimes(1);
    expect(input.value).toBe("");
  });
});
