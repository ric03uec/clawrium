"use client";

import { useEffect, useId, useRef } from "react";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}

export function Modal({ open, onClose, title, children, footer }: ModalProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  // ATX-1 W5: pair the <dialog> with a stable id so screen readers
  // announce the title via aria-labelledby. useId is stable across
  // renders + SSR-safe; one id per modal instance.
  const titleId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (open) {
      dialog.showModal();
    } else {
      dialog.close();
    }
  }, [open]);

  // Keep latest onClose in a ref so the listener registers once per mount
  // even when parents pass a new closure each render. Re-subscribing on
  // every render (deps: [onClose]) is wasteful and was flagged in review.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    const handleClose = () => onCloseRef.current();
    dialog.addEventListener("close", handleClose);
    return () => dialog.removeEventListener("close", handleClose);
  }, []);

  if (!open) return null;

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      // ATX-2 B3: VoiceOver / older JAWS use virtual-cursor navigation
      // that ignores <dialog>'s native focus trap, so background DOM
      // is still readable. aria-modal="true" is the explicit signal
      // those assistive techs honor.
      aria-modal="true"
      className="backdrop:bg-black/40 rounded-xl border border-default shadow-xl p-0 max-w-lg w-full"
      onClick={(e) => {
        if (e.target === dialogRef.current) onClose();
      }}
    >
      <div className="p-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <h2 id={titleId} className="text-lg font-semibold text-primary-text">
            {title}
          </h2>
          <button
            onClick={onClose}
            aria-label="Close dialog"
            className="text-muted hover:text-secondary p-1 rounded"
          >
            ✕
          </button>
        </div>

        {/* Content */}
        <div className="text-sm text-secondary">{children}</div>

        {/* Footer */}
        {footer && (
          <div className="mt-6 flex items-center justify-end gap-3">
            {footer}
          </div>
        )}
      </div>
    </dialog>
  );
}
