/**
 * Upload form (S2-T2): contracts A…E, each with its files.
 *
 * - Files are checked in the browser first (limits, `.doc`, `.pages`), then
 *   sent one by one to `POST /api/extract` as raw bytes (ADR 0010) by
 *   `useCheckScheduler`: at most 2 checks at a time in the whole form.
 * - Removing a file or a contract aborts its checks (the scheduler sees the
 *   file leave the state). Unmounting the form aborts every check.
 * - File names are rendered as plain text only, inside `<bdi>`, and never
 *   leave the browser (threat model T1, T11). Server text is never shown:
 *   only our messages for allowlisted error codes.
 * - Scanned PDF pages (`ocr_pages`) are recognized in the browser, one job at
 *   a time in the whole form (`useOcrScheduler`); removing the file cancels it.
 * - A Google document is added by link (S3-T6): the browser keeps only the ID,
 *   in memory, and sends it to `POST /api/extract/google-doc` through the same
 *   scheduler. The row is shown as "Google Docs document …<last 6 of the ID>".
 * - An accepted file with its text complete is split into clauses by
 *   `POST /api/segment` (S5-T2, `useSegmentScheduler`); the cleaned blocks of the
 *   reply replace its text. A failed split shows its message and "Try again".
 * - Accepted files keep their extracted text in memory only; the per-contract
 *   `Preview` shows it as plain text (S3-T4).
 */
import type { TFunction } from "i18next";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useReducer,
  useRef,
  useState,
  type DragEvent,
} from "react";
import { useTranslation } from "react-i18next";
import { extractFile, isSafetyOnlyCode } from "../api/extract";
import { extractGoogleDoc, parseGoogleDocLink } from "../api/googleDoc";
import { segmentBlocks } from "../api/segment";
import { formReducer, initialFormState, type Announcement } from "./announcements";
import { FileStatusIcon } from "./FileStatusIcon";
import { displaySize, limitText } from "./format";
import { fileDisplayName } from "./names";
import { MAX_FILE_BYTES, MAX_FILES_PER_CONTRACT, MAX_TOTAL_BYTES } from "./limits";
import { Preview, type PreviewFile } from "./Preview";
import { PseudoSection } from "../pseudo/PseudoSection";
import { usePseudoReviews, type PseudoReviews } from "../pseudo/usePseudoReviews";
import {
  canAddContract,
  canRemoveContract,
  contractLabel,
  fileIdsToKeep,
  initialUploadState,
  needsOcr,
  awaitsSegment,
  hashNotes,
  readiness,
  type Contract,
  type HashNote,
  type RejectionCode,
  type UploadFile,
  type UploadFileStatus,
} from "./state";
import { createRequestBudget } from "./budget";
import { useCheckScheduler, type CheckFile } from "./useCheckScheduler";
import { useHashing } from "./useHashing";
import { useOcrScheduler } from "./useOcrScheduler";
import { useSegmentScheduler, type SegmentRow } from "./useSegmentScheduler";

const NO_NOTES: readonly HashNote[] = [];

const ACCEPT = ".pdf,.docx,.txt";

type FocusTarget =
  | { type: "addFiles"; contractId: string }
  | { type: "newContract"; count: number }
  | { type: "addContract" };

/** Why a pasted Google Docs link was not added. */
type GoogleLinkProblem = "invalid" | "duplicate";

/** Characters of the ID shown in the label of a Google document. */
const GOOGLE_SUFFIX_LENGTH = 6;

function hasFiles(event: DragEvent<HTMLElement>): boolean {
  return Array.from(event.dataTransfer.types).includes("Files");
}

/** Localized size text, for example "2 KB". */
function sizeText(t: TFunction, bytes: number, locale: string): string {
  const size = displaySize(bytes, locale);
  return t(`upload.size.${size.unit}`, { value: size.value });
}

/** Codes whose message names a limit: a short reason plus a detail with the limit. */
const LIMIT_CODES = ["file_too_large", "too_many_files", "total_too_large"] as const;
type LimitCode = (typeof LIMIT_CODES)[number];

function isLimitCode(code: RejectionCode): code is LimitCode {
  return (LIMIT_CODES as readonly string[]).includes(code);
}

/** Message for an error code. Limits come from `limits.ts`, never from the strings. */
function errorText(t: TFunction, code: RejectionCode, locale: string): string {
  if (isSafetyOnlyCode(code)) {
    return t("upload.errors.unknown_error");
  }
  if (!isLimitCode(code)) {
    return t(`upload.errors.${code}`);
  }
  const detail = t(`upload.errors.${code}.detail`, {
    maxSize: limitText(MAX_FILE_BYTES, locale),
    maxTotal: limitText(MAX_TOTAL_BYTES, locale),
    maxFiles: MAX_FILES_PER_CONTRACT,
  });
  return `${t(`upload.errors.${code}.reason`)} ${detail}`;
}

function announcementText(t: TFunction, announcement: Announcement, locale: string): string {
  switch (announcement.type) {
    case "contractAdded":
      return t("upload.announce.contractAdded", { label: announcement.label });
    case "contractRemoved":
      return t("upload.announce.contractRemoved", { label: announcement.label });
    case "filesAdded":
      return t("upload.announce.filesAdded", {
        label: announcement.label,
        count: announcement.count,
      });
    case "fileRemoved":
      return t("upload.announce.fileRemoved", { name: fileDisplayName(t, announcement) });
    case "fileAccepted":
      return t("upload.announce.fileAccepted", {
        name: fileDisplayName(t, announcement),
        kind: t(`upload.kind.${announcement.kind}`),
      });
    case "fileRejected":
      return t("upload.announce.fileRejected", {
        name: fileDisplayName(t, announcement),
        reason: errorText(t, announcement.code, locale),
      });
    case "segmentFailed":
      return t("upload.announce.segmentFailed", {
        name: fileDisplayName(t, announcement),
        reason: errorText(t, announcement.code, locale),
      });
  }
}

/** The clause split of an accepted row, shown next to its kind: the count, or "splitting". */
function segmentNote(t: TFunction, file: UploadFile): string | null {
  if (file.status !== "accepted" || needsOcr(file) || file.segment?.status === "failed") {
    return null;
  }
  return file.segment?.status === "done"
    ? t("upload.clauses.count", { count: file.segment.clauses.length })
    : t("upload.clauses.splitting");
}

function statusText(t: TFunction, file: UploadFile, locale: string): string {
  switch (file.status) {
    case "queued":
      return t("upload.status.queued");
    case "checking":
      return t("upload.status.checking");
    case "accepted":
      if (needsOcr(file)) {
        return file.ocr === undefined
          ? t("upload.ocr.waiting")
          : t("upload.ocr.progress", { current: file.ocr.current, total: file.ocr.total });
      }
      if (file.segment?.status === "failed") {
        return errorText(t, file.segment.code, locale);
      }
      return t(`upload.kind.${file.kind}`);
    case "rejected":
      return errorText(t, file.code, locale);
  }
}

function isPreviewFile(file: UploadFile): file is UploadFile & PreviewFile {
  return file.status === "accepted";
}

function useLocale(): string {
  const { i18n } = useTranslation();
  return i18n.resolvedLanguage ?? i18n.language;
}

function noteText(t: TFunction, note: HashNote): string {
  switch (note.type) {
    case "sameFileIn":
      return t("upload.hash.sameFileIn", { label: note.label });
    case "sameTextHere":
      return t("upload.hash.sameTextHere");
    case "sameTextIn":
      return t("upload.hash.sameTextIn", { label: note.label });
  }
}

/** The icon follows the work in progress: OCR and the clause split show as "checking". */
function rowIconStatus(file: UploadFile): UploadFileStatus {
  if (file.status !== "accepted") {
    return file.status;
  }
  if (file.segment?.status === "failed") {
    return "rejected";
  }
  return needsOcr(file) || awaitsSegment(file) ? "checking" : "accepted";
}

interface FileRowProps {
  file: UploadFile;
  notes: readonly HashNote[];
  onRemove: () => void;
  onRetry: () => void;
}

function FileRow({ file, notes, onRemove, onRetry }: FileRowProps) {
  const { t } = useTranslation();
  const locale = useLocale();
  const name = fileDisplayName(t, file);
  const note = segmentNote(t, file);
  // A Google document has no size until the server has read it.
  const sizeKnown = file.googleSuffix === undefined || file.size > 0;
  return (
    <li className={`file-row file-row--${file.status}`}>
      <span className="file-row__main">
        <bdi className="file-row__name">{name}</bdi>
        {sizeKnown && <span className="file-row__size">{sizeText(t, file.size, locale)}</span>}
      </span>
      <span className="file-row__status">
        <FileStatusIcon status={rowIconStatus(file)} />
        <span className="file-row__status-text">
          <span>{statusText(t, file, locale)}</span>
          {note !== null && (
            <>
              {" · "}
              <span>{note}</span>
            </>
          )}
          {/* Keeps the text apart from the next control for readers of the row text. */}{" "}
        </span>
      </span>
      {notes.length > 0 && (
        <span className="file-row__notes">
          {notes.map((note) => {
            const text = noteText(t, note);
            return (
              <span key={text} className="file-row__note">
                {text}
              </span>
            );
          })}
        </span>
      )}
      {file.status === "accepted" && file.segment?.status === "failed" && (
        <button type="button" className="button button--small" onClick={onRetry}>
          {t("upload.retry")}
        </button>
      )}
      <button
        type="button"
        className="button button--small file-row__remove"
        aria-label={t("upload.removeFileNamed", { name })}
        onClick={onRemove}
      >
        {t("upload.removeFile")}
      </button>
    </li>
  );
}

interface ContractCardProps {
  contract: Contract;
  notes: ReadonlyMap<string, readonly HashNote[]>;
  index: number;
  pseudo: PseudoReviews;
  removable: boolean;
  onAddFiles: (contractId: string, files: File[]) => void;
  onAddGoogleDoc: (contractId: string, link: string) => GoogleLinkProblem | null;
  onRemoveFile: (contractId: string, fileId: string) => void;
  onRetryFile: (fileId: string) => void;
  onRemoveContract: (contractId: string) => void;
  addButtonRef: (contractId: string, element: HTMLButtonElement | null) => void;
}

function ContractCard({
  contract,
  notes,
  index,
  pseudo,
  removable,
  onAddFiles,
  onAddGoogleDoc,
  onRemoveFile,
  onRetryFile,
  onRemoveContract,
  addButtonRef,
}: ContractCardProps) {
  const { t } = useTranslation();
  const locale = useLocale();
  const headingId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const linkId = useId();
  const [dragging, setDragging] = useState(false);
  /** The pasted text lives only here, until "Add" turns it into an ID. */
  const [link, setLink] = useState("");
  const [linkProblem, setLinkProblem] = useState<GoogleLinkProblem | null>(null);
  const label = contractLabel(index);
  const previewFiles = useMemo(() => contract.files.filter(isPreviewFile), [contract.files]);

  const onDragOver = (event: DragEvent<HTMLElement>): void => {
    if (!hasFiles(event)) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setDragging(true);
  };

  const onDragLeave = (event: DragEvent<HTMLElement>): void => {
    const next = event.relatedTarget;
    if (next instanceof Node && event.currentTarget.contains(next)) {
      return;
    }
    setDragging(false);
  };

  const onDrop = (event: DragEvent<HTMLElement>): void => {
    // Never let the browser open the dropped file instead of the app.
    event.preventDefault();
    setDragging(false);
    const files = Array.from(event.dataTransfer.files);
    if (files.length > 0) {
      onAddFiles(contract.id, files);
    }
  };

  const addLink = (): void => {
    const problem = onAddGoogleDoc(contract.id, link);
    setLinkProblem(problem);
    if (problem === null) {
      setLink("");
    }
  };

  return (
    <section
      className={dragging ? "contract contract--dragging" : "contract"}
      aria-labelledby={headingId}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <div className="contract__header">
        <h3 id={headingId} className="contract__title">
          {t("upload.contract", { label })}
        </h3>
        {removable && (
          <button
            type="button"
            className="button button--small button--quiet"
            aria-label={t("upload.removeContractNamed", { label })}
            onClick={() => {
              onRemoveContract(contract.id);
            }}
          >
            {t("upload.removeContract")}
          </button>
        )}
      </div>

      {contract.files.length === 0 ? (
        <p className="contract__empty">{t("upload.noFiles")}</p>
      ) : (
        <ul className="file-list">
          {contract.files.map((file) => (
            <FileRow
              key={file.id}
              file={file}
              notes={notes.get(file.id) ?? NO_NOTES}
              onRemove={() => {
                onRemoveFile(contract.id, file.id);
              }}
              onRetry={() => {
                onRetryFile(file.id);
              }}
            />
          ))}
        </ul>
      )}

      <div className="contract__actions">
        <button
          type="button"
          className="button"
          ref={(element) => {
            addButtonRef(contract.id, element);
            return () => {
              addButtonRef(contract.id, null);
            };
          }}
          aria-label={t("upload.addFilesTo", { label })}
          onClick={() => inputRef.current?.click()}
        >
          {t("upload.addFiles")}
        </button>
        <p className="contract__hint">
          {t("upload.dropHint", {
            maxSize: limitText(MAX_FILE_BYTES, locale),
            maxFiles: MAX_FILES_PER_CONTRACT,
          })}
        </p>
      </div>

      <div className="google-link">
        <label className="google-link__label" htmlFor={`${linkId}-input`}>
          {t("upload.google.label")}
        </label>
        <div className="google-link__row">
          <input
            id={`${linkId}-input`}
            type="text"
            className="google-link__input"
            value={link}
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
            inputMode="url"
            aria-invalid={linkProblem !== null}
            aria-describedby={`${linkId}-hint${linkProblem === null ? "" : ` ${linkId}-error`}`}
            onChange={(event) => {
              setLink(event.currentTarget.value);
              setLinkProblem(null);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.nativeEvent.isComposing) {
                event.preventDefault();
                addLink();
              }
            }}
          />
          <button type="button" className="button" onClick={addLink}>
            {t("upload.google.add")}
          </button>
        </div>
        <p id={`${linkId}-hint`} className="contract__hint">
          {t("upload.google.hint")}
        </p>
        {linkProblem !== null && (
          <p id={`${linkId}-error`} className="google-link__error" role="alert">
            {t(linkProblem === "invalid" ? "upload.google.invalid" : "upload.google.duplicate")}
          </p>
        )}
      </div>

      {previewFiles.length > 0 && <Preview files={previewFiles} />}

      <PseudoSection label={label} section={pseudo.forContract(contract.id, index)} />

      {/* Opened by the button above; hidden from the tab order and from assistive technology. */}
      <input
        ref={inputRef}
        type="file"
        className="visually-hidden"
        multiple
        accept={ACCEPT}
        tabIndex={-1}
        aria-hidden="true"
        onChange={(event) => {
          const input = event.currentTarget;
          const files = Array.from(input.files ?? []);
          // Allow picking the same file again after a removal.
          input.value = "";
          if (files.length > 0) {
            onAddFiles(contract.id, files);
          }
        }}
      />
    </section>
  );
}

export function UploadForm() {
  const { t, i18n } = useTranslation();
  const locale = useLocale();
  const titleId = useId();
  const [form, dispatch] = useReducer(formReducer, initialUploadState, initialFormState);
  const state = form.upload;

  /** `File` objects of files still waiting or accepted, by id. Only in this tab. */
  const filesRef = useRef(new Map<string, File>());
  /**
   * Google document IDs by row id. Memory only (threat model T7): never written
   * to storage, the URL or the console. An entry is dropped with its row. It is
   * needed to send the request and to refuse the same document twice.
   */
  const googleIdsRef = useRef(new Map<string, string>());
  const addButtonsRef = useRef(new Map<string, HTMLButtonElement>());
  const addContractRef = useRef<HTMLButtonElement>(null);
  const focusRef = useRef<FocusTarget | null>(null);
  const nextFileNumberRef = useRef(1);

  const check = useCallback<CheckFile>((file, signal) => {
    const documentId = googleIdsRef.current.get(file.id);
    if (documentId !== undefined) {
      return extractGoogleDoc(documentId, { signal });
    }
    const blob = filesRef.current.get(file.id);
    if (blob === undefined) {
      return Promise.resolve({ ok: false, code: "unknown_error" });
    }
    return extractFile(blob, { signal });
  }, []);

  const segment = useCallback<SegmentRow>(
    (file, signal) => segmentBlocks(file.extraction.blocks, file.extraction.pages, { signal }),
    [],
  );
  // One budget of in-flight requests for checks and splits. The split hook runs first
  // (effects run in order), so a row that is already extracted goes before new checks.
  const [budget] = useState(createRequestBudget);
  useSegmentScheduler(state, dispatch, segment, budget);
  useCheckScheduler(state, dispatch, check, budget);
  const pseudo = usePseudoReviews(state, dispatch, budget);

  const fileById = useCallback((fileId: string) => filesRef.current.get(fileId), []);
  useOcrScheduler(state, dispatch, fileById);
  useHashing(state, dispatch, fileById);
  const notes = useMemo(() => hashNotes(state), [state]);

  // Keep a `File` only while it can still be needed: a check (queued or checking,
  // also after a requeue) or OCR. Accepted files without OCR, rejected and removed
  // files lose their reference.
  // A `File` just added is in the map before its row is in the state: an effect of an
  // older state must not drop it. Only ids the state has shown (or shows) are dropped.
  // Only ids the state has shown before (`seen`) or shows now (`present`) are dropped.
  const seenIdsRef = useRef(new Set<string>());
  useEffect(() => {
    const keep = fileIdsToKeep(state);
    const present = new Set(state.contracts.flatMap((c) => c.files.map((f) => f.id)));
    const seen = seenIdsRef.current;
    for (const id of filesRef.current.keys()) {
      if (!keep.has(id) && (present.has(id) || seen.has(id))) {
        filesRef.current.delete(id);
      }
    }
    seenIdsRef.current = present;
  }, [state]);

  // Forget the ID of a row that left the state (row or contract removed).
  useEffect(() => {
    const present = new Set(state.contracts.flatMap((c) => c.files.map((f) => f.id)));
    for (const id of googleIdsRef.current.keys()) {
      if (!present.has(id)) {
        googleIdsRef.current.delete(id);
      }
    }
  }, [state]);

  // Move focus after a contract or file change, once the DOM shows it.
  // A target is applied only if its element still exists.
  useEffect(() => {
    const target = focusRef.current;
    if (target === null) {
      return;
    }
    focusRef.current = null;
    if (target.type === "addFiles") {
      addButtonsRef.current.get(target.contractId)?.focus();
    } else if (target.type === "newContract") {
      const last = state.contracts.at(-1);
      if (state.contracts.length === target.count && last !== undefined) {
        addButtonsRef.current.get(last.id)?.focus();
      }
    } else {
      addContractRef.current?.focus();
    }
  }, [state]);

  // Old announcements are in the old language: clear them on a switch.
  useEffect(() => {
    const clear = (): void => {
      dispatch({ type: "announcementsCleared" });
    };
    i18n.on("languageChanged", clear);
    return () => {
      i18n.off("languageChanged", clear);
    };
  }, [i18n]);

  // Keep a file dropped next to a card from replacing the whole page.
  useEffect(() => {
    const block = (event: globalThis.DragEvent): void => {
      if (event.dataTransfer?.types.includes("Files") === true) {
        event.preventDefault();
      }
    };
    window.addEventListener("dragover", block);
    window.addEventListener("drop", block);
    return () => {
      window.removeEventListener("dragover", block);
      window.removeEventListener("drop", block);
    };
  }, []);

  const addFiles = (contractId: string, files: File[]): void => {
    const specs = files.map((file) => {
      const id = `file-${nextFileNumberRef.current}`;
      nextFileNumberRef.current += 1;
      filesRef.current.set(id, file);
      return { id, name: file.name, size: file.size, hashPending: true };
    });
    dispatch({ type: "filesAdded", contractId, files: specs });
  };

  /** Adds a row for a Google document, or says why not. The link itself is never kept. */
  const addGoogleDoc = (contractId: string, link: string): GoogleLinkProblem | null => {
    const documentId = parseGoogleDocLink(link);
    if (documentId === null) {
      return "invalid";
    }
    const contract = state.contracts.find((c) => c.id === contractId);
    if (contract === undefined) {
      return "invalid";
    }
    const isDuplicate = contract.files.some(
      (file) => file.status !== "rejected" && googleIdsRef.current.get(file.id) === documentId,
    );
    if (isDuplicate) {
      return "duplicate";
    }
    const fileId = `file-${nextFileNumberRef.current}`;
    nextFileNumberRef.current += 1;
    googleIdsRef.current.set(fileId, documentId);
    dispatch({
      type: "googleDocAdded",
      contractId,
      fileId,
      suffix: documentId.slice(-GOOGLE_SUFFIX_LENGTH),
    });
    return null;
  };

  const removeFile = (contractId: string, fileId: string): void => {
    focusRef.current = { type: "addFiles", contractId };
    dispatch({ type: "fileRemoved", contractId, fileId });
  };

  const retryFile = (fileId: string): void => {
    dispatch({ type: "segmentRetried", fileId });
  };

  const removeContract = (contractId: string): void => {
    focusRef.current = { type: "addContract" };
    dispatch({ type: "contractRemoved", contractId });
  };

  const addContract = (): void => {
    focusRef.current = { type: "newContract", count: state.contracts.length + 1 };
    dispatch({ type: "contractAdded" });
  };

  const registerAddButton = (contractId: string, element: HTMLButtonElement | null): void => {
    if (element === null) {
      addButtonsRef.current.delete(contractId);
    } else {
      addButtonsRef.current.set(contractId, element);
    }
  };

  const ready = readiness(state);
  const removable = canRemoveContract(state);

  return (
    <section className="card upload" aria-labelledby={titleId}>
      <h2 id={titleId} className="card__title">
        {t("upload.title")}
      </h2>
      <p className="card__note">{t("upload.intro")}</p>

      <div className="upload__contracts">
        {state.contracts.map((contract, index) => (
          <ContractCard
            key={contract.id}
            contract={contract}
            notes={notes}
            index={index}
            pseudo={pseudo}
            removable={removable}
            onAddFiles={addFiles}
            onAddGoogleDoc={addGoogleDoc}
            onRemoveFile={removeFile}
            onRetryFile={retryFile}
            onRemoveContract={removeContract}
            addButtonRef={registerAddButton}
          />
        ))}
      </div>

      <div className="upload__footer">
        <button
          ref={addContractRef}
          type="button"
          className="button"
          disabled={!canAddContract(state)}
          onClick={addContract}
        >
          {t("upload.addContract")}
        </button>
        <p className="upload__readiness">
          {ready.ready
            ? t("upload.readiness.ready", { count: ready.contracts })
            : t(`upload.readiness.${ready.reason}`)}
        </p>
      </div>

      <p className="card__note upload__privacy">{t("upload.privacy")}</p>

      <div className="visually-hidden" aria-live="polite">
        {form.announcements.map((entry) => (
          <p key={entry.id}>{announcementText(t, entry.announcement, locale)}</p>
        ))}
      </div>
    </section>
  );
}

export default UploadForm;
