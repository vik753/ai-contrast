/**
 * Google Docs by public link (S3-T6b, threat model T7).
 *
 * - `parseGoogleDocLink` accepts only a full document link on exactly
 *   `docs.google.com` and returns the document ID, nothing else. The pasted
 *   link is never kept, shown or opened.
 * - `extractGoogleDoc` sends only the ID, in the JSON body of
 *   `POST /api/extract/google-doc` (never in a URL or a header), and reuses the
 *   strict response validation of `extract.ts`.
 */
import {
  postExtract,
  type ErrorTable,
  type ExtractOptions,
  type ExtractResult,
  type ResponseRules,
  type ServerErrorCode,
} from "./extract";
import { MAX_FILE_BYTES } from "../upload/limits";

export const GOOGLE_DOC_URL = "/api/extract/google-doc";

/** Same pattern as the server (`[A-Za-z0-9_-]{25,100}`, full match). */
const ID_PATTERN = /^[A-Za-z0-9_-]{25,100}$/;

/** `/document/d/<ID>`, then `/`, or `/edit`, `/view`, `/preview`, `/copy`. */
const PATH_PATTERN = /^\/document\/d\/([A-Za-z0-9_-]+)(?:\/(?:edit|view|preview|copy)?)?$/;

/**
 * The document ID of a Google Docs link, or `null` if the text is not exactly
 * such a link. Leading and trailing whitespace is trimmed; whitespace or a line
 * break inside the text is refused (`new URL()` would silently drop tabs and
 * line breaks). Query and fragment are ignored.
 */
export function parseGoogleDocLink(text: string): string | null {
  const link = text.trim();
  if (link === "" || /\s/u.test(link)) {
    return null;
  }
  let url: URL;
  try {
    url = new URL(link);
  } catch {
    return null;
  }
  if (
    url.protocol !== "https:" ||
    url.hostname !== "docs.google.com" ||
    url.username !== "" ||
    url.password !== "" ||
    url.port !== ""
  ) {
    return null;
  }
  const id = PATH_PATTERN.exec(url.pathname)?.[1];
  return id !== undefined && ID_PATTERN.test(id) ? id : null;
}

/** Codes of `POST /api/extract/google-doc`, each with the status of S3-T6a item 6. */
const GOOGLE_ERRORS: ErrorTable = new Map<number, ReadonlySet<ServerErrorCode>>([
  [413, new Set<ServerErrorCode>(["request_too_large"])],
  [415, new Set<ServerErrorCode>(["unsupported_media_type"])],
  [
    422,
    new Set<ServerErrorCode>([
      "invalid_request",
      "invalid_google_doc_id",
      "google_doc_not_public",
      "google_doc_not_found",
      "google_doc_too_large",
      "extraction_failed",
      "extraction_timeout",
      "too_many_pages",
      "too_much_text",
      "encrypted_unsupported",
      "no_text_extracted",
      "text_decoding_failed",
      "suspicious_package",
      "archive_rejected",
      "docx_strict_unsupported",
    ]),
  ],
  [502, new Set<ServerErrorCode>(["google_doc_unavailable"])],
  [503, new Set<ServerErrorCode>(["busy"])],
  [504, new Set<ServerErrorCode>(["google_doc_timeout"])],
]);

/**
 * There is no local file: `bytes` must be a positive size within the file
 * limit, and the server detects DOCX by magic bytes, so `kind` must be `docx`.
 */
const GOOGLE_RULES: ResponseRules = {
  errors: GOOGLE_ERRORS,
  acceptBytes: (bytes) => bytes > 0 && bytes <= MAX_FILE_BYTES,
  acceptKind: (kind) => kind === "docx",
};

/**
 * Asks the server to fetch and read a public Google document. Never throws.
 * The result never contains server text and never contains the ID.
 */
export function extractGoogleDoc(
  documentId: string,
  options: ExtractOptions = {},
): Promise<ExtractResult> {
  return postExtract(
    {
      url: GOOGLE_DOC_URL,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_id: documentId }),
    },
    GOOGLE_RULES,
    options,
  );
}
