import "i18next";
import type en from "./locales/en.json";

// Type-checked translation keys: `t("home.tagline")` compiles, a typo does not.
declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: "translation";
    resources: {
      translation: typeof en;
    };
  }
}
