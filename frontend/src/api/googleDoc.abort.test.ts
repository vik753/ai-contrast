/** S3-T6b review fixes: the body is not read after an abort, even if `fetch` ignores the signal. */
import { describe, expect, it, vi } from "vitest";
import { extractFile } from "./extract";
import { extractGoogleDoc } from "./googleDoc";
import { stage3Body } from "../test/upload-fakes";

const ID = "1AbCdEfGhIjKlMnOpQrStUvWx_-9";

function setup(): { fetchImpl: typeof fetch; cancelled: () => boolean } {
  let cancelled = false;
  const text = JSON.stringify(stage3Body("docx", 100));
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      controller.enqueue(new TextEncoder().encode(text));
      controller.close();
    },
    cancel() {
      cancelled = true;
    },
  });
  const fetchImpl = vi.fn(async () => {
    // Ignores the signal, like a misbehaving fetch; the caller aborts meanwhile.
    await Promise.resolve();
    return new Response(stream, { status: 200, headers: { "Content-Type": "application/json" } });
  });
  return {
    fetchImpl,
    cancelled: () => cancelled,
  };
}

describe("abort before the body is read", () => {
  it("test_google_doc_abort_while_fetch_ignores_signal_cancels_body_and_returns_aborted", async () => {
    const probe = setup();
    const controller = new AbortController();
    const pending = extractGoogleDoc(ID, { fetchImpl: probe.fetchImpl, signal: controller.signal });
    controller.abort();
    expect(await pending).toEqual({ ok: false, code: "aborted" });
    expect(probe.cancelled()).toBe(true);
  });

  it("test_extract_file_abort_while_fetch_ignores_signal_cancels_body_and_returns_aborted", async () => {
    const probe = setup();
    const controller = new AbortController();
    const pending = extractFile(new Blob(["x".repeat(100)]), {
      fetchImpl: probe.fetchImpl,
      signal: controller.signal,
    });
    controller.abort();
    expect(await pending).toEqual({ ok: false, code: "aborted" });
    expect(probe.cancelled()).toBe(true);
  });
});
