import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { AnimatePresence, motion } from "framer-motion";
import type { MarketplaceQueueItem } from "@/bridge/types";
import { useLocale } from "@/hooks/useLocale";

function isWorkingStatus(status: string) {
  return ["queued", "downloading", "paused", "installing", "starting"].includes(String(status || ""));
}

function itemProgress(item: MarketplaceQueueItem, fallback = 0) {
  const byteProgress = item.bytesTotal && item.bytesTotal > 0
    ? Number(item.bytesDone || 0) / item.bytesTotal
    : 0;
  const raw = Math.max(Number(item.progress || 0), byteProgress, Number(fallback || 0));
  if (item.status === "installing") {
    return Math.max(0, Math.min(1, Math.max(raw, 0.85)));
  }
  return Math.max(0, Math.min(1, raw));
}

function MiniCover({ url, title }: { url?: string; title: string }) {
  const [failed, setFailed] = useState(false);
  if (!url || failed) {
    return (
      <div className="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-bg-3 text-[10px] font-semibold text-fg-mute">
        {(title.trim()[0] || "?").toUpperCase()}
      </div>
    );
  }
  return (
    <img src={url} alt="" className="h-8 w-8 shrink-0 rounded-md object-cover" onError={() => setFailed(true)} />
  );
}

function IconButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="grid h-6 w-6 place-items-center rounded-md text-fg-mute transition hover:bg-bg-3 hover:text-fg"
    >
      {children}
    </button>
  );
}

function SortableQueuedRow({
  item,
  onCancel,
  onResume,
}: {
  item: MarketplaceQueueItem;
  onCancel: () => void;
  onResume: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: item.slug });
  const paused = item.status === "paused";
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.7 : 0.55 }}
      className="flex items-center gap-2 px-1 py-1"
    >
      <MiniCover url={item.iconUrl} title={item.title || item.slug} />
      <div className="min-w-0 flex-1 truncate text-[11px] text-fg-dim">{item.title || item.slug}</div>
      {paused ? (
        <IconButton label="Resume" onClick={onResume}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor">
            <path d="M8 5v14l11-7-11-7z" />
          </svg>
        </IconButton>
      ) : null}
      <IconButton label="Cancel" onClick={onCancel}>
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
        </svg>
      </IconButton>
      <button
        type="button"
        className="grid h-6 w-5 cursor-grab place-items-center text-fg-mute active:cursor-grabbing"
        aria-label="Reorder"
        {...attributes}
        {...listeners}
      >
        <svg width="10" height="12" viewBox="0 0 10 12" fill="currentColor" aria-hidden>
          <rect x="0" y="1" width="10" height="1.5" rx="0.75" />
          <rect x="0" y="5.25" width="10" height="1.5" rx="0.75" />
          <rect x="0" y="9.5" width="10" height="1.5" rx="0.75" />
        </svg>
      </button>
    </div>
  );
}

function ActiveRow({
  item,
  locale,
  fallbackProgress = 0,
  onCancel,
  onPause,
  onResume,
}: {
  item: MarketplaceQueueItem;
  locale: string;
  fallbackProgress?: number;
  onCancel: () => void;
  onPause: () => void;
  onResume: () => void;
}) {
  const ru = locale === "ru";
  const paused = item.status === "paused";
  const queued = item.status === "queued";
  const progress = itemProgress(item, fallbackProgress);
  const [visualProgress, setVisualProgress] = useState(progress);
  useLayoutEffect(() => {
    setVisualProgress(progress);
  }, [progress]);
  return (
    <div className="px-1 py-1">
      <div className="flex items-center gap-2">
        <MiniCover url={item.iconUrl} title={item.title || item.slug} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[12px] font-medium text-fg">{item.title || item.slug}</div>
          <div className="truncate text-[10px] text-fg-mute">
            {paused
              ? ru
                ? "Пауза"
                : "Paused"
              : queued
                ? ru
                  ? "В очереди"
                  : "Queued"
                : item.status === "installing"
                  ? ru
                    ? "Установка…"
                    : "Installing…"
                  : ru
                    ? "Загрузка…"
                    : "Downloading…"}
          </div>
        </div>
        <IconButton label={ru ? "Отменить" : "Cancel"} onClick={onCancel}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
          </svg>
        </IconButton>
        <IconButton
          label={paused ? (ru ? "Продолжить" : "Resume") : ru ? "Пауза" : "Pause"}
          onClick={paused ? onResume : onPause}
        >
          {paused ? (
            <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor">
              <path d="M8 5v14l11-7-11-7z" />
            </svg>
          ) : (
            <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor">
              <rect x="6" y="5" width="4" height="14" rx="1" />
              <rect x="14" y="5" width="4" height="14" rx="1" />
            </svg>
          )}
        </IconButton>
      </div>
      <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-bg-3">
        <div
          className="h-full rounded-full transition-[width] duration-700 ease-linear"
          style={{
            width: `${Math.max(progress > 0 ? 2 : 0, visualProgress * 100)}%`,
            backgroundColor: "rgb(var(--page-accent-rgb))",
          }}
        />
      </div>
    </div>
  );
}

function ErrorRow({ item, locale }: { item: MarketplaceQueueItem; locale: string }) {
  const ru = locale === "ru";
  return (
    <div className="flex items-center gap-2 rounded-lg bg-red-500/8 px-1.5 py-1.5">
      <MiniCover url={item.iconUrl} title={item.title || item.slug} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[11px] font-medium text-fg">{item.title || item.slug}</div>
        <div className="line-clamp-2 text-[9px] leading-tight text-red-300">
          {item.message || (ru ? "Установка не завершена. Попробуйте ещё раз или перезапустите приложение." : "Installation failed. Try again or restart the app.")}
        </div>
      </div>
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" className="shrink-0 text-red-400">
        <path d="M6 6l12 12M18 6 6 18" strokeLinecap="round" />
      </svg>
    </div>
  );
}

export function DownloadQueueButton({
  visible,
  progress,
  completedFlash,
  items,
  onCancel,
  onPause,
  onResume,
  onReorder,
}: {
  visible: boolean;
  progress: number;
  completedFlash: boolean;
  items: MarketplaceQueueItem[];
  onCancel: (slug: string, jobId?: string) => void;
  onPause: (slug: string, jobId?: string) => void;
  onResume: (slug: string, jobId?: string) => void;
  onReorder: (orderedSlugs: string[]) => void;
}) {
  const { locale } = useLocale();
  const ru = locale === "ru";
  const [open, setOpen] = useState(false);
  const [panelStyle, setPanelStyle] = useState<CSSProperties>({});
  const rootRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));

  useLayoutEffect(() => {
    if (!open || !buttonRef.current) return;
    const update = () => {
      const rect = buttonRef.current!.getBoundingClientRect();
      const inset = 8;
      const gap = 10;
      const width = Math.max(180, Math.min(280, window.innerWidth - inset * 2));
      const maxHeight = Math.max(120, Math.min(280, window.innerHeight - inset * 2));
      const panelHeight = Math.min(panelRef.current?.offsetHeight || maxHeight, maxHeight);
      const preferredLeft = rect.right + gap;
      const fallbackLeft = rect.left - width - gap;
      const leftCandidate = preferredLeft + width <= window.innerWidth - inset ? preferredLeft : fallbackLeft;
      const left = Math.min(Math.max(inset, leftCandidate), window.innerWidth - width - inset);
      const top = Math.min(
        Math.max(inset, rect.bottom - panelHeight),
        window.innerHeight - panelHeight - inset,
      );
      setPanelStyle({
        position: "fixed",
        left,
        top,
        width,
        maxHeight,
        zIndex: 5000,
      });
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [open, items.length]);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node;
      if (rootRef.current?.contains(target) || panelRef.current?.contains(target)) return;
      setOpen(false);
    };
    window.addEventListener("pointerdown", onPointer);
    return () => window.removeEventListener("pointerdown", onPointer);
  }, [open]);

  const active = useMemo(
    () =>
      items.find((item) => item.status === "downloading" || item.status === "installing" || item.status === "starting")
      || items.find((item) => item.status === "paused")
      || items.find((item) => item.status === "queued")
      || null,
    [items],
  );
  const queued = useMemo(
    () => items.filter((item) => item.slug !== active?.slug && isWorkingStatus(item.status)),
    [items, active?.slug],
  );
  const errors = useMemo(() => items.filter((item) => item.status === "error"), [items]);
  const hasError = errors.length > 0;
  const activeKey = active ? `${active.slug}:${active.jobId || ""}` : "";
  const previousActiveKey = useRef(activeKey);
  const resetProgress = previousActiveKey.current !== activeKey;
  previousActiveKey.current = activeKey;

  const targetRing = Math.max(0, Math.min(1, progress));
  const [visualRing, setVisualRing] = useState(0);
  useEffect(() => {
    if (resetProgress) setVisualRing(0);
    const frame = requestAnimationFrame(() => setVisualRing(targetRing));
    return () => cancelAnimationFrame(frame);
  }, [activeKey, resetProgress, targetRing]);
  const ring = resetProgress ? 0 : visualRing;
  const deg = ring * 360;

  const onDragEnd = (event: DragEndEvent) => {
    const { over, active: drag } = event;
    if (!over || drag.id === over.id) return;
    const ids = queued.map((item) => item.slug);
    const oldIndex = ids.indexOf(String(drag.id));
    const newIndex = ids.indexOf(String(over.id));
    if (oldIndex < 0 || newIndex < 0) return;
    const nextQueued = arrayMove(ids, oldIndex, newIndex);
    onReorder(active ? [active.slug, ...nextQueued] : nextQueued);
  };

  if (!visible) return null;

  return (
    <div ref={rootRef} className="relative mb-1">
      <button
        ref={buttonRef}
        type="button"
        aria-label={ru ? "Очередь загрузок" : "Download queue"}
        title={ru ? "Очередь загрузок" : "Download queue"}
        onClick={() => setOpen((v) => !v)}
        className="relative grid h-11 w-11 place-items-center text-fg-dim transition hover:text-fg"
      >
        <span
          className="absolute inset-[6px] rounded-full"
          style={{
            "--download-progress": `${deg}deg`,
            background: completedFlash
              ? "transparent"
              : hasError
                ? "transparent"
                : ring <= 0
                  ? "color-mix(in srgb, var(--fg-mute) 28%, transparent)"
                  : "conic-gradient(rgb(var(--page-accent-rgb)) var(--download-progress), color-mix(in srgb, var(--fg-mute) 28%, transparent) 0deg)",
            transition: resetProgress ? "none" : "--download-progress 700ms linear",
            WebkitMask: "radial-gradient(farthest-side, transparent calc(100% - 2px), #000 calc(100% - 1.5px))",
            mask: "radial-gradient(farthest-side, transparent calc(100% - 2px), #000 calc(100% - 1.5px))",
          } as CSSProperties}
          aria-hidden
        />
        {hasError ? (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" className="text-red-400">
            <path d="M6 6l12 12M18 6 6 18" strokeLinecap="round" />
          </svg>
        ) : completedFlash ? (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" className="text-[rgb(var(--page-accent-rgb))]">
            <path d="M5 12.5l4.5 4.5L19 7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ) : (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M12 3v12m0 0 4-4m-4 4-4-4M5 19h14" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </button>

      {typeof document !== "undefined"
        ? createPortal(
            <AnimatePresence>
              {open ? (
                <motion.div
                  ref={panelRef}
                  initial={{ opacity: 0, x: -6, scale: 0.98 }}
                  animate={{ opacity: 1, x: 0, scale: 1 }}
                  exit={{ opacity: 0, x: -6, scale: 0.98 }}
                  transition={{ duration: 0.16 }}
                  style={panelStyle}
                  className="overflow-hidden rounded-[14px] border border-line-1 bg-bg-1/95 p-2 shadow-[0_12px_40px_rgba(0,0,0,0.45)] backdrop-blur-md"
                >
                  <div className="mb-1 px-1 text-[10px] font-semibold uppercase tracking-wide text-fg-mute">
                    {ru ? "Загрузки" : "Downloads"}
                  </div>
                  <div className="max-h-[240px] overflow-y-auto">
                    {items.length === 0 ? (
                      <div className="px-1 py-3 text-center text-[11px] text-fg-mute">
                        {completedFlash ? (ru ? "Готово" : "Done") : ru ? "Очередь пуста" : "Queue empty"}
                      </div>
                    ) : (
                      <>
                        {errors.map((item) => <ErrorRow key={`error-${item.jobId}`} item={item} locale={locale} />)}
                        {active ? (
                          <ActiveRow
                            key={activeKey}
                            item={active}
                            locale={locale}
                            fallbackProgress={targetRing}
                            onCancel={() => onCancel(active.slug, active.jobId)}
                            onPause={() => onPause(active.slug, active.jobId)}
                            onResume={() => onResume(active.slug, active.jobId)}
                          />
                        ) : null}
                        {queued.length > 0 ? (
                          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
                            <SortableContext items={queued.map((item) => item.slug)} strategy={verticalListSortingStrategy}>
                              <div className="mt-1 space-y-0.5 border-t border-line-1/70 pt-1">
                                {queued.map((item) => (
                                  <SortableQueuedRow
                                    key={item.slug}
                                    item={item}
                                    onCancel={() => onCancel(item.slug, item.jobId)}
                                    onResume={() => onResume(item.slug, item.jobId)}
                                  />
                                ))}
                              </div>
                            </SortableContext>
                          </DndContext>
                        ) : null}
                      </>
                    )}
                  </div>
                </motion.div>
              ) : null}
            </AnimatePresence>,
            document.body,
          )
        : null}
    </div>
  );
}
