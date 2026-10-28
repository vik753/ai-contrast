import { useId } from "react";
import { useTranslation } from "react-i18next";
import { ModalDialog } from "./ModalDialog";

export interface CachedResultDialogProps {
  /** When the result was saved: epoch milliseconds. */
  savedAt: number;
  onChoice: (choice: "cached" | "new" | "cancel") => void;
}

/** "Already analyzed": show the saved result or run a new analysis. */
export function CachedResultDialog({ savedAt, onChoice }: CachedResultDialogProps) {
  const { t, i18n } = useTranslation();
  const titleId = useId();
  const textId = useId();
  const date = new Date(savedAt);
  const formatted = new Intl.DateTimeFormat(i18n.resolvedLanguage ?? i18n.language, {
    dateStyle: "long",
    timeStyle: "short",
  }).format(date);

  return (
    <ModalDialog
      role="dialog"
      labelledBy={titleId}
      describedBy={textId}
      onEscape={() => {
        onChoice("cancel");
      }}
    >
      <h2 id={titleId} className="modal__title">
        {t("cachedResult.title")}
      </h2>
      <p id={textId}>
        {t("cachedResult.text")} <time dateTime={date.toISOString()}>{formatted}</time>
      </p>
      <div className="modal__actions">
        <button
          type="button"
          className="button"
          onClick={() => {
            onChoice("cached");
          }}
        >
          {t("cachedResult.show")}
        </button>
        <button
          type="button"
          className="button button--quiet"
          onClick={() => {
            onChoice("new");
          }}
        >
          {t("cachedResult.new")}
        </button>
      </div>
    </ModalDialog>
  );
}
