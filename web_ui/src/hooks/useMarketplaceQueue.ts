import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { getBridge } from "@/bridge";
import type { MarketplaceQueueItem, MarketplaceQueueStatus } from "@/bridge/types";
import { applyMarketplaceMods, refreshMarketplaceMods } from "@/hooks/useBridgeState";

const EMPTY: MarketplaceQueueStatus = {
  busy: false,
  activeSlug: "",
  overallProgress: 0,
  pending: [],
  items: [],
};

type Store = {
  queue: MarketplaceQueueStatus;
  completedFlash: boolean;
  recentlyInstalled: Set<string>;
  storageWarning: boolean;
};

let store: Store = { queue: EMPTY, completedFlash: false, recentlyInstalled: new Set(), storageWarning: false };
const listeners = new Set<() => void>();
let wired = false;
let flashTimer: number | undefined;
const terminalTimers = new Map<string, number>();
let observedInstallRevision = 0;

function isWorking(item: MarketplaceQueueItem) {
  return ["queued", "downloading", "paused", "installing", "starting"].includes(String(item.status || ""));
}

function emitStore() {
  for (const listener of listeners) listener();
}

function setStore(next: Partial<Store>) {
  store = { ...store, ...next };
  emitStore();
}

function clearRecentlyInstalled(slug: string) {
  if (!store.recentlyInstalled.has(slug)) return;
  const recentlyInstalled = new Set(store.recentlyInstalled);
  recentlyInstalled.delete(slug);
  setStore({ recentlyInstalled });
}

function normalize(status: Partial<MarketplaceQueueStatus> | null | undefined): MarketplaceQueueStatus {
  const items = Array.isArray(status?.items) ? status!.items : [];
  return {
    busy: Boolean(status?.busy),
    activeSlug: String(status?.activeSlug || ""),
    overallProgress: Number(status?.overallProgress || 0),
    pending: Array.isArray(status?.pending) ? status!.pending.map(String) : items.map((i) => i.slug),
    items,
    installRevision: Number(status?.installRevision || 0),
    lastCompleted: status?.lastCompleted,
  };
}

function reconcileCompletedInstall(next: MarketplaceQueueStatus) {
  const completed = next.lastCompleted;
  const revision = Number(completed?.revision || next.installRevision || 0);
  const slug = String(completed?.slug || "");
  if (!slug || revision <= observedInstallRevision) return;
  observedInstallRevision = revision;
  const recentlyInstalled = new Set(store.recentlyInstalled);
  recentlyInstalled.add(slug);
  setStore({ recentlyInstalled });
  void refreshMarketplaceMods(slug)
    .then((confirmed) => {
      if (confirmed) clearRecentlyInstalled(slug);
    })
    .catch(() => undefined);
}

function applyQueue(next: MarketplaceQueueStatus) {
  reconcileCompletedInstall(next);
  // Keep the higher progress if a poll races with a fresher download-progress event.
  const prevBySlug = new Map(store.queue.items.map((item) => [item.slug, item]));
  const mergedItems = next.items.map((item) => {
    const prev = prevBySlug.get(item.slug);
    if (!prev) return item;
    return {
      ...item,
      progress: Math.max(Number(item.progress || 0), Number(prev.progress || 0)),
      bytesDone: Math.max(Number(item.bytesDone || 0), Number(prev.bytesDone || 0)),
      bytesTotal: Math.max(Number(item.bytesTotal || 0), Number(prev.bytesTotal || 0)),
    };
  });
  next = { ...next, items: mergedItems };
  const active = mergedItems.find((item) => item.status === "downloading" || item.status === "installing" || item.status === "starting");
  if (active) {
    const byteRatio = active.bytesTotal && active.bytesTotal > 0
      ? Number(active.bytesDone || 0) / active.bytesTotal
      : 0;
    let overall = Math.max(Number(next.overallProgress || 0), Number(active.progress || 0), byteRatio);
    if (active.status === "installing") overall = Math.max(overall, 0.85);
    next = { ...next, overallProgress: Math.max(0, Math.min(1, overall)) };
  }
  const hadActive = store.queue.busy || store.queue.items.some(isWorking);
  const idle = next.items.length === 0 && !next.busy;
  if (hadActive && idle) {
    setStore({ queue: next, completedFlash: true });
    window.clearTimeout(flashTimer);
    flashTimer = window.setTimeout(() => setStore({ completedFlash: false }), 3200);
    return;
  }
  if (!idle && store.completedFlash) {
    window.clearTimeout(flashTimer);
    setStore({ queue: next, completedFlash: false });
    return;
  }
  setStore({ queue: next });
}

let pollTimer: number | undefined;

function pollQueueOnce() {
  const bridge = getBridge();
  void bridge
    .call("marketplace.queue", undefined)
    .then((result) => applyQueue(normalize(result)))
    .catch(() => undefined);
}

function armQueuePoll() {
  if (typeof window === "undefined") return;
  if (pollTimer != null) return;
  // bridgeEvent/subscribe can miss updates in WebEngine — poll while work is active.
  pollTimer = window.setInterval(() => {
    const busy =
      store.queue.busy ||
      store.queue.items.some((item) =>
        ["queued", "downloading", "paused", "installing", "starting"].includes(String(item.status || "")),
      );
    if (!busy) {
      window.clearInterval(pollTimer);
      pollTimer = undefined;
      return;
    }
    pollQueueOnce();
  }, 1000);
}

function ensureWired() {
  if (wired || typeof window === "undefined") return;
  wired = true;
  const bridge = getBridge();
  pollQueueOnce();
  bridge.subscribe("marketplace.queue", (payload) => {
    const next = normalize(payload);
    const retainedErrors = store.queue.items.filter(
      (item) => item.status === "error" && !next.items.some((candidate) => candidate.slug === item.slug),
    );
    applyQueue({ ...next, items: [...next.items, ...retainedErrors] });
    armQueuePoll();
  });
  bridge.subscribe("marketplace.download-progress", (payload) => {
    const slug = String(payload?.slug || "");
    const status = String(payload?.status || "");
    if (status === "error" && String(payload?.error || "") === "insufficient_disk_space") {
      setStore({ storageWarning: true });
    }
    if (!slug) return;
    const items = [...store.queue.items];
    const idx = items.findIndex((item) => item.slug === slug || (payload.jobId && item.jobId === payload.jobId));
    const prev = idx >= 0 ? items[idx] : undefined;
    const nextProgress = Math.max(
      Number(payload.progress ?? 0) || 0,
      Number(prev?.progress || 0) || 0,
    );
    const nextBytesDone = Math.max(
      Number(payload.bytesDone ?? prev?.bytesDone ?? 0) || 0,
      Number(prev?.bytesDone || 0) || 0,
    );
    const nextBytesTotal = Math.max(
      Number(payload.bytesTotal ?? prev?.bytesTotal ?? 0) || 0,
      Number(prev?.bytesTotal || 0) || 0,
    );
    const nextItem: MarketplaceQueueItem = {
      jobId: String(payload.jobId || prev?.jobId || slug),
      slug,
      status,
      message: payload.message,
      title: payload.title || prev?.title || slug,
      iconUrl: payload.iconUrl || prev?.iconUrl || "",
      compatibility: payload.compatibility || prev?.compatibility || "",
      progress: nextProgress,
      bytesDone: nextBytesDone,
      bytesTotal: nextBytesTotal,
      error: payload.error,
    };
    if (status === "done" || status === "cancelled") {
      if (idx >= 0) items.splice(idx, 1);
      if (status === "done") {
        const recentlyInstalled = new Set(store.recentlyInstalled);
        recentlyInstalled.add(slug);
        setStore({ recentlyInstalled });
        if (Array.isArray(payload.mods) && Array.isArray(payload.mods2)) {
          applyMarketplaceMods(payload.mods, payload.mods2);
        }
        void refreshMarketplaceMods(slug)
          .then((confirmed) => {
            if (confirmed) clearRecentlyInstalled(slug);
          })
          .catch(() => undefined);
      }
    } else if (status === "error") {
      if (idx >= 0) items[idx] = { ...items[idx], ...nextItem };
      else items.push(nextItem);
      window.clearTimeout(terminalTimers.get(slug));
      terminalTimers.set(
        slug,
        window.setTimeout(() => {
          terminalTimers.delete(slug);
          setStore({
            queue: {
              ...store.queue,
              items: store.queue.items.filter((item) => !(item.slug === slug && item.status === "error")),
              pending: store.queue.pending.filter((entry) => entry !== slug),
            },
          });
        }, 12_000),
      );
    } else if (idx >= 0) {
      items[idx] = { ...items[idx], ...nextItem };
    } else {
      items.push(nextItem);
    }
    const busy = items.some((item) => item.status === "downloading" || item.status === "installing" || item.status === "starting");
    const active = items.find((item) => item.status === "downloading" || item.status === "installing" || item.status === "starting");
    const byteRatio =
      active?.bytesTotal && active.bytesTotal > 0
        ? Math.max(0, Math.min(1, Number(active.bytesDone || 0) / active.bytesTotal))
        : 0;
    const jobProgress = active ? Math.max(0, Math.min(1, Number(active.progress || 0))) : 0;
    let overall = Math.max(byteRatio, jobProgress);
    if (active?.status === "installing") {
      overall = Math.max(overall, 0.85, jobProgress || 0.85);
    } else if (active && overall <= 0) {
      overall = 0.02;
    } else if (!active && items.some(isWorking)) {
      overall = 0.02;
    }
    applyQueue({
      busy,
      activeSlug: active?.slug || "",
      overallProgress: overall,
      pending: items.map((item) => item.slug),
      items,
    });
    if (busy || items.length > 0) armQueuePoll();
  });
}

function subscribe(listener: () => void) {
  ensureWired();
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot() {
  return store;
}

export function useMarketplaceQueue() {
  const snap = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  const bySlug = useMemo(() => {
    const map = new Map<string, MarketplaceQueueItem>();
    for (const item of snap.queue.items) {
      if (isWorking(item)) map.set(item.slug, item);
    }
    return map;
  }, [snap.queue.items]);

  const visible = snap.queue.items.length > 0 || snap.queue.busy || snap.completedFlash;
  const progress = snap.completedFlash ? 1 : Math.max(0, Math.min(1, Number(snap.queue.overallProgress || 0)));

  const cancel = useCallback(async (slug: string, jobId?: string) => {
    applyQueue({
      ...store.queue,
      items: store.queue.items.filter((item) => !(item.slug === slug || (jobId && item.jobId === jobId))),
      pending: store.queue.pending.filter((entry) => entry !== slug),
    });
    const result = await getBridge().call("marketplace.cancel", { slug, jobId });
    applyQueue(normalize(result));
  }, []);

  const pause = useCallback(async (slug: string, jobId?: string) => {
    applyQueue({
      ...store.queue,
      items: store.queue.items.map((item) =>
        item.slug === slug || (jobId && item.jobId === jobId) ? { ...item, status: "paused", message: "paused" } : item,
      ),
    });
    const result = await getBridge().call("marketplace.pause", { slug, jobId });
    applyQueue(normalize(result));
  }, []);

  const resume = useCallback(async (slug: string, jobId?: string) => {
    applyQueue({
      ...store.queue,
      items: store.queue.items.map((item) =>
        item.slug === slug || (jobId && item.jobId === jobId) ? { ...item, status: "queued", message: item.title || item.slug } : item,
      ),
    });
    const result = await getBridge().call("marketplace.resume", { slug, jobId });
    applyQueue(normalize(result));
  }, []);

  const reorder = useCallback(async (orderedSlugs: string[]) => {
    const result = await getBridge().call("marketplace.reorder-queue", { orderedSlugs });
    applyQueue(normalize(result));
  }, []);

  const markUninstalled = useCallback((slug: string) => {
    clearRecentlyInstalled(slug);
  }, []);

  const enqueue = useCallback(
    async (item: {
      slug: string;
      title?: string;
      compatibility?: string;
      versionId?: number | null;
      author?: string;
      summary?: string;
      iconUrl?: string;
      projectUrl?: string;
      marketplaceVersion?: string;
      allowUpdate?: boolean;
    }) => {
      if (!store.queue.items.some((entry) => entry.slug === item.slug && isWorking(entry))) {
        applyQueue({
          ...store.queue,
          busy: store.queue.busy || store.queue.items.length === 0,
          pending: [...store.queue.pending, item.slug],
          items: [
            ...store.queue.items,
            {
              jobId: `local-${item.slug}`,
              slug: item.slug,
              status: "queued",
              title: item.title || item.slug,
              iconUrl: item.iconUrl || "",
              compatibility: item.compatibility || "",
              progress: 0,
              bytesDone: 0,
              bytesTotal: 0,
            },
          ],
        });
      }
      if (store.queue.items.some((entry) => entry.slug === item.slug && entry.status === "error")) {
        window.clearTimeout(terminalTimers.get(item.slug));
        terminalTimers.delete(item.slug);
        applyQueue({
          ...store.queue,
          items: store.queue.items.filter((entry) => !(entry.slug === item.slug && entry.status === "error")),
          pending: store.queue.pending.filter((slug) => slug !== item.slug),
        });
      }
      try {
        const result = await getBridge().call("marketplace.download", {
          slug: item.slug,
          title: item.title,
          compatibility: item.compatibility,
          versionId: item.versionId ?? null,
          author: item.author,
          summary: item.summary,
          iconUrl: item.iconUrl,
          projectUrl: item.projectUrl,
          marketplaceVersion: item.marketplaceVersion || "",
          allowUpdate: Boolean(item.allowUpdate),
        });
        if (result.alreadyInstalled) {
          // Drop optimistic queue row — nothing will download.
          applyQueue({
            ...store.queue,
            items: store.queue.items.filter((entry) => entry.slug !== item.slug),
            pending: store.queue.pending.filter((slug) => slug !== item.slug),
          });
          const recentlyInstalled = new Set(store.recentlyInstalled);
          recentlyInstalled.add(item.slug);
          setStore({ recentlyInstalled });
          void refreshMarketplaceMods(item.slug)
            .then((confirmed) => {
              if (confirmed) clearRecentlyInstalled(item.slug);
            })
            .catch(() => undefined);
        }
        armQueuePoll();
        const snapQueue = await getBridge().call("marketplace.queue", undefined);
        applyQueue(normalize(snapQueue));
        return result;
      } catch (error) {
        applyQueue({
          ...store.queue,
          items: store.queue.items.filter((entry) => entry.slug !== item.slug),
          pending: store.queue.pending.filter((slug) => slug !== item.slug),
        });
        if (String(error).includes("insufficient_disk_space")) {
          setStore({ storageWarning: true });
        }
        throw error;
      }
    },
    [],
  );

  // Keep hook reactive even if no components subscribed yet when first import happens in SSR-less env.
  useEffect(() => {
    ensureWired();
  }, []);

  return {
    queue: snap.queue,
    bySlug,
    visible,
    progress,
    completedFlash: snap.completedFlash,
    recentlyInstalled: snap.recentlyInstalled,
    storageWarning: snap.storageWarning,
    clearStorageWarning: () => setStore({ storageWarning: false }),
    cancel,
    pause,
    resume,
    reorder,
    markUninstalled,
    enqueue,
  };
}
