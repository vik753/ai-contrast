import { useId } from "react";
import { useT } from "./useT";
import { directionOptions, type AttributeDefinition } from "./types";

interface Props {
  attribute: AttributeDefinition;
  onChange: (next: AttributeDefinition) => void;
  onRemove: () => void;
}

/** One editable attribute row. The model proposal is a plain text start value. */
export function AttributeEditor({ attribute, onChange, onRemove }: Props) {
  const { t } = useT();
  const labelId = useId();
  const dirId = useId();
  return (
    <li>
      <div className="provider__field">
        <label htmlFor={labelId} className="provider__label">
          {t("topics.attr.label")}
        </label>
        <input
          id={labelId}
          className="provider__input"
          type="text"
          maxLength={200}
          autoComplete="off"
          value={attribute.label}
          onChange={(e) => {
            onChange({ ...attribute, label: e.target.value });
          }}
        />
      </div>
      <div className="provider__field">
        <label htmlFor={dirId} className="provider__label">
          {t("topics.attr.direction")}
        </label>
        <select
          id={dirId}
          className="provider__input"
          value={attribute.direction}
          onChange={(e) => {
            onChange({ ...attribute, direction: e.target.value, direction_source: "client" });
          }}
        >
          {directionOptions(attribute.type).map((d) => (
            <option key={d} value={d}>
              {t(`topics.direction.${d}` as "topics.direction.none")}
            </option>
          ))}
        </select>
      </div>
      <button type="button" className="button button--quiet button--small" onClick={onRemove}>
        {t("topics.attr.remove")}
      </button>
    </li>
  );
}
