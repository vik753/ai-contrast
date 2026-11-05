import { useId } from "react";
import { useT } from "./useT";
import { AttributeEditor } from "./AttributeEditor";
import type { AttributeDefinition } from "./types";

export interface EditorState {
  name: string;
  description: string;
  /** Set when the topic comes from an accepted suggestion. */
  suggestedId: string | null;
  /** `null` until the attributes were proposed. */
  attributes: AttributeDefinition[] | null;
}

interface Props {
  state: EditorState;
  busy: boolean;
  canPropose: boolean;
  canConfirm: boolean;
  onChange: (next: EditorState) => void;
  onPropose: () => void;
  onConfirm: () => void;
}

export function OwnTopicEditor({
  state,
  busy,
  canPropose,
  canConfirm,
  onChange,
  onPropose,
  onConfirm,
}: Props) {
  const { t } = useT();
  const nameId = useId();
  const descId = useId();
  const attrs = state.attributes;
  const nameOk = state.name.trim() !== "";
  return (
    <fieldset>
      <legend>{t("topics.own.heading")}</legend>
      <div className="provider__field">
        <label htmlFor={nameId} className="provider__label">
          {t("topics.own.name")}
        </label>
        <input
          id={nameId}
          className="provider__input"
          type="text"
          maxLength={80}
          autoComplete="off"
          value={state.name}
          onChange={(e) => {
            onChange({ ...state, name: e.target.value });
          }}
        />
      </div>
      <div className="provider__field">
        <label htmlFor={descId} className="provider__label">
          {t("topics.own.description")}
        </label>
        <input
          id={descId}
          className="provider__input"
          type="text"
          maxLength={200}
          autoComplete="off"
          value={state.description}
          onChange={(e) => {
            onChange({ ...state, description: e.target.value });
          }}
        />
      </div>
      <div className="provider__actions">
        <button
          type="button"
          className="button"
          disabled={busy || !nameOk || !canPropose}
          onClick={onPropose}
        >
          {t("topics.own.propose")}
        </button>
        <button
          type="button"
          className="button"
          disabled={busy || !nameOk || !canConfirm}
          onClick={onConfirm}
        >
          {t("topics.own.confirm")}
        </button>
      </div>
      {attrs !== null ? (
        <ul aria-label={t("topics.attr.list")}>
          {attrs.map((a, i) => (
            <AttributeEditor
              key={`${a.id}-${String(i)}`}
              attribute={a}
              onChange={(next) => {
                onChange({ ...state, attributes: attrs.map((x, j) => (j === i ? next : x)) });
              }}
              onRemove={() => {
                onChange({ ...state, attributes: attrs.filter((_, j) => j !== i) });
              }}
            />
          ))}
        </ul>
      ) : null}
    </fieldset>
  );
}
