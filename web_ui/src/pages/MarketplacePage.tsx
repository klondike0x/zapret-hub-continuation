import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { motion, AnimatePresence } from "framer-motion";
import { applyMarketplaceMods, useAppState, useBridge } from "@/hooks/useBridgeState";
import { useLocale } from "@/hooks/useLocale";
import { useMarketplaceQueue } from "@/hooks/useMarketplaceQueue";
import { MarkdownContent } from "@/components/ui/MarkdownContent";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { ScrollGlassHeader } from "@/components/ui/ScrollGlassHeader";
import { getBridge } from "@/bridge";
import type {
  MarketplaceCard,
  MarketplaceCompatibility,
  MarketplaceProject,
  MarketplaceQueueItem,
} from "@/bridge/types";

type CompatFilter = "" | MarketplaceCompatibility;
type SortKey = "relevance" | "popular" | "downloads" | "updated" | "newest";

const CATEGORIES = ["Игры", "Программы", "Соцсети"] as const;
const PAGE_LIMIT = 5;

function formatFileSize(bytes?: number) {
  const value = Math.max(0, Number(bytes || 0));
  if (!value) return "";
  if (value < 1024) return `${Math.round(value)} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(value < 10 * 1024 ? 1 : 0)} KB`;
  return `${(value / (1024 * 1024)).toFixed(value < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

// Marketplace returns the compressed archive size. The on-disk estimate is a
// conservative UI hint until the installer can report an exact unpacked size.
const UNPACKED_SIZE_ESTIMATE_MULTIPLIER = 4.5;

function FileSizeHint({ bytes, installed, locale }: { bytes: number; installed: boolean; locale: string }) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ left: 0, top: 0 });
  const anchorRef = useRef<HTMLButtonElement>(null);
  const ru = locale === "ru";
  const estimate = Math.round(bytes * UNPACKED_SIZE_ESTIMATE_MULTIPLIER);

  const updatePosition = useCallback(() => {
    const rect = anchorRef.current?.getBoundingClientRect();
    if (!rect) return;
    setPosition({
      left: Math.max(12, Math.min(window.innerWidth - 276, rect.right - 264)),
      top: Math.min(window.innerHeight - 92, rect.bottom + 8),
    });
  }, []);

  useEffect(() => {
    if (!open) return;
    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [open, updatePosition]);

  const show = () => {
    updatePosition();
    setOpen(true);
  };

  return (
    <>
      <button
        ref={anchorRef}
        type="button"
        onClick={(event) => event.stopPropagation()}
        onPointerEnter={show}
        onPointerLeave={() => setOpen(false)}
        onFocus={show}
        onBlur={() => setOpen(false)}
        className="cursor-help whitespace-nowrap text-[10px] text-fg-mute underline decoration-dotted underline-offset-2 transition hover:text-fg"
        aria-label={ru ? "Информация о размере файла" : "File size information"}
      >
        {formatFileSize(bytes)}
      </button>
      {open && typeof document !== "undefined"
        ? createPortal(
            <div
              role="tooltip"
              style={{ left: position.left, top: position.top, zIndex: 1000 }}
              className="pointer-events-none fixed w-[264px] rounded-[10px] border border-line-2 bg-bg-2/95 px-3 py-2 text-[10px] leading-relaxed text-fg-dim shadow-[0_14px_34px_-16px_rgba(0,0,0,.75)] backdrop-blur-xl"
            >
              {installed ? (
                <>
                  <span className="font-medium text-fg">{ru ? "Размер на диске: " : "Disk usage: "}</span>
                  {formatFileSize(bytes)}. {ru ? "Это фактический размер распакованной модификации." : "This is the actual unpacked modification size."}
                </>
              ) : (
                <>
                  <span className="font-medium text-fg">{ru ? "Размер загрузки: " : "Download size: "}</span>
                  {formatFileSize(bytes)}. {ru ? "После распаковки модификация может занимать около " : "After extraction, the modification may use about "}
                  <span className="font-medium text-fg">{formatFileSize(estimate)}</span>. {ru ? "Итоговый размер зависит от содержимого и сжатия архива." : "The final size depends on archive contents and compression."}
                </>
              )}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}

function BackArrow() {
  return (
    <svg viewBox="0 0 18 18" aria-hidden="true" className="h-4 w-4 fill-none stroke-current" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10.8 4.2 6 9l4.8 4.8" />
      <path d="M6.3 9H15" />
    </svg>
  );
}

function formatUpdated(ts: number, locale: string) {
  if (!ts) return "—";
  const ms = ts > 1e12 ? ts : ts * 1000;
  try {
    return new Date(ms).toLocaleDateString(locale === "ru" ? "ru-RU" : "en-US", {
      day: "numeric",
      month: "long",
      year: "numeric",
    });
  } catch {
    return "—";
  }
}

function CompatPill({ value }: { value: MarketplaceCompatibility }) {
  const label = value === "zapret2" ? "Zapret 2" : "Zapret";
  const tone = value === "zapret2"
    ? "bg-[color-mix(in_srgb,#9b69e8_28%,transparent)] text-[#c4b5fd]"
    : "bg-[color-mix(in_srgb,#35bf7d_25%,transparent)] text-[#74dca6]";
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${tone}`}>
      {label}
    </span>
  );
}

function Stat({ icon, value }: { icon: "dl" | "heart" | "bookmark"; value: string | number }) {
  const paths = {
    dl: "M12 3v12m0 0 4-4m-4 4-4-4M5 19h14",
    heart: "M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78L12 21.23l8.84-8.84a5.5 5.5 0 0 0 0-7.78Z",
    bookmark: "M7 4h10v16l-5-3-5 3V4z",
  };
  return (
    <span className="inline-flex items-center gap-1 text-[10px] text-fg-mute">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
        <path d={paths[icon]} strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {value}
    </span>
  );
}

function ProjectCover({
  url,
  title,
  eager = false,
  catalog = false,
}: {
  url?: string;
  title: string;
  eager?: boolean;
  catalog?: boolean;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [visible, setVisible] = useState(eager);
  const [failed, setFailed] = useState(false);
  const [resolvedUrl, setResolvedUrl] = useState("");

  useEffect(() => {
    setFailed(false);
    setResolvedUrl("");
    if (!url) return;
    if (!url.startsWith("https://")) {
      setResolvedUrl(url);
      return;
    }
    let cancelled = false;
    void getBridge()
      .call("marketplace.image", { url })
      .then((result) => {
        if (!cancelled) setResolvedUrl(String(result?.dataUrl || ""));
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [url]);

  useEffect(() => {
    if (eager || visible) return;
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          io.disconnect();
        }
      },
      { rootMargin: "120px 0px", threshold: 0.01 },
    );
    io.observe(node);
    return () => io.disconnect();
  }, [eager, visible]);

  const showImage = Boolean(resolvedUrl) && visible && !failed;
  return (
    <div
      ref={ref}
      className={`relative shrink-0 overflow-hidden rounded-[12px] border border-line-1 bg-bg-2 ${
        catalog ? "h-[76px] w-[76px] self-center" : "h-14 w-14"
      }`}
      aria-hidden={!showImage}
    >
      {showImage ? (
        <img
          key={resolvedUrl}
          src={resolvedUrl}
          alt=""
          loading={eager ? "eager" : "lazy"}
          decoding="async"
          referrerPolicy="no-referrer"
          className="absolute inset-0 h-full w-full object-cover object-center"
          onError={() => setFailed(true)}
        />
      ) : (
        <div className="grid h-full w-full place-items-center text-[15px] font-semibold text-fg-mute">
          {(title || "?").slice(0, 1).toUpperCase()}
        </div>
      )}
    </div>
  );
}

function statusLabel(item: MarketplaceQueueItem | undefined, ru: boolean) {
  if (!item) return ru ? "Добавить" : "Add";
  if (item.status === "paused") return ru ? "Пауза" : "Paused";
  if (item.status === "downloading" || item.status === "installing" || item.status === "starting") {
    return ru ? "Устанавливается" : "Installing";
  }
  return ru ? "В очереди" : "Queued";
}

function QueueActionButtons({
  item,
  ru,
  onCancel,
  onPause,
  onResume,
}: {
  item: MarketplaceQueueItem;
  ru: boolean;
  onCancel: () => void;
  onPause: () => void;
  onResume: () => void;
}) {
  const paused = item.status === "paused";
  const active = item.status === "downloading" || item.status === "installing" || item.status === "starting";
  return (
    <motion.div
      initial={{ width: 0, opacity: 0 }}
      animate={{ width: "auto", opacity: 1 }}
      exit={{ width: 0, opacity: 0 }}
      transition={{ duration: 0.18 }}
      className="flex overflow-hidden"
    >
      <div className="flex items-center gap-1 pr-1">
        {(active || paused) && (
          <button
            type="button"
            onClick={paused ? onResume : onPause}
            className="grid h-7 w-7 place-items-center rounded-lg border border-line-1 bg-bg-1 text-fg-dim transition hover:bg-bg-3 hover:text-fg"
            aria-label={paused ? (ru ? "Продолжить" : "Resume") : ru ? "Пауза" : "Pause"}
            title={paused ? (ru ? "Продолжить" : "Resume") : ru ? "Пауза" : "Pause"}
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
          </button>
        )}
        <button
          type="button"
          onClick={onCancel}
          className="grid h-7 w-7 place-items-center rounded-lg border border-line-1 bg-bg-1 text-fg-dim transition hover:bg-bg-3 hover:text-fg"
          aria-label={ru ? "Отменить" : "Cancel"}
          title={ru ? "Отменить" : "Cancel"}
        >
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
          </svg>
        </button>
      </div>
    </motion.div>
  );
}

function CatalogCard({
  item,
  locale,
  queueItem,
  installed,
  installedSize,
  onOpen,
  onDownload,
  onRemove,
  onCancel,
  onPause,
  onResume,
}: {
  item: MarketplaceCard;
  locale: string;
  queueItem?: MarketplaceQueueItem;
  installed: boolean;
  installedSize?: number;
  onOpen: () => void;
  onDownload: () => void;
  onRemove: () => void;
  onCancel: () => void;
  onPause: () => void;
  onResume: () => void;
}) {
  const ru = locale === "ru";
  const downloading = Boolean(queueItem);
  return (
    <article
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      className="group flex cursor-pointer items-stretch gap-3 rounded-[14px] border border-line-1 bg-[color-mix(in_srgb,var(--bg-2)_88%,transparent)] px-3.5 py-3 transition-colors hover:border-line-2 hover:bg-bg-2"
    >
      <ProjectCover url={item.iconUrl} title={item.title} eager catalog />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <h3 className="truncate text-[13px] font-semibold text-fg">{item.title}</h3>
          {item.author ? (
            <span className="truncate text-[11px] text-fg-mute">
              {ru ? "от" : "by"} @{item.author}
            </span>
          ) : null}
        </div>
        <p className="mt-0.5 line-clamp-1 text-[11px] text-fg-dim">{item.summary || "—"}</p>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          <CompatPill value={item.compatibility} />
          {item.categories.map((c) => (
            <span key={c} className="rounded-full bg-bg-3 px-2 py-0.5 text-[10px] text-fg-dim">
              {c}
            </span>
          ))}
        </div>
      </div>
      <div className="flex shrink-0 flex-col items-end justify-between gap-2 pl-1">
        <div className="flex flex-col items-end gap-1">
          <div className="flex items-center gap-2.5">
            <Stat icon="dl" value={item.downloadsCompact || item.downloads} />
            <Stat icon="heart" value={item.likes} />
            <Stat icon="bookmark" value={item.favorites} />
          </div>
          <span className="text-[10px] text-fg-mute">
            {ru ? "Обновлено" : "Updated"} {formatUpdated(item.updatedAt, locale)}
          </span>
        </div>
        <div className="flex items-center justify-end gap-2" onClick={(e) => e.stopPropagation()}>
          <AnimatePresence initial={false}>
            {queueItem ? (
              <QueueActionButtons
                key="actions"
                item={queueItem}
                ru={ru}
                onCancel={onCancel}
                onPause={onPause}
                onResume={onResume}
              />
            ) : null}
          </AnimatePresence>
          {!queueItem && (installed ? installedSize : item.latestVersionSize) ? (
            <FileSizeHint bytes={installed ? installedSize! : item.latestVersionSize!} installed={installed} locale={locale} />
          ) : null}
          {installed ? (
            <button
              type="button"
              onClick={onRemove}
              className="rounded-lg border border-line-1 bg-bg-3/70 px-3 py-1 text-[11px] text-fg-dim transition-colors hover:border-red-400/50 hover:bg-red-500/10 hover:text-red-300"
            >
              {ru ? "Удалить" : "Remove"}
            </button>
          ) : (
            <button
              type="button"
              disabled={downloading}
              onClick={onDownload}
              className="rounded-lg bg-[rgb(var(--page-accent-rgb))] px-3 py-1 text-[11px] font-medium text-white transition hover:brightness-110 disabled:opacity-50"
            >
              {statusLabel(queueItem, ru)}
            </button>
          )}
        </div>
      </div>
    </article>
  );
}

function CatalogSkeleton() {
  return (
    <div className="flex items-stretch gap-3 rounded-[14px] border border-line-1 bg-bg-2/50 px-3.5 py-3">
      <div className="h-14 w-14 shrink-0 animate-pulse rounded-[12px] bg-bg-3" />
      <div className="min-w-0 flex-1 space-y-2 py-0.5">
        <div className="h-3 w-2/5 animate-pulse rounded bg-bg-3" />
        <div className="h-2.5 w-4/5 animate-pulse rounded bg-bg-3/80" />
        <div className="h-5 w-24 animate-pulse rounded-full bg-bg-3/70" />
      </div>
      <div className="flex w-24 flex-col items-end justify-between">
        <div className="h-2.5 w-16 animate-pulse rounded bg-bg-3/80" />
        <div className="h-7 w-20 animate-pulse rounded-lg bg-bg-3" />
      </div>
    </div>
  );
}

function FilterSelect({
  value,
  onChange,
  options,
  ariaLabel,
  align = "left",
}: {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  ariaLabel: string;
  align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [menuStyle, setMenuStyle] = useState<React.CSSProperties>({});
  const selected = options.find((option) => option.value === value) ?? options[0];
  const menuWidth = align === "right" ? 220 : 200;

  const updateMenuPosition = useCallback(() => {
    const button = buttonRef.current;
    if (!button) return;
    const rect = button.getBoundingClientRect();
    const gap = 4;
    const maxHeight = 192; // max-h-48
    const left =
      align === "right"
        ? Math.min(Math.max(8, rect.right - menuWidth), window.innerWidth - menuWidth - 8)
        : Math.min(Math.max(8, rect.left), window.innerWidth - menuWidth - 8);
    setMenuStyle({
      position: "fixed",
      top: rect.bottom + gap,
      left,
      width: menuWidth,
      maxHeight,
      zIndex: 80,
    });
  }, [align, menuWidth]);

  useLayoutEffect(() => {
    if (!open) return;
    updateMenuPosition();
    const onReposition = () => updateMenuPosition();
    window.addEventListener("resize", onReposition);
    window.addEventListener("scroll", onReposition, true);
    return () => {
      window.removeEventListener("resize", onReposition);
      window.removeEventListener("scroll", onReposition, true);
    };
  }, [open, updateMenuPosition]);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node;
      if (rootRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("pointerdown", onPointer);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onPointer);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative shrink-0">
      <button
        ref={buttonRef}
        type="button"
        aria-label={ariaLabel}
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        className="flex h-7 max-w-[220px] items-center gap-1.5 rounded-lg border border-line-1 bg-bg-1 px-2.5 text-[10px] text-fg-dim outline-none transition hover:border-line-2 hover:text-fg"
      >
        <span className="truncate">{selected?.label ?? value}</span>
        <svg
          className={`shrink-0 text-fg-mute transition-transform ${open ? "rotate-180" : ""}`}
          width="10"
          height="10"
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
          aria-hidden
        >
          <path d="m3 4.5 3 3 3-3" />
        </svg>
      </button>
      {typeof document !== "undefined"
        ? createPortal(
            <AnimatePresence>
              {open ? (
                <motion.div
                  ref={menuRef}
                  initial={{ opacity: 0, y: -4, scale: 0.985 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -3, scale: 0.985 }}
                  transition={{ duration: 0.14 }}
                  style={menuStyle}
                  className="overflow-y-auto rounded-[11px] border border-line-2 bg-bg-2 p-1 shadow-[0_12px_28px_-18px_rgba(0,0,0,.65)]"
                >
                  {options.map((option) => (
                    <button
                      key={option.value || "all"}
                      type="button"
                      onClick={() => {
                        onChange(option.value);
                        setOpen(false);
                      }}
                      className={`flex w-full items-center justify-between rounded-[8px] px-2.5 py-1.5 text-left text-[11px] transition-colors ${
                        option.value === value ? "bg-bg-3 text-fg" : "text-fg-dim hover:bg-bg-3 hover:text-fg"
                      }`}
                    >
                      <span className="truncate">{option.label}</span>
                      {option.value === value ? (
                        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[rgb(var(--page-accent-rgb))]" />
                      ) : null}
                    </button>
                  ))}
                </motion.div>
              ) : null}
            </AnimatePresence>,
            document.body,
          )
        : null}
    </div>
  );
}

function DetailSkeleton({ onBack, locale }: { onBack: () => void; locale: string }) {
  const ru = locale === "ru";
  return (
    <div className="scroll-area h-full overflow-auto">
      <div className="border-b border-line-1 px-6 pb-4 pt-5">
        <button type="button" onClick={onBack} className="mb-3 inline-flex items-center gap-1.5 text-[11px] text-fg-mute transition hover:text-fg">
          <BackArrow /> {ru ? "Каталог" : "Catalog"}
        </button>
        <div className="grid items-start gap-x-3 gap-y-3 sm:grid-cols-[minmax(0,1fr)_auto_220px]">
          <div className="h-14 w-14 animate-pulse rounded-[12px] bg-bg-3" />
          <div className="min-w-0 flex-1 space-y-2">
            <div className="h-5 w-48 animate-pulse rounded bg-bg-3" />
            <div className="h-3 w-full max-w-md animate-pulse rounded bg-bg-3/80" />
            <div className="h-3 w-40 animate-pulse rounded bg-bg-3/70" />
          </div>
          <div className="h-10 w-[200px] shrink-0 animate-pulse rounded-[10px] bg-bg-3" />
        </div>
      </div>
      <div className="px-6 py-4">
        <div className="grid gap-4 lg:grid-cols-[1fr_220px]">
          <div className="h-64 animate-pulse rounded-[14px] bg-bg-2/70" />
          <div className="h-40 animate-pulse rounded-[14px] bg-bg-2/70" />
        </div>
      </div>
    </div>
  );
}

function DetailView({
  project,
  locale,
  queueItem,
  installed,
  installedSize,
  onBack,
  onDownload,
  onRemove,
  onCancel,
  onPause,
  onResume,
  onOpenSite,
}: {
  project: MarketplaceProject;
  locale: string;
  queueItem?: MarketplaceQueueItem;
  installed: boolean;
  installedSize?: number;
  onBack: () => void;
  onDownload: () => void;
  onRemove: () => void;
  onCancel: () => void;
  onPause: () => void;
  onResume: () => void;
  onOpenSite: () => void;
}) {
  const ru = locale === "ru";
  const latest = project.versions?.[0];
  const downloading = Boolean(queueItem);
  return (
    <div className="scroll-area h-full overflow-auto">
      <div className="border-b border-line-1 px-6 pb-4 pt-5">
        <button type="button" onClick={onBack} className="mb-3 inline-flex items-center gap-1.5 text-[11px] text-fg-mute transition hover:text-fg">
          <BackArrow /> {ru ? "Каталог" : "Catalog"} / {project.title}
        </button>
        <div className="flex items-start gap-4">
          <ProjectCover url={project.iconUrl} title={project.title} eager />
          <div className="min-w-0 flex-1">
            <div className="mb-1.5 flex flex-wrap gap-1.5">
              <CompatPill value={project.compatibility} />
              {project.categories.map((c) => (
                <span key={c} className="rounded-full bg-bg-3 px-2 py-0.5 text-[10px] text-fg-dim">
                  {c}
                </span>
              ))}
            </div>
            <h2 className="text-[18px] font-semibold text-fg">{project.title}</h2>
            <p className="mt-1 text-[12px] text-fg-dim">{project.summary}</p>
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <Stat icon="dl" value={project.downloadsCompact || project.downloads} />
              <Stat icon="heart" value={project.likes} />
              <Stat icon="bookmark" value={project.favorites} />
              {project.author ? <span className="text-[11px] text-fg-mute">@{project.author}</span> : null}
            </div>
          </div>
          <div className="hidden shrink-0 self-center sm:block">
            {installed
              ? installedSize ? <FileSizeHint bytes={installedSize} installed locale={locale} /> : null
              : !queueItem && latest?.size ? <FileSizeHint bytes={latest.size} installed={false} locale={locale} /> : null}
          </div>
          <div className="flex w-full min-w-0 flex-col gap-2 self-end sm:w-[220px]">
            {installed ? (
              <div className="flex items-center">
                <button
                  type="button"
                  onClick={onRemove}
                  className="min-w-0 flex-1 rounded-[10px] border border-line-1 bg-bg-3/70 px-3 py-2 text-[12px] text-fg-dim transition-colors hover:border-red-400/50 hover:bg-red-500/10 hover:text-red-300"
                >
                  {ru ? "Удалить" : "Remove"}
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-1">
                <AnimatePresence initial={false}>
                  {queueItem ? (
                    <QueueActionButtons
                      key="detail-actions"
                      item={queueItem}
                      ru={ru}
                      onCancel={onCancel}
                      onPause={onPause}
                      onResume={onResume}
                    />
                  ) : null}
                </AnimatePresence>
                <button
                  type="button"
                  disabled={downloading}
                  onClick={onDownload}
                  className="min-w-0 flex-1 rounded-[10px] bg-[rgb(var(--page-accent-rgb))] px-3 py-2 text-[12px] font-medium text-white transition hover:brightness-110 disabled:opacity-50"
                >
                  {downloading
                    ? statusLabel(queueItem, ru)
                    : ru
                      ? `Добавить${latest?.version ? ` v${latest.version}` : ""}`
                      : `Add${latest?.version ? ` v${latest.version}` : ""}`}
                </button>
              </div>
            )}
            <button
              type="button"
              onClick={onOpenSite}
              className="w-full rounded-[10px] border border-line-1 bg-bg-1 px-3 py-2 text-[11px] text-fg-dim transition hover:bg-bg-3 hover:text-fg"
            >
              {ru ? "Открыть на сайте" : "Open on website"}
            </button>
          </div>
        </div>
      </div>
      <div className="px-6 py-4">
        <div className="grid gap-4 lg:grid-cols-[1fr_220px]">
          <section className="rounded-[14px] border border-line-1 bg-bg-2/70 p-4">
            <h3 className="text-[13px] font-semibold text-fg">{project.title}</h3>
            <p className="mt-1 text-[12px] text-fg-dim">{project.summary}</p>
            {project.bodyHtml ? (
              <div
                className="marketplace-body mt-3 text-[12px] leading-relaxed text-fg-dim [&_a]:text-[rgb(var(--page-accent-rgb))] [&_h1]:mb-2 [&_h1]:text-[14px] [&_h1]:font-semibold [&_h1]:text-fg [&_h2]:mb-2 [&_h2]:mt-3 [&_h2]:text-[13px] [&_h2]:font-semibold [&_h2]:text-fg [&_li]:ml-4 [&_li]:list-disc [&_p]:mb-2 [&_ul]:mb-2"
                dangerouslySetInnerHTML={{ __html: project.bodyHtml }}
              />
            ) : project.body ? (
              <pre className="mt-3 whitespace-pre-wrap text-[12px] text-fg-dim">{project.body}</pre>
            ) : (
              <p className="mt-3 text-[12px] text-fg-mute">{ru ? "Описание пока пустое." : "No description yet."}</p>
            )}
            {project.versions && project.versions.length > 0 ? (
              <div className="mt-4 border-t border-line-1 pt-3">
                <h4 className="text-[12px] font-semibold text-fg">{ru ? "Версии" : "Versions"}</h4>
                <ul className="mt-2 space-y-2">
                  {project.versions.slice(0, 5).map((v) => (
                    <li key={v.id || v.version} className="rounded-lg border border-line-1 bg-bg-1/60 px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[12px] font-medium text-fg">v{v.version}</span>
                        <span className="text-[10px] text-fg-mute">{v.downloads} dl</span>
                      </div>
                      {v.changelog ? <MarkdownContent className="mt-1 text-[11px] text-fg-dim">{v.changelog}</MarkdownContent> : null}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </section>
          <aside className="space-y-3">
            <div className="rounded-[14px] border border-line-1 bg-bg-2/70 p-3">
              <h4 className="text-[11px] font-semibold uppercase tracking-wide text-fg-mute">
                {ru ? "Совместимость" : "Compatibility"}
              </h4>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <CompatPill value={project.compatibility} />
              </div>
              <h4 className="mt-3 text-[11px] font-semibold uppercase tracking-wide text-fg-mute">
                {ru ? "Категории" : "Categories"}
              </h4>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {project.categories.length ? (
                  project.categories.map((c) => (
                    <span key={c} className="rounded-full bg-bg-3 px-2 py-0.5 text-[10px] text-fg-dim">
                      {c}
                    </span>
                  ))
                ) : (
                  <span className="text-[11px] text-fg-mute">—</span>
                )}
              </div>
            </div>
            <div className="rounded-[14px] border border-line-1 bg-bg-2/70 p-3">
              <h4 className="text-[11px] font-semibold uppercase tracking-wide text-fg-mute">
                {ru ? "О проекте" : "About"}
              </h4>
              <dl className="mt-2 space-y-1.5 text-[11px]">
                <div className="flex justify-between gap-2">
                  <dt className="text-fg-mute">{ru ? "Автор" : "Author"}</dt>
                  <dd className="text-fg">@{project.author || "—"}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-fg-mute">{ru ? "Лицензия" : "License"}</dt>
                  <dd className="text-fg">{project.license || "—"}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-fg-mute">{ru ? "Обновлено" : "Updated"}</dt>
                  <dd className="text-fg">{formatUpdated(project.updatedAt, locale)}</dd>
                </div>
              </dl>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}

export function MarketplacePage({
  active,
  openSlug,
  autoInstall = false,
  openVersionId = null,
  onSlugHandled,
}: {
  active: boolean;
  openSlug?: string | null;
  autoInstall?: boolean;
  openVersionId?: string | null;
  onSlugHandled?: () => void;
}) {
  const bridge = useBridge();
  const state = useAppState();
  const { locale } = useLocale();
  const ru = locale === "ru";
  const queueApi = useMarketplaceQueue();

  const [q, setQ] = useState("");
  const [qDebounced, setQDebounced] = useState("");
  const [compat, setCompat] = useState<CompatFilter>("");
  const [category, setCategory] = useState("");
  const [sort, setSort] = useState<SortKey>("relevance");
  const [page, setPage] = useState(1);
  const [projects, setProjects] = useState<MarketplaceCard[]>([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);
  const [categories, setCategories] = useState<string[]>([...CATEGORIES]);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [pendingRemoval, setPendingRemoval] = useState<{ slug: string; title: string } | null>(null);
  const [detailSlug, setDetailSlug] = useState<string | null>(null);
  const [detail, setDetail] = useState<MarketplaceProject | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const loadSeq = useRef(0);

  useEffect(() => {
    const t = window.setTimeout(() => setQDebounced(q.trim()), 280);
    return () => window.clearTimeout(t);
  }, [q]);

  const loadList = useCallback(
    async (opts?: { append?: boolean; page?: number; refresh?: boolean }) => {
      const nextPage = opts?.page ?? 1;
      const seq = ++loadSeq.current;
      if (opts?.append) setLoadingMore(true);
      else setLoading(true);
      setError("");
      try {
        const result = await bridge.call("marketplace.list", {
          q: qDebounced,
          compatibility: compat,
          category,
          sort,
          page: nextPage,
          limit: PAGE_LIMIT,
          refresh: Boolean(opts?.refresh),
        });
        if (loadSeq.current !== seq) return;
        const list = result?.projects ?? [];
        setProjects((prev) => (opts?.append ? [...prev, ...list] : list));
        setTotal(result?.total ?? list.length);
        setPages(result?.pages ?? 1);
        setPage(result?.page ?? nextPage);
        if (Array.isArray(result?.categories) && result.categories.length) {
          setCategories(result.categories.map(String));
        }
      } catch (err) {
        if (loadSeq.current !== seq) return;
        setError(err instanceof Error ? err.message : String(err));
        if (!opts?.append) setProjects([]);
      } finally {
        if (loadSeq.current === seq) {
          setLoading(false);
          setLoadingMore(false);
        }
      }
    },
    [bridge, qDebounced, compat, category, sort],
  );

  useEffect(() => {
    if (!active || detailSlug) return;
    void loadList({ page: 1, refresh: true });
  }, [active, loadList, detailSlug]);

  useEffect(() => {
    if (detailSlug || loading || loadingMore || page >= pages) return;
    const root = scrollRef.current;
    const sentinel = sentinelRef.current;
    if (!root || !sentinel || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          void loadList({ append: true, page: page + 1 });
        }
      },
      { root, rootMargin: "180px 0px", threshold: 0.01 },
    );
    io.observe(sentinel);
    return () => io.disconnect();
  }, [detailSlug, loading, loadingMore, page, pages, loadList, projects.length]);

  const openProject = useCallback(
    async (slug: string) => {
      setDetailSlug(slug);
      setDetail(null);
      setDetailLoading(true);
      setError("");
      try {
        const result = await bridge.call("marketplace.get", { slug });
        setDetail(result.project);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setDetailSlug(null);
      } finally {
        setDetailLoading(false);
      }
    },
    [bridge],
  );

  const enqueueDownload = queueApi.enqueue;
  const onSlugHandledRef = useRef(onSlugHandled);
  onSlugHandledRef.current = onSlugHandled;

  useEffect(() => {
    if (!openSlug) return;
    let cancelled = false;
    setDetailSlug(openSlug);
    setDetail(null);
    setDetailLoading(true);
    setError("");
    void (async () => {
      try {
        const result = await bridge.call("marketplace.get", { slug: openSlug });
        if (cancelled) return;
        setDetail(result.project);
        if (autoInstall && result.project) {
          const project = result.project;
          const versionRaw = String(openVersionId || "").trim();
          const versionId = versionRaw && /^\d+$/.test(versionRaw)
            ? Number(versionRaw)
            : project.versions?.[0]?.id ?? null;
          void enqueueDownload({
            slug: project.slug,
            title: project.title,
            compatibility: project.compatibility,
            versionId,
            author: project.author,
            summary: project.summary,
            iconUrl: project.iconUrl,
            projectUrl: project.projectUrl,
          });
        }
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        setDetailSlug(null);
        setDetail(null);
      } finally {
        if (!cancelled) {
          setDetailLoading(false);
          onSlugHandledRef.current?.();
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [openSlug, autoInstall, openVersionId, bridge, enqueueDownload]);

  const installedSlugs = useMemo(() => {
    const slugs = new Set<string>(queueApi.recentlyInstalled);
    for (const mod of [...(state?.mods || []), ...(state?.mods2 || [])]) {
      const slug = String(mod.marketplaceSlug || "").trim();
      if (slug) slugs.add(slug);
    }
    return slugs;
  }, [state?.mods, state?.mods2, queueApi.recentlyInstalled]);
  const installedSizeBySlug = useMemo(() => {
    const sizes = new Map<string, number>();
    for (const mod of [...(state?.mods || []), ...(state?.mods2 || [])]) {
      const slug = String(mod.marketplaceSlug || "").trim();
      if (slug && mod.diskSize) sizes.set(slug, mod.diskSize);
    }
    return sizes;
  }, [state?.mods, state?.mods2]);

  const removeInstalled = useCallback(
    (slug: string, title: string) => {
      setPendingRemoval({ slug, title });
    },
    [],
  );

  const confirmRemoval = useCallback(
    async () => {
      const target = pendingRemoval;
      if (!target) return;
      setPendingRemoval(null);
      const previousMods = state?.mods || [];
      const previousMods2 = state?.mods2 || [];
      applyMarketplaceMods(
        previousMods.filter((mod) => mod.marketplaceSlug !== target.slug),
        previousMods2.filter((mod) => mod.marketplaceSlug !== target.slug),
      );
      queueApi.markUninstalled(target.slug);
      try {
        const result = await bridge.call("marketplace.remove", { slug: target.slug });
        applyMarketplaceMods(result.mods || [], result.mods2 || []);
      } catch (err) {
        applyMarketplaceMods(previousMods, previousMods2);
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [bridge, pendingRemoval, queueApi, state?.mods, state?.mods2],
  );

  const compatOptions = useMemo(
    () => [
      { value: "" as CompatFilter, label: ru ? "Все" : "All" },
      { value: "zapret" as CompatFilter, label: "Zapret" },
      { value: "zapret2" as CompatFilter, label: "Zapret 2" },
    ],
    [ru],
  );

  const closeDetail = () => {
    setDetailSlug(null);
    setDetail(null);
    setDetailLoading(false);
  };

  return (
    <div className="relative flex h-full flex-col">
      <AnimatePresence mode="wait" initial={false}>
        {detailSlug ? (
          <motion.div
            key={`detail-${detailSlug}`}
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -10 }}
            transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
            className="absolute inset-0"
          >
            {detailLoading || !detail ? (
              <DetailSkeleton onBack={closeDetail} locale={locale} />
            ) : (
              <DetailView
                project={detail}
                locale={locale}
                queueItem={queueApi.bySlug.get(detail.slug)}
                installed={installedSlugs.has(detail.slug)}
                installedSize={installedSizeBySlug.get(detail.slug)}
                onBack={closeDetail}
                onDownload={() =>
                  void queueApi.enqueue({
                    slug: detail.slug,
                    title: detail.title,
                    compatibility: detail.compatibility,
                    versionId: detail.versions?.[0]?.id ?? null,
                    author: detail.author,
                    summary: detail.summary,
                    iconUrl: detail.iconUrl,
                    projectUrl: detail.projectUrl,
                  })
                }
                onRemove={() => void removeInstalled(detail.slug, detail.title)}
                onCancel={() => {
                  const item = queueApi.bySlug.get(detail.slug);
                  void queueApi.cancel(detail.slug, item?.jobId);
                }}
                onPause={() => {
                  const item = queueApi.bySlug.get(detail.slug);
                  void queueApi.pause(detail.slug, item?.jobId);
                }}
                onResume={() => {
                  const item = queueApi.bySlug.get(detail.slug);
                  void queueApi.resume(detail.slug, item?.jobId);
                }}
                onOpenSite={() => {
                  if (detail.projectUrl) void bridge.call("marketplace.open-url", { url: detail.projectUrl });
                }}
              />
            )}
          </motion.div>
        ) : (
          <motion.div
            key="catalog"
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 12 }}
            transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
            className="absolute inset-0 flex flex-col"
          >
            <ScrollGlassHeader scrollerRef={scrollRef} contentKey="marketplace-catalog" className="absolute inset-x-0 top-0 z-30 border-b border-line-1 px-6 pb-3 pt-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-[15px] font-semibold text-fg">Marketplace</h2>
                  <p className="mt-0.5 text-[11px] text-fg-dim">
                    {ru ? "Каталог модификаций для Zapret и Zapret 2" : "Mods catalog for Zapret and Zapret 2"}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void bridge.call("marketplace.open-url", { url: "https://goshkow.com/zapret-hub/marketplace" })}
                    className="flex h-8 items-center gap-1.5 rounded-lg border border-line-1 bg-bg-1 px-2.5 text-[11px] text-fg-dim transition-colors hover:border-line-2 hover:bg-bg-3 hover:text-fg"
                  >
                    <svg viewBox="0 0 16 16" aria-hidden="true" className="h-3.5 w-3.5 fill-none stroke-current" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M6 3H3.8A1.8 1.8 0 0 0 2 4.8v7.4A1.8 1.8 0 0 0 3.8 14h7.4a1.8 1.8 0 0 0 1.8-1.8V10" />
                      <path d="M9 2h5v5M14 2 7.2 8.8" />
                    </svg>
                    {ru ? "Открыть сайт" : "Open website"}
                  </button>
                  <input
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                    placeholder={ru ? "Поиск…" : "Search…"}
                    className="h-8 w-48 rounded-lg border border-line-1 bg-bg-1 px-2.5 text-[11px] text-fg outline-none placeholder:text-fg-mute focus:border-line-2"
                  />
                </div>
              </div>
              <div className="relative z-20 mt-3 flex flex-nowrap items-center gap-2">
                <FilterSelect
                  value={compat}
                  onChange={(value) => setCompat(value as CompatFilter)}
                  ariaLabel={ru ? "Совместимость" : "Compatibility"}
                  options={compatOptions.map((opt) => ({
                    value: opt.value,
                    label: opt.value
                      ? `${ru ? "Совместимость" : "Compatibility"}: ${opt.label}`
                      : ru
                        ? "Совместимость: все"
                        : "Compatibility: all",
                  }))}
                />
                <div className="flex min-w-0 flex-1 flex-nowrap items-center gap-1 overflow-x-auto overflow-y-visible">
                  <button
                    type="button"
                    onClick={() => setCategory("")}
                    className={`shrink-0 rounded-full px-2.5 py-1 text-[10px] transition ${
                      !category ? "bg-[rgb(var(--page-accent-rgb))] text-white" : "bg-bg-3 text-fg-dim hover:text-fg"
                    }`}
                  >
                    {ru ? "Все теги" : "All tags"}
                  </button>
                  {categories.map((c) => (
                    <button
                      key={c}
                      type="button"
                      onClick={() => setCategory(category === c ? "" : c)}
                      className={`shrink-0 rounded-full px-2.5 py-1 text-[10px] transition ${
                        category === c ? "bg-[rgb(var(--page-accent-rgb))] text-white" : "bg-bg-3 text-fg-dim hover:text-fg"
                      }`}
                    >
                      {c}
                    </button>
                  ))}
                </div>
                <div className="ml-auto flex shrink-0 items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => void loadList({ page: 1, refresh: true })}
                    disabled={loading}
                    aria-label={ru ? "Обновить каталог" : "Refresh catalog"}
                    title={ru ? "Обновить каталог" : "Refresh catalog"}
                    className="grid h-7 w-7 place-items-center rounded-full border border-line-1 bg-bg-1 text-fg-dim transition hover:border-line-2 hover:bg-bg-3 hover:text-fg disabled:opacity-50"
                  >
                    <svg
                      viewBox="0 0 12 12"
                      aria-hidden="true"
                      className={`h-4 w-4 fill-none stroke-current ${loading ? "animate-spin" : ""}`}
                    >
                      <path
                        d="M10 4c-.8-1.1-2-2.5-4.1-2.5-2.5 0-4.4 2-4.4 4.5s2 4.5 4.4 4.5c1.3 0 2.5-.6 3.3-1.5m1.3-7.5V4c0 .3-.2.5-.5.5H7.5"
                        strokeLinecap="round"
                      />
                    </svg>
                  </button>
                  <FilterSelect
                    value={sort}
                    onChange={(value) => setSort(value as SortKey)}
                    ariaLabel={ru ? "Сортировка" : "Sort"}
                    align="right"
                    options={[
                      { value: "relevance", label: ru ? "Сортировка: по релевантности" : "Sort: relevance" },
                      { value: "popular", label: ru ? "Сортировка: популярные" : "Sort: popular" },
                      { value: "downloads", label: ru ? "Сортировка: скачивания" : "Sort: downloads" },
                      { value: "updated", label: ru ? "Сортировка: обновлённые" : "Sort: updated" },
                      { value: "newest", label: ru ? "Сортировка: новые" : "Sort: newest" },
                    ]}
                  />
                </div>
              </div>
            </ScrollGlassHeader>

            <div ref={scrollRef} className="scroll-area glass-page-scroll h-full overflow-auto" style={{ "--glass-header-height": "132px" } as React.CSSProperties}>
              <div className="scroll-content px-6 pb-3 pt-[132px]">
              {error ? (
                <div className="mb-3 rounded-lg border border-[color-mix(in_srgb,var(--err)_40%,transparent)] bg-[color-mix(in_srgb,var(--err)_8%,transparent)] px-3 py-2 text-[11px] text-[var(--err)]">
                  {error}
                </div>
              ) : null}
              {loading && projects.length === 0 ? (
                <div className="flex flex-col gap-2.5">
                  {Array.from({ length: PAGE_LIMIT }).map((_, i) => (
                    <CatalogSkeleton key={`sk-${i}`} />
                  ))}
                </div>
              ) : null}
              {!loading && projects.length === 0 && !error ? (
                <div className="mb-2 grid h-24 place-items-center text-center text-[12px] text-fg-mute">
                  {ru ? "Пока нет опубликованных модификаций." : "No published mods yet."}
                </div>
              ) : null}
              <div className="flex flex-col gap-2.5">
                {projects.map((item) => (
                  <CatalogCard
                    key={item.slug}
                    item={item}
                    locale={locale}
                    queueItem={queueApi.bySlug.get(item.slug)}
                    installed={installedSlugs.has(item.slug)}
                    installedSize={installedSizeBySlug.get(item.slug)}
                    onOpen={() => void openProject(item.slug)}
                    onDownload={() =>
                      void queueApi.enqueue({
                        slug: item.slug,
                        title: item.title,
                        compatibility: item.compatibility,
                        author: item.author,
                        summary: item.summary,
                        iconUrl: item.iconUrl,
                        projectUrl: item.projectUrl,
                      })
                    }
                    onRemove={() => void removeInstalled(item.slug, item.title)}
                    onCancel={() => {
                      const qItem = queueApi.bySlug.get(item.slug);
                      void queueApi.cancel(item.slug, qItem?.jobId);
                    }}
                    onPause={() => {
                      const qItem = queueApi.bySlug.get(item.slug);
                      void queueApi.pause(item.slug, qItem?.jobId);
                    }}
                    onResume={() => {
                      const qItem = queueApi.bySlug.get(item.slug);
                      void queueApi.resume(item.slug, qItem?.jobId);
                    }}
                  />
                ))}
                {loadingMore
                  ? Array.from({ length: 2 }).map((_, i) => <CatalogSkeleton key={`more-${i}`} />)
                  : null}
              </div>
              {page < pages ? <div ref={sentinelRef} className="h-8" aria-hidden /> : null}
              {!loading && !loadingMore && page < pages && total > projects.length ? (
                <div className="mt-2 text-center text-[10px] text-fg-mute">
                  {ru ? `Показано ${projects.length} из ${total}` : `Shown ${projects.length} of ${total}`}
                </div>
              ) : null}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      <ConfirmModal
        open={Boolean(pendingRemoval)}
        title={ru ? "Удаление модификации" : "Remove modification"}
        message={
          pendingRemoval
            ? ru
              ? `Вы действительно хотите удалить «${pendingRemoval.title}»?`
              : `Do you really want to remove “${pendingRemoval.title}”?`
            : ""
        }
        confirmLabel={ru ? "Удалить" : "Remove"}
        cancelLabel={ru ? "Отмена" : "Cancel"}
        onConfirm={() => void confirmRemoval()}
        onCancel={() => setPendingRemoval(null)}
      />
    </div>
  );
}
