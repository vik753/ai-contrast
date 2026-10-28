import { useId } from "react";
import { useTranslation } from "react-i18next";
import { ModalDialog } from "./ModalDialog";

interface ConfirmDialogProps {
  title: string;
  message: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}

/** In-page confirmation with exactly two buttons: Cancel and the confirm action. */
export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const textId = useId();
  return (
    <ModalDialog role="alertdialog" labelledBy={titleId} describedBy={textId} onEscape={onCancel}>
      <h2 id={titleId} className="modal__title">
        {title}
      </h2>
      <p id={textId}>{message}</p>
      <div className="modal__actions">
        <button type="button" className="button button--quiet" onClick={onCancel}>
          {t("settings.cancel")}
        </button>
        <button type="button" className="button" onClick={onConfirm}>
          {confirmLabel}
        </button>
      </div>
    </ModalDialog>
  );
}
