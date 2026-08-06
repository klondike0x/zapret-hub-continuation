import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { restrictToVerticalAxis } from "@dnd-kit/modifiers";
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { getBridge } from "@/bridge";
import { applyMarketplaceMods, useAppState, useBridge, patchOptimistic } from "@/hooks/useBridgeState";
import { useLocale } from "@/hooks/useLocale";
import { useMarketplaceQueue } from "@/hooks/useMarketplaceQueue";
import { Segmented } from "@/components/ui/Segmented";
import { IosToggle } from "@/components/ui/IosToggle";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { ScrollGlassHeader } from "@/components/ui/ScrollGlassHeader";
import { useToast } from "@/components/shell/ToastHost";
import type { MarketplaceCompatibility, Mod } from "@/bridge/types";

type InstalledView = "zapret" | "zapret2";

function formatFileSize(bytes?: number) {
  const value = Math.max(0, Number(bytes || 0));
  if (!value) return "";
  if (value < 1024) return `${Math.round(value)} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(value < 10 * 1024 ? 1 : 0)} KB`;
  return `${(value / (1024 * 1024)).toFixed(value < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

function ProjectCover({ url, title }: { url?: string; title: string }) {
  const [failed, setFailed] = useState(false);
  return (
    <div className="relative h-14 w-14 shrink-0 overflow-hidden rounded-[10px] border border-line-1 bg-bg-2">
      {url && !failed ? (
        <img
          src={url}
          alt=""
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          className="absolute inset-0 h-full w-full object-cover object-center"
          onError={() => setFailed(true)}
        />
      ) : (
        <div className="grid h-full w-full place-items-center text-[15px] font-semibold text-fg-mute">
          {(title.trim()[0] || "?").toUpperCase()}
        </div>
      )}
    </div>
  );
}

function CompatPill({ value }: { value: MarketplaceCompatibility }) {
  const label = value === "zapret2" ? "Zapret 2" : "Zapret";
  return (
    <span className="rounded-full bg-[color-mix(in_srgb,#9b69e8_28%,transparent)] px-2 py-0.5 text-[10px] font-medium text-[#c4b5fd]">
      {label}
    </span>
  );
}

function ModCardBody({
  mod,
  locale,
  compatibility,
  downloading,
  onToggle,
  onUpdate,
  onOpenSite,
  onDelete,
  dragHandle,
}: {
  mod: Mod;
  locale: string;
  compatibility: MarketplaceCompatibility;
  downloading: boolean;
  onToggle?: (on: boolean) => void;
  onUpdate?: () => void;
  onOpenSite?: () => void;
  onDelete?: () => void;
  dragHandle?: ReactNode;
}) {
  const ru = locale === "ru";
  const canOpenSite = Boolean(mod.sourceUrl);
  const canUpdate = Boolean(mod.marketplaceSlug && mod.updateAvailable);
  return (
    <>
      {dragHandle}
      <ProjectCover url={mod.iconUrl} title={mod.name} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <h3 className="truncate text-[13px] font-semibold text-fg">{mod.name}</h3>
          {mod.author ? (
            <span className="truncate text-[11px] text-fg-mute">
              {ru ? "от" : "by"} @{mod.author.replace(/^@/, "")}
            </span>
          ) : null}
        </div>
        <p className="mt-0.5 line-clamp-2 text-[11px] text-fg-dim">{mod.description || "—"}</p>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          <CompatPill value={compatibility} />
          {mod.version ? <span className="rounded-full bg-bg-3 px-2 py-0.5 text-[10px] text-fg-dim">v{mod.version}</span> : null}
          {canUpdate ? (
            <span className="rounded-full bg-[color-mix(in_srgb,rgb(var(--page-accent-rgb))_22%,transparent)] px-2 py-0.5 text-[10px] text-[rgb(var(--page-accent-rgb))]">
              {ru ? `есть v${mod.latestVersion}` : `v${mod.latestVersion} available`}
            </span>
          ) : null}
        </div>
      </div>
      <div className="flex shrink-0 flex-col items-end justify-between gap-2 pl-1">
        <div className="flex items-center gap-2">
          {mod.diskSize ? <span className="text-[10px] text-fg-mute">{formatFileSize(mod.diskSize)}</span> : null}
          <IosToggle on={mod.enabled} onChange={onToggle ?? (() => undefined)} />
        </div>
        <div className="flex flex-wrap items-center justify-end gap-1">
          {canUpdate ? (
            <button
              type="button"
              disabled={downloading || !onUpdate}
              onClick={onUpdate}
              className="rounded-md bg-[rgb(var(--page-accent-rgb))] px-2 py-0.5 text-[10px] font-medium text-white disabled:opacity-50"
            >
              {downloading ? "…" : ru ? "Обновить" : "Update"}
            </button>
          ) : null}
          {canOpenSite ? (
            <button
              type="button"
              onClick={onOpenSite}
              className="rounded-lg border border-line-1 bg-bg-3/70 px-2.5 py-1 text-[10px] text-fg-dim transition-colors hover:border-line-2 hover:bg-bg-3 hover:text-fg"
            >
              {ru ? "На сайте" : "Website"}
            </button>
          ) : null}
          <button
            type="button"
            onClick={onDelete}
            className="rounded-lg border border-line-1 bg-bg-3/70 px-2.5 py-1 text-[10px] text-fg-dim transition-colors hover:border-red-400/50 hover:bg-red-500/10 hover:text-red-300"
          >
            {ru ? "Удалить" : "Remove"}
          </button>
        </div>
      </div>
    </>
  );
}

function SortableLocalCard({
  mod,
  locale,
  compatibility,
  downloading,
  onToggle,
  onUpdate,
  onOpenSite,
  onDelete,
}: {
  mod: Mod;
  locale: string;
  compatibility: MarketplaceCompatibility;
  downloading: boolean;
  onToggle: (on: boolean) => void;
  onUpdate: () => void;
  onOpenSite: () => void;
  onDelete: () => void;
}) {
  const ru = locale === "ru";
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: mod.id,
    // Avoid a second layout animation after drop — siblings already shifted live.
    animateLayoutChanges: () => false,
  });

  const style: CSSProperties = {
    // Translate only — CSS.Transform also applies scale and makes cards shrink/grow.
    transform: CSS.Translate.toString(transform),
    transition: isDragging ? undefined : transition,
    opacity: isDragging ? 0 : 1,
    pointerEvents: isDragging ? "none" : undefined,
  };

  return (
    <article
      ref={setNodeRef}
      style={style}
      className="flex items-stretch gap-3 rounded-[14px] border border-line-1 bg-[color-mix(in_srgb,var(--bg-2)_88%,transparent)] px-3.5 py-3"
    >
      <ModCardBody
        mod={mod}
        locale={locale}
        compatibility={compatibility}
        downloading={downloading}
        onToggle={onToggle}
        onUpdate={onUpdate}
        onOpenSite={onOpenSite}
        onDelete={onDelete}
        dragHandle={(
          <button
            type="button"
            className="mt-1 grid h-8 w-6 shrink-0 cursor-grab touch-none place-items-center text-fg-mute active:cursor-grabbing"
            aria-label={ru ? "Перетащить" : "Drag"}
            {...attributes}
            {...listeners}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
              <circle cx="8" cy="6" r="1.5" />
              <circle cx="8" cy="12" r="1.5" />
              <circle cx="8" cy="18" r="1.5" />
              <circle cx="16" cy="6" r="1.5" />
              <circle cx="16" cy="12" r="1.5" />
              <circle cx="16" cy="18" r="1.5" />
            </svg>
          </button>
        )}
      />
    </article>
  );
}

function OverlayLocalCard({
  mod,
  locale,
  compatibility,
  downloading,
}: {
  mod: Mod;
  locale: string;
  compatibility: MarketplaceCompatibility;
  downloading: boolean;
}) {
  return (
    <article className="flex cursor-grabbing items-stretch gap-3 rounded-[14px] border border-line-2 bg-[color-mix(in_srgb,var(--bg-2)_96%,transparent)] px-3.5 py-3 shadow-[0_12px_28px_rgba(0,0,0,0.28)]">
      <ModCardBody
        mod={mod}
        locale={locale}
        compatibility={compatibility}
        downloading={downloading}
        dragHandle={(
          <div className="mt-1 grid h-8 w-6 shrink-0 place-items-center text-fg-mute" aria-hidden>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
              <circle cx="8" cy="6" r="1.5" />
              <circle cx="8" cy="12" r="1.5" />
              <circle cx="8" cy="18" r="1.5" />
              <circle cx="16" cy="6" r="1.5" />
              <circle cx="16" cy="12" r="1.5" />
              <circle cx="16" cy="18" r="1.5" />
            </svg>
          </div>
        )}
      />
    </article>
  );
}

function isMarketplaceMod(mod: Mod) {
  return Boolean(String(mod.marketplaceSlug || "").trim());
}

export function InstalledModsPage({ onOpenMarketplace }: { onOpenMarketplace?: () => void }) {
  const bridge = useBridge();
  const state = useAppState();
  const { locale } = useLocale();
  const toast = useToast();
  const queueApi = useMarketplaceQueue();
  const ru = locale === "ru";
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
  );
  const [view, setView] = useState<InstalledView>("zapret");
  const [queued, setQueued] = useState<Set<string>>(new Set());
  const [pendingDelete, setPendingDelete] = useState<{ id: string; slug: string; name: string; prefix: "mods" | "mods2" } | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const dragWidthRef = useRef<number | null>(null);

  useEffect(() => {
    const off = getBridge().subscribe("marketplace.download-progress", (payload) => {
      const slug = String(payload?.slug || "");
      const status = String(payload?.status || "");
      if (!slug) return;
      setQueued((prev) => {
        const next = new Set(prev);
        if (status === "queued" || status === "starting" || status === "downloading" || status === "installing" || status === "removing") {
          next.add(slug);
        } else {
          next.delete(slug);
        }
        return next;
      });
    });
    return off;
  }, []);

  useEffect(() => {
    void bridge.call("marketplace.check-updates", undefined).catch(() => undefined);
  }, [bridge]);

  useEffect(() => {
    // Legacy Zapret2 installs could retain a file:// cover from a deleted
    // temporary folder. Repairing runs in the backend and never blocks this list.
    void bridge.call("marketplace.repair-covers", undefined).catch(() => undefined);
  }, [bridge]);

  const installedZapret = useMemo(
    () =>
      (state?.mods || []).filter(
        (m) => isMarketplaceMod(m) && m.id.toLowerCase() !== "hub" && m.name.trim().toLowerCase() !== "hub",
      ),
    [state?.mods],
  );
  const installedZapret2 = useMemo(
    () => (state?.mods2 || []).filter((m) => isMarketplaceMod(m)),
    [state?.mods2],
  );

  const list = view === "zapret2" ? installedZapret2 : installedZapret;
  const prefix = view === "zapret2" ? "mods2" : "mods";
  const compatibility: MarketplaceCompatibility = view === "zapret2" ? "zapret2" : "zapret";
  const itemIds = useMemo(() => list.map((m) => m.id), [list]);
  const activeMod = activeId ? list.find((m) => m.id === activeId) ?? null : null;

  const onDragStart = (event: DragStartEvent) => {
    const id = String(event.active.id);
    setActiveId(id);
    const rect = event.active.rect.current.initial;
    dragWidthRef.current = rect?.width ?? null;
  };

  const finishDrag = () => {
    setActiveId(null);
    dragWidthRef.current = null;
  };

  const onDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    finishDrag();
    if (!over || active.id === over.id || !state) return;
    const ids = list.map((m) => m.id);
    const oldIndex = ids.indexOf(String(active.id));
    const newIndex = ids.indexOf(String(over.id));
    if (oldIndex < 0 || newIndex < 0 || oldIndex === newIndex) return;

    const orderedIds = arrayMove(ids, oldIndex, newIndex);
    const byId = new Map(list.map((m) => [m.id, m]));
    const nextList = orderedIds.map((id) => byId.get(id)!).filter(Boolean);

    // Optimistic order first so drop lands in place (no second reshuffle).
    if (prefix === "mods2") {
      applyMarketplaceMods(state.mods || [], nextList);
    } else {
      applyMarketplaceMods(nextList, state.mods2 || []);
    }
    void bridge.call(`${prefix}.reorder`, { orderedIds });
  };

  const enqueue = async (mod: Mod) => {
    if (!mod.marketplaceSlug) return;
    const slug = mod.marketplaceSlug;
    setQueued((prev) => new Set(prev).add(slug));
    const clearQueued = () =>
      setQueued((prev) => {
        const next = new Set(prev);
        next.delete(slug);
        return next;
      });
    try {
      const result = await queueApi.enqueue({
        slug,
        title: mod.name,
        compatibility,
        author: mod.author,
        summary: mod.description,
        iconUrl: mod.iconUrl,
        projectUrl: mod.sourceUrl,
        versionId: mod.versionId ?? null,
        marketplaceVersion: mod.latestVersion || "",
        allowUpdate: Boolean(mod.updateAvailable),
      });
      // No-op / reject: clear spinner immediately. Real jobs clear via download-progress.
      if (!result?.queued || result.alreadyInstalled) {
        clearQueued();
      }
    } catch {
      clearQueued();
    }
  };

  return (
    <div className="relative h-full overflow-hidden">
      <div ref={scrollerRef} className="scroll-area glass-page-scroll h-full overflow-auto" style={{ "--glass-header-height": "86px" } as CSSProperties}>
      <div className="scroll-content px-6 pb-3 pt-[86px]">
        {list.length === 0 ? (
          <div className="grid h-40 place-content-center justify-items-center gap-3 text-center">
            <p className="text-[12px] text-fg-mute">
              {ru ? "Пока нет модификаций…" : "No mods yet…"}
            </p>
            <button
              type="button"
              onClick={() => onOpenMarketplace?.()}
              className="rounded-lg bg-[rgb(var(--page-accent-rgb))] px-3.5 py-1.5 text-[11px] font-medium text-white transition hover:brightness-110"
            >
              {ru ? "Добавить" : "Add"}
            </button>
          </div>
        ) : (
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            modifiers={[restrictToVerticalAxis]}
            onDragStart={onDragStart}
            onDragCancel={finishDrag}
            onDragEnd={onDragEnd}
          >
            <SortableContext items={itemIds} strategy={verticalListSortingStrategy}>
              <div className="flex flex-col gap-2.5">
                {list.map((mod) => (
                  <SortableLocalCard
                    key={mod.id}
                    mod={mod}
                    locale={locale}
                    compatibility={compatibility}
                    downloading={Boolean(mod.marketplaceSlug && queued.has(mod.marketplaceSlug))}
                    onToggle={(on) => {
                      if (prefix === "mods2") {
                        patchOptimistic({ mods2: { [mod.id]: { enabled: on } } });
                      } else {
                        patchOptimistic({ mods: { [mod.id]: { enabled: on } } });
                      }
                      void bridge.call(`${prefix}.toggle`, { id: mod.id, on });
                    }}
                    onUpdate={() => void enqueue(mod)}
                    onOpenSite={() => {
                      if (mod.sourceUrl) void bridge.call("marketplace.open-url", { url: mod.sourceUrl });
                    }}
                    onDelete={() => {
                      setPendingDelete({ id: mod.id, slug: String(mod.marketplaceSlug || ""), name: mod.name, prefix });
                    }}
                  />
                ))}
              </div>
            </SortableContext>
            <DragOverlay dropAnimation={null} adjustScale={false}>
              {activeMod ? (
                <div style={dragWidthRef.current ? { width: dragWidthRef.current } : undefined}>
                  <OverlayLocalCard
                    mod={activeMod}
                    locale={locale}
                    compatibility={compatibility}
                    downloading={Boolean(activeMod.marketplaceSlug && queued.has(activeMod.marketplaceSlug))}
                  />
                </div>
              ) : null}
            </DragOverlay>
          </DndContext>
        )}
      </div>
      </div>
      <ScrollGlassHeader scrollerRef={scrollerRef} contentKey={view} className="absolute inset-x-0 top-0 z-20 border-b border-line-1 px-6 pb-3 pt-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[15px] font-semibold text-fg">{ru ? "Установленные модификации" : "Installed mods"}</h2>
            <p className="mt-0.5 text-[11px] text-fg-dim">
              {ru
                ? "Модификации, установленные из Zapret Marketplace"
                : "Mods installed from Zapret Marketplace"}
            </p>
          </div>
          <Segmented
            value={view}
            onChange={setView}
            size="sm"
            options={[
              { value: "zapret", label: ru ? "Zapret" : "Zapret" },
              { value: "zapret2", label: "Zapret 2" },
            ]}
          />
        </div>
      </ScrollGlassHeader>
      <ConfirmModal
        open={Boolean(pendingDelete)}
        title={ru ? "Удаление модификации" : "Remove modification"}
        message={pendingDelete ? (ru ? `Вы действительно хотите удалить «${pendingDelete.name}»?` : `Do you really want to remove “${pendingDelete.name}”?`) : ""}
        confirmLabel={ru ? "Удалить" : "Remove"}
        cancelLabel={ru ? "Отмена" : "Cancel"}
        onConfirm={() => {
          const target = pendingDelete;
          setPendingDelete(null);
          if (!target || !state) return;
          const previousMods = state.mods || [];
          const previousMods2 = state.mods2 || [];
          const nextMods = target.prefix === "mods" ? previousMods.filter((mod) => mod.id !== target.id) : previousMods;
          const nextMods2 = target.prefix === "mods2" ? previousMods2.filter((mod) => mod.id !== target.id) : previousMods2;
          applyMarketplaceMods(nextMods, nextMods2);
          void bridge.call("marketplace.remove", { slug: target.slug }).then((result) => {
            applyMarketplaceMods(result.mods || [], result.mods2 || []);
          }).catch(() => {
            applyMarketplaceMods(previousMods, previousMods2);
            toast.push({ message: ru ? "Не удалось удалить модификацию" : "Could not remove the modification", kind: "error" });
          });
        }}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}
