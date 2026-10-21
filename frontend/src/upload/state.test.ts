// @vitest-environment node
/**
 * S2-T2 — pure upload state (src/upload/state.ts) and limits
 * (src/upload/limits.ts). Covers AC1 (contracts, labels, limits), AC3 (client
 * checks), AC4 (file status after the server check) and AC9 (readiness).
 *
 * Assumed state shape (not fixed by the public interface; see the report):
 *   state.contracts: { id: string; files: UploadFile[] }[]
 *   UploadFile: { id; name; size; status; code?; kind? }
 *   - `code` holds the rejection code when status is "rejected";
 *   - `kind` holds the file kind when status is "accepted".
 * Only the accessors below read the shape.
 *
 * These tests fail until the modules exist.
 */
import { describe, expect, it } from "vitest";
import type { ExtractResult } from "../api/extract";
import { okResult } from "../test/upload-fakes";
import {
  MAX_CONTRACTS,
  MAX_FILES_PER_CONTRACT,
  MAX_FILE_BYTES,
  MAX_PARALLEL_REQUESTS,
  MAX_TOTAL_BYTES,
  MIN_CONTRACTS,
} from "./limits";
import {
  canAddContract,
  canRemoveContract,
  contractLabel,
  initialUploadState,
  readiness,
  uploadReducer,
} from "./state";

const MIB = 1024 * 1024;

type State = typeof initialUploadState;
type Action = Parameters<typeof uploadReducer>[1];

interface FileView {
  id: string;
  name: string;
  size: number;
  status: string;
  code?: string;
  kind?: string;
}

interface ContractView {
  id: string;
  files: FileView[];
}

function contracts(state: State): ContractView[] {
  return (state as unknown as { contracts: ContractView[] }).contracts;
}

function contractId(state: State, index: number): string {
  const contract = contracts(state)[index];
  if (contract === undefined) {
    throw new Error(`No contract at index ${index}`);
  }
  return contract.id;
}

function filesOf(state: State, index: number): FileView[] {
  return contracts(state)[index]?.files ?? [];
}

function file(state: State, fileId: string): FileView {
  for (const contract of contracts(state)) {
    const found = contract.files.find((f) => f.id === fileId);
    if (found !== undefined) {
      return found;
    }
  }
  throw new Error(`No file ${fileId}`);
}

function reduce(state: State, ...actions: unknown[]): State {
  return actions.reduce<State>((s, a) => uploadReducer(s, a as Action), state);
}

let nextId = 0;
function spec(name: string, size = 1000): { id: string; name: string; size: number } {
  nextId += 1;
  return { id: `f${nextId}`, name, size };
}

function addFiles(
  state: State,
  index: number,
  ...files: { id: string; name: string; size: number }[]
) {
  return reduce(state, { type: "filesAdded", contractId: contractId(state, index), files });
}

function checked(fileId: string, result: ExtractResult) {
  return { type: "fileChecked", fileId, result };
}

function withContracts(count: number): State {
  let state = initialUploadState;
  while (contracts(state).length < count) {
    state = reduce(state, { type: "contractAdded" });
  }
  return state;
}

/** Recursively freezes a value so that a mutating reducer throws. */
function deepFreeze<T>(value: T): T {
  if (typeof value === "object" && value !== null && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const child of Object.values(value)) {
      deepFreeze(child);
    }
  }
  return value;
}

describe("limits.ts — constants from the limits table", () => {
  it("test_limits_match_the_stage_2_table", () => {
    expect(MAX_FILE_BYTES).toBe(10_485_760);
    expect(MAX_FILES_PER_CONTRACT).toBe(5);
    expect(MAX_CONTRACTS).toBe(5);
    expect(MIN_CONTRACTS).toBe(2);
    expect(MAX_TOTAL_BYTES).toBe(50 * MIB);
    expect(MAX_PARALLEL_REQUESTS).toBe(2);
  });
});

describe("AC1 — contracts and labels", () => {
  it("test_initial_state_has_two_empty_contracts", () => {
    expect(contracts(initialUploadState)).toHaveLength(2);
    expect(filesOf(initialUploadState, 0)).toEqual([]);
    expect(filesOf(initialUploadState, 1)).toEqual([]);
  });

  it("test_initial_contract_ids_are_distinct", () => {
    const ids = contracts(initialUploadState).map((c) => c.id);
    expect(new Set(ids).size).toBe(2);
  });

  it.each([
    [0, "A"],
    [1, "B"],
    [2, "C"],
    [3, "D"],
    [4, "E"],
  ])("test_contract_label_of_index_%i_is_%s", (index, label) => {
    expect(contractLabel(index)).toBe(label);
  });

  it("test_contract_added_appends_an_empty_contract", () => {
    const state = reduce(initialUploadState, { type: "contractAdded" });
    expect(contracts(state)).toHaveLength(3);
    expect(filesOf(state, 2)).toEqual([]);
  });

  it("test_contract_added_up_to_five_gives_unique_ids", () => {
    const state = withContracts(5);
    expect(new Set(contracts(state).map((c) => c.id)).size).toBe(5);
  });

  it("test_contract_added_at_five_contracts_changes_nothing", () => {
    const state = withContracts(5);
    const next = reduce(state, { type: "contractAdded" });
    expect(contracts(next)).toHaveLength(5);
  });

  it("test_ids_stay_unique_after_remove_and_add", () => {
    let state = withContracts(3);
    state = reduce(state, { type: "contractRemoved", contractId: contractId(state, 1) });
    state = reduce(state, { type: "contractAdded" });
    expect(new Set(contracts(state).map((c) => c.id)).size).toBe(3);
  });

  it.each([
    [2, true],
    [3, true],
    [4, true],
    [5, false],
  ])("test_can_add_contract_with_%i_contracts_is_%s", (count, expected) => {
    expect(canAddContract(withContracts(count))).toBe(expected);
  });

  it.each([
    [2, false],
    [3, true],
    [5, true],
  ])("test_can_remove_contract_with_%i_contracts_is_%s", (count, expected) => {
    expect(canRemoveContract(withContracts(count))).toBe(expected);
  });

  it("test_contract_removed_with_two_contracts_changes_nothing", () => {
    const state = reduce(initialUploadState, {
      type: "contractRemoved",
      contractId: contractId(initialUploadState, 1),
    });
    expect(contracts(state)).toHaveLength(2);
  });

  it("test_removing_b_moves_c_to_position_b", () => {
    let state = withContracts(3);
    const cId = contractId(state, 2);
    const cFile = spec("annex-c.pdf");
    state = addFiles(state, 2, cFile);
    state = reduce(state, { type: "contractRemoved", contractId: contractId(state, 1) });
    expect(contracts(state)).toHaveLength(2);
    expect(contractId(state, 1)).toBe(cId);
    expect(filesOf(state, 1).map((f) => f.id)).toEqual([cFile.id]);
    // Labels follow the position: index 1 is "B".
    expect(contractLabel(contracts(state).findIndex((c) => c.id === cId))).toBe("B");
  });

  it("test_contract_removed_with_unknown_id_changes_nothing", () => {
    const state = withContracts(3);
    const next = reduce(state, { type: "contractRemoved", contractId: "no-such-contract" });
    expect(contracts(next).map((c) => c.id)).toEqual(contracts(state).map((c) => c.id));
  });
});

describe("AC3 — client checks in filesAdded", () => {
  it("test_valid_file_is_queued", () => {
    const f = spec("contract.pdf", 1234);
    const state = addFiles(initialUploadState, 0, f);
    expect(filesOf(state, 0)).toHaveLength(1);
    expect(file(state, f.id)).toMatchObject({
      id: f.id,
      name: f.name,
      size: 1234,
      status: "queued",
    });
  });

  it("test_files_are_added_to_the_given_contract_only", () => {
    const f = spec("b.docx");
    const state = addFiles(initialUploadState, 1, f);
    expect(filesOf(state, 0)).toEqual([]);
    expect(filesOf(state, 1).map((x) => x.id)).toEqual([f.id]);
  });

  it("test_file_of_exactly_10_mib_is_queued", () => {
    const f = spec("big.pdf", MAX_FILE_BYTES);
    expect(file(addFiles(initialUploadState, 0, f), f.id).status).toBe("queued");
  });

  it("test_file_above_10_mib_is_rejected_file_too_large", () => {
    const f = spec("big.pdf", MAX_FILE_BYTES + 1);
    expect(file(addFiles(initialUploadState, 0, f), f.id)).toMatchObject({
      status: "rejected",
      code: "file_too_large",
    });
  });

  it("test_zero_byte_file_is_rejected_empty_file", () => {
    const f = spec("empty.txt", 0);
    expect(file(addFiles(initialUploadState, 0, f), f.id)).toMatchObject({
      status: "rejected",
      code: "empty_file",
    });
  });

  it.each(["report.pages", "REPORT.PAGES", "My Contract.Pages"])(
    "test_pages_extension_%j_is_rejected_pages_unsupported",
    (name) => {
      const f = spec(name);
      expect(file(addFiles(initialUploadState, 0, f), f.id)).toMatchObject({
        status: "rejected",
        code: "pages_unsupported",
      });
    },
  );

  it.each(["old.doc", "OLD.DOC", "a.b.Doc"])(
    "test_doc_extension_%j_is_rejected_legacy_office_unsupported",
    (name) => {
      const f = spec(name);
      expect(file(addFiles(initialUploadState, 0, f), f.id)).toMatchObject({
        status: "rejected",
        code: "legacy_office_unsupported",
      });
    },
  );

  it.each(["a.docx", "a.doc.pdf", "a.pages.txt", "doc", "pages", "a.PDF", "no-extension", "a.odt"])(
    "test_name_%j_is_left_to_the_server_check",
    (name) => {
      const f = spec(name);
      expect(file(addFiles(initialUploadState, 0, f), f.id).status).toBe("queued");
    },
  );

  it("test_sixth_and_seventh_file_in_one_batch_are_rejected_too_many_files", () => {
    const batch = Array.from({ length: 7 }, (_, i) => spec(`part-${i}.pdf`));
    const state = addFiles(initialUploadState, 0, ...batch);
    expect(filesOf(state, 0)).toHaveLength(7);
    const statuses = batch.map((f) => file(state, f.id));
    expect(statuses.slice(0, 5).every((f) => f.status === "queued")).toBe(true);
    for (const f of statuses.slice(5)) {
      expect(f).toMatchObject({ status: "rejected", code: "too_many_files" });
    }
  });

  it("test_sixth_file_added_later_is_rejected_too_many_files", () => {
    let state = initialUploadState;
    for (let i = 0; i < 5; i += 1) {
      state = addFiles(state, 0, spec(`part-${i}.pdf`));
    }
    const sixth = spec("part-5.pdf");
    state = addFiles(state, 0, sixth);
    expect(file(state, sixth.id)).toMatchObject({ status: "rejected", code: "too_many_files" });
  });

  it("test_file_limit_is_per_contract", () => {
    let state = addFiles(
      initialUploadState,
      0,
      ...Array.from({ length: 5 }, (_, i) => spec(`a${i}.pdf`)),
    );
    const inB = spec("b.pdf");
    state = addFiles(state, 1, inB);
    expect(file(state, inB.id).status).toBe("queued");
  });

  it("test_total_of_exactly_50_mib_is_allowed", () => {
    const files = Array.from({ length: 5 }, (_, i) => spec(`big-${i}.pdf`, MAX_FILE_BYTES));
    const state = addFiles(initialUploadState, 0, ...files);
    expect(files.every((f) => file(state, f.id).status === "queued")).toBe(true);
  });

  it("test_file_pushing_total_above_50_mib_is_rejected_total_too_large", () => {
    const files = Array.from({ length: 5 }, (_, i) => spec(`big-${i}.pdf`, MAX_FILE_BYTES));
    let state = addFiles(initialUploadState, 0, ...files);
    const extra = spec("one-more.txt", 1);
    state = addFiles(state, 1, extra);
    expect(file(state, extra.id)).toMatchObject({ status: "rejected", code: "total_too_large" });
  });

  it("test_total_counts_files_of_all_contracts", () => {
    let state = addFiles(
      initialUploadState,
      0,
      ...Array.from({ length: 3 }, (_, i) => spec(`a${i}.pdf`, 10 * MIB)),
    );
    state = addFiles(state, 1, spec("b0.pdf", 10 * MIB));
    const fits = spec("b1.pdf", 10 * MIB);
    state = addFiles(state, 1, fits);
    expect(file(state, fits.id).status).toBe("queued");
    const over = spec("b2.pdf", 1);
    state = addFiles(state, 1, over);
    expect(file(state, over.id)).toMatchObject({ status: "rejected", code: "total_too_large" });
  });

  it("test_rejected_oversized_file_does_not_count_toward_total", () => {
    let state = addFiles(initialUploadState, 0, spec("huge.pdf", 40 * MIB + MAX_FILE_BYTES));
    const files = Array.from({ length: 5 }, (_, i) => spec(`b${i}.pdf`, MAX_FILE_BYTES));
    state = addFiles(state, 1, ...files);
    expect(files.every((f) => file(state, f.id).status === "queued")).toBe(true);
  });

  it("test_removing_files_frees_total_budget", () => {
    const files = Array.from({ length: 5 }, (_, i) => spec(`big-${i}.pdf`, MAX_FILE_BYTES));
    let state = addFiles(initialUploadState, 0, ...files);
    state = reduce(state, {
      type: "fileRemoved",
      contractId: contractId(state, 0),
      fileId: files[0]?.id,
    });
    const next = spec("fits.pdf", MAX_FILE_BYTES);
    state = addFiles(state, 1, next);
    expect(file(state, next.id).status).toBe("queued");
  });

  it("test_rejected_files_stay_in_the_list", () => {
    const bad = spec("x.doc");
    const good = spec("y.pdf");
    const state = addFiles(initialUploadState, 0, bad, good);
    expect(filesOf(state, 0).map((f) => f.id)).toEqual([bad.id, good.id]);
  });

  it("test_files_added_to_unknown_contract_change_nothing", () => {
    const state = reduce(initialUploadState, {
      type: "filesAdded",
      contractId: "no-such-contract",
      files: [spec("a.pdf")],
    });
    expect(contracts(state).flatMap((c) => c.files)).toEqual([]);
  });
});

describe("fileRemoved and contractRemoved", () => {
  it("test_file_removed_drops_the_file", () => {
    const a = spec("a.pdf");
    const b = spec("b.pdf");
    let state = addFiles(initialUploadState, 0, a, b);
    state = reduce(state, { type: "fileRemoved", contractId: contractId(state, 0), fileId: a.id });
    expect(filesOf(state, 0).map((f) => f.id)).toEqual([b.id]);
  });

  it("test_contract_removed_drops_its_files", () => {
    let state = withContracts(3);
    const f = spec("c.pdf");
    state = addFiles(state, 2, f);
    state = reduce(state, { type: "contractRemoved", contractId: contractId(state, 2) });
    expect(contracts(state).flatMap((c) => c.files.map((x) => x.id))).not.toContain(f.id);
  });
});

describe("AC4 — fileChecked", () => {
  it.each(["pdf", "docx", "text"] as const)(
    "test_ok_result_%s_marks_file_accepted_with_kind",
    (kind) => {
      const f = spec("a.bin", 10);
      let state = addFiles(initialUploadState, 0, f);
      state = reduce(state, checked(f.id, okResult(kind, 10)));
      expect(file(state, f.id)).toMatchObject({ status: "accepted", kind });
    },
  );

  it.each([
    "unsupported_type",
    "archive_rejected",
    "timeout",
    "network_error",
    "unknown_error",
    "busy",
  ] as const)("test_error_result_%s_marks_file_rejected_with_code", (code) => {
    const f = spec("a.pdf");
    let state = addFiles(initialUploadState, 0, f);
    state = reduce(state, checked(f.id, { ok: false, code }));
    expect(file(state, f.id)).toMatchObject({ status: "rejected", code });
  });

  it("test_file_checked_for_removed_file_changes_nothing", () => {
    const a = spec("a.pdf");
    let state = addFiles(initialUploadState, 0, a);
    state = reduce(state, { type: "fileRemoved", contractId: contractId(state, 0), fileId: a.id });
    const next = reduce(state, checked(a.id, okResult("pdf", 1000)));
    expect(contracts(next).flatMap((c) => c.files)).toEqual([]);
  });

  it("test_file_checked_does_not_touch_other_files", () => {
    const a = spec("a.pdf");
    const b = spec("b.pdf");
    let state = addFiles(initialUploadState, 0, a, b);
    state = reduce(state, checked(a.id, okResult("pdf", 1000)));
    expect(file(state, b.id).status).toBe("queued");
  });

  it("test_file_checked_does_not_override_client_rejection", () => {
    const a = spec("a.doc");
    let state = addFiles(initialUploadState, 0, a);
    state = reduce(state, checked(a.id, okResult("docx", 1000)));
    expect(file(state, a.id)).toMatchObject({
      status: "rejected",
      code: "legacy_office_unsupported",
    });
  });
});

describe("AC9 — readiness()", () => {
  function accept(state: State, f: { id: string; size: number }): State {
    return reduce(state, checked(f.id, okResult("pdf", f.size)));
  }

  it("test_initial_state_is_not_ready_contract_without_file", () => {
    expect(readiness(initialUploadState)).toEqual({
      ready: false,
      reason: "contract_without_file",
    });
  });

  it("test_one_contract_without_file_is_not_ready", () => {
    const a = spec("a.pdf");
    const state = accept(addFiles(initialUploadState, 0, a), a);
    expect(readiness(state)).toEqual({ ready: false, reason: "contract_without_file" });
  });

  // Review round 1: order checking -> rejected_files -> contract_without_file -> ready.
  it("test_contract_with_only_rejected_files_is_rejected_files", () => {
    const a = spec("a.pdf");
    let state = accept(addFiles(initialUploadState, 0, a), a);
    state = addFiles(state, 1, spec("b.doc"));
    expect(readiness(state)).toEqual({ ready: false, reason: "rejected_files" });
  });

  it("test_rejected_file_next_to_accepted_files_is_rejected_files", () => {
    const a = spec("a.pdf");
    const b = spec("b.pdf");
    let state = accept(addFiles(initialUploadState, 0, a), a);
    state = accept(addFiles(state, 1, b), b);
    state = addFiles(state, 1, spec("annex.doc"));
    expect(readiness(state)).toEqual({ ready: false, reason: "rejected_files" });
  });

  it("test_server_rejected_file_is_rejected_files", () => {
    const a = spec("a.pdf");
    const b = spec("b.pdf");
    let state = accept(addFiles(initialUploadState, 0, a), a);
    state = addFiles(state, 1, b);
    state = reduce(state, checked(b.id, { ok: false, code: "unsupported_type" }));
    expect(readiness(state)).toEqual({ ready: false, reason: "rejected_files" });
  });

  it("test_checking_comes_before_rejected_files", () => {
    let state = addFiles(initialUploadState, 0, spec("a.pdf"), spec("a.doc"));
    state = addFiles(state, 1, spec("b.pdf"));
    expect(readiness(state)).toEqual({ ready: false, reason: "checking" });
  });

  it("test_checking_comes_before_contract_without_file", () => {
    const state = addFiles(initialUploadState, 0, spec("a.pdf"));
    expect(readiness(state)).toEqual({ ready: false, reason: "checking" });
  });

  it("test_rejected_files_comes_before_contract_without_file", () => {
    const state = addFiles(initialUploadState, 0, spec("a.doc"));
    expect(readiness(state)).toEqual({ ready: false, reason: "rejected_files" });
  });

  it("test_removing_the_rejected_file_makes_state_ready", () => {
    const a = spec("a.pdf");
    const b = spec("b.pdf");
    const bad = spec("bad.doc");
    let state = accept(addFiles(initialUploadState, 0, a), a);
    state = accept(addFiles(state, 1, b, bad), b);
    state = reduce(state, {
      type: "fileRemoved",
      contractId: contractId(state, 1),
      fileId: bad.id,
    });
    expect(readiness(state)).toEqual({ ready: true, contracts: 2 });
  });

  it("test_queued_file_in_every_contract_is_checking", () => {
    let state = addFiles(initialUploadState, 0, spec("a.pdf"));
    state = addFiles(state, 1, spec("b.pdf"));
    expect(readiness(state)).toEqual({ ready: false, reason: "checking" });
  });

  it("test_queued_file_next_to_accepted_files_is_checking", () => {
    const a = spec("a.pdf");
    const b = spec("b.pdf");
    let state = accept(addFiles(initialUploadState, 0, a), a);
    state = accept(addFiles(state, 1, b), b);
    state = addFiles(state, 1, spec("annex.pdf"));
    expect(readiness(state)).toEqual({ ready: false, reason: "checking" });
  });

  it("test_every_contract_with_accepted_file_is_ready_with_count", () => {
    const a = spec("a.pdf");
    const b = spec("b.pdf");
    let state = accept(addFiles(initialUploadState, 0, a), a);
    state = accept(addFiles(state, 1, b), b);
    expect(readiness(state)).toEqual({ ready: true, contracts: 2 });
  });

  it("test_ready_counts_all_contracts", () => {
    let state = withContracts(3);
    for (let i = 0; i < 3; i += 1) {
      const f = spec(`c${i}.pdf`);
      state = accept(addFiles(state, i, f), f);
    }
    expect(readiness(state)).toEqual({ ready: true, contracts: 3 });
  });

  it("test_added_empty_contract_makes_state_not_ready", () => {
    const a = spec("a.pdf");
    const b = spec("b.pdf");
    let state = accept(addFiles(initialUploadState, 0, a), a);
    state = accept(addFiles(state, 1, b), b);
    state = reduce(state, { type: "contractAdded" });
    expect(readiness(state)).toEqual({ ready: false, reason: "contract_without_file" });
  });
});

describe("purity", () => {
  it("test_reducer_does_not_mutate_previous_state", () => {
    const a = spec("a.pdf");
    const frozen = deepFreeze(addFiles(initialUploadState, 0, a));
    const snapshot = JSON.stringify(frozen);
    const actions: unknown[] = [
      { type: "contractAdded" },
      { type: "filesAdded", contractId: contractId(frozen, 1), files: [spec("b.pdf")] },
      checked(a.id, okResult("pdf", 1000)),
      { type: "fileRemoved", contractId: contractId(frozen, 0), fileId: a.id },
    ];
    for (const action of actions) {
      expect(() => uploadReducer(frozen, action as Action)).not.toThrow();
    }
    expect(JSON.stringify(frozen)).toBe(snapshot);
  });

  it("test_initial_state_is_not_mutated_by_actions", () => {
    const before = JSON.stringify(initialUploadState);
    addFiles(initialUploadState, 0, spec("a.pdf"));
    reduce(initialUploadState, { type: "contractAdded" });
    expect(JSON.stringify(initialUploadState)).toBe(before);
  });
});
