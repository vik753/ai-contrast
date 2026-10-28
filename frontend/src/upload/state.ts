/**
 * Upload form state: contracts and their files. Pure reducer, no I/O.
 *
 * File names stay here, in the browser. They are never sent to the server
 * (ADR 0010, threat model T11). The `File` objects themselves live outside
 * the state (see `UploadForm`), so the state stays serializable.
 */
import {
  MAX_BLOCKS,
  MAX_TEXT_CHARS,
  withinCharCap,
  type Block,
  type ExtractErrorCode,
  type ExtractResult,
  type Extraction,
  type ExtractionWarning,
  type FileKind,
} from "../api/extract";
import {
  MAX_CONTRACTS,
  MAX_FILE_BYTES,
  MAX_FILES_PER_CONTRACT,
  MAX_OCR_PAGES,
  MAX_TOTAL_BYTES,
  MIN_CONTRACTS,
  OCR_LOW_CONFIDENCE,
} from "./limits";
import type { Clause, SegmentResult, SegmentWarning } from "../api/segment";
import { canonicalJson } from "../hash/key";
import { normalizeForHash } from "../hash/normalize";
import { sha256Hex } from "../hash/sha256";

/** Codes of checks made in the browser before any request. */
export type ClientRejectionCode =
  | "file_too_large"
  | "too_many_files"
  | "total_too_large"
  | "empty_file"
  | "pages_unsupported"
  | "legacy_office_unsupported"
  | "too_many_ocr_pages"
  | "ocr_failed"
  | "duplicate_file";

export type RejectionCode = ExtractErrorCode | ClientRejectionCode;

/**
 * Where the clause split of an accepted row stands (S5-T2). Absent: waiting for
 * its request. Clauses live in memory only, next to the extracted text, and go
 * with the row (threat model T3 control 7).
 */
export type SegmentState =
  | { readonly status: "running" }
  | { readonly status: "failed"; readonly code: RejectionCode }
  | {
      readonly status: "done";
      readonly clauses: readonly Clause[];
      readonly warnings: readonly SegmentWarning[];
    };

export type UploadFileStatus = "queued" | "checking" | "accepted" | "rejected";

interface UploadFileBase {
  readonly id: string;
  /** File name. Empty for a Google document: the UI builds its label from `googleSuffix`. */
  readonly name: string;
  /** Size in bytes. `0` for a Google document until the server has read it. */
  readonly size: number;
  /**
   * Set only for a Google document: the last characters of its ID, shown in the
   * label. The full ID never enters the state (threat model T7).
   */
  readonly googleSuffix?: string;
  /**
   * SHA-256 of the file bytes (S4-T1). In memory only; never shown, stored or
   * sent. Absent for a Google document and while the hash is computed.
   */
  readonly fileHash?: string;
  /** `true` while the browser hashes the bytes: the row stays `queued` until then. */
  readonly awaitingHash?: true;
}

export type UploadFile =
  | (UploadFileBase & { readonly status: "queued" | "checking" })
  | (UploadFileBase & {
      readonly status: "accepted";
      readonly kind: FileKind;
      /** Extracted text, in memory only (never written to storage). */
      readonly extraction: Extraction;
      /**
       * SHA-256 of the normalized text (S4-T1). In memory only. Absent while it is
       * computed and while OCR still has pages to read.
       */
      readonly textHash?: string;
      /** Set while OCR runs: the page being recognized (1-based) of the total. */
      readonly ocr?: OcrProgress;
      /** The clause split. Starts when the text is complete (no OCR pages left). */
      readonly segment?: SegmentState;
    })
  | (UploadFileBase & { readonly status: "rejected"; readonly code: RejectionCode });

export type AcceptedFile = Extract<UploadFile, { status: "accepted" }>;

export interface OcrProgress {
  readonly current: number;
  readonly total: number;
}

/** Text of one page recognized in the browser. */
export interface OcrPage {
  readonly page: number;
  readonly text: string;
  /** Mean confidence of the engine, 0-100. */
  readonly confidence: number;
}

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
  /** The form sets this: the row waits (queued) until its bytes are hashed. */
  readonly hashPending?: boolean;
}

export type UploadAction =
  | { type: "contractAdded" }
  /** A Google document was added by link. `suffix` is the last characters of its ID. */
  | { type: "googleDocAdded"; contractId: string; fileId: string; suffix: string }
  | { type: "contractRemoved"; contractId: string }
  | { type: "filesAdded"; contractId: string; files: readonly FileSpec[] }
  | { type: "fileRemoved"; contractId: string; fileId: string }
  /** Internal: the bytes of a queued file were hashed (`hash` absent: hashing failed). */
  | { type: "fileHashed"; fileId: string; hash?: string }
  /** Internal: the blocks of an accepted file were sent for the clause split. */
  | { type: "segmentStarted"; fileId: string }
  /** Internal: `running` splits without a request in flight wait for a new request. */
  | { type: "segmentsRequeued"; fileIds: readonly string[] }
  | { type: "segmentFinished"; fileId: string; result: SegmentResult }
  /** The user asked to send a failed split again. */
  | { type: "segmentRetried"; fileId: string }
  /** Internal: the text of an accepted file was hashed. */
  | { type: "textHashed"; fileId: string; hash: string }
  /** Internal: a queued file was sent to the server. */
  | { type: "fileCheckStarted"; fileId: string }
  /** Internal: `checking` files without a request in flight go back to `queued`. */
  | { type: "checksRequeued"; fileIds: readonly string[] }
  | { type: "fileChecked"; fileId: string; result: ExtractResult }
  /** OCR started a page of this file. */
  | { type: "ocrProgress"; fileId: string; current: number; total: number }
  /** OCR recognized every page of `ocrPages`: merge the text into the extraction. */
  | { type: "ocrFinished"; fileId: string; pages: readonly OcrPage[] }
  /** OCR failed. The reason is never shown (it may contain document data). */
  | { type: "ocrFailed"; fileId: string };

export type Readiness =
  | { ready: true; contracts: number }
  | {
      ready: false;
      reason: "checking" | "rejected_files" | "segment_failed" | "contract_without_file";
    };

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

/** An accepted file with scanned pages that the browser still has to recognize. */
export function needsOcr(file: UploadFile): boolean {
  return file.status === "accepted" && file.extraction.ocrPages.length > 0;
}

/** An accepted file whose text is complete but whose clauses are not there yet. */
export function awaitsSegment(file: UploadFile): file is AcceptedFile {
  return (
    file.status === "accepted" &&
    !needsOcr(file) &&
    (file.segment === undefined || file.segment.status === "running")
  );
}

/** An accepted file with its clauses. */
export function isSegmented(file: UploadFile): file is AcceptedFile {
  return file.status === "accepted" && file.segment?.status === "done";
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
      added.push(
        spec.hashPending === true
          ? { ...base, status: "queued", awaitingHash: true }
          : { ...base, status: "queued" },
      );
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

/** A Google document counts like a file; its size is unknown until it is read. */
function addGoogleDoc(
  state: UploadState,
  targetId: string,
  fileId: string,
  suffix: string,
): UploadState {
  const target = state.contracts.find((c) => c.id === targetId);
  if (target === undefined) {
    return state;
  }
  const base: UploadFileBase = { id: fileId, name: "", size: 0, googleSuffix: suffix };
  const file: UploadFile =
    target.files.filter(isActive).length >= MAX_FILES_PER_CONTRACT
      ? { ...base, status: "rejected", code: "too_many_files" }
      : { ...base, status: "queued" };
  return {
    ...state,
    contracts: state.contracts.map((c) =>
      c.id === targetId ? { ...c, files: [...c.files, file] } : c,
    ),
  };
}

/** The identity of a file without its status data (the label suffix is kept). */
function baseOf(file: UploadFile): UploadFileBase {
  return {
    id: file.id,
    name: file.name,
    size: file.size,
    ...(file.googleSuffix === undefined ? {} : { googleSuffix: file.googleSuffix }),
    ...(file.fileHash === undefined ? {} : { fileHash: file.fileHash }),
  };
}

/** A queued file got its byte hash: refuse a copy of a file of the same contract. */
function applyFileHash(state: UploadState, fileId: string, hash: string | undefined): UploadState {
  const contract = state.contracts.find((c) => c.files.some((f) => f.id === fileId));
  const file = contract?.files.find((f) => f.id === fileId);
  if (contract === undefined || file?.status !== "queued" || file.awaitingHash !== true) {
    // Removed, or not waiting for a hash any more: drop the result.
    return state;
  }
  const isCopy =
    hash !== undefined &&
    contract.files.some((f) => f.id !== fileId && f.status !== "rejected" && f.fileHash === hash);
  return updateFile(state, fileId, (current) => {
    if (isCopy) {
      return rejected(current, "duplicate_file");
    }
    const next: UploadFile = { ...baseOf(current), status: "queued" };
    return hash === undefined ? next : { ...next, fileHash: hash };
  });
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
  // A Google document has no local file: its size is what the server read.
  const base: UploadFileBase =
    result.ok && file.googleSuffix !== undefined
      ? { ...baseOf(file), size: result.bytes }
      : baseOf(file);
  if (result.ok && result.extraction.ocrPages.length > MAX_OCR_PAGES) {
    return { ...base, status: "rejected", code: "too_many_ocr_pages" };
  }
  return result.ok
    ? { ...base, status: "accepted", kind: result.kind, extraction: result.extraction }
    : { ...base, status: "rejected", code: result.code };
}

/** Paragraphs of OCR text: split on blank lines, cleaned, trimmed, no empty ones. */
function ocrBlocks(page: OcrPage): Block[] {
  return page.text
    .split(/\n\s*\n/)
    .map((paragraph) =>
      // Same idea as the server: no control or format characters in the text.
      paragraph
        .normalize("NFC")
        .replace(/[^\P{Cc}\n\t]|\p{Cf}|\p{Default_Ignorable_Code_Point}/gu, "")
        .trim(),
    )
    .filter((text) => text !== "")
    .map((text) => ({ text, part: "body", page: page.page }));
}

function rejected(file: UploadFile, code: RejectionCode): UploadFile {
  return { ...baseOf(file), status: "rejected", code };
}

function applyOcr(file: UploadFile, pages: readonly OcrPage[]): UploadFile {
  if (file.status !== "accepted" || !needsOcr(file)) {
    return file;
  }
  const expected = file.extraction.ocrPages;
  const got = pages.map((p) => p.page).sort((a, b) => a - b);
  if (got.length !== expected.length || got.some((page, i) => page !== expected[i])) {
    return rejected(file, "ocr_failed");
  }
  const added = pages.flatMap(ocrBlocks);
  // Stable sort by page keeps the order of server blocks and of paragraphs.
  const blocks = [...file.extraction.blocks, ...added].sort(
    (a, b) => (a.page ?? 0) - (b.page ?? 0),
  );
  if (
    blocks.length > MAX_BLOCKS ||
    !withinCharCap(
      blocks.map((b) => b.text),
      MAX_TEXT_CHARS,
    )
  ) {
    return rejected(file, "too_much_text");
  }
  if (blocks.length === 0) {
    return rejected(file, "no_text_extracted");
  }
  const byPage = [...pages].sort((a, b) => a.page - b.page);
  // A page with no text is a visible gap, not a silent one.
  const emptyPages = new Set(byPage.filter((p) => ocrBlocks(p).length === 0).map((p) => p.page));
  const warnings: ExtractionWarning[] = [
    ...file.extraction.warnings,
    ...byPage.map((p) => ({ code: "ocr_used", page: p.page })),
    ...byPage
      .filter((p) => p.confidence < OCR_LOW_CONFIDENCE || emptyPages.has(p.page))
      .map((p) => ({ code: "ocr_low_confidence", page: p.page })),
  ];
  return {
    ...baseOf(file),
    status: "accepted",
    kind: file.kind,
    extraction: { ...file.extraction, blocks, ocrPages: [], warnings },
  };
}

function withoutSegment(file: AcceptedFile): AcceptedFile {
  const copy = { ...file };
  delete copy.segment;
  return copy;
}

/**
 * The reply of the clause split. On success the cleaned blocks replace the row's
 * text; the text hash is computed from them afterwards. A reply for a row that is
 * not waiting for one (removed, or not running) is dropped.
 */
function applySegment(file: UploadFile, result: SegmentResult): UploadFile {
  if (file.status !== "accepted" || file.segment?.status !== "running") {
    return file;
  }
  if (!result.ok) {
    return { ...file, segment: { status: "failed", code: result.code } };
  }
  const { clauses, blocks, removed, warnings } = result.segmentation;
  return {
    ...file,
    extraction: {
      ...file.extraction,
      blocks,
      removed: [...file.extraction.removed, ...removed],
    },
    segment: { status: "done", clauses, warnings },
  };
}

/**
 * The size of a Google document is known only after the server read it. If it
 * pushes the total over the limit, the document is rejected like a file would be.
 */
function checkTotal(state: UploadState, fileId: string): UploadState {
  if (totalActiveBytes(state) <= MAX_TOTAL_BYTES) {
    return state;
  }
  return updateFile(state, fileId, (file) =>
    file.googleSuffix !== undefined && file.status === "accepted"
      ? rejected(file, "total_too_large")
      : file,
  );
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
    case "googleDocAdded":
      return addGoogleDoc(state, action.contractId, action.fileId, action.suffix);
    case "fileHashed":
      return applyFileHash(state, action.fileId, action.hash);
    case "segmentStarted":
      return updateFile(state, action.fileId, (file) =>
        file.status === "accepted" && !needsOcr(file) && file.segment === undefined
          ? { ...file, segment: { status: "running" } }
          : file,
      );
    case "segmentsRequeued": {
      let next = state;
      for (const fileId of action.fileIds) {
        next = updateFile(next, fileId, (file) =>
          file.status === "accepted" && file.segment?.status === "running"
            ? withoutSegment(file)
            : file,
        );
      }
      return next;
    }
    case "segmentFinished":
      return updateFile(state, action.fileId, (file) => applySegment(file, action.result));
    case "segmentRetried":
      return updateFile(state, action.fileId, (file) =>
        file.status === "accepted" && file.segment?.status === "failed"
          ? withoutSegment(file)
          : file,
      );
    case "textHashed":
      return updateFile(state, action.fileId, (file) =>
        isSegmented(file) && file.textHash === undefined
          ? { ...file, textHash: action.hash }
          : file,
      );
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
      return checkTotal(
        updateFile(state, action.fileId, (file) => applyResult(file, action.result)),
        action.fileId,
      );
    case "ocrProgress":
      return updateFile(state, action.fileId, (file) =>
        file.status === "accepted" && needsOcr(file)
          ? { ...file, ocr: { current: action.current, total: action.total } }
          : file,
      );
    case "ocrFinished":
      return updateFile(state, action.fileId, (file) => applyOcr(file, action.pages));
    case "ocrFailed":
      return updateFile(state, action.fileId, (file) =>
        needsOcr(file) ? rejected(file, "ocr_failed") : file,
      );
  }
}

/**
 * Ids of files whose original `File` is still needed: a check (queued or
 * checking, also after a requeue) or OCR. Every other `File` can be dropped.
 */
export function fileIdsToKeep(state: UploadState): Set<string> {
  return new Set(
    state.contracts.flatMap((c) =>
      c.files.filter((f) => isPending(f) || needsOcr(f)).map((f) => f.id),
    ),
  );
}

/** Every file with `status`, in display order. */
export function filesWithStatus(state: UploadState, status: UploadFileStatus): UploadFile[] {
  return state.contracts.flatMap((c) => c.files.filter((f) => f.status === status));
}

/**
 * Whether the contracts can be compared. The first unmet condition wins:
 * 1. every check, OCR job and clause split is finished (`checking`);
 * 2. no file was rejected: rejected files must be removed (`rejected_files`);
 * 2a. no clause split failed: retry or remove the file (`segment_failed`);
 * 3. every contract has an accepted file (`contract_without_file`).
 */
export function readiness(state: UploadState): Readiness {
  const files = state.contracts.flatMap((c) => c.files);
  if (files.some((f) => isPending(f) || needsOcr(f) || awaitsSegment(f))) {
    return { ready: false, reason: "checking" };
  }
  if (files.some((f) => f.status === "rejected")) {
    return { ready: false, reason: "rejected_files" };
  }
  if (files.some((f) => f.status === "accepted" && f.segment?.status === "failed")) {
    return { ready: false, reason: "segment_failed" };
  }
  if (!state.contracts.every((c) => c.files.some(isActive))) {
    return { ready: false, reason: "contract_without_file" };
  }
  return { ready: true, contracts: state.contracts.length };
}

/** Text that is hashed for an accepted file: blocks in order, joined by a blank line. */
export function textToHash(file: AcceptedFile): string {
  return normalizeForHash(file.extraction.blocks.map((b) => b.text).join("\n\n"));
}

/**
 * Hash of the text of a contract: the canonical JSON of the ordered text hashes
 * of its accepted rows. `null` while a row is queued or checking, or while an
 * accepted row has no text hash yet. Rejected rows are ignored. For stage 9.
 */
export async function contractTextHash(contract: Contract): Promise<string | null> {
  const hashes: string[] = [];
  for (const file of contract.files) {
    if (isPending(file)) {
      return null;
    }
    if (file.status === "accepted") {
      if (file.textHash === undefined) {
        return null;
      }
      hashes.push(file.textHash);
    }
  }
  return sha256Hex(canonicalJson(hashes));
}

/** A note about a file that also appears elsewhere. Shown in the row, never stored. */
export type HashNote =
  | { type: "sameFileIn"; label: string }
  | { type: "sameTextHere" }
  | { type: "sameTextIn"; label: string };

/** Notes by file id (only files that have one). Derived from the in-memory hashes. */
export function hashNotes(state: UploadState): Map<string, HashNote[]> {
  const notes = new Map<string, HashNote[]>();
  const add = (id: string, note: HashNote): void => {
    notes.set(id, [...(notes.get(id) ?? []), note]);
  };
  state.contracts.forEach((contract) => {
    for (const file of contract.files) {
      if (file.status === "rejected") {
        continue;
      }
      const sameFile = new Set<number>();
      const sameText = new Set<number>();
      const sameHere = new Set<number>();
      state.contracts.forEach((other, index) => {
        for (const peer of other.files) {
          if (peer.id === file.id || peer.status === "rejected") {
            continue;
          }
          if (
            other !== contract &&
            file.fileHash !== undefined &&
            peer.fileHash === file.fileHash
          ) {
            sameFile.add(index);
          }
          if (
            file.status === "accepted" &&
            peer.status === "accepted" &&
            file.textHash !== undefined &&
            peer.textHash === file.textHash
          ) {
            if (other === contract) {
              sameHere.add(index);
            } else {
              sameText.add(index);
            }
          }
        }
      });
      for (const index of sameFile) {
        add(file.id, { type: "sameFileIn", label: contractLabel(index) });
      }
      if (sameHere.size > 0) {
        add(file.id, { type: "sameTextHere" });
      }
      for (const index of sameText) {
        add(file.id, { type: "sameTextIn", label: contractLabel(index) });
      }
    }
  });
  return notes;
}
