import { useCallback, useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  clearAllData,
  countSavedResults,
  isHistoryAvailable,
  isHistoryEnabled,
  setHistoryEnabled,
  subscribeHistoryChanges,
} from "../storage/historySetting";
import { ConfirmDialog } from "./ConfirmDialog";

type Confirm = "turnOff" | "deleteAll" | null;
type Notice = "deleted" | "blocked" | "failed" | null;

/** "Data and history": history switch, saved results count, delete all data. */
export function SettingsPanel({ id }: { id: string }) {
  const { t } = useTranslation();
  const titleId = useId();
  const [enabled, setEnabled] = useState(isHistoryEnabled);
  // undefined: still loading; null: history is on but the saved results cannot be read.
  const [count, setCount] = useState<number | null | undefined>(enabled ? undefined : 0);
  const available = isHistoryAvailable() && !(enabled && count === null);
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [notice, setNotice] = useState<Notice>(null);

  const refresh = useCallback(async () => {
    const on = isHistoryEnabled();
    const saved = await countSavedResults();
    setEnabled(on);
    setCount(saved);
  }, []);

  useEffect(() => {
    let active = true;
    void countSavedResults().then((saved) => {
      if (active) {
        setEnabled(isHistoryEnabled());
        setCount(saved);
      }
    });
    const unsubscribe = subscribeHistoryChanges(() => {
      void refresh();
    });
    return () => {
      active = false;
      unsubscribe();
    };
  }, [refresh]);

  const turnOff = async () => {
    setConfirm(null);
    const result = await setHistoryEnabled(false);
    setEnabled(false);
    setCount(0);
    setNotice(result === "deleted" ? null : result);
  };

  const onToggle = async () => {
    setNotice(null);
    if (!enabled) {
      try {
        await setHistoryEnabled(true);
      } catch {
        // Blocked storage: the switch shows the real state below.
      }
      await refresh();
      return;
    }
    const saved = await countSavedResults();
    if (saved === 0 || saved === null) {
      await turnOff();
    } else {
      setConfirm("turnOff");
    }
  };

  const deleteAll = async () => {
    setConfirm(null);
    const result = await clearAllData();
    setEnabled(false);
    setCount(0);
    setNotice(result === "cleared" ? "deleted" : result);
  };

  return (
    <section id={id} className="card settings" aria-labelledby={titleId}>
      <h2 id={titleId} className="card__title">
        {t("settings.title")}
      </h2>
      <div className="settings__row">
        <button
          type="button"
          role="switch"
          className="switch"
          aria-checked={enabled}
          disabled={!available && !enabled}
          onClick={() => {
            void onToggle();
          }}
        >
          <span className="switch__track" aria-hidden="true">
            <span className="switch__thumb" />
          </span>
          <span className="switch__label">{t("settings.history.label")}</span>
        </button>
        <span className="switch__state">
          {enabled ? t("settings.history.on") : t("settings.history.off")}
        </span>
      </div>
      <p className="note">{t("settings.history.explanation")}</p>
      {available ? (
        <p className="note">{t("settings.count", { count: count ?? 0 })}</p>
      ) : (
        <p className="note">{t("settings.unavailable")}</p>
      )}
      <button
        type="button"
        className="button button--quiet"
        onClick={() => {
          setConfirm("deleteAll");
        }}
      >
        {t("settings.deleteAll.button")}
      </button>
      <div role="status" className="settings__notice">
        {notice === null ? null : <p>{t(`settings.notice.${notice}`)}</p>}
      </div>
      {confirm === "turnOff" ? (
        <ConfirmDialog
          title={t("settings.turnOff.title")}
          message={t("settings.turnOff.message")}
          confirmLabel={t("settings.turnOff.confirm")}
          onConfirm={() => {
            void turnOff();
          }}
          onCancel={() => {
            setConfirm(null);
          }}
        />
      ) : null}
      {confirm === "deleteAll" ? (
        <ConfirmDialog
          title={t("settings.deleteAll.title")}
          message={t("settings.deleteAll.message")}
          confirmLabel={t("settings.deleteAll.confirm")}
          onConfirm={() => {
            void deleteAll();
          }}
          onCancel={() => {
            setConfirm(null);
          }}
        />
      ) : null}
    </section>
  );
}
