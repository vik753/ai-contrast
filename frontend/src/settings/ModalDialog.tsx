import { useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";

interface ModalDialogProps {
  role: "dialog" | "alertdialog";
  labelledBy: string;
  describedBy?: string;
  /** Called once when the person presses Escape. */
  onEscape: () => void;
  children: ReactNode;
}

const FOCUSABLE =
  "button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex='-1'])";

function focusablesIn(node: HTMLElement | null): HTMLElement[] {
  return node ? Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE)) : [];
}

/**
 * Modal dialog: focus moves to the first control, stays inside, and returns to the
 * element that was focused before the dialog opened when it unmounts.
 */
export function ModalDialog({
  role,
  labelledBy,
  describedBy,
  onEscape,
  children,
}: ModalDialogProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const opener = document.activeElement;
    focusablesIn(ref.current)[0]?.focus();
    const onFocusIn = (event: FocusEvent) => {
      const node = ref.current;
      if (node && event.target instanceof Node && !node.contains(event.target)) {
        focusablesIn(node)[0]?.focus();
      }
    };
    document.addEventListener("focusin", onFocusIn);
    return () => {
      document.removeEventListener("focusin", onFocusIn);
      if (opener instanceof HTMLElement && opener.isConnected) {
        opener.focus();
      }
    };
  }, []);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onEscape();
      return;
    }
    if (event.key !== "Tab") {
      return;
    }
    const items = focusablesIn(ref.current);
    const first = items[0];
    const last = items[items.length - 1];
    if (!first || !last) {
      event.preventDefault();
      return;
    }
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div className="modal-backdrop">
      <div
        ref={ref}
        className="modal"
        role={role}
        aria-modal="true"
        aria-labelledby={labelledBy}
        aria-describedby={describedBy}
        onKeyDown={onKeyDown}
      >
        {children}
      </div>
    </div>
  );
}
