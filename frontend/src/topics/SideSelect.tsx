import { useId } from "react";
import { useT } from "./useT";
import type { CatalogDomain, Lang } from "./types";

interface Props {
  domain: CatalogDomain;
  lang: Lang;
  value: string;
  onChange: (id: string) => void;
}

export function SideSelect({ domain, lang, value, onChange }: Props) {
  const { t } = useT();
  const id = useId();
  return (
    <div className="provider__field">
      <label htmlFor={id} className="provider__label">
        {t("topics.side.label")}
      </label>
      <select
        id={id}
        className="provider__input"
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
        }}
      >
        {domain.sides.map((s) => (
          <option key={s.id} value={s.id}>
            {s.names[lang]}
          </option>
        ))}
      </select>
    </div>
  );
}
