import { createFrameController } from "./frameController";
import { resolveSiteKey } from "./siteKey";

const API_URL = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
const DEV_APP_ORIGIN = "http://localhost:5173";

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

function appOrigin(): string {
  const raw = import.meta.env.VITE_TURNSTILE_APP_ORIGIN ?? "";
  if (raw !== "") return new URL(raw).origin;
  if (import.meta.env.DEV) return DEV_APP_ORIGIN;
  throw new Error("VITE_TURNSTILE_APP_ORIGIN is required in production");
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

/** Starts the widget and wires the postMessage protocol. Runs only on the frame origin. */
export async function boot(): Promise<void> {
  const container = document.getElementById("widget");
  if (!container || window.parent === window) return;
  const origin = appOrigin();
  const siteKey = resolveSiteKey(import.meta.env);
  const api = await loadApi();
  let widgetId = "";
  const controller = createFrameController({
    appOrigin: origin,
    parent: window.parent,
    widget: {
      reset: () => {
        api.reset(widgetId);
      },
    },
  });
  widgetId = api.render(container, {
    sitekey: siteKey,
    action: "check",
    callback: controller.onWidgetToken,
    "expired-callback": () => {
      api.reset(widgetId);
    },
    "error-callback": () => {
      api.reset(widgetId);
    },
  });
  window.addEventListener("message", controller.onMessage);
}
