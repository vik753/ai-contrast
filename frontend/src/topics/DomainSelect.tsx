import { useId } from "react";
import { useT } from "./useT";
import type { Catalog, Lang } from "./types";

interface Props {
  catalog: Catalog;
  lang: Lang;
  value: string;
  onChange: (id: string) => void;
}

export function DomainSelect({ catalog, lang, value, onChange }: Props) {
  const { t } = useT();
  const id = useId();
  return (
    <div className="provider__field">
      <label htmlFor={id} className="provider__label">
        {t("topics.domain.label")}
      </label>
      <select
        id={id}
        className="provider__input"
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
        }}
      >
        <option value="">{t("topics.domain.none")}</option>
        {catalog.domains.map((d) => (
          <option key={d.id} value={d.id}>
            {d.names[lang]}
          </option>
        ))}
      </select>
    </div>
  );
}
