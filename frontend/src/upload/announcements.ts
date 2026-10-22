/**
 * Screen-reader announcements for the upload form (S2-T2 AC7).
 *
 * Pure: an announcement describes what an action changed. The component
 * translates it at render time, so a language switch also switches the
 * announcements. File names are plain text values (threat model T1).
 */
import type { FileKind } from "../api/extract";
import {
  contractLabel,
  uploadReducer,
  type RejectionCode,
  type UploadAction,
  type UploadFile,
  type UploadState,
} from "./state";

export type Announcement =
  | { type: "contractAdded"; label: string }
  | { type: "contractRemoved"; label: string }
  | { type: "filesAdded"; label: string; count: number }
  | { type: "fileRemoved"; name: string; googleSuffix?: string }
  | { type: "fileAccepted"; name: string; kind: FileKind; googleSuffix?: string }
  | { type: "fileRejected"; name: string; code: RejectionCode; googleSuffix?: string };

/** The part of a file that names it: its file name, or the suffix of a Google document. */
function nameOf(file: UploadFile): { name: string; googleSuffix?: string } {
  return file.googleSuffix === undefined
    ? { name: file.name }
    : { name: file.name, googleSuffix: file.googleSuffix };
}

/** How many recent announcements stay in the live region. */
export const MAX_ANNOUNCEMENTS = 5;

function findFile(state: UploadState, fileId: string): UploadFile | undefined {
  for (const contract of state.contracts) {
    const file = contract.files.find((f) => f.id === fileId);
    if (file !== undefined) {
      return file;
    }
  }
  return undefined;
}

function resultOf(file: UploadFile | undefined): Announcement[] {
  if (file?.status === "accepted") {
    return [{ type: "fileAccepted", ...nameOf(file), kind: file.kind }];
  }
  if (file?.status === "rejected") {
    return [{ type: "fileRejected", ...nameOf(file), code: file.code }];
  }
  return [];
}

/** What `action` changed between `prev` and `next`, as announcements. */
export function describeChange(
  prev: UploadState,
  next: UploadState,
  action: UploadAction,
): Announcement[] {
  if (next === prev) {
    return [];
  }
  switch (action.type) {
    case "contractAdded":
      return [{ type: "contractAdded", label: contractLabel(next.contracts.length - 1) }];
    case "contractRemoved": {
      const index = prev.contracts.findIndex((c) => c.id === action.contractId);
      return [{ type: "contractRemoved", label: contractLabel(index) }];
    }
    case "filesAdded": {
      const index = next.contracts.findIndex((c) => c.id === action.contractId);
      const added: Announcement[] = [
        { type: "filesAdded", label: contractLabel(index), count: action.files.length },
      ];
      for (const spec of action.files) {
        const file = findFile(next, spec.id);
        if (file?.status === "rejected") {
          added.push(...resultOf(file));
        }
      }
      return added;
    }
    case "googleDocAdded": {
      const index = next.contracts.findIndex((c) => c.id === action.contractId);
      const file = findFile(next, action.fileId);
      return [
        { type: "filesAdded", label: contractLabel(index), count: 1 },
        ...(file?.status === "rejected" ? resultOf(file) : []),
      ];
    }
    case "fileRemoved": {
      const file = findFile(prev, action.fileId);
      return file === undefined ? [] : [{ type: "fileRemoved", ...nameOf(file) }];
    }
    case "fileCheckStarted":
    case "checksRequeued":
      // Internal steps; announcing them would only add noise.
      return [];
    case "fileChecked":
      return resultOf(findFile(next, action.fileId));
    case "ocrProgress":
      return [];
    case "ocrFinished":
    case "ocrFailed": {
      // The file was announced as accepted before OCR; only a rejection is news.
      const file = findFile(next, action.fileId);
      return file?.status === "rejected" ? resultOf(file) : [];
    }
  }
}

export interface AnnouncedEntry {
  readonly id: number;
  readonly announcement: Announcement;
}

export interface FormState {
  readonly upload: UploadState;
  readonly announcements: readonly AnnouncedEntry[];
  readonly nextAnnouncementId: number;
}

export function initialFormState(upload: UploadState): FormState {
  return { upload, announcements: [], nextAnnouncementId: 1 };
}

/** Form actions: upload actions plus clearing the live region. */
export type FormAction = UploadAction | { type: "announcementsCleared" };

/** `uploadReducer` plus the announcements of each change. Pure. */
export function formReducer(state: FormState, action: FormAction): FormState {
  if (action.type === "announcementsCleared") {
    return state.announcements.length === 0 ? state : { ...state, announcements: [] };
  }
  const upload = uploadReducer(state.upload, action);
  if (upload === state.upload) {
    return state;
  }
  const changes = describeChange(state.upload, upload, action);
  const entries = changes.map((announcement, i) => ({
    id: state.nextAnnouncementId + i,
    announcement,
  }));
  return {
    upload,
    announcements: [...state.announcements, ...entries].slice(-MAX_ANNOUNCEMENTS),
    nextAnnouncementId: state.nextAnnouncementId + entries.length,
  };
}
