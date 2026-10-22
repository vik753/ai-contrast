import type { TFunction } from "i18next";

/** What names a row: a file name, or the suffix of a Google document (S3-T6b). */
export interface NamedFile {
  readonly name: string;
  readonly googleSuffix?: string;
}

/**
 * The text shown for a file. A Google document is shown as
 * "Google Docs document …<last 6 characters of the ID>" in the current
 * language; the full ID is never shown (threat model T7).
 */
export function fileDisplayName(t: TFunction, file: NamedFile): string {
  return file.googleSuffix === undefined
    ? file.name
    : t("upload.google.name", { suffix: file.googleSuffix });
}
