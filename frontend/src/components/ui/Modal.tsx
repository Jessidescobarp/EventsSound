import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";

const FOCUSABLE = 'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

/**
 * Accessible modal dialog: labelled, aria-modal, Tab stays inside, Escape closes, focus moves in when it
 * opens (or when `step` changes) and returns to `returnFocus` when it closes.
 */
export function Modal({
  title,
  step,
  onClose,
  returnFocus,
  children,
}: {
  title: string;
  /** Changing it moves focus to the first control again (a new screen inside the same dialog). */
  step: string;
  onClose: () => void;
  returnFocus: HTMLElement | null;
  children: ReactNode;
}) {
  const titleId = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const opener = useRef(returnFocus);

  useEffect(() => {
    const target = dialog.current?.querySelector<HTMLElement>("[data-autofocus]") ?? dialog.current?.querySelector<HTMLElement>(FOCUSABLE);
    (target ?? dialog.current)?.focus();
  }, [step]);

  useEffect(() => () => opener.current?.focus(), []);

  function onKeyDown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const items = Array.from(dialog.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    const first = items[0];
    const last = items.at(-1);
    if (!first || !last) return event.preventDefault();
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return createPortal(
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-ink/60 p-4">
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onKeyDown={onKeyDown}
        className="max-h-full w-full max-w-lg space-y-4 overflow-y-auto rounded-card bg-surface p-6 shadow-card"
      >
        <h2 id={titleId} className="text-xl font-semibold">
          {title}
        </h2>
        {children}
      </div>
    </div>,
    document.body,
  );
}
