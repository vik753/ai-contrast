import i18next from "i18next";
import { useEffect, useRef } from "react";
import { getFrameOrigin } from "./frameOrigin";
import { RESET_MESSAGE, parseTokenMessage } from "./turnstileProtocol";

/** The title is read once at render; the frame is short lived. */
function frameTitle(): string {
  return i18next.isInitialized ? i18next.t("provider.frame.title") : "provider.frame.title";
}

interface Props {
  onToken: (token: string) => void;
  /** A change posts a `reset` to the frame so that it solves a fresh challenge. */
  resetSignal?: number;
}

/**
 * Sandboxed iframe on the separate frame origin (ADR 0016 point 7). The Cloudflare script runs
 * only there. A message counts only if its origin equals the frame origin, its source is this
 * iframe's window and its shape is exact.
 */
export function TurnstileFrame({ onToken, resetSignal }: Props) {
  const frame = useRef<HTMLIFrameElement>(null);
  const latest = useRef(onToken);
  const lastReset = useRef(resetSignal);
  const origin = getFrameOrigin();

  useEffect(() => {
    latest.current = onToken;
  });

  useEffect(() => {
    const handler = (event: MessageEvent): void => {
      const win = frame.current?.contentWindow;
      if (event.origin !== origin || !win || event.source !== win) return;
      const token = parseTokenMessage(event.data);
      if (token !== null) latest.current(token);
    };
    window.addEventListener("message", handler);
    return () => {
      window.removeEventListener("message", handler);
    };
  }, [origin]);

  useEffect(() => {
    if (lastReset.current === resetSignal) return;
    lastReset.current = resetSignal;
    frame.current?.contentWindow?.postMessage(RESET_MESSAGE, origin);
  }, [resetSignal, origin]);

  return (
    <iframe
      ref={frame}
      className="turnstile-frame"
      src={`${origin}/turnstile.html`}
      sandbox="allow-scripts allow-same-origin"
      referrerPolicy="no-referrer"
      title={frameTitle()}
    />
  );
}
