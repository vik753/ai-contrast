/** S4-T1 follow-up: reading and hashing a file is sequential and has a 30 s timeout. */
import { act, renderHook } from "@testing-library/react";
import { useReducer } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { initialUploadState, uploadReducer, type UploadAction } from "./state";
import { HASH_TIMEOUT_MS, useHashing } from "./useHashing";

afterEach(() => {
  vi.useRealTimers();
});

const add: UploadAction = {
  type: "filesAdded",
  contractId: "contract-1",
  files: [
    { id: "f1", name: "a.pdf", size: 5, hashPending: true },
    { id: "f2", name: "b.pdf", size: 5, hashPending: true },
  ],
};

describe("file hashing timeout", () => {
  it("test_never_settling_read_times_out_and_does_not_hold_back_later_rows", async () => {
    vi.useFakeTimers();
    const second = vi.fn(() => Promise.resolve(new TextEncoder().encode("bytes").buffer));
    const files: Record<string, { arrayBuffer: () => Promise<ArrayBuffer> }> = {
      f1: { arrayBuffer: () => new Promise<ArrayBuffer>(() => undefined) },
      f2: { arrayBuffer: second },
    };
    const { result } = renderHook(() => {
      const [state, dispatch] = useReducer(uploadReducer, initialUploadState, (s) =>
        uploadReducer(s, add),
      );
      useHashing(state, dispatch, (id) => files[id] as unknown as File);
      return state;
    });
    const rows = () => result.current.contracts.flatMap((c) => c.files);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(HASH_TIMEOUT_MS - 1);
    });
    // One at a time: the second file is not even read while the first is stuck.
    expect(second).not.toHaveBeenCalled();
    expect(rows().every((f) => f.status === "queued" && f.awaitingHash === true)).toBe(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    await act(async () => {
      await vi.waitFor(() => {
        expect(rows()[1]?.awaitingHash).toBeUndefined();
      });
    });
    const [first, next] = rows();
    expect(first?.status).toBe("queued");
    expect(first?.awaitingHash).toBeUndefined();
    expect(first?.fileHash).toBeUndefined();
    expect(next?.awaitingHash).toBeUndefined();
    expect(next?.fileHash).toMatch(/^[0-9a-f]{64}$/);
  });
});
