/**
 * Upload form state: contracts and their files. Pure reducer, no I/O.
 *
 * File names stay here, in the browser. They are never sent to the server
 * (ADR 0010, threat model T11). The `File` objects themselves live outside
 * the state (see `UploadForm`), so the state stays serializable.
 */
import type { ExtractErrorCode, ExtractResult, FileKind } from "../api/extract";
import {
  MAX_CONTRACTS,
  MAX_FILE_BYTES,
  MAX_FILES_PER_CONTRACT,
  MAX_TOTAL_BYTES,
  MIN_CONTRACTS,
} from "./limits";

/** Codes of checks made in the browser before any request. */
export type ClientRejectionCode =
  | "file_too_large"
  | "too_many_files"
  | "total_too_large"
  | "empty_file"
  | "pages_unsupported"
  | "legacy_office_unsupported";

export type RejectionCode = ExtractErrorCode | ClientRejectionCode;

export type UploadFileStatus = "queued" | "checking" | "accepted" | "rejected";

interface UploadFileBase {
  readonly id: string;
  readonly name: string;
  readonly size: number;
}

export type UploadFile =
  | (UploadFileBase & { readonly status: "queued" | "checking" })
  | (UploadFileBase & { readonly status: "accepted"; readonly kind: FileKind })
  | (UploadFileBase & { readonly status: "rejected"; readonly code: RejectionCode });

export interface Contract {
  readonly id: string;
  readonly files: readonly UploadFile[];
}

export interface UploadState {
  readonly contracts: readonly Contract[];
  /** Number for the next contract id. Ids are never reused. */
  readonly nextContractNumber: number;
}

export interface FileSpec {
  readonly id: string;
  readonly name: string;
  readonly size: number;
}

export type UploadAction =
  | { type: "contractAdded" }
  | { type: "contractRemoved"; contractId: string }
  | { type: "filesAdded"; contractId: string; files: readonly FileSpec[] }
  | { type: "fileRemoved"; contractId: string; fileId: string }
  /** Internal: a queued file was sent to the server. */
  | { type: "fileCheckStarted"; fileId: string }
  /** Internal: `checking` files without a request in flight go back to `queued`. */
  | { type: "checksRequeued"; fileIds: readonly string[] }
  | { type: "fileChecked"; fileId: string; result: ExtractResult };

export type Readiness =
  | { ready: true; contracts: number }
  | { ready: false; reason: "checking" | "rejected_files" | "contract_without_file" };

function contractId(number: number): string {
  return `contract-${number}`;
}

export const initialUploadState: UploadState = {
  contracts: [
    { id: contractId(1), files: [] },
    { id: contractId(2), files: [] },
  ],
  nextContractNumber: 3,
};

const LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

/** Label of the contract at `index`: "A", "B", … Labels follow the position. */
export function contractLabel(index: number): string {
  return LABELS.charAt(index);
}

export function canAddContract(state: UploadState): boolean {
  return state.contracts.length < MAX_CONTRACTS;
}

export function canRemoveContract(state: UploadState): boolean {
  return state.contracts.length > MIN_CONTRACTS;
}

/** A file that still counts: waiting, being checked or accepted. */
export function isActive(file: UploadFile): boolean {
  return file.status !== "rejected";
}

export function isPending(file: UploadFile): boolean {
  return file.status === "queued" || file.status === "checking";
}

function totalActiveBytes(state: UploadState): number {
  let total = 0;
  for (const contract of state.contracts) {
    for (const file of contract.files) {
      if (isActive(file)) {
        total += file.size;
      }
    }
  }
  return total;
}

/** Client checks on the file itself (size and extension). */
function intrinsicRejection(spec: FileSpec): ClientRejectionCode | null {
  if (spec.size === 0) {
    return "empty_file";
  }
  if (spec.size > MAX_FILE_BYTES) {
    return "file_too_large";
  }
  const name = spec.name.toLowerCase();
  if (name.endsWith(".pages")) {
    return "pages_unsupported";
  }
  if (name.endsWith(".doc")) {
    return "legacy_office_unsupported";
  }
  return null;
}

function addFiles(state: UploadState, targetId: string, specs: readonly FileSpec[]): UploadState {
  const target = state.contracts.find((c) => c.id === targetId);
  if (target === undefined || specs.length === 0) {
    return state;
  }
  let activeInContract = target.files.filter(isActive).length;
  let total = totalActiveBytes(state);
  const added: UploadFile[] = [];
  for (const spec of specs) {
    const base: UploadFileBase = { id: spec.id, name: spec.name, size: spec.size };
    let code: ClientRejectionCode | null = intrinsicRejection(spec);
    if (code === null && activeInContract >= MAX_FILES_PER_CONTRACT) {
      code = "too_many_files";
    }
    if (code === null && total + spec.size > MAX_TOTAL_BYTES) {
      code = "total_too_large";
    }
    if (code === null) {
      activeInContract += 1;
      total += spec.size;
      added.push({ ...base, status: "queued" });
    } else {
      added.push({ ...base, status: "rejected", code });
    }
  }
  return {
    ...state,
    contracts: state.contracts.map((c) =>
      c.id === targetId ? { ...c, files: [...c.files, ...added] } : c,
    ),
  };
}

/** Replaces one file wherever it is. Returns `state` itself if nothing changed. */
function updateFile(
  state: UploadState,
  fileId: string,
  update: (file: UploadFile) => UploadFile,
): UploadState {
  const contracts = state.contracts.map((contract) => {
    const index = contract.files.findIndex((f) => f.id === fileId);
    const current = contract.files[index];
    if (current === undefined) {
      return contract;
    }
    const next = update(current);
    if (next === current) {
      return contract;
    }
    return { ...contract, files: contract.files.map((f, i) => (i === index ? next : f)) };
  });
  const changed = contracts.some((contract, i) => contract !== state.contracts[i]);
  return changed ? { ...state, contracts } : state;
}

function applyResult(file: UploadFile, result: ExtractResult): UploadFile {
  if (!isPending(file)) {
    // Client rejections and earlier results are final.
    return file;
  }
  const base: UploadFileBase = { id: file.id, name: file.name, size: file.size };
  return result.ok
    ? { ...base, status: "accepted", kind: result.kind }
    : { ...base, status: "rejected", code: result.code };
}

export function uploadReducer(state: UploadState, action: UploadAction): UploadState {
  switch (action.type) {
    case "contractAdded":
      if (!canAddContract(state)) {
        return state;
      }
      return {
        contracts: [...state.contracts, { id: contractId(state.nextContractNumber), files: [] }],
        nextContractNumber: state.nextContractNumber + 1,
      };
    case "contractRemoved": {
      if (!canRemoveContract(state) || !state.contracts.some((c) => c.id === action.contractId)) {
        return state;
      }
      return { ...state, contracts: state.contracts.filter((c) => c.id !== action.contractId) };
    }
    case "filesAdded":
      return addFiles(state, action.contractId, action.files);
    case "fileRemoved": {
      const target = state.contracts.find((c) => c.id === action.contractId);
      if (target?.files.some((f) => f.id === action.fileId) !== true) {
        return state;
      }
      return {
        ...state,
        contracts: state.contracts.map((c) =>
          c.id === action.contractId
            ? { ...c, files: c.files.filter((f) => f.id !== action.fileId) }
            : c,
        ),
      };
    }
    case "fileCheckStarted":
      return updateFile(state, action.fileId, (file) =>
        file.status === "queued" ? { ...file, status: "checking" } : file,
      );
    case "checksRequeued": {
      let next = state;
      for (const fileId of action.fileIds) {
        next = updateFile(next, fileId, (file) =>
          file.status === "checking" ? { ...file, status: "queued" } : file,
        );
      }
      return next;
    }
    case "fileChecked":
      return updateFile(state, action.fileId, (file) => applyResult(file, action.result));
  }
}

/** Every file with `status`, in display order. */
export function filesWithStatus(state: UploadState, status: UploadFileStatus): UploadFile[] {
  return state.contracts.flatMap((c) => c.files.filter((f) => f.status === status));
}

/**
 * Whether the contracts can be compared. The first unmet condition wins:
 * 1. every check is finished (`checking`);
 * 2. no file was rejected: rejected files must be removed (`rejected_files`);
 * 3. every contract has an accepted file (`contract_without_file`).
 */
export function readiness(state: UploadState): Readiness {
  const files = state.contracts.flatMap((c) => c.files);
  if (files.some(isPending)) {
    return { ready: false, reason: "checking" };
  }
  if (files.some((f) => f.status === "rejected")) {
    return { ready: false, reason: "rejected_files" };
  }
  if (!state.contracts.every((c) => c.files.some(isActive))) {
    return { ready: false, reason: "contract_without_file" };
  }
  return { ready: true, contracts: state.contracts.length };
}
