import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { setupI18n } from "./i18n";
import "./styles.css";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("Root element #root is missing");
}
const root = createRoot(container);

void setupI18n().then(() => {
  root.render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
