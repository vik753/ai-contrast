/**
 * S2-T2 review round 1 — the check scheduler hook
 * `useCheckScheduler(state, dispatch, check)` in src/upload/useCheckScheduler.ts.
 *
 * The hook gets an injected `check`; there is no global `fetch` stub.
 * Assumed contract (see the report):
 * - `check` makes ONE attempt for one file and resolves to an `ExtractResult`.
 *   Its arguments contain the file id (a string, or an object with `id`) and
 *   an `AbortSignal`. The hook retries `busy` itself (Retry-After, capped at
 *   10 s, at most 3 attempts in total).
 * - The hook dispatches `fileCheckStarted` / `fileChecked` to the reducer.
 *
 * State lives in a parent component, so the hook can be unmounted and
 * mounted again while the state is kept.
 */
import { act, render } from "@testing-library/react";
import { StrictMode, useEffect, useReducer, type Dispatch, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ExtractResult } from "../api/extract";
import { resetBrowserEnv } from "../test/browser-env";
import {
  initialUploadState,
  uploadReducer,
  type UploadAction,
  type UploadFile,
  type UploadState,
} from "./state";
import { useCheckScheduler } from "./useCheckScheduler";

type Check = Parameters<typeof useCheckScheduler>[2];

interface PendingCheck {
  fileId: string;
  signal: AbortSignal | undefined;
  resolve: (result: ExtractResult) => void;
  settled: boolean;
}

class FakeCheck {
  readonly calls: PendingCheck[] = [];
  autoResult: ((fileId: string, attempt: number) => ExtractResult) | null = null;
  /** When false, an aborted call never settles (its continuation never runs). */
  settleOnAbort = true;

  readonly fn = vi.fn((...args: unknown[]): Promise<ExtractResult> => {
    const fileId = idOf(args);
    const signal = args.find((a): a is AbortSignal => a instanceof AbortSignal);
    return new Promise<ExtractResult>((resolve) => {
      const call: PendingCheck = {
        fileId,
        signal,
        settled: false,
        resolve: (result) => {
          if (!call.settled) {
            call.settled = true;
            resolve(result);
          }
        },
      };
      this.calls.push(call);
      signal?.addEventListener("abort", () => {
        if (this.settleOnAbort) {
          call.resolve({ ok: false, code: "aborted" });
        }
      });
      if (this.autoResult !== null) {
        const attempt = this.calls.filter((c) => c.fileId === fileId).length;
        call.resolve(this.autoResult(fileId, attempt));
      }
    });
  });

  get check(): Check {
    return this.fn;
  }

  /** Calls not settled and not aborted: requests really in flight. */
  active(): PendingCheck[] {
    return this.calls.filter((c) => !c.settled && c.signal?.aborted !== true);
  }

  callsFor(fileId: string): PendingCheck[] {
    return this.calls.filter((c) => c.fileId === fileId);
  }
}

function idOf(args: unknown[]): string {
  for (const arg of args) {
    if (typeof arg === "string") {
      return arg;
    }
    if (typeof arg === "object" && arg !== null && "id" in arg && typeof arg.id === "string") {
      return arg.id;
    }
  }
  throw new Error("check() was called without a file id");
}

const ok = (): ExtractResult => ({ ok: true, kind: "pdf", bytes: 1000 });
const busy = (seconds = 5): ExtractResult => ({
  ok: false,
  code: "busy",
  retryAfterSeconds: seconds,
});

/** Latest state and dispatch of the parent, filled in after every commit. */
const harness: { state: UploadState; dispatch: Dispatch<UploadAction> } = {
  state: initialUploadState,
  dispatch: () => undefined,
};

function report(state: UploadState, dispatch: Dispatch<UploadAction>): void {
  harness.state = state;
  harness.dispatch = dispatch;
}

function Scheduler({
  state,
  dispatch,
  check,
}: {
  state: UploadState;
  dispatch: Dispatch<UploadAction>;
  check: Check;
}): null {
  useCheckScheduler(state, dispatch, check);
  return null;
}

function Parent({
  initial,
  check,
  mounted,
}: {
  initial: UploadState;
  check: Check;
  mounted: boolean;
}): ReactNode {
  const [state, dispatch] = useReducer(uploadReducer, initial);
  useEffect(() => {
    report(state, dispatch);
  });
  return mounted ? <Scheduler state={state} dispatch={dispatch} check={check} /> : null;
}

function withFiles(count: number, contractIndex = 0): UploadState {
  const contract = initialUploadState.contracts[contractIndex];
  if (contract === undefined) {
    throw new Error("no contract");
  }
  return uploadReducer(initialUploadState, {
    type: "filesAdded",
    contractId: contract.id,
    files: Array.from({ length: count }, (_, i) => ({
      id: `file-${i}`,
      name: `f${i}.pdf`,
      size: 1000,
    })),
  });
}

function allFiles(): UploadFile[] {
  return harness.state.contracts.flatMap((c) => c.files);
}

function statusOf(fileId: string): string | undefined {
  return allFiles().find((f) => f.id === fileId)?.status;
}

async function flush(ms = 0): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  resetBrowserEnv();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  resetBrowserEnv();
});

describe("useCheckScheduler — queue", () => {
  it("test_at_most_two_checks_in_flight", async () => {
    const fake = new FakeCheck();
    render(<Parent initial={withFiles(4)} check={fake.check} mounted />);
    await flush();
    expect(fake.calls).toHaveLength(2);
    await flush(30_000);
    expect(fake.calls).toHaveLength(2);
  });

  it("test_started_files_are_checking_others_queued", async () => {
    const fake = new FakeCheck();
    render(<Parent initial={withFiles(3)} check={fake.check} mounted />);
    await flush();
    const started = new Set(fake.calls.map((c) => c.fileId));
    for (const file of allFiles()) {
      expect(file.status).toBe(started.has(file.id) ? "checking" : "queued");
    }
  });

  it("test_finished_check_starts_the_next_file", async () => {
    const fake = new FakeCheck();
    render(<Parent initial={withFiles(3)} check={fake.check} mounted />);
    await flush();
    act(() => fake.calls[0]?.resolve(ok()));
    await flush();
    expect(fake.calls).toHaveLength(3);
    expect(fake.active()).toHaveLength(2);
  });

  it("test_all_files_finish_as_accepted", async () => {
    const fake = new FakeCheck();
    fake.autoResult = ok;
    render(<Parent initial={withFiles(5)} check={fake.check} mounted />);
    await flush();
    await flush();
    expect(allFiles().map((f) => f.status)).toEqual(Array(5).fill("accepted"));
    expect(fake.calls).toHaveLength(5);
  });

  it("test_error_result_marks_file_rejected", async () => {
    const fake = new FakeCheck();
    fake.autoResult = () => ({ ok: false, code: "unsupported_type" });
    render(<Parent initial={withFiles(1)} check={fake.check} mounted />);
    await flush();
    expect(allFiles()[0]).toMatchObject({ status: "rejected", code: "unsupported_type" });
  });
});

describe("useCheckScheduler — busy retry", () => {
  it("test_busy_is_retried_after_retry_after", async () => {
    const fake = new FakeCheck();
    render(<Parent initial={withFiles(1)} check={fake.check} mounted />);
    await flush();
    act(() => fake.calls[0]?.resolve(busy(5)));
    await flush(4_999);
    expect(fake.calls).toHaveLength(1);
    await flush(1);
    expect(fake.calls).toHaveLength(2);
    act(() => fake.calls[1]?.resolve(ok()));
    await flush();
    expect(statusOf("file-0")).toBe("accepted");
  });

  it("test_busy_delay_is_capped_at_10_seconds", async () => {
    const fake = new FakeCheck();
    render(<Parent initial={withFiles(1)} check={fake.check} mounted />);
    await flush();
    act(() => fake.calls[0]?.resolve(busy(120)));
    await flush(9_999);
    expect(fake.calls).toHaveLength(1);
    await flush(1);
    expect(fake.calls).toHaveLength(2);
  });

  it("test_busy_makes_at_most_three_attempts", async () => {
    const fake = new FakeCheck();
    fake.autoResult = () => busy(1);
    render(<Parent initial={withFiles(1)} check={fake.check} mounted />);
    await flush();
    await flush(10_000);
    await flush(10_000);
    await flush(60_000);
    expect(fake.callsFor("file-0")).toHaveLength(3);
    expect(allFiles()[0]).toMatchObject({ status: "rejected", code: "busy" });
  });

  it("test_file_waiting_for_retry_is_still_checking", async () => {
    const fake = new FakeCheck();
    render(<Parent initial={withFiles(1)} check={fake.check} mounted />);
    await flush();
    act(() => fake.calls[0]?.resolve(busy(5)));
    await flush(1_000);
    expect(statusOf("file-0")).toBe("checking");
  });
});

describe("useCheckScheduler — removal", () => {
  it("test_removing_a_file_aborts_its_check", async () => {
    const fake = new FakeCheck();
    render(<Parent initial={withFiles(1)} check={fake.check} mounted />);
    await flush();
    const contractId = harness.state.contracts[0]?.id ?? "";
    act(() => harness.dispatch({ type: "fileRemoved", contractId, fileId: "file-0" }));
    await flush();
    expect(fake.calls[0]?.signal?.aborted).toBe(true);
  });

  it("test_removing_a_file_frees_its_slot", async () => {
    const fake = new FakeCheck();
    render(<Parent initial={withFiles(3)} check={fake.check} mounted />);
    await flush();
    const first = fake.calls[0]?.fileId ?? "";
    const contractId = harness.state.contracts[0]?.id ?? "";
    act(() => harness.dispatch({ type: "fileRemoved", contractId, fileId: first }));
    await flush();
    expect(fake.calls).toHaveLength(3);
    expect(fake.active()).toHaveLength(2);
  });

  it("test_removing_a_file_waiting_for_retry_stops_the_retry", async () => {
    const fake = new FakeCheck();
    render(<Parent initial={withFiles(1)} check={fake.check} mounted />);
    await flush();
    act(() => fake.calls[0]?.resolve(busy(5)));
    await flush(1_000);
    const contractId = harness.state.contracts[0]?.id ?? "";
    act(() => harness.dispatch({ type: "fileRemoved", contractId, fileId: "file-0" }));
    await flush(30_000);
    expect(fake.calls).toHaveLength(1);
  });

  it("test_removing_a_contract_aborts_all_its_checks", async () => {
    const fake = new FakeCheck();
    let initial = uploadReducer(initialUploadState, { type: "contractAdded" });
    const third = initial.contracts[2]?.id ?? "";
    initial = uploadReducer(initial, {
      type: "filesAdded",
      contractId: third,
      files: [
        { id: "c1", name: "c1.pdf", size: 1000 },
        { id: "c2", name: "c2.pdf", size: 1000 },
      ],
    });
    render(<Parent initial={initial} check={fake.check} mounted />);
    await flush();
    expect(fake.calls).toHaveLength(2);
    act(() => harness.dispatch({ type: "contractRemoved", contractId: third }));
    await flush();
    expect(fake.calls.every((c) => c.signal?.aborted === true)).toBe(true);
  });
});

describe("useCheckScheduler — effect restarts", () => {
  it("test_remount_puts_checking_files_back_to_queue_and_they_finish", async () => {
    const fake = new FakeCheck();
    const { rerender } = render(<Parent initial={withFiles(2)} check={fake.check} mounted />);
    await flush();
    expect(fake.calls).toHaveLength(2);
    // Unmount the hook only; the state (two `checking` files) is kept.
    rerender(<Parent initial={withFiles(2)} check={fake.check} mounted={false} />);
    await flush();
    fake.autoResult = ok;
    rerender(<Parent initial={withFiles(2)} check={fake.check} mounted />);
    await flush();
    await flush();
    // Late answers of the first requests, if any, must not break the state.
    for (const call of fake.calls.slice(0, 2)) {
      act(() => call.resolve(ok()));
    }
    await flush();
    expect(allFiles().map((f) => f.status)).toEqual(["accepted", "accepted"]);
    expect(fake.calls.length).toBeGreaterThanOrEqual(3);
  });

  it("test_effect_restart_requeues_checking_files_whose_request_never_settles", async () => {
    // The old requests never answer, so only the restart can rescue the files.
    const fake = new FakeCheck();
    fake.settleOnAbort = false;
    const { rerender } = render(<Parent initial={withFiles(2)} check={fake.check} mounted />);
    await flush();
    expect(allFiles().map((f) => f.status)).toEqual(["checking", "checking"]);
    rerender(<Parent initial={withFiles(2)} check={fake.check} mounted={false} />);
    await flush();
    fake.autoResult = ok;
    rerender(<Parent initial={withFiles(2)} check={fake.check} mounted />);
    await flush();
    await flush();
    expect(allFiles().map((f) => f.status)).toEqual(["accepted", "accepted"]);
    expect(fake.callsFor("file-0").length).toBeGreaterThanOrEqual(2);
  });

  it("test_strict_mode_with_never_settling_aborts_finishes_all_files", async () => {
    const fake = new FakeCheck();
    fake.settleOnAbort = false;
    fake.autoResult = ok;
    render(
      <StrictMode>
        <Parent initial={withFiles(3)} check={fake.check} mounted />
      </StrictMode>,
    );
    await flush();
    await flush();
    await flush();
    expect(allFiles().map((f) => f.status)).toEqual(["accepted", "accepted", "accepted"]);
  });

  it("test_remount_never_exceeds_two_active_checks", async () => {
    const fake = new FakeCheck();
    const { rerender } = render(<Parent initial={withFiles(4)} check={fake.check} mounted />);
    await flush();
    rerender(<Parent initial={withFiles(4)} check={fake.check} mounted={false} />);
    await flush();
    rerender(<Parent initial={withFiles(4)} check={fake.check} mounted />);
    await flush();
    expect(fake.active().length).toBeLessThanOrEqual(2);
    expect(allFiles().filter((f) => f.status === "checking").length).toBeLessThanOrEqual(2);
  });

  it("test_unmount_with_no_answer_leaves_no_file_stuck_in_checking", async () => {
    const fake = new FakeCheck();
    const { rerender } = render(<Parent initial={withFiles(2)} check={fake.check} mounted />);
    await flush();
    rerender(<Parent initial={withFiles(2)} check={fake.check} mounted={false} />);
    await flush();
    rerender(<Parent initial={withFiles(2)} check={fake.check} mounted />);
    await flush();
    // Every `checking` file has a request in flight after the restart.
    const active = new Set(fake.active().map((c) => c.fileId));
    for (const file of allFiles().filter((f) => f.status === "checking")) {
      expect(active.has(file.id)).toBe(true);
    }
  });

  it("test_strict_mode_with_files_present_finishes_all_files", async () => {
    const fake = new FakeCheck();
    fake.autoResult = ok;
    render(
      <StrictMode>
        <Parent initial={withFiles(3)} check={fake.check} mounted />
      </StrictMode>,
    );
    await flush();
    await flush();
    await flush();
    expect(allFiles().map((f) => f.status)).toEqual(["accepted", "accepted", "accepted"]);
  });

  it("test_strict_mode_with_pending_checks_keeps_at_most_two_active", async () => {
    const fake = new FakeCheck();
    render(
      <StrictMode>
        <Parent initial={withFiles(4)} check={fake.check} mounted />
      </StrictMode>,
    );
    await flush();
    expect(fake.active().length).toBeLessThanOrEqual(2);
    expect(fake.active().length).toBeGreaterThan(0);
    for (const call of fake.active()) {
      act(() => call.resolve(ok()));
    }
    fake.autoResult = ok;
    await flush();
    await flush();
    await flush();
    expect(allFiles().every((f) => f.status === "accepted")).toBe(true);
  });
});
