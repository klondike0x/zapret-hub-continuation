import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { PowerButton } from "@/components/ui/PowerButton";
import { StatusPill } from "@/components/ui/Chevron";
import { useAppState, useBridge, patchOptimistic } from "@/hooks/useBridgeState";
import { useLocale } from "@/hooks/useLocale";
import { bridgeIdle } from "@/lib/schedule";
import { playSound } from "@/lib/sounds";
import type { RuntimeId, RuntimeStatus } from "@/bridge/types";

const modeColor: Record<RuntimeId, string> = {
  zapret: "#28c77b",
  zapret2: "#3d9fea",
  none: "#858b96",
};

const themeName: Record<string, string> = { oled: "Obsidian", light: "Concrete", night: "Aurora" };

function statusTone(status: RuntimeStatus) {
  return status === "on" ? "ok" : status === "starting" || status === "stopping" ? "warn" : status === "error" ? "err" : "muted" as const;
}

function StatusIcon({ kind, status }: { kind: "app" | "mode" | "tg" | "mods" | "theme"; status?: string }) {
  if (kind === "theme") return <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-sky-500/15 text-sky-400"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" className="block"><path d="M12 3a9 9 0 1 0 9 9 7 7 0 1 1-9-9Z" /></svg></span>;
  if (kind === "mods") return <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-violet-500/15 text-violet-400"><svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" className="block"><path d="m12 2 8.7 5v10L12 22l-8.7-5V7z" /></svg></span>;
  const color = status === "on" ? "var(--ok)" : status === "error" ? "var(--err)" : status === "starting" || status === "stopping" ? "var(--warn)" : "var(--fg-mute)";
  const symbol = status === "on"
    ? <path d="M3.4 7.6 L5.9 10.1 L10.6 4.6" />
    : status === "error" ? <><path d="M7 4v3" /><path d="M7 10h.01" /></>
    : status === "starting" ? <><path d="M7 3v5" /><path d="M7 11h.01" /></>
    : <path d="M4.2 4.2l5.6 5.6M9.8 4.2l-5.6 5.6" />;
  return <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full" style={{ background: color }}><svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="block" aria-hidden="true">{symbol}</svg></span>;
}

export function QuickAccessPage({ onOpenComponent }: {
  onOpenComponent?: (id: "zapret" | "zapret2" | "tg-ws-proxy") => void;
}) {
  const state = useAppState();
  const bridge = useBridge();
  const { t, locale } = useLocale();
  const modeNames: Record<RuntimeId, string> = {
    zapret: "Zapret",
    zapret2: "Zapret 2",
    none: locale === "ru" ? "Без основного компонента" : "No primary component",
  };
  const [previewMode, setPreviewMode] = useState<RuntimeId | null>(null);
  const [pendingPower, setPendingPower] = useState<"starting" | "stopping" | null>(null);
  const switchTimer = useRef<number | null>(null);
  const pendingModeRef = useRef<RuntimeId | null>(null);
  /** Keep power on across browse→commit so intermediate/failed selects don't leave the button off. */
  const keepPowerRef = useRef(false);
  const stageRef = useRef<HTMLDivElement>(null);
  const wheelLock = useRef(0);
  const previewModeRef = useRef<RuntimeId | null>(null);
  const stateRef = useRef(state);
  const bridgeRef = useRef(bridge);
  previewModeRef.current = previewMode;
  stateRef.current = state;
  bridgeRef.current = bridge;

  // Commit only after the user stops browsing (wheel / clicks) for 1.5s.
  const MODE_SETTLE_MS = 1500;

  const clearModeTimer = () => {
    if (switchTimer.current !== null) {
      window.clearTimeout(switchTimer.current);
      switchTimer.current = null;
    }
  };

  const notePowerIntent = (currentState: NonNullable<typeof state>) => {
    const status = currentState.runtime.status;
    keepPowerRef.current = status === "on" || status === "starting";
  };

  const scheduleModeCommit = (nextId: RuntimeId) => {
    const currentState = stateRef.current;
    if (!currentState) return;
    pendingModeRef.current = nextId;
    clearModeTimer();
    if (nextId === currentState.runtime.active) {
      setPreviewMode(null);
      pendingModeRef.current = null;
      return;
    }
    setPreviewMode(nextId);
    playSound("switch");
    switchTimer.current = window.setTimeout(() => {
      const target = pendingModeRef.current;
      const latest = stateRef.current;
      switchTimer.current = null;
      pendingModeRef.current = null;
      if (!target || !latest || target === latest.runtime.active) {
        setPreviewMode(null);
        return;
      }
      const keepPower = keepPowerRef.current
        || latest.runtime.status === "on"
        || latest.runtime.status === "starting";
      patchOptimistic({
        runtime: {
          active: target,
          status: keepPower ? "starting" : latest.runtime.status,
        },
      });
      bridgeIdle(() => bridgeRef.current.call("runtime.select", { id: target, keepPower }));
    }, MODE_SETTLE_MS);
  };

  // Keep preview (and "Переключение…") until the new mode is active AND power settled.
  useEffect(() => {
    if (!previewMode) return;
    if (previewMode !== state?.runtime.active) return;
    if (state?.runtime.status === "starting" || state?.runtime.status === "stopping") return;
    setPreviewMode(null);
    if (state?.runtime.status === "on") keepPowerRef.current = true;
    if (state?.runtime.status === "off") keepPowerRef.current = false;
  }, [previewMode, state?.runtime.active, state?.runtime.status]);
  // Tray/context-menu changes bypass the local selector. Once no local action is
  // pending, mirror the authoritative power state so a later browse cannot
  // accidentally restore an old "on" intent.
  useEffect(() => {
    if (!state || previewMode || pendingPower || pendingModeRef.current) return;
    keepPowerRef.current = state.runtime.status === "on" || state.runtime.status === "starting";
  }, [pendingPower, previewMode, state?.runtime.active, state?.runtime.status]);
  useEffect(() => () => {
    clearModeTimer();
  }, []);
  useEffect(() => {
    if (pendingPower === "starting" && (state?.runtime.status === "on" || state?.runtime.status === "error")) {
      setPendingPower(null);
    }
    if (pendingPower === "stopping" && (state?.runtime.status === "off" || state?.runtime.status === "error")) {
      setPendingPower(null);
    }
    if (state?.runtime.status === "error") setPendingPower(null);
  }, [pendingPower, state?.runtime.status]);
  useEffect(() => {
    if (!pendingPower && !previewMode) return;
    const timeout = window.setTimeout(() => {
      setPendingPower(null);
      setPreviewMode(null);
    }, 30000);
    return () => window.clearTimeout(timeout);
  }, [pendingPower, previewMode]);

  // Wheel listener uses refs so it is not rebound on every preview/state change.
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const onWheel = (event: WheelEvent) => {
      const currentState = stateRef.current;
      if (!currentState) return;
      if (currentState.settings.scrollModeSwitch === false) return;
      if (Math.abs(event.deltaY) < 2) return;
      event.preventDefault();
      notePowerIntent(currentState);
      // Any wheel activity delays commit — even when mode step is throttled.
      if (pendingModeRef.current || previewModeRef.current) {
        const pending = pendingModeRef.current ?? previewModeRef.current;
        if (pending && pending !== currentState.runtime.active) {
          scheduleModeCommit(pending);
        }
      }
      const now = performance.now();
      if (now - wheelLock.current < 280) return;
      wheelLock.current = now;
      const order = currentState.runtime.order;
      const current = previewModeRef.current ?? pendingModeRef.current ?? currentState.runtime.active;
      const index = Math.max(0, order.indexOf(current));
      const nextIndex = event.deltaY < 0
        ? (index - 1 + order.length) % order.length
        : (index + 1) % order.length;
      const nextId = order[nextIndex];
      if (!nextId || nextId === current) return;
      scheduleModeCommit(nextId);
    };
    stage.addEventListener("wheel", onWheel, { passive: false });
    return () => stage.removeEventListener("wheel", onWheel);
  }, [bridge]);

  if (!state) return null;

  const order = state.runtime.order;
  const displayedMode = previewMode ?? state.runtime.active;
  const activeIdx = Math.max(0, order.indexOf(displayedMode));
  const active = order[activeIdx];
  // Mode switch in flight (preview settle or backend starting after select).
  const modeSwitching = Boolean(previewMode) || (state.runtime.status === "starting" && !pendingPower);
  const status: RuntimeStatus = modeSwitching && (state.runtime.status === "on" || state.runtime.status === "starting" || keepPowerRef.current)
    ? "starting"
    : pendingPower ?? state.runtime.status;
  const on = status === "on";
  const enabledMods = state.mods.filter((mod) => mod.enabled).length;
  const tgStatus = state.components["tg-ws-proxy"]?.status ?? "off";
  // Same settle for click and wheel — apply only after 1.5s without further input.
  const selectMode = (id: RuntimeId) => {
    notePowerIntent(state);
    scheduleModeCommit(id);
  };
  const togglePower = () => {
    // Allow cancel during "starting" (incl. Auto tuning restarts). Only block while already stopping.
    if (status === "stopping") return;
    const nextOn = status === "off" || status === "error";
    keepPowerRef.current = nextOn;
    setPendingPower(nextOn ? "starting" : "stopping");
    patchOptimistic({ runtime: { status: nextOn ? "starting" : "stopping" } });
    bridgeIdle(() => bridge.call("runtime.power", { on: nextOn }));
  };
  const runtimeLabel = (value: RuntimeStatus) => value === "starting"
    ? t("power.starting")
    : value === "stopping"
      ? (locale === "ru" ? "Отключение…" : "Disconnecting…")
      : value === "on"
        ? t("power.on")
        : value === "error"
          ? t("power.error")
          : t("power.off");
  const cards = [
    { label: t("status.app"), value: runtimeLabel(status), kind: "app" as const, status },
    { label: modeNames[active], value: runtimeLabel(status), kind: "mode" as const, status },
    { label: t("status.tgproxy"), value: tgStatus === "on" ? t("power.on") : tgStatus === "starting" ? t("power.starting") : tgStatus === "stopping" ? (locale === "ru" ? "Отключение…" : "Disconnecting…") : tgStatus === "error" ? t("power.error") : t("power.off"), kind: "tg" as const, status: tgStatus },
    { label: t("status.mods"), value: `${enabledMods} ${locale === "ru" ? "активно" : "active"}`, kind: "mods" as const },
    { label: t("status.theme"), value: themeName[state.settings.theme] ?? state.settings.theme, kind: "theme" as const },
  ];
  return (
    <div className="h-full p-3">
      <div className="quick-access-surface flex h-full flex-col rounded-[16px] border border-line-1 px-4 pb-4 pt-3">
      <h1 className="text-[18px] font-semibold text-fg">{t("nav.quick")}</h1>
      <section ref={stageRef} className="flex min-h-0 flex-1 flex-col" aria-label="Runtime selector">
        <div className="relative mx-auto h-[188px] w-[540px] shrink-0">
          {order.map((id, index) => {
            const distance = index - activeIdx;
            const visible = Math.abs(distance) <= 1;
            const selected = distance === 0;
            return (
              <motion.div
                key={id}
                initial={{ opacity: 0 }}
                animate={{ x: distance * 170, scale: selected ? 1 : 0.94, opacity: visible ? (selected ? 1 : 0.43) : 0 }}
                transition={{ x: { type: "spring", stiffness: 225, damping: 25, mass: 0.9 }, scale: { duration: 0.24 }, opacity: { duration: 0.22 } }}
                className="absolute left-1/2 top-1/2 grid h-[174px] w-[174px] -translate-x-1/2 -translate-y-1/2 place-items-center"
                style={{ zIndex: selected ? 3 : visible ? 2 : 0, pointerEvents: visible ? "auto" : "none" }}
              >
                {selected ? (
                  <PowerButton data-sound={on || status === "starting" ? "off" : "none"} accent={modeColor[id]} on={on || status === "starting"} status={status} disabled={status === "stopping"} onClick={togglePower} />
                ) : (
                  <PowerButton
                    variant="side"
                    data-sound="none"
                    aria-label={`Select ${modeNames[id]}`}
                    onClick={() => selectMode(id)}
                    accent={modeColor[id]}
                    on={false}
                    status="off"
                    title={modeNames[id]}
                    style={{ maskImage: `linear-gradient(${distance < 0 ? "to left" : "to right"}, #000 52%, transparent 100%)` }}
                  />
                )}
              </motion.div>
            );
          })}
        </div>
        <div className="flex min-h-[74px] flex-1 flex-col items-center justify-center pb-2 text-center">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={`${active}-label`} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -5 }} transition={{ duration: 0.16 }} className="flex items-center justify-center gap-2 text-[18px] font-semibold text-fg">
              <span>{modeNames[active]}</span>
              {(["zapret", "zapret2"] as const).includes(active as "zapret" | "zapret2") && (state.orchestrator?.isAuto || state.orchestrator?.mode === "auto" || state.settings.zapret.controlMode === "auto") && (
                <span className="rounded-full border border-line-2 bg-bg-1 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-fg-dim">{t("orch.badge")}</span>
              )}
            </motion.div>
          </AnimatePresence>
          <div className="mt-2">
            {(active === "zapret" || active === "zapret2") && (state.orchestrator?.isAuto || state.orchestrator?.mode === "auto" || state.settings.zapret.controlMode === "auto") ? (
              <StatusPill
                label={
                  ["tuning", "picking", "bootstrap"].includes(String(state.orchestrator?.status || ""))
                    ? (state.orchestrator?.statusText || t("orch.status.tuning"))
                    : ["ok", "watching"].includes(String(state.orchestrator?.status || ""))
                      ? (state.orchestrator?.statusText || t("orch.status.running"))
                      : (state.orchestrator?.statusText || t("orch.status.idle"))
                }
                tone={["tuning", "picking", "bootstrap"].includes(String(state.orchestrator?.status || "")) ? "warn" : ["ok", "watching"].includes(String(state.orchestrator?.status || "")) ? "ok" : "muted"}
              />
            ) : <StatusPill label={modeSwitching ? (locale === "ru" ? "Переключение…" : "Switching…") : runtimeLabel(status)} tone={statusTone(status)} />}
          </div>
        </div>
      </section>

      <div className="grid w-full shrink-0 grid-cols-5 gap-2.5">
        {cards.map((card) => {
          const componentId = card.kind === "mode" && active !== "none" ? active : card.kind === "tg" ? "tg-ws-proxy" : null;
          return (
          <button key={card.kind} disabled={!componentId} onClick={() => componentId && onOpenComponent?.(componentId)} className="quick-status-card soft-card min-w-0 rounded-[15px] border border-line-1 px-3.5 py-3.5 text-left disabled:cursor-default">
            <AnimatePresence mode="wait" initial={false}>
              <motion.div key={`${card.label}-${card.status}`} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.18 }} className="flex min-w-0 items-center gap-2 leading-none text-[12px] text-fg-dim"><StatusIcon kind={card.kind} status={card.status} /><span className="truncate leading-5">{card.label}</span></motion.div>
            </AnimatePresence>
            <div className="relative mt-2.5 h-5 overflow-hidden">
              <AnimatePresence mode="wait" initial={false}>
                <motion.div
                  key={`${card.label}-${card.value}`}
                  initial={{ opacity: 0, y: 5 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -4 }}
                  transition={{ duration: 0.16, ease: [0.22, 1, 0.36, 1] }}
                  className="truncate text-[16px] font-semibold text-fg"
                >
                  {card.value}
                </motion.div>
              </AnimatePresence>
            </div>
          </button>
          );
        })}
      </div>
      </div>
    </div>
  );
}
