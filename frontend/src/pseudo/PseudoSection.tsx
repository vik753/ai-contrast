/**
 * Status, error and the review of one contract (S5b-T3). The status and the error are the
 * only live text here: our messages, never a contract value (threat model T11).
 */
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { relabel } from "./masking";
import { ReviewPanel } from "./ReviewPanel";
import type { ContractSection } from "./usePseudoReviews";

const ERROR_CODES = [
  "detector_version_mismatch",
  "input_not_clean",
  "invalid_placeholder",
  "invalid_request",
  "request_too_large",
  "busy",
  "safety_timeout",
  "network_error",
  "invalid_response",
  "timeout",
  "unmasked_identifier",
  "too_many_identifiers",
  "safety_failed",
  "unmapped_span",
  "too_much_text",
  "length_mismatch",
] as const;
type ErrorCode = (typeof ERROR_CODES)[number];

function isErrorCode(code: string): code is ErrorCode {
  return (ERROR_CODES as readonly string[]).includes(code);
}

export function PseudoSection({ label, section }: { label: string; section: ContractSection }) {
  const { t } = useTranslation();
  const { entry } = section;
  // A contract that moved up keeps its review; only the label prefix follows its place.
  const stored = entry?.review ?? null;
  const review = useMemo(() => (stored === null ? null : relabel(stored, label)), [stored, label]);
  if (!section.available && entry === undefined) {
    return null;
  }
  const phase = entry?.phase ?? "editing";
  const status =
    phase === "ready" ? "ready" : phase === "confirmAgain" ? "confirmAgain" : "notReviewed";
  const error = entry?.error ?? null;
  return (
    <div className="pseudo">
      <p className="pseudo__status">
        <span>{t("pseudo.status.label")}: </span>
        <span role="status" data-testid={`pseudo-status-${label}`}>
          {t(`pseudo.status.${status}`)}
        </span>
      </p>
      {error !== null && (
        <p role="alert" className="pseudo__error">
          {t(`pseudo.error.${isErrorCode(error) ? error : "unknown_error"}`)}
        </p>
      )}
      {review === null ? (
        section.available && (
          <button type="button" className="button" onClick={section.open}>
            {t("pseudo.checkReplacements")}
          </button>
        )
      ) : (
        <ReviewPanel
          review={review}
          phase={phase}
          onChange={section.edit}
          onConfirm={section.confirm}
        />
      )}
    </div>
  );
}
