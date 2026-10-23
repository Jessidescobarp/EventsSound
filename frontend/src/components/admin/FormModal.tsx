import { useCallback, useState, type ReactNode } from "react";
import { Modal } from "../ui/Modal";

/** Remembers the control focused when a form opens so the dialog can hand focus back on close. */
export function useOpener() {
  const [opener, setOpener] = useState<HTMLElement | null>(null);
  const remember = useCallback(
    () => setOpener(document.activeElement instanceof HTMLElement ? document.activeElement : null),
    [],
  );
  return { opener, remember };
}

/** Hosts a create/edit form in the shared Modal; closing is blocked while the form reports a save in flight. */
export function FormModal({
  title,
  returnFocus,
  onClose,
  children,
}: {
  title: string;
  returnFocus: HTMLElement | null;
  onClose: () => void;
  children: (onBusyChange: (busy: boolean) => void) => ReactNode;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={title} step="form" onClose={onClose} dismissible={!busy} returnFocus={returnFocus}>
      {children(setBusy)}
    </Modal>
  );
}
