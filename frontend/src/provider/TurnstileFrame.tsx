import i18next from "i18next";
import { useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import { getFrameOrigin } from "./frameOrigin";
import {
  RESET_MESSAGE,
  isErrorMessage,
  isExpiredMessage,
  parseTokenMessage,
} from "./turnstileProtocol";

interface Props {
  onToken: (token: string) => void;
  /** The frame says its token expired. */
  onExpired?: () => void;
  /** The frame could not start or the check failed. */
  onError?: () => void;
  /** A change posts a `reset` to the frame so that it solves a fresh challenge. */
  resetSignal?: number;
}

function safeOrigin(): string | null {
  try {
    return getFrameOrigin();
  } catch {
    return null;
  }
}

/**
 * Sandboxed iframe on the separate frame origin (ADR 0016 point 7). A message counts only if its
 * origin equals the frame origin, its source is this iframe's window and its shape is exact.
 */
export function TurnstileFrame({ onToken, onExpired, onError, resetSignal }: Props) {
  const { t, ready } = useTranslation(undefined, { i18n: i18next, useSuspense: false });
  const frame = useRef<HTMLIFrameElement>(null);
  const latest = useRef({ onToken, onExpired, onError });
  const lastReset = useRef(resetSignal);
  const origin = useMemo(() => safeOrigin(), []);

  useEffect(() => {
    latest.current = { onToken, onExpired, onError };
  });

  useEffect(() => {
    if (origin === null) return;
    const handler = (event: MessageEvent): void => {
      const win = frame.current?.contentWindow;
      if (event.origin !== origin || !win || event.source !== win) return;
      const token = parseTokenMessage(event.data);
      if (token !== null) latest.current.onToken(token);
      else if (isExpiredMessage(event.data)) latest.current.onExpired?.();
      else if (isErrorMessage(event.data)) latest.current.onError?.();
    };
    window.addEventListener("message", handler);
    return () => {
      window.removeEventListener("message", handler);
    };
  }, [origin]);

  useEffect(() => {
    if (origin === null || lastReset.current === resetSignal) return;
    lastReset.current = resetSignal;
    frame.current?.contentWindow?.postMessage(RESET_MESSAGE, origin);
  }, [resetSignal, origin]);

  if (origin === null) return null;
  return (
    <iframe
      ref={frame}
      className="turnstile-frame"
      src={`${origin}/turnstile.html`}
      sandbox="allow-scripts allow-same-origin"
      referrerPolicy="no-referrer"
      title={ready ? t("provider.frame.title") : "provider.frame.title"}
    />
  );
}
