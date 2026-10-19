import { StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import App from "./App";
import { setupFallbackI18n, setupI18n } from "./i18n";

/**
 * Starts the app in `container`.
 *
 * Runs `setup` (i18n by default) and renders the app. If `setup` rejects, the
 * app still renders, in English: a broken language setup must never leave the
 * user with a blank page.
 */
export async function start(
  container: Element,
  setup: () => Promise<unknown> = setupI18n,
): Promise<Root> {
  try {
    await setup();
  } catch {
    await setupFallbackI18n();
  }
  const root = createRoot(container);
  root.render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  return root;
}
