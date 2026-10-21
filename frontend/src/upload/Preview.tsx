/**
 * Preview of the extracted text per contract (S3-T4).
 *
 * - Collapsed by default. Nothing of the text is rendered until it opens.
 * - Files in contract order (main text, then annexes), each with its
 *   language, OCR note, warnings, removed text and blocks.
 * - Long text: the first `PREVIEW_BLOCK_LIMIT` blocks, then "Show all".
 * - All server text (blocks, samples) and file names are plain text inside
 *   `<bdi>`; no HTML sinks, links are not clickable (threat model T1, T5).
 *   Reason and warning codes are never shown: only our messages for known
 *   codes, a generic message otherwise.
 */
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import type { BlockPart, Extraction, ExtractionWarning, RemovedText } from "../api/extract";

/** Blocks rendered per file before "Show all". */
export const PREVIEW_BLOCK_LIMIT = 200;

export interface PreviewFile {
  readonly id: string;
  readonly name: string;
  readonly extraction: Extraction;
}

type WarningKey =
  | "upload.preview.warning.not_read_altchunk"
  | "upload.preview.warning.not_read_object"
  | "upload.preview.warning.not_read_subdocument"
  | "upload.preview.warning.borderline_text"
  | "upload.preview.warning.pdf_edited"
  | "upload.preview.warning.external_reference"
  | "upload.preview.warning.unknown";

/** Known warning codes. `Map` lookups never reach `Object.prototype`. */
const WARNING_KEYS: ReadonlyMap<string, WarningKey> = new Map<string, WarningKey>([
  ["not_read_altchunk", "upload.preview.warning.not_read_altchunk"],
  ["not_read_object", "upload.preview.warning.not_read_object"],
  ["not_read_subdocument", "upload.preview.warning.not_read_subdocument"],
  ["borderline_text", "upload.preview.warning.borderline_text"],
  ["pdf_edited", "upload.preview.warning.pdf_edited"],
  ["external_reference", "upload.preview.warning.external_reference"],
]);

type ReasonKey =
  | "upload.preview.removed.reason.hidden_formatting"
  | "upload.preview.removed.reason.same_color"
  | "upload.preview.removed.reason.tiny_text"
  | "upload.preview.removed.reason.control_characters"
  | "upload.preview.removed.reason.other";

const REASON_KEYS: ReadonlyMap<string, ReasonKey> = new Map<string, ReasonKey>([
  ["hidden_formatting", "upload.preview.removed.reason.hidden_formatting"],
  ["same_color", "upload.preview.removed.reason.same_color"],
  ["tiny_text", "upload.preview.removed.reason.tiny_text"],
  ["control_characters", "upload.preview.removed.reason.control_characters"],
]);

export function warningKey(code: string): WarningKey {
  return WARNING_KEYS.get(code) ?? "upload.preview.warning.unknown";
}

export function reasonKey(reason: string): ReasonKey {
  return REASON_KEYS.get(reason) ?? "upload.preview.removed.reason.other";
}

export interface WarningGroup {
  readonly key: WarningKey;
  /** Sorted unique page numbers; empty when no warning of the group has a page. */
  readonly pages: readonly number[];
}

/** One entry per message, in first-seen order, so repeated codes stay short. */
export function groupWarnings(warnings: readonly ExtractionWarning[]): WarningGroup[] {
  const groups = new Map<WarningKey, Set<number>>();
  for (const warning of warnings) {
    const key = warningKey(warning.code);
    let pages = groups.get(key);
    if (pages === undefined) {
      pages = new Set();
      groups.set(key, pages);
    }
    if (warning.page !== null) {
      pages.add(warning.page);
    }
  }
  return Array.from(groups, ([key, pages]) => ({
    key,
    pages: Array.from(pages).sort((a, b) => a - b),
  }));
}

function pageList(pages: readonly number[], locale: string): string {
  const format = new Intl.NumberFormat(locale);
  return pages.map((page) => format.format(page)).join(", ");
}

function useLocale(): string {
  const { i18n } = useTranslation();
  return i18n.resolvedLanguage ?? i18n.language;
}

function WarningIcon() {
  return (
    <svg
      className="preview-warning__icon"
      viewBox="0 0 20 20"
      width="18"
      height="18"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M10 2.5l8 14.5H2z" className="preview-warning__badge" />
      <path d="M10 8v4M10 14.5h.01" className="preview-warning__mark" />
    </svg>
  );
}

function RemovedList({ removed }: { removed: readonly RemovedText[] }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const listId = useId();
  return (
    <div className="preview-removed">
      <button
        type="button"
        className="disclosure preview-removed__toggle"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => {
          setOpen((value) => !value);
        }}
      >
        {t("upload.preview.removed.title")}
      </button>
      <ul id={listId} className="preview-removed__list" hidden={!open}>
        {open &&
          removed.map((item, index) => (
            <li key={index} className="preview-removed__item">
              <span className="preview-removed__reason">{t(reasonKey(item.reason))}</span>{" "}
              <span className="preview-removed__count">
                {t("upload.preview.removed.count", { count: item.count })}
              </span>
              {item.sample !== "" && (
                <bdi className="preview-removed__sample preview-text">{item.sample}</bdi>
              )}
            </li>
          ))}
      </ul>
    </div>
  );
}

function partLabel(t: ReturnType<typeof useTranslation>["t"], part: BlockPart): string {
  return t(`upload.preview.part.${part}`);
}

function FilePreview({ file }: { file: PreviewFile }) {
  const { t } = useTranslation();
  const locale = useLocale();
  const headingId = useId();
  const [showAll, setShowAll] = useState(false);
  const { extraction } = file;
  const blocks = showAll ? extraction.blocks : extraction.blocks.slice(0, PREVIEW_BLOCK_LIMIT);
  const hiddenBlocks = extraction.blocks.length - blocks.length;
  const warnings = groupWarnings(extraction.warnings);

  return (
    <div className="preview-file" role="group" aria-labelledby={headingId}>
      <h5 id={headingId} className="preview-file__title">
        <bdi>{file.name}</bdi>
      </h5>
      <p className="preview-file__language">
        {t("upload.preview.languageLabel")}{" "}
        <span>{t(`upload.preview.language.${extraction.language}`)}</span>
      </p>

      {(extraction.ocrPages.length > 0 || warnings.length > 0) && (
        <ul className="preview-warnings">
          {extraction.ocrPages.length > 0 && (
            <li className="preview-warning">
              <WarningIcon />
              <span>
                {t("upload.preview.ocrPages", { pages: pageList(extraction.ocrPages, locale) })}
              </span>
            </li>
          )}
          {warnings.map((group) => (
            <li key={group.key} className="preview-warning">
              <WarningIcon />
              <span>{t(group.key)}</span>
              {group.pages.length > 0 && (
                <span className="preview-warning__pages">
                  {" "}
                  {t("upload.preview.warningPages", { pages: pageList(group.pages, locale) })}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      {extraction.removed.length > 0 && <RemovedList removed={extraction.removed} />}

      <ol className="preview-blocks">
        {blocks.map((block, index) => (
          <li key={index} className="preview-block">
            <span className="preview-block__meta">
              {partLabel(t, block.part)}
              {block.page !== null && ` · ${t("upload.preview.page", { page: block.page })}`}
            </span>
            <bdi className="preview-block__text preview-text">{block.text}</bdi>
          </li>
        ))}
      </ol>
      {hiddenBlocks > 0 && (
        <button
          type="button"
          className="button button--small button--quiet"
          onClick={() => {
            setShowAll(true);
          }}
        >
          {t("upload.preview.showAll", { count: extraction.blocks.length })}
        </button>
      )}
    </div>
  );
}

/** The "Preview" disclosure of one contract. Render it only with accepted files. */
export function Preview({ files }: { files: readonly PreviewFile[] }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  return (
    <div className="preview">
      <h4 className="preview__title">
        <button
          type="button"
          className="disclosure"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => {
            setOpen((value) => !value);
          }}
        >
          {t("upload.preview.title")}
        </button>
      </h4>
      <div id={bodyId} className="preview__body" hidden={!open}>
        {open && files.map((file) => <FilePreview key={file.id} file={file} />)}
      </div>
    </div>
  );
}
