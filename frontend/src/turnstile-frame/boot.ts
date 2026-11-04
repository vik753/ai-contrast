import { resolveAppOrigin } from "./appOrigin";
import { createFrameController } from "./frameController";
import { resolveSiteKey } from "./siteKey";

const API_URL = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

interface TurnstileApi {
  render: (
    container: HTMLElement,
    options: {
      sitekey: string;
      action: string;
      callback: (token: string) => void;
      "expired-callback": () => void;
      "error-callback": () => void;
    },
  ) => string;
  reset: (widgetId: string) => void;
}

function loadApi(): Promise<TurnstileApi> {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = API_URL;
    script.async = true;
    script.onload = () => {
      const api = (window as { turnstile?: TurnstileApi }).turnstile;
      if (api) resolve(api);
      else reject(new Error("turnstile api missing"));
    };
    script.onerror = () => {
      reject(new Error("turnstile api failed"));
    };
    document.head.append(script);
  });
}

/**
 * Starts the widget and wires the postMessage protocol. Runs only on the frame origin.
 * Any failure is reported to the app as a strict error message (no text).
 */
export async function boot(): Promise<void> {
  if (window.parent === window) return;
  let widgetId = "";
  let api: TurnstileApi | null = null;
  let controller: ReturnType<typeof createFrameController> | null = null;
  try {
    controller = createFrameController({
      appOrigin: resolveAppOrigin(import.meta.env),
      parent: window.parent,
      widget: {
        reset: () => {
          api?.reset(widgetId);
        },
      },
    });
    const container = document.getElementById("widget");
    if (!container) throw new Error("no container");
    const siteKey = resolveSiteKey(import.meta.env);
    api = await loadApi();
    widgetId = api.render(container, {
      sitekey: siteKey,
      action: "check",
      callback: controller.onWidgetToken,
      "expired-callback": controller.onWidgetExpired,
      "error-callback": controller.onWidgetError,
    });
    const c = controller;
    window.addEventListener("message", (event) => {
      c.onMessage(event);
    });
  } catch {
    controller?.onWidgetError();
  }
}
