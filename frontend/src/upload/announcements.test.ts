// @vitest-environment node
/**
 * Unit tests (frontend-dev) for upload announcements and `formReducer`.
 */
import { describe, expect, it } from "vitest";
import {
  MAX_ANNOUNCEMENTS,
  describeChange,
  formReducer,
  initialFormState,
  type FormState,
} from "./announcements";
import { initialUploadState, uploadReducer, type UploadAction } from "./state";

const A = initialUploadState.contracts[0]?.id ?? "";
const B = initialUploadState.contracts[1]?.id ?? "";

function run(...actions: UploadAction[]): FormState {
  return actions.reduce(formReducer, initialFormState(initialUploadState));
}

function messages(state: FormState) {
  return state.announcements.map((e) => e.announcement);
}

describe("describeChange", () => {
  it("announces added files with the count and client rejections", () => {
    const action: UploadAction = {
      type: "filesAdded",
      contractId: B,
      files: [
        { id: "f1", name: "main.pdf", size: 10 },
        { id: "f2", name: "old.doc", size: 10 },
      ],
    };
    const next = uploadReducer(initialUploadState, action);
    expect(describeChange(initialUploadState, next, action)).toEqual([
      { type: "filesAdded", label: "B", count: 2 },
      { type: "fileRejected", name: "old.doc", code: "legacy_office_unsupported" },
    ]);
  });

  it("announces nothing when the state did not change", () => {
    const action: UploadAction = { type: "contractRemoved", contractId: A };
    expect(describeChange(initialUploadState, initialUploadState, action)).toEqual([]);
  });

  it("announces the server result and a removal", () => {
    const state = run(
      { type: "filesAdded", contractId: A, files: [{ id: "f1", name: "a.pdf", size: 10 }] },
      { type: "fileCheckStarted", fileId: "f1" },
      { type: "fileChecked", fileId: "f1", result: { ok: true, kind: "docx", bytes: 10 } },
      { type: "fileRemoved", contractId: A, fileId: "f1" },
    );
    expect(messages(state)).toEqual([
      { type: "filesAdded", label: "A", count: 1 },
      { type: "fileAccepted", name: "a.pdf", kind: "docx" },
      { type: "fileRemoved", name: "a.pdf" },
    ]);
  });

  it("announces added and removed contracts by their label", () => {
    const state = run({ type: "contractAdded" });
    const c = state.upload.contracts[2]?.id ?? "";
    const next = formReducer(state, { type: "contractRemoved", contractId: c });
    expect(messages(next)).toEqual([
      { type: "contractAdded", label: "C" },
      { type: "contractRemoved", label: "C" },
    ]);
  });
});

describe("formReducer", () => {
  it("keeps the same object when nothing changes", () => {
    const state = initialFormState(initialUploadState);
    expect(formReducer(state, { type: "contractRemoved", contractId: A })).toBe(state);
  });

  it("keeps only the latest announcements with unique ids", () => {
    let state = initialFormState(initialUploadState);
    for (let i = 0; i < MAX_ANNOUNCEMENTS + 3; i += 1) {
      state = formReducer(state, {
        type: "filesAdded",
        contractId: A,
        files: [{ id: `f${i}`, name: `x${i}.doc`, size: 1 }],
      });
    }
    expect(state.announcements).toHaveLength(MAX_ANNOUNCEMENTS);
    const ids = state.announcements.map((e) => e.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(state.announcements.at(-1)?.announcement).toEqual({
      type: "fileRejected",
      name: `x${MAX_ANNOUNCEMENTS + 2}.doc`,
      code: "legacy_office_unsupported",
    });
  });

  it("clears announcements and ignores internal steps", () => {
    const state = run(
      { type: "filesAdded", contractId: A, files: [{ id: "f1", name: "a.pdf", size: 10 }] },
      { type: "fileCheckStarted", fileId: "f1" },
      { type: "checksRequeued", fileIds: ["f1"] },
    );
    expect(messages(state)).toEqual([{ type: "filesAdded", label: "A", count: 1 }]);
    expect(state.upload.contracts[0]?.files[0]?.status).toBe("queued");
    expect(formReducer(state, { type: "announcementsCleared" }).announcements).toEqual([]);
  });
});
