import { AnimatePresence, motion } from "framer-motion";
import { createPortal } from "react-dom";

export function ConfirmModal({
  open,
  title,
  message,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (typeof document === "undefined") return null;
  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          key="confirm-modal"
          className="fixed inset-0 z-[6000] grid place-items-center bg-black/46 backdrop-blur-[2px]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={(event) => {
            event.stopPropagation();
            onCancel();
          }}
        >
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-modal-title"
            initial={{ opacity: 0, y: 8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.98 }}
            transition={{ duration: 0.18 }}
            onClick={(event) => event.stopPropagation()}
            className="flex w-[420px] max-w-[92%] flex-col overflow-hidden rounded-[16px] border border-line-2 bg-bg-2 shadow-[0_18px_42px_-20px_rgba(0,0,0,0.75)]"
          >
            <header className="flex h-12 items-center justify-between border-b border-line-1 px-4">
              <div id="confirm-modal-title" className="text-[13px] font-semibold text-fg">{title}</div>
              <button
                type="button"
                onClick={onCancel}
                className="grid h-7 w-7 place-items-center rounded-[8px] text-fg-dim hover:bg-bg-3 hover:text-fg"
                aria-label={cancelLabel}
              >
                ×
              </button>
            </header>
            <div className="px-4 py-3">
              <p className="whitespace-pre-line text-[12px] leading-relaxed text-fg-dim">{message}</p>
            </div>
            <footer className="flex items-center justify-end gap-2 border-t border-line-1 px-4 py-3">
              <button
                type="button"
                onClick={onCancel}
                className="rounded-[9px] border border-line-1 bg-bg-1 px-3 py-1.5 text-[11px] text-fg-dim hover:bg-bg-3 hover:text-fg"
              >
                {cancelLabel}
              </button>
              <button
                type="button"
                onClick={onConfirm}
                className="rounded-[9px] border border-line-2 bg-fg px-3 py-1.5 text-[11px] font-medium text-bg-0 hover:opacity-90"
              >
                {confirmLabel}
              </button>
            </footer>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
