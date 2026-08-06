import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { getBridge } from "@/bridge";
import { useLocale } from "@/hooks/useLocale";
import { MarkdownContent } from "@/components/ui/MarkdownContent";
import { useMarketplaceQueue } from "@/hooks/useMarketplaceQueue";

export type ModUpdateItem = {
  slug: string;
  title: string;
  author?: string;
  summary?: string;
  iconUrl?: string;
  projectUrl?: string;
  compatibility?: "zapret" | "zapret2" | string;
  currentVersion?: string;
  latestVersion: string;
  changelog?: string;
  versionId?: number | null;
  modId?: string;
};

function Cover({ url, title }: { url?: string; title: string }) {
  const [failed, setFailed] = useState(false);
  const show = Boolean(url) && !failed;
  return (
    <div className="relative h-12 w-12 shrink-0 overflow-hidden rounded-[11px] border border-line-1 bg-bg-1">
      {show ? (
        <img
          src={url}
          alt=""
          className="absolute inset-0 h-full w-full object-cover object-center"
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
        />
      ) : (
        <div className="grid h-full w-full place-items-center text-[13px] font-semibold text-fg-mute">
          {(title || "?").slice(0, 1).toUpperCase()}
        </div>
      )}
    </div>
  );
}

export function ModUpdatesModal({
  updates,
  onClose,
}: {
  updates: ModUpdateItem[] | null;
  onClose: () => void;
}) {
  const { locale } = useLocale();
  const queueApi = useMarketplaceQueue();
  const ru = locale === "ru";
  const [items, setItems] = useState<ModUpdateItem[]>(updates || []);
  const [busySlug, setBusySlug] = useState<string | null>(null);
  const [busyAll, setBusyAll] = useState(false);

  useEffect(() => {
    setItems(updates || []);
  }, [updates]);

  if (!updates || updates.length === 0) return null;

  const dismissAndClose = async () => {
    try {
      await getBridge().call("marketplace.dismiss-updates", {
        updates: items.map((item) => ({ slug: item.slug, latestVersion: item.latestVersion })),
      });
    } catch {
      /* ignore */
    }
    onClose();
  };

  const updateOne = async (item: ModUpdateItem) => {
    if (busySlug || busyAll) return;
    setBusySlug(item.slug);
    try {
      await queueApi.enqueue({
        slug: item.slug,
        title: item.title,
        compatibility: item.compatibility || "",
        author: item.author,
        summary: item.summary,
        iconUrl: item.iconUrl,
        projectUrl: item.projectUrl,
        versionId: item.versionId ?? null,
        marketplaceVersion: item.latestVersion || "",
        allowUpdate: true,
      });
      setItems((prev) => prev.filter((row) => row.slug !== item.slug));
    } catch {
      /* toast comes from backend */
    } finally {
      setBusySlug(null);
    }
  };

  const updateAll = async () => {
    if (busyAll || busySlug) return;
    setBusyAll(true);
    try {
      for (const item of items) {
        await queueApi.enqueue({
          slug: item.slug,
          title: item.title,
          compatibility: item.compatibility || "",
          author: item.author,
          summary: item.summary,
          iconUrl: item.iconUrl,
          projectUrl: item.projectUrl,
          versionId: item.versionId ?? null,
          marketplaceVersion: item.latestVersion || "",
          allowUpdate: true,
        });
      }
      onClose();
    } catch {
      setBusyAll(false);
    }
  };

  const visible = items.length ? items : updates;

  return (
    <AnimatePresence>
      <motion.div
        key="mod-updates-modal"
        className="absolute inset-0 z-[90] grid place-items-center bg-black/46"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={() => {
          if (!busyAll && !busySlug) void dismissAndClose();
        }}
      >
        <motion.div
          initial={{ opacity: 0, y: 8, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 6, scale: 0.98 }}
          transition={{ duration: 0.18 }}
          onClick={(event) => event.stopPropagation()}
          className="flex max-h-[82%] w-[560px] max-w-[94%] flex-col overflow-hidden rounded-[16px] border border-line-2 bg-bg-2 shadow-[0_18px_42px_-20px_rgba(0,0,0,0.75)]"
        >
          <header className="flex h-12 items-center justify-between border-b border-line-1 px-4">
            <div className="text-[13px] font-semibold text-fg">
              {ru ? "Обновления модификаций" : "Mod updates"}
            </div>
            <button
              type="button"
              disabled={Boolean(busyAll || busySlug)}
              onClick={() => void dismissAndClose()}
              className="grid h-7 w-7 place-items-center rounded-[8px] text-fg-dim hover:bg-bg-3 hover:text-fg disabled:opacity-40"
            >
              ×
            </button>
          </header>
          <div className="scroll-area min-h-0 flex-1 space-y-2 overflow-auto px-4 py-3">
            <p className="text-[11px] text-fg-dim">
              {ru
                ? "Обновление удаляет старую версию и сразу скачивает новую. Можно обновить по одной или все сразу."
                : "An update removes the old version and immediately re-downloads the new one. Update them one by one or all at once."}
            </p>
            {visible.map((item) => (
              <div
                key={item.slug}
                className="flex items-start gap-3 rounded-[12px] border border-line-1 bg-bg-1/70 px-3 py-2.5"
              >
                <Cover url={item.iconUrl} title={item.title} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <div className="truncate text-[13px] font-semibold text-fg">{item.title}</div>
                    {item.author ? <div className="text-[11px] text-fg-mute">@{item.author.replace(/^@/, "")}</div> : null}
                  </div>
                  <div className="mt-0.5 text-[11px] text-fg-dim">
                    v{item.currentVersion || "?"} → v{item.latestVersion}
                  </div>
                  {item.summary ? <div className="mt-1 line-clamp-2 text-[11px] text-fg-mute">{item.summary}</div> : null}
                  {item.changelog ? <MarkdownContent className="mt-1 line-clamp-3 text-[10px] text-fg-mute">{item.changelog}</MarkdownContent> : null}
                </div>
                <button
                  type="button"
                  disabled={Boolean(busyAll || busySlug)}
                  onClick={() => void updateOne(item)}
                  className="shrink-0 rounded-lg bg-[rgb(var(--page-accent-rgb))] px-2.5 py-1.5 text-[11px] font-medium text-white disabled:opacity-45"
                >
                  {busySlug === item.slug ? (ru ? "…" : "…") : ru ? "Обновить" : "Update"}
                </button>
              </div>
            ))}
            {items.length === 0 ? (
              <div className="grid h-20 place-items-center text-[12px] text-fg-mute">
                {ru ? "Обновления поставлены в очередь загрузки." : "Updates were queued for download."}
              </div>
            ) : null}
          </div>
          <footer className="flex items-center justify-end gap-2 border-t border-line-1 px-4 py-3">
            <button
              type="button"
              disabled={Boolean(busyAll || busySlug)}
              onClick={() => void dismissAndClose()}
              className="rounded-lg border border-line-1 bg-bg-1 px-3 py-1.5 text-[11px] text-fg-dim hover:bg-bg-3 hover:text-fg disabled:opacity-40"
            >
              {ru ? "Закрыть" : "Close"}
            </button>
            <button
              type="button"
              disabled={Boolean(busyAll || busySlug) || items.length === 0}
              onClick={() => void updateAll()}
              className="rounded-lg bg-[rgb(var(--page-accent-rgb))] px-3 py-1.5 text-[11px] font-medium text-white disabled:opacity-40"
            >
              {busyAll ? (ru ? "Очередь…" : "Queuing…") : ru ? "Обновить все" : "Update all"}
            </button>
          </footer>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
