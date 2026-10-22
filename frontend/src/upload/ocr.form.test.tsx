/**
 * S3-T5 AC5, AC6, AC7 — OCR orchestration through the rendered upload form.
 *
 * `../ocr/ocrPdf` is mocked (its own behavior is tested in ocrPdf.test.ts).
 * Assumed contract: the form loads `../ocr/ocrPdf` lazily (dynamic import)
 * only when an accepted file has `ocr_pages`, and calls
 *   recognizePages(file, pages, { signal, onProgress })
 * with the very `File` the person added; `onProgress({current,total,page})`.
 * It runs one OCR job in the whole form, shows "Recognizing page N of M…"
 * (N = `current`, M = `total`), aborts the job when the file is removed or the
 * form unmounts, and merges the result into the file's extraction.
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import i18next from "i18next";
import type { ComponentType } from "react";
import { I18nextProvider } from "react-i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setupI18n } from "../i18n";
import enJson from "../i18n/locales/en.json";
import { resetBrowserEnv } from "../test/browser-env";
import { flattenLocale } from "../test/locale-utils";
import { FakeFetch, fileList, makeFile, okResponse } from "../test/upload-fakes";
import * as UploadFormModule from "./UploadForm";

interface Job {
  file: File;
  pages: readonly number[];
  signal: AbortSignal;
  onProgress: (p: { current: number; total: number; page: number }) => void;
  resolve: (r: { page: number; text: string; confidence: number }[]) => void;
  reject: (e: unknown) => void;
}

const h = vi.hoisted(() => ({ loads: 0, jobs: [] as unknown[] }));

vi.mock("../ocr/ocrPdf", () => {
  h.loads += 1;
  return {
    recognizePages: (file: File, pages: readonly number[], opts: Record<string, unknown>) =>
      new Promise((resolve, reject) => {
        const job = { file, pages, ...opts, resolve, reject };
        h.jobs.push(job);
        (opts.signal as AbortSignal).addEventListener("abort", () => {
          reject(new DOMException("aborted", "AbortError"));
        });
      }),
  };
});

const EN = flattenLocale(enJson);
const moduleExports: Record<string, unknown> = UploadFormModule;
const UploadForm = (moduleExports.UploadForm ?? moduleExports.default) as ComponentType;
const jobs = (): Job[] => h.jobs as Job[];
function jobAt(index: number): Job {
  const job = jobs()[index];
  if (job === undefined) {
    throw new Error(`no OCR job ${String(index)}`);
  }
  return job;
}

let server: FakeFetch;
/** Server answer per file name: the `ocr_pages` to report. */
let ocrPagesFor: Record<string, number[]>;
const sentFiles = new Map<string, File>();

beforeEach(() => {
  resetBrowserEnv();
  h.jobs.length = 0;
  ocrPagesFor = {};
  server = new FakeFetch();
  server.autoRespond = (body) => {
    const blob = body as File;
    const name = [...sentFiles].find(([, f]) => f === blob)?.[0] ?? "";
    const pages = ocrPagesFor[name] ?? [];
    const count = Math.max(4, ...pages);
    return okResponse("pdf", blob.size, {
      pages: count,
      blocks: pages.length === 0 ? [{ text: "Server text.", part: "body", page: 1 }] : [],
      ocr_pages: pages,
    });
  };
  vi.stubGlobal("fetch", server.fetch);
});

afterEach(() => {
  vi.unstubAllGlobals();
  resetBrowserEnv();
  sentFiles.clear();
});

async function renderForm(): Promise<() => void> {
  await setupI18n();
  const { unmount } = render(
    <I18nextProvider i18n={i18next}>
      <UploadForm />
    </I18nextProvider>,
  );
  await screen.findByRole("region", { name: "Contract A" });
  return unmount;
}

function add(contract: "A" | "B", name: string): File {
  const file = makeFile(name);
  sentFiles.set(name, file);
  const input = screen
    .getByRole("region", { name: `Contract ${contract}` })
    .querySelector('input[type="file"]');
  if (input === null) {
    throw new Error("no input");
  }
  act(() => {
    fireEvent.change(input, { target: { files: fileList([file]) } });
  });
  return file;
}

const progress = (job: Job, current: number, total: number, page: number): void => {
  act(() => {
    job.onProgress({ current, total, page });
  });
};

const settle = async (job: Job, pages: { page: number; text: string; confidence: number }[]) => {
  await act(async () => {
    job.resolve(pages);
    await Promise.resolve();
  });
};

describe("lazy loading (AC7), must run first in this file", () => {
  it("test_ocr_module_is_not_loaded_when_no_file_needs_ocr", async () => {
    await renderForm();
    add("A", "plain.pdf");
    await waitFor(() => {
      expect(server.calls.length).toBe(1);
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(jobs()).toHaveLength(0);
    expect(h.loads).toBe(0);
  });
});

describe("start and file hand-over (AC5)", () => {
  it("test_accepted_pdf_with_ocr_pages_starts_one_job_with_the_original_file", async () => {
    ocrPagesFor["scan.pdf"] = [2, 3];
    await renderForm();
    const file = add("A", "scan.pdf");
    await waitFor(() => {
      expect(jobs()).toHaveLength(1);
    });
    expect(jobs()[0]?.file).toBe(file);
    expect(jobs()[0]?.pages).toEqual([2, 3]);
    expect(jobs()[0]?.signal.aborted).toBe(false);
  });

  it("test_progress_text_shows_page_n_of_m", async () => {
    ocrPagesFor["scan.pdf"] = [2, 3];
    await renderForm();
    add("A", "scan.pdf");
    await waitFor(() => {
      expect(jobs()).toHaveLength(1);
    });
    const job = jobAt(0);
    progress(job, 1, 2, 2);
    expect(await screen.findByText("Recognizing page 1 of 2…")).toBeTruthy();
    progress(job, 2, 2, 3);
    expect(await screen.findByText("Recognizing page 2 of 2…")).toBeTruthy();
    expect(screen.queryByText("Recognizing page 1 of 2…")).toBeNull();
  });

  it("test_form_is_not_ready_while_ocr_runs", async () => {
    ocrPagesFor["scan.pdf"] = [2];
    await renderForm();
    add("A", "scan.pdf");
    await waitFor(() => {
      expect(jobs()).toHaveLength(1);
    });
    expect(screen.getAllByText(EN["upload.readiness.checking"] as string).length).toBeGreaterThan(
      0,
    );
  });
});

describe("one job at a time (AC5)", () => {
  it("test_second_scan_waits_until_the_first_job_ends", async () => {
    ocrPagesFor["one.pdf"] = [1];
    ocrPagesFor["two.pdf"] = [2];
    await renderForm();
    add("A", "one.pdf");
    add("B", "two.pdf");
    await waitFor(() => {
      expect(server.calls).toHaveLength(2);
    });
    await waitFor(() => {
      expect(jobs()).toHaveLength(1);
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(jobs()).toHaveLength(1);
    await settle(jobAt(0), [{ page: 1, text: "First", confidence: 90 }]);
    await waitFor(() => {
      expect(jobs()).toHaveLength(2);
    });
    expect(jobs()[1]?.pages).toEqual([2]);
  });

  it("test_next_job_starts_after_a_failed_job", async () => {
    ocrPagesFor["one.pdf"] = [1];
    ocrPagesFor["two.pdf"] = [2];
    await renderForm();
    add("A", "one.pdf");
    add("B", "two.pdf");
    await waitFor(() => {
      expect(jobs()).toHaveLength(1);
    });
    await act(async () => {
      jobAt(0).reject(new Error("synthetic failure"));
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(jobs()).toHaveLength(2);
    });
  });
});

describe("cancel (AC5)", () => {
  it("test_removing_the_file_aborts_the_running_job", async () => {
    ocrPagesFor["scan.pdf"] = [2];
    await renderForm();
    add("A", "scan.pdf");
    await waitFor(() => {
      expect(jobs()).toHaveLength(1);
    });
    const region = screen.getByRole("region", { name: "Contract A" });
    act(() => {
      fireEvent.click(within(region).getByRole("button", { name: /remove/i }));
    });
    expect(jobAt(0).signal.aborted).toBe(true);
  });

  it("test_removing_the_running_file_starts_the_next_scan", async () => {
    ocrPagesFor["one.pdf"] = [1];
    ocrPagesFor["two.pdf"] = [2];
    await renderForm();
    add("A", "one.pdf");
    add("B", "two.pdf");
    await waitFor(() => {
      expect(jobs()).toHaveLength(1);
    });
    const region = screen.getByRole("region", { name: "Contract A" });
    act(() => {
      fireEvent.click(within(region).getByRole("button", { name: /remove/i }));
    });
    await waitFor(() => {
      expect(jobs()).toHaveLength(2);
    });
    expect(jobs()[1]?.pages).toEqual([2]);
  });

  it("test_a_result_that_arrives_after_removal_is_ignored", async () => {
    ocrPagesFor["scan.pdf"] = [2];
    await renderForm();
    add("A", "scan.pdf");
    await waitFor(() => {
      expect(jobs()).toHaveLength(1);
    });
    const region = screen.getByRole("region", { name: "Contract A" });
    act(() => {
      fireEvent.click(within(region).getByRole("button", { name: /remove/i }));
    });
    await settle(jobAt(0), [{ page: 2, text: "Ghost text", confidence: 90 }]);
    expect(screen.queryByText("Ghost text")).toBeNull();
  });

  it("test_unmounting_the_form_aborts_the_running_job", async () => {
    ocrPagesFor["scan.pdf"] = [2];
    const unmount = await renderForm();
    add("A", "scan.pdf");
    await waitFor(() => {
      expect(jobs()).toHaveLength(1);
    });
    unmount();
    expect(jobAt(0).signal.aborted).toBe(true);
  });
});

describe("merge and warnings (AC5, AC6)", () => {
  async function finishScan(
    pages: { page: number; text: string; confidence: number }[],
  ): Promise<HTMLElement> {
    ocrPagesFor["scan.pdf"] = pages.map((p) => p.page);
    await renderForm();
    add("A", "scan.pdf");
    await waitFor(() => {
      expect(jobs()).toHaveLength(1);
    });
    await settle(jobAt(0), pages);
    const region = screen.getByRole("region", { name: "Contract A" });
    await waitFor(() => within(region).getByRole("button", { name: "Preview" }));
    act(() => {
      fireEvent.click(within(region).getByRole("button", { name: "Preview" }));
    });
    return region;
  }

  it("test_recognized_text_appears_in_the_preview_as_page_blocks", async () => {
    const region = await finishScan([{ page: 2, text: "Recognized clause.", confidence: 90 }]);
    expect(within(region).getByText("Recognized clause.")).toBeTruthy();
    expect(within(region).getByText(/Page 2/)).toBeTruthy();
  });

  it("test_need_recognition_note_is_gone_after_ocr", async () => {
    const region = await finishScan([{ page: 2, text: "Recognized clause.", confidence: 90 }]);
    expect(within(region).queryByText(/Pages that need text recognition/)).toBeNull();
  });

  it("test_ocr_used_warning_is_shown_with_icon_and_text", async () => {
    const region = await finishScan([{ page: 2, text: "Recognized clause.", confidence: 90 }]);
    const text = within(region).getByText(EN["upload.preview.warning.ocr_used"] as string);
    const item = text.closest("li");
    expect(item?.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
  });

  it("test_low_confidence_warning_is_shown_with_icon_and_text", async () => {
    const region = await finishScan([{ page: 2, text: "Blurry clause.", confidence: 41 }]);
    const text = within(region).getByText(
      EN["upload.preview.warning.ocr_low_confidence"] as string,
    );
    expect(text.closest("li")?.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
  });

  it("test_low_confidence_warning_is_absent_for_confident_pages", async () => {
    const region = await finishScan([{ page: 2, text: "Clear clause.", confidence: 88 }]);
    expect(
      within(region).queryByText(EN["upload.preview.warning.ocr_low_confidence"] as string),
    ).toBeNull();
  });

  it("test_ocr_text_with_markup_is_rendered_as_plain_text", async () => {
    const evil = '<img src=x onerror="alert(1)"> [link](https://evil.example) <script>1</script>';
    const region = await finishScan([{ page: 2, text: evil, confidence: 90 }]);
    expect(within(region).getByText(evil)).toBeTruthy();
    expect(region.querySelector("img, script, a")).toBeNull();
  });
});

describe("rejections (AC5)", () => {
  it("test_more_than_30_ocr_pages_rejects_the_file_and_starts_no_job", async () => {
    ocrPagesFor["big.pdf"] = Array.from({ length: 31 }, (_, i) => i + 1);
    await renderForm();
    add("A", "big.pdf");
    const message = EN["upload.errors.too_many_ocr_pages"] as string;
    expect(await screen.findByText(message)).toBeTruthy();
    expect(jobs()).toHaveLength(0);
  });

  it("test_failed_ocr_rejects_the_file_with_a_message", async () => {
    ocrPagesFor["scan.pdf"] = [2];
    await renderForm();
    add("A", "scan.pdf");
    await waitFor(() => {
      expect(jobs()).toHaveLength(1);
    });
    await act(async () => {
      jobAt(0).reject(new Error("synthetic engine failure with SECRET-TEXT"));
      await Promise.resolve();
    });
    expect(await screen.findByText(EN["upload.errors.ocr_failed"] as string)).toBeTruthy();
    expect(screen.queryByText(/SECRET-TEXT/)).toBeNull();
  });
});
