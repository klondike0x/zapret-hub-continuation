import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useAppState, useBridge, patchOptimistic } from "@/hooks/useBridgeState";
import { useLocale } from "@/hooks/useLocale";
import { IosToggle } from "@/components/ui/IosToggle";
import { Segmented } from "@/components/ui/Segmented";
import type { ComponentId, ComponentStatus, ComponentUpdateCheck, Settings } from "@/bridge/types";
import type { LocaleKey } from "@/locale/dict";
import { uiAssetUrl } from "@/lib/assets";
import { ScrollGlassHeader } from "@/components/ui/ScrollGlassHeader";
import { ConfirmModal } from "@/components/ui/ConfirmModal";

const ORDER: ComponentId[] = ["zapret", "zapret2", "xbox-dns"];
const GITHUB_VERSION_IDS: ComponentId[] = ["zapret", "zapret2"];

const componentIcon: Record<ComponentId, string> = {
  zapret: "component_zapret.svg", zapret2: "component_zapret2.svg", "xbox-dns": "component_xbox_dns.svg",
};

const DNS_PROFILE_IDS: Array<Settings["dns"]["profile"]> = ["dhcp", "xbox", "cloudflare", "adguard", "google", "yandex"];

const DNS_ADDRESSES: Record<Settings["dns"]["profile"], string> = {
  dhcp: "",
  xbox: "111.88.96.50 · 111.88.96.51",
  cloudflare: "1.1.1.1 · 1.0.0.1",
  adguard: "94.140.14.14 · 94.140.15.15",
  google: "8.8.8.8 · 8.8.4.4",
  yandex: "77.88.8.8 · 77.88.8.1",
};

function statusLabel(status: ComponentStatus, t: (key: LocaleKey) => string): string {
  if (status === "on") return t("power.on");
  if (status === "off") return t("power.off");
  if (status === "starting") return t("power.starting");
  if (status === "stopping") return t("component.stopping");
  if (status === "updating") return t("component.updating");
  if (status === "error") return t("power.error");
  return status;
}

export function ComponentsPage({ onConfigure, onReconfigure, onOpenManual, focusId, onFocusHandled }: {
  onConfigure?: (id: ComponentId) => void;
  onReconfigure?: () => void;
  onOpenManual?: (backend: "zapret" | "zapret2", target: "mods" | "files") => void;
  focusId?: string | null;
  onFocusHandled?: () => void;
}) {
  const state = useAppState();
  const bridge = useBridge();
  const { t, locale } = useLocale();
  const [checkingId, setCheckingId] = useState<ComponentId | null>(null);
  const [updatingId, setUpdatingId] = useState<ComponentId | null>(null);
  const [updateCheck, setUpdateCheck] = useState<ComponentUpdateCheck | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<string | null>(null);
  const [dnsOpen, setDnsOpen] = useState(false);
  const [confirmManualOpen, setConfirmManualOpen] = useState(false);
  const [confirmManualBackend, setConfirmManualBackend] = useState<"zapret" | "zapret2">("zapret");
  const [optimisticDns, setOptimisticDns] = useState<Settings["dns"]["profile"] | null>(null);
  const [optimisticToggle, setOptimisticToggle] = useState<Partial<Record<ComponentId, boolean>>>({});
  const toggleTimers = useRef<Partial<Record<ComponentId, number>>>({});
  const scrollerRef = useRef<HTMLDivElement>(null);
  const versionListRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (optimisticDns === state?.settings.dns.profile) setOptimisticDns(null);
  }, [optimisticDns, state?.settings.dns.profile]);
  // Keep wheel scroll inside the version list (do not scroll the page behind the modal).
  useLayoutEffect(() => {
    if (!updateCheck) return;
    let list: HTMLDivElement | null = null;
    let onWheel: ((event: WheelEvent) => void) | null = null;
    const frame = window.requestAnimationFrame(() => {
      list = versionListRef.current;
      if (!list) return;
      onWheel = (event: WheelEvent) => {
        // Capture phase: stop before parent modal/page handlers steal the wheel.
        event.stopPropagation();
        const canScroll = list!.scrollHeight > list!.clientHeight + 1;
        const atTop = list!.scrollTop <= 0;
        const atBottom = list!.scrollTop + list!.clientHeight >= list!.scrollHeight - 1;
        if (!canScroll || (event.deltaY < 0 && atTop) || (event.deltaY > 0 && atBottom)) {
          event.preventDefault();
        }
        // Else: native overflow scroll moves the list only.
      };
      list.addEventListener("wheel", onWheel, { capture: true, passive: false });
    });
    return () => {
      window.cancelAnimationFrame(frame);
      if (list && onWheel) list.removeEventListener("wheel", onWheel, { capture: true });
    };
  }, [updateCheck]);
  useEffect(() => {
    if (!state) return;
    setOptimisticToggle((current) => {
      let changed = false;
      const next = { ...current };
      for (const id of Object.keys(current) as ComponentId[]) {
        const component = state.components[id];
        const actualEnabled = Boolean(component?.enabled) || component?.status === "on";
        if (current[id] === actualEnabled) {
          delete next[id];
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [state]);
  useEffect(() => () => {
    for (const timer of Object.values(toggleTimers.current)) {
      if (timer) window.clearTimeout(timer);
    }
  }, []);
  useEffect(() => {
    if (!focusId) return;
    const target = document.querySelector<HTMLElement>(`[data-component-id="${focusId}"]`);
    window.setTimeout(() => {
      target?.scrollIntoView({ behavior: "smooth", block: "center" });
      target?.animate(
        [{ borderColor: "var(--line-1)" }, { borderColor: "var(--nav-accent)" }, { borderColor: "var(--line-1)" }],
        { duration: 900, easing: "ease-out" },
      );
      onFocusHandled?.();
    }, 80);
  }, [focusId, onFocusHandled]);
  useEffect(() => bridge.subscribe("component.update-check", (result) => {
    setCheckingId(null);
    setUpdateCheck((prev) => {
      let next = result;
      // After GitHub rate-limit the API used to collapse to 0–1 versions. Prefer the
      // richer list we already showed for the same component in this session.
      if (
        prev
        && prev.id === result.id
        && GITHUB_VERSION_IDS.includes(result.id)
        && (prev.versions?.length ?? 0) > 1
        && (result.versions?.length ?? 0) <= 1
        && !result.error
      ) {
        next = {
          ...result,
          versions: prev.versions,
          latestVersion: prev.latestVersion || result.latestVersion,
          recommendedVersion: prev.recommendedVersion || result.recommendedVersion,
          available: prev.available || result.available,
        };
      }
      if (GITHUB_VERSION_IDS.includes(next.id) && (next.versions?.length ?? 0) > 0) {
        const preferred = next.available
          ? (next.latestVersion || next.versions?.find((item) => item.recommended)?.version || next.currentVersion)
          : (next.versions?.find((item) => item.current)?.version || next.currentVersion);
        setSelectedVersion(preferred || null);
      } else {
        setSelectedVersion(null);
      }
      return next;
    });
  }), [bridge]);
  useEffect(() => bridge.subscribe("component.update-result", (result) => {
    setUpdatingId(result.status === "started" ? result.id : null);
  }), [bridge]);
  if (!state) return null;

  const powered = state.runtime.status === "on" || state.runtime.status === "starting";

  const checkUpdate = (id: ComponentId) => {
    setCheckingId(id);
    bridge.call("component.check-update", { id, requestId: `${id}-${Date.now()}` });
  };

  const toggleComponent = (id: ComponentId, on: boolean) => {
    setOptimisticToggle((current) => ({ ...current, [id]: on }));
    // Only show starting/stopping when power is on (backend will actually start/stop).
    // With power off, toggle only updates "enabled" — process stays off.
    if (powered) {
      patchOptimistic({
        components: {
          [id]: {
            enabled: on,
            status: on ? "starting" : "stopping",
          },
        },
      });
    } else {
      patchOptimistic({
        components: {
          [id]: { enabled: on },
        },
      });
    }
    const existing = toggleTimers.current[id];
    if (existing) window.clearTimeout(existing);
    toggleTimers.current[id] = window.setTimeout(() => {
      void bridge.call("component.toggle", { id, on });
      delete toggleTimers.current[id];
    }, 180);
  };

  const dnsTitle = (id: Settings["dns"]["profile"]) => t(`dns.profile.${id}.title` as LocaleKey);
  const dnsDesc = (id: Settings["dns"]["profile"]) => t(`dns.profile.${id}.desc` as LocaleKey);
  const dhcpAddresses = t("dns.profile.dhcp.addresses");
  const controlMode = (id: "zapret" | "zapret2") => id === "zapret2"
    ? (state.settings.zapret2.controlMode ?? "manual")
    : (state.settings.zapret.controlMode ?? "manual");

  const setControlMode = (backend: "zapret" | "zapret2", mode: "manual" | "auto") => {
    const current = controlMode(backend);
    if (mode === current) return;
    if (mode === "manual" && current === "auto") {
      setConfirmManualBackend(backend);
      setConfirmManualOpen(true);
      return;
    }
    applyControlMode(backend, mode);
  };

  const applyControlMode = (backend: "zapret" | "zapret2", mode: "manual" | "auto") => {
    const active = state.runtime.active === backend;
    patchOptimistic(backend === "zapret2" ? {
      settings: { zapret2: { ...state.settings.zapret2, controlMode: mode } },
      ...(active ? { orchestrator: { mode, isAuto: mode === "auto", backend } } : {}),
    } : {
      settings: { zapret: { ...state.settings.zapret, controlMode: mode } },
      ...(active ? { orchestrator: { mode, isAuto: mode === "auto", backend } } : {}),
    });
    if (active && powered) {
      patchOptimistic({
        runtime: { status: "starting" },
        components: { [backend]: { status: "starting" } },
      });
    }
    void bridge.call("orchestrator.setMode", { mode, backend });
  };

  return (
    <div className="relative h-full overflow-hidden">
      <div ref={scrollerRef} className="scroll-area glass-page-scroll h-full overflow-auto">
      <div className="scroll-content px-6 pb-6 pt-[86px]">
        <div className="grid grid-cols-2 gap-4">
          {ORDER.map((id) => {
            const c = state.components[id];
            const on = optimisticToggle[id] ?? (Boolean(c.enabled) || c.status === "on");
            const toneColor = c.status === "on" ? "var(--ok)" : c.status === "error" ? "var(--err)" : c.status === "updating" || c.status === "starting" || c.status === "stopping" ? "var(--warn)" : "var(--fg-mute)";
            return (
              <div key={id} data-component-id={id} className="soft-card flex min-h-[152px] flex-col rounded-[16px] border border-line-1 p-4">
                <div className="flex items-start justify-between gap-3">
                <div className="grid h-11 w-11 place-items-center rounded-xl border border-line-1 bg-bg-1 p-2 text-fg-dim">
                  <img className={`h-full w-full object-contain ${id === "zapret2" ? "scale-[1.16]" : ""}`} src={uiAssetUrl(`icons/${componentIcon[id]}`)} aria-hidden="true" />
                </div>
                <div className="flex items-center gap-1">
                  <button onClick={() => onConfigure?.(id)} className="rounded-lg px-2 py-1 text-[11px] text-fg-dim transition-all duration-200 hover:bg-bg-3 hover:text-fg">{t("component.settings")}</button>
                  {c.externalUrl && <button aria-label={t("component.open")} onClick={() => bridge.call("component.open-external", { id })} className="grid h-7 w-7 place-items-center rounded-[9px] text-fg-dim transition-all duration-200 hover:bg-bg-3 hover:text-fg"><svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M4 12 12 4" /><path d="M7.5 4H12v4.5" /></svg></button>}
                </div>
                </div>
                <div className="mt-3 min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[14px] font-semibold text-fg">{c.name}</span>
                    {c.version && <span className="text-[10px] text-fg-mute">v{c.version}</span>}
                    <span className="ml-1 flex items-center gap-1 text-[10px] text-fg-dim">
                      <span className="h-1.5 w-1.5 rounded-full" style={{ background: toneColor }} />
                      {statusLabel(c.status, t)}
                    </span>
                  </div>
                  <div className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-fg-dim">{c.description}</div>
                  <div className="mt-2 truncate text-[10px] text-fg-mute">{c.config}</div>
                </div>
                <div className="mt-3 flex items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    {id !== "xbox-dns" && <button disabled={checkingId === id || updatingId === id} onClick={() => checkUpdate(id)} className="rounded-lg border border-line-1 bg-bg-1 px-2.5 py-1.5 text-[11px] text-fg-dim transition-all duration-200 hover:bg-bg-3 hover:text-fg disabled:opacity-50">{updatingId === id ? t("component.updating") : checkingId === id ? t("component.checking") : t("component.update")}</button>}
                    {id === "xbox-dns" && <button onClick={() => setDnsOpen((value) => !value)} className="rounded-lg border border-line-1 bg-bg-1 px-2.5 py-1.5 text-[11px] text-fg-dim transition-all duration-200 hover:bg-bg-3 hover:text-fg">{t("component.chooseDns")}</button>}
                    {id === "zapret" && controlMode("zapret") !== "auto" && <button onClick={onReconfigure} className="rounded-lg border border-line-1 bg-bg-1 px-2.5 py-1.5 text-[11px] text-fg-dim transition-all duration-200 hover:bg-bg-3 hover:text-fg">{locale === "ru" ? "Настроить сервисы" : "Configure services"}</button>}
                  </div>
                  {id === "xbox-dns" && <IosToggle on={on} onChange={(v) => toggleComponent(id, v)} label={c.name} />}
                </div>
                {(id === "zapret" || id === "zapret2") && controlMode(id) === "manual" && (
                  <div className="mt-2.5 border-t border-line-1 pt-2.5">
                    <div className="flex flex-wrap gap-1.5">
                      <button
                        type="button"
                        onClick={() => onOpenManual?.(id, "mods")}
                        className="inline-flex items-center rounded-lg border border-line-1 bg-bg-1 px-2.5 py-1.5 text-[11px] text-fg-dim transition-colors hover:bg-bg-3 hover:text-fg"
                      >
                        {locale === "ru" ? "Пользовательские модификации" : "Custom modifications"}
                      </button>
                      <button
                        type="button"
                        onClick={() => onOpenManual?.(id, "files")}
                        className="inline-flex items-center rounded-lg border border-line-1 bg-bg-1 px-2.5 py-1.5 text-[11px] text-fg-dim transition-colors hover:bg-bg-3 hover:text-fg"
                      >
                        {locale === "ru" ? "Файлы" : "Files"}
                      </button>
                    </div>
                  </div>
                )}
                {(id === "zapret" || id === "zapret2") && (
                  <div className="mt-2.5 flex items-center justify-between gap-2 border-t border-line-1 pt-2.5">
                    <span className="text-[10px] text-fg-mute">
                      {id === "zapret2" ? (locale === "ru" ? "Режим управления Zapret 2" : "Zapret 2 control mode") : t("component.mode.hint")}
                    </span>
                    <Segmented
                      size="sm"
                      value={controlMode(id)}
                      onChange={(mode) => setControlMode(id, mode)}
                      options={[
                        { value: "auto", label: t("component.mode.auto") },
                        { value: "manual", label: t("component.mode.manual") },
                      ]}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
      </div>
      <AnimatePresence>
          {dnsOpen && (
            <motion.div className="fixed inset-0 z-[80] grid place-items-center bg-black/45 backdrop-blur-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setDnsOpen(false)}>
              <motion.div initial={{ opacity: 0, y: 10, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 7, scale: 0.98 }} className="w-[620px] rounded-[18px] border border-line-2 bg-bg-1 p-4 shadow-[0_20px_48px_-24px_rgba(0,0,0,.8)]" onClick={(event) => event.stopPropagation()}>
                <div className="mb-3 flex items-center justify-between">
                  <div>
                    <h3 className="text-[15px] font-semibold text-fg">{t("dns.chooseTitle")}</h3>
                    <p className="mt-0.5 text-[10px] text-fg-dim">{t("dns.chooseDesc")}</p>
                  </div>
                  <button aria-label={t("common.cancel")} onClick={() => setDnsOpen(false)} className="grid h-8 w-8 place-items-center rounded-[9px] text-fg-dim transition-colors hover:bg-bg-3 hover:text-fg">×</button>
                </div>
                <div className="grid grid-cols-2 gap-2.5">
                {DNS_PROFILE_IDS.map((profileId) => {
                  const selected = (optimisticDns ?? state.settings.dns.profile) === profileId;
                  return (
                    <button
                      key={profileId}
                      onClick={() => {
                        setOptimisticDns(profileId);
                        patchOptimistic({ settings: { dns: { profile: profileId } } });
                        void bridge.call("dns.select-profile", { profile: profileId });
                      }}
                      className="group rounded-[13px] border p-3 text-left transition-all duration-200"
                      style={{ borderColor: selected ? "var(--ok)" : "var(--line-1)", background: selected ? "color-mix(in srgb, var(--ok) 8%, var(--bg-2))" : "var(--bg-2)" }}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-[12px] font-semibold text-fg">{dnsTitle(profileId)}</span>
                        {selected && <span className="rounded-full bg-ok/15 px-2 py-0.5 text-[9px] font-semibold text-ok">{t("dns.selected")}</span>}
                      </div>
                      <div className="mt-1 text-[10px] text-fg-dim">{dnsDesc(profileId)}</div>
                      <div className="mt-2 font-mono text-[9px] text-fg-mute">{profileId === "dhcp" ? dhcpAddresses : DNS_ADDRESSES[profileId]}</div>
                    </button>
                  );
                })}
                </div>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>
      <AnimatePresence>
        {updateCheck && (
          <motion.div className="fixed inset-0 z-[80] grid place-items-center bg-black/45 backdrop-blur-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => { setUpdateCheck(null); setSelectedVersion(null); }} onWheel={(event) => { event.stopPropagation(); event.preventDefault(); }}>
            <motion.div initial={{ opacity: 0, y: 12, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 8, scale: 0.98 }} className={`rounded-[18px] border border-line-1 bg-bg-1 p-5 shadow-2xl ${(updateCheck.versions?.length ?? 0) > 0 ? "w-[440px]" : "w-[390px]"}`} onClick={(event) => event.stopPropagation()} onWheel={(event) => { event.stopPropagation(); event.preventDefault(); }}>
              {(() => {
                const hasVersions = GITHUB_VERSION_IDS.includes(updateCheck.id) && (updateCheck.versions?.length ?? 0) > 0;
                const versionChanged = Boolean(selectedVersion && selectedVersion !== updateCheck.currentVersion);
                const canInstall = !updateCheck.error && (versionChanged || (updateCheck.available && !hasVersions));
                const title = updateCheck.error
                  ? t("update.checkFailed")
                  : hasVersions
                    ? t("update.changeTitle")
                    : updateCheck.available
                      ? t("update.found")
                      : t("update.uptodate");
                const normVersion = (value: string) => value.trim().replace(/^v/i, "").toLowerCase();
                const currentNorm = normVersion(updateCheck.currentVersion || "");
                const currentExact = updateCheck.versions?.find((item) => item.current)?.version
                  || updateCheck.versions?.find((item) => normVersion(item.version) === currentNorm)?.version
                  || "";
                return (
                  <>
              <h3 className="text-[15px] font-semibold text-fg">{title}</h3>
              {updateCheck.error ? <p className="mt-2 text-[11px] leading-relaxed text-err">{updateCheck.error}</p> : (
                <>
                  <div className="mt-3 grid grid-cols-2 gap-2 rounded-xl border border-line-1 bg-bg-2 p-3 text-[11px]">
                    <div><div className="text-fg-mute">{t("update.current")}</div><div className="mt-1 font-semibold text-fg">{updateCheck.currentVersion}</div></div>
                    <div><div className="text-fg-mute">{t("update.latest")}</div><div className="mt-1 font-semibold text-fg">{updateCheck.latestVersion}</div></div>
                  </div>
                  {hasVersions && (
                    <div className="mt-3">
                      <div className="mb-1.5 text-[11px] font-medium text-fg">{t("update.chooseVersion")}</div>
                      <p className="mb-2 text-[10px] leading-relaxed text-fg-dim">{t("update.versionsHint")}</p>
                      <div
                        ref={versionListRef}
                        className="scroll-area max-h-[220px] space-y-1.5 overflow-y-auto overscroll-contain pr-1"
                      >
                        {updateCheck.versions!.map((release) => {
                          const selected = (selectedVersion ?? updateCheck.currentVersion) === release.version;
                          const isCurrent = currentExact !== "" && release.version === currentExact;
                          return (
                            <button
                              key={release.version}
                              type="button"
                              disabled={updatingId === updateCheck.id}
                              onClick={() => setSelectedVersion(release.version)}
                              className="flex w-full items-center justify-between gap-2 rounded-[11px] border px-3 py-2 text-left transition-colors disabled:opacity-50"
                              style={{
                                borderColor: selected ? "var(--ok)" : "var(--line-1)",
                                background: selected ? "color-mix(in srgb, var(--ok) 8%, var(--bg-2))" : "var(--bg-2)",
                              }}
                            >
                              <div className="min-w-0">
                                <div className="truncate text-[12px] font-semibold text-fg">{release.version}</div>
                                {release.publishedAt && (
                                  <div className="mt-0.5 text-[9px] text-fg-mute">
                                    {new Date(release.publishedAt).toLocaleDateString(locale === "ru" ? "ru-RU" : "en-US")}
                                  </div>
                                )}
                              </div>
                              <div className="flex shrink-0 flex-wrap items-center justify-end gap-1">
                                {isCurrent && <span className="rounded-full bg-fg/10 px-1.5 py-0.5 text-[9px] text-fg-dim">{t("update.currentBadge")}</span>}
                                {release.recommended && <span className="rounded-full bg-ok/15 px-1.5 py-0.5 text-[9px] text-ok">{t("update.recommended")}</span>}
                                {release.prerelease && <span className="rounded-full bg-warn/15 px-1.5 py-0.5 text-[9px] text-warn">{t("update.prerelease")}</span>}
                              </div>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </>
              )}
              <div className="mt-4 flex justify-end gap-2">
                <button onClick={() => { setUpdateCheck(null); setSelectedVersion(null); }} className="rounded-[10px] border border-line-1 px-3 py-2 text-[11px] text-fg-dim hover:bg-bg-2">{canInstall ? t("update.keep") : t("settings.close")}</button>
                {canInstall && (
                  <button
                    disabled={updatingId === updateCheck.id}
                    onClick={() => {
                      const version = hasVersions
                        ? (selectedVersion && selectedVersion !== updateCheck.currentVersion ? selectedVersion : (updateCheck.available ? updateCheck.latestVersion : undefined))
                        : (updateCheck.available ? updateCheck.latestVersion : undefined);
                      setUpdatingId(updateCheck.id);
                      bridge.call("component.install-update", { id: updateCheck.id, ...(version ? { version } : {}) });
                      setUpdateCheck(null);
                      setSelectedVersion(null);
                    }}
                    className="rounded-[10px] bg-fg px-3 py-2 text-[11px] font-semibold text-bg-0 hover:opacity-90 disabled:opacity-50"
                  >
                    {updatingId === updateCheck.id ? t("update.installing") : t("update.installVersion")}
                  </button>
                )}
              </div>
                  </>
                );
              })()}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
      <ConfirmModal
        open={confirmManualOpen}
        title={t("component.mode.confirmTitle")}
        message={t("component.mode.confirmManual")}
        confirmLabel={t("component.mode.confirmAction")}
        cancelLabel={t("common.cancel")}
        onCancel={() => setConfirmManualOpen(false)}
        onConfirm={() => {
          setConfirmManualOpen(false);
          applyControlMode(confirmManualBackend, "manual");
        }}
      />
      <ScrollGlassHeader scrollerRef={scrollerRef} className="absolute inset-x-0 top-0 z-20 border-b border-line-1 px-6 pb-4 pt-5">
        <h2 className="text-[15px] font-semibold text-fg">{t("components.title")}</h2>
        <p className="mt-0.5 text-[11px] text-fg-dim">{t("components.desc")}</p>
      </ScrollGlassHeader>
    </div>
  );
}
