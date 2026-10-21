import type { UploadFileStatus } from "./state";

/**
 * Decorative file status icon. Each status has its own shape (clock, dots,
 * check, cross), so the status never depends on color alone. Always render
 * it next to the status text; it is hidden from assistive technology.
 */
export function FileStatusIcon({ status }: { status: UploadFileStatus }) {
  return (
    <svg
      className={`file-status-icon file-status-icon--${status}`}
      viewBox="0 0 20 20"
      width="20"
      height="20"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="10" cy="10" r="9" className="file-status-icon__badge" />
      {status === "queued" && <path d="M10 5.5V10l3 2" className="file-status-icon__mark" />}
      {status === "checking" && (
        <path d="M6 10h.01M10 10h.01M14 10h.01" className="file-status-icon__mark" />
      )}
      {status === "accepted" && <path d="M5.5 10.5l3 3 6-6.5" className="file-status-icon__mark" />}
      {status === "rejected" && (
        <path d="M6.5 6.5l7 7M13.5 6.5l-7 7" className="file-status-icon__mark" />
      )}
    </svg>
  );
}
