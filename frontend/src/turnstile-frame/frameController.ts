import {
  MAX_TOKEN_LENGTH,
  TOKEN_MESSAGE_TYPE,
  isResetMessage,
} from "../provider/turnstileProtocol";

export interface FrameController {
  onWidgetToken: (token: string) => void;
  onMessage: (event: { origin: string; source: unknown; data: unknown }) => void;
}

/**
 * Frame side of the protocol (ADR 0016 point 7). The token goes only to the exact app origin.
 * The only message accepted is an exact `reset` from the app origin and the parent window.
 */
export function createFrameController(deps: {
  appOrigin: string;
  parent: { postMessage: (message: unknown, targetOrigin: string) => void };
  widget: { reset: () => void };
}): FrameController {
  return {
    onWidgetToken(token) {
      if (token.length === 0 || token.length > MAX_TOKEN_LENGTH) return;
      deps.parent.postMessage({ type: TOKEN_MESSAGE_TYPE, token }, deps.appOrigin);
    },
    onMessage(event) {
      if (event.origin !== deps.appOrigin || event.source !== deps.parent) return;
      if (isResetMessage(event.data)) deps.widget.reset();
    },
  };
}
