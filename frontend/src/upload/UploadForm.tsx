/**
 * Upload form (S2-T2): contracts A…E, each with up to 5 files.
 *
 * - Files are checked in the browser first (limits, `.doc`, `.pages`), then
 *   sent one by one to `POST /api/extract` as raw bytes (ADR 0010). At most
 *   2 checks run at a time in the whole form; the rest wait as `queued`.
 * - Removing a file or a contract aborts its checks and frees the slots.
 *   Unmounting the form aborts every check.
 * - File names are rendered as plain text only and never leave the browser
 *   (threat model T1, T11). Server text is never shown: only our messages
 *   for allowlisted error codes.
 */
import type { TFunction } from "i18next";
import { useEffect, useId, useReducer, useRef, useState, type DragEvent } from "react";
import { useTranslation } from "react-i18next";
import { checkFile } from "./check";
import { FileStatusIcon } from "./FileStatusIcon";
import { displaySize } from "./format";
import { MAX_PARALLEL_REQUESTS } from "./limits";
import {
  canAddContract,
  canRemoveContract,
  contractLabel,
  initialUploadState,
  queuedFiles,
  readiness,
  type Contract,
  type UploadFile,
} from "./state";
import { formReducer, initialFormState, type Announcement } from "./announcements";

const ACCEPT = ".pdf,.docx,.txt";

type FocusTarget = { type: "addFiles"; contractId: string } | { type: "addContract" };

function hasFiles(event: DragEvent<HTMLElement>): boolean {
  return Array.from(event.dataTransfer.types).includes("Files");
}

function announcementText(t: TFunction, announcement: Announcement): string {
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
      return t("upload.announce.fileRemoved", { name: announcement.name });
    case "fileAccepted":
      return t("upload.announce.fileAccepted", {
        name: announcement.name,
        kind: t(`upload.kind.${announcement.kind}`),
      });
    case "fileRejected":
      return t("upload.announce.fileRejected", {
        name: announcement.name,
        reason: t(`upload.errors.${announcement.code}`),
      });
  }
}

function statusText(t: TFunction, file: UploadFile): string {
  switch (file.status) {
    case "queued":
      return t("upload.status.queued");
    case "checking":
      return t("upload.status.checking");
    case "accepted":
      return t(`upload.kind.${file.kind}`);
    case "rejected":
      return t(`upload.errors.${file.code}`);
  }
}

interface FileRowProps {
  file: UploadFile;
  onRemove: () => void;
}

function FileRow({ file, onRemove }: FileRowProps) {
  const { t, i18n } = useTranslation();
  const size = displaySize(file.size, i18n.resolvedLanguage ?? i18n.language);
  return (
    <li className={`file-row file-row--${file.status}`}>
      <span className="file-row__main">
        <span className="file-row__name">{file.name}</span>
        <span className="file-row__size">
          {t(`upload.size.${size.unit}`, { value: size.value })}
        </span>
      </span>
      <span className="file-row__status">
        <FileStatusIcon status={file.status} />
        <span className="file-row__status-text">{statusText(t, file)}</span>
      </span>
      <button
        type="button"
        className="button button--small file-row__remove"
        aria-label={t("upload.removeFileNamed", { name: file.name })}
        onClick={onRemove}
      >
        {t("upload.removeFile")}
      </button>
    </li>
  );
}

interface ContractCardProps {
  contract: Contract;
  index: number;
  removable: boolean;
  onAddFiles: (contractId: string, files: File[]) => void;
  onRemoveFile: (contractId: string, fileId: string) => void;
  onRemoveContract: (contractId: string) => void;
  addButtonRef: (contractId: string, element: HTMLButtonElement | null) => void;
}

function ContractCard({
  contract,
  index,
  removable,
  onAddFiles,
  onRemoveFile,
  onRemoveContract,
  addButtonRef,
}: ContractCardProps) {
  const { t } = useTranslation();
  const headingId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const label = contractLabel(index);

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
              onRemove={() => {
                onRemoveFile(contract.id, file.id);
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
        <p className="contract__hint">{t("upload.dropHint")}</p>
      </div>

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
  const { t } = useTranslation();
  const titleId = useId();
  const [form, dispatch] = useReducer(formReducer, initialUploadState, initialFormState);
  const state = form.upload;

  /** `File` objects by file id. They stay in memory in this tab only. */
  const filesRef = useRef(new Map<string, File>());
  /** Checks in flight (also during a `busy` wait) by file id. */
  const inFlightRef = useRef(new Map<string, AbortController>());
  const addButtonsRef = useRef(new Map<string, HTMLButtonElement>());
  const addContractRef = useRef<HTMLButtonElement>(null);
  const focusRef = useRef<FocusTarget | null>(null);
  const nextFileNumberRef = useRef(1);

  // Scheduler: start queued checks while fewer than 2 are in flight.
  useEffect(() => {
    const inFlight = inFlightRef.current;
    const free = MAX_PARALLEL_REQUESTS - inFlight.size;
    if (free <= 0) {
      return;
    }
    const next = queuedFiles(state)
      .filter((file) => !inFlight.has(file.id))
      .slice(0, free);
    for (const { id } of next) {
      const blob = filesRef.current.get(id);
      if (blob === undefined) {
        continue;
      }
      const controller = new AbortController();
      inFlight.set(id, controller);
      dispatch({ type: "fileCheckStarted", fileId: id });
      void checkFile(blob, controller.signal).then((result) => {
        if (inFlight.get(id) !== controller) {
          // Removed while in flight: its slot is already free.
          return;
        }
        inFlight.delete(id);
        if (!controller.signal.aborted) {
          dispatch({ type: "fileChecked", fileId: id, result });
        }
      });
    }
  }, [state]);

  // Unmount: abort every check.
  useEffect(() => {
    const inFlight = inFlightRef.current;
    return () => {
      for (const controller of inFlight.values()) {
        controller.abort();
      }
      inFlight.clear();
    };
  }, []);

  // Move focus after a removal, once the DOM shows the new state.
  useEffect(() => {
    const target = focusRef.current;
    if (target === null) {
      return;
    }
    focusRef.current = null;
    if (target.type === "addFiles") {
      addButtonsRef.current.get(target.contractId)?.focus();
    } else {
      addContractRef.current?.focus();
    }
  }, [state]);

  const abortFile = (fileId: string): void => {
    const controller = inFlightRef.current.get(fileId);
    inFlightRef.current.delete(fileId);
    controller?.abort();
    filesRef.current.delete(fileId);
  };

  const addFiles = (contractId: string, files: File[]): void => {
    const specs = files.map((file) => {
      const id = `file-${nextFileNumberRef.current}`;
      nextFileNumberRef.current += 1;
      filesRef.current.set(id, file);
      return { id, name: file.name, size: file.size };
    });
    dispatch({ type: "filesAdded", contractId, files: specs });
  };

  const removeFile = (contractId: string, fileId: string): void => {
    abortFile(fileId);
    focusRef.current = { type: "addFiles", contractId };
    dispatch({ type: "fileRemoved", contractId, fileId });
  };

  const removeContract = (contractId: string): void => {
    const contract = state.contracts.find((c) => c.id === contractId);
    for (const file of contract?.files ?? []) {
      abortFile(file.id);
    }
    focusRef.current = { type: "addContract" };
    dispatch({ type: "contractRemoved", contractId });
  };

  const registerAddButton = (contractId: string, element: HTMLButtonElement | null): void => {
    if (element === null) {
      addButtonsRef.current.delete(contractId);
    } else {
      addButtonsRef.current.set(contractId, element);
    }
  };

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
            index={index}
            removable={removable}
            onAddFiles={addFiles}
            onRemoveFile={removeFile}
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
          onClick={() => {
            dispatch({ type: "contractAdded" });
          }}
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
          <p key={entry.id}>{announcementText(t, entry.announcement)}</p>
        ))}
      </div>
    </section>
  );
}

export default UploadForm;
