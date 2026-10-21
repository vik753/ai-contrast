/**
 * Unit tests (frontend-dev) for UploadForm behavior not covered by the
 * acceptance tests: unmount aborts, focus after a contract removal, input
 * reset, drag highlight.
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import i18next from "i18next";
import { StrictMode } from "react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setupI18n } from "../i18n";
import { resetBrowserEnv } from "../test/browser-env";
import { FakeFetch, acceptAsPdf, fileList, makeFile } from "../test/upload-fakes";
import { UploadForm } from "./UploadForm";

let server: FakeFetch;

beforeEach(() => {
  resetBrowserEnv();
  server = new FakeFetch();
  vi.stubGlobal("fetch", server.fetch);
});

afterEach(() => {
  vi.unstubAllGlobals();
  resetBrowserEnv();
});

async function renderForm() {
  await setupI18n();
  const view = render(
    <I18nextProvider i18n={i18next}>
      <UploadForm />
    </I18nextProvider>,
  );
  await screen.findByRole("region", { name: "Contract A" });
  return view;
}

function input(label: string): HTMLInputElement {
  const el = screen
    .getByRole("region", { name: `Contract ${label}` })
    .querySelector<HTMLInputElement>('input[type="file"]');
  if (el === null) {
    throw new Error("no input");
  }
  return el;
}

function add(label: string, ...files: File[]): void {
  act(() => {
    fireEvent.change(input(label), { target: { files: fileList(files) } });
  });
}

describe("UploadForm internals", () => {
  it("aborts every check on unmount", async () => {
    const view = await renderForm();
    add("A", makeFile("a.pdf"), makeFile("b.pdf"));
    await waitFor(() => expect(server.calls).toHaveLength(2));
    view.unmount();
    expect(server.calls.every((c) => c.signal?.aborted === true)).toBe(true);
  });

  it("moves focus to Add contract after a contract removal", async () => {
    await renderForm();
    fireEvent.click(screen.getByRole("button", { name: "Add contract" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove Contract C" }));
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("button", { name: "Add contract" })),
    );
  });

  it("re-enables Add contract after a removal at five contracts", async () => {
    await renderForm();
    const addContract = screen.getByRole("button", { name: "Add contract" });
    for (let i = 0; i < 3; i += 1) {
      fireEvent.click(addContract);
    }
    expect(addContract.hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Remove Contract E" }));
    expect(addContract.hasAttribute("disabled")).toBe(false);
  });

  it("clears the input value so the same file can be picked again", async () => {
    await renderForm();
    const el = input("A");
    add("A", makeFile("a.doc"));
    expect(el.value).toBe("");
  });

  it("the hidden file input is out of the tab order", async () => {
    await renderForm();
    expect(input("A").tabIndex).toBe(-1);
    expect(input("A").className).toContain("visually-hidden");
  });

  it("highlights the card while files are dragged over it", async () => {
    await renderForm();
    const card = screen.getByRole("region", { name: "Contract A" });
    const dataTransfer = { files: fileList([]), types: ["Files"] };
    act(() => {
      fireEvent.dragOver(card, { dataTransfer });
    });
    expect(card.className).toContain("contract--dragging");
    act(() => {
      fireEvent.dragLeave(card, { dataTransfer, relatedTarget: document.body });
    });
    expect(card.className).not.toContain("contract--dragging");
  });

  it("ignores a drag without files", async () => {
    await renderForm();
    const card = screen.getByRole("region", { name: "Contract A" });
    let notPrevented = false;
    act(() => {
      notPrevented = fireEvent.dragOver(card, {
        dataTransfer: { files: [], types: ["text/plain"] },
      });
    });
    expect(notPrevented).toBe(true);
    expect(card.className).not.toContain("contract--dragging");
  });

  it("file name with markup appears only as text in the live region", async () => {
    await renderForm();
    const name = "<b>bold</b>.doc";
    add("A", makeFile(name));
    const live = document.querySelector('[aria-live="polite"]');
    expect(live?.textContent).toContain(name);
    expect(live?.querySelector("b")).toBeNull();
    expect(within(screen.getByRole("region", { name: "Contract A" })).getByText(name)).toBeTruthy();
  });

  it("keeps two checks in flight under StrictMode", async () => {
    await setupI18n();
    render(
      <StrictMode>
        <I18nextProvider i18n={i18next}>
          <UploadForm />
        </I18nextProvider>
      </StrictMode>,
    );
    await screen.findByRole("region", { name: "Contract A" });
    add("A", makeFile("f0.pdf"), makeFile("f1.pdf"), makeFile("f2.pdf"));
    await waitFor(() => expect(server.calls).toHaveLength(2));
    expect(server.calls.some((c) => c.signal?.aborted === true)).toBe(false);
    const first = server.calls[0];
    act(() => first?.respond(acceptAsPdf(first.body)));
    await waitFor(() => expect(server.calls).toHaveLength(3));
  });
});
