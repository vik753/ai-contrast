/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Origin of the Turnstile frame page (app build). */
  readonly VITE_TURNSTILE_FRAME_ORIGIN?: string;
  /** Exact app origin that may embed the frame (frame build). */
  readonly VITE_TURNSTILE_APP_ORIGIN?: string;
  /** Turnstile site key (frame build). */
  readonly VITE_TURNSTILE_SITE_KEY?: string;
}
