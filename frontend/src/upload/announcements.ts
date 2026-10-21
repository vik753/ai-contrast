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
  | { type: "fileRemoved"; name: string }
  | { type: "fileAccepted"; name: string; kind: FileKind }
  | { type: "fileRejected"; name: string; code: RejectionCode };

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
    return [{ type: "fileAccepted", name: file.name, kind: file.kind }];
  }
  if (file?.status === "rejected") {
    return [{ type: "fileRejected", name: file.name, code: file.code }];
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
    case "fileRemoved": {
      const file = findFile(prev, action.fileId);
      return file === undefined ? [] : [{ type: "fileRemoved", name: file.name }];
    }
    case "fileCheckStarted":
      return [];
    case "fileChecked":
      return resultOf(findFile(next, action.fileId));
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

/** `uploadReducer` plus the announcements of each change. Pure. */
export function formReducer(state: FormState, action: UploadAction): FormState {
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
