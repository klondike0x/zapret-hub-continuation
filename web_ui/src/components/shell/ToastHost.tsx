import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { getBridge } from "@/bridge";

type Toast = { id: string; message: string; kind?: "info" | "success" | "error" | "warn" };

type Ctx = { push: (t: Omit<Toast, "id"> & { id?: string }) => string; dismiss: (id: string) => void };
const ToastCtx = createContext<Ctx | null>(null);

export function useToast() {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error("ToastProvider missing");
  return ctx;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef(new Map<string, number>());

  const dismiss = useCallback((id: string) => {
    const timer = timers.current.get(id);
    if (timer) {
      window.clearTimeout(timer);
      timers.current.delete(id);
    }
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const push = useCallback<Ctx["push"]>((t) => {
    const id = t.id ?? `t${Date.now()}${Math.random()}`;
    setToasts((prev) => {
      if (prev.some((x) => x.id === id)) {
        return prev.map((x) => (x.id === id ? { id, message: t.message, kind: t.kind } : x));
      }
      return [...prev, { id, message: t.message, kind: t.kind }];
    });
    const previous = timers.current.get(id);
    if (previous) window.clearTimeout(previous);
    timers.current.set(
      id,
      window.setTimeout(() => {
        timers.current.delete(id);
        dismiss(id);
      }, 2500),
    );
    return id;
  }, [dismiss]);

  useEffect(() => {
    const b = getBridge();
    const off1 = b.subscribe("toast.show", (t) => push(t));
    const off2 = b.subscribe("toast.dismiss", (t) => dismiss(t.id));
    return () => { off1(); off2(); };
  }, [push, dismiss]);

  const current = toasts.length > 0 ? toasts[toasts.length - 1] : null;

  return (
    <ToastCtx.Provider value={{ push, dismiss }}>
      {children}
      <div className="pointer-events-none absolute inset-x-0 top-3 z-[100] flex justify-center">
        <AnimatePresence mode="wait">
          {current && (
            <motion.div
              key={current.id}
              initial={{ opacity: 0, y: -12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
              className="pointer-events-auto max-w-[min(420px,92vw)] rounded-xl border border-line-1 bg-bg-2 px-4 py-2.5 text-[13px] leading-snug text-fg shadow-[0_8px_28px_-12px_rgba(0,0,0,0.9)]"
              role="status"
              aria-live="polite"
            >
              <div className="whitespace-pre-wrap break-words">{current.message}</div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </ToastCtx.Provider>
  );
}
