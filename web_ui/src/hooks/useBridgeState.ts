import { startTransition, useEffect, useState } from "react";
import { getBridge } from "@/bridge";
import type {
  AppState,
  ComponentId,
  Locale,
  OrchestratorStatus,
  RuntimeId,
  RuntimeStatus,
  Settings,
} from "@/bridge/types";

/** Partial settings patch used for optimistic UI overlays. */
export type SettingsPatch = Partial<Settings> & {
  locale?: Locale;
  modeOrder?: RuntimeId[];
};

type Optimistic = {
  settings?: SettingsPatch;
  runtime?: Partial<{ active: RuntimeId; order: RuntimeId[]; status: RuntimeStatus }>;
  components?: Partial<Record<ComponentId, { status?: string; enabled?: boolean }>>;
  mods?: Record<string, { enabled?: boolean }>;
  mods2?: Record<string, { enabled?: boolean }>;
  servicesSelected?: string[];
  orchestrator?: Partial<OrchestratorStatus>;
};

let baseState: AppState | null = null;
let optimistic: Optimistic = {};
const listeners = new Set<() => void>();
/** Drop non-urgent state / runtime pushes until this time (ms since performance.now origin). */
let quietUntilMs = 0;

/** Pause state.changed + runtime.status application so blur slides aren't interrupted. */
export function pauseStatePushes(ms = 420) {
  quietUntilMs = Math.max(quietUntilMs, performance.now() + ms);
}

function notify() {
  for (const listener of listeners) listener();
}

function deepMergeSettings(base: Settings, patch?: SettingsPatch): Settings {
  if (!patch) return base;
  const next: Settings = { ...base, ...patch };
  if (patch.zapret) next.zapret = { ...base.zapret, ...patch.zapret };
  if (patch.zapret2) next.zapret2 = { ...base.zapret2, ...patch.zapret2 };
  if (patch.vpn) next.vpn = { ...base.vpn, ...patch.vpn };
  if (patch.tg) next.tg = { ...base.tg, ...patch.tg };
  if (patch.dns) next.dns = { ...base.dns, ...patch.dns };
  // locale / modeOrder live outside Settings in AppState
  delete (next as Settings & { locale?: Locale }).locale;
  delete (next as Settings & { modeOrder?: RuntimeId[] }).modeOrder;
  return next;
}

function mergeSettingsPatch(current: SettingsPatch | undefined, patch: SettingsPatch): SettingsPatch {
  const next: SettingsPatch = { ...current, ...patch };
  if (patch.zapret || current?.zapret) {
    next.zapret = { ...(current?.zapret as object), ...(patch.zapret as object) } as Settings["zapret"];
  }
  if (patch.zapret2 || current?.zapret2) {
    next.zapret2 = { ...(current?.zapret2 as object), ...(patch.zapret2 as object) } as Settings["zapret2"];
  }
  if (patch.vpn || current?.vpn) {
    next.vpn = { ...(current?.vpn as object), ...(patch.vpn as object) } as Settings["vpn"];
  }
  if (patch.tg || current?.tg) {
    next.tg = { ...(current?.tg as object), ...(patch.tg as object) } as Settings["tg"];
  }
  if (patch.dns || current?.dns) {
    next.dns = { ...(current?.dns as object), ...(patch.dns as object) } as Settings["dns"];
  }
  return next;
}

function mergeDisplayed(base: AppState, opt: Optimistic): AppState {
  let next: AppState = base;
  if (opt.settings) {
    const settings = deepMergeSettings(base.settings, opt.settings);
    next = {
      ...next,
      settings,
      ui: {
        ...next.ui,
        ...(opt.settings.locale ? { locale: opt.settings.locale } : null),
        ...(opt.settings.theme ? { theme: opt.settings.theme } : null),
      },
    };
  }
  if (opt.runtime) {
    next = {
      ...next,
      runtime: {
        ...next.runtime,
        ...opt.runtime,
        ...(opt.settings?.modeOrder ? { order: opt.settings.modeOrder } : null),
      },
    };
  } else if (opt.settings?.modeOrder) {
    next = { ...next, runtime: { ...next.runtime, order: opt.settings.modeOrder } };
  }
  if (opt.components) {
    const components = { ...next.components };
    for (const id of Object.keys(opt.components) as ComponentId[]) {
      const patch = opt.components[id];
      if (!patch || !components[id]) continue;
      components[id] = {
        ...components[id],
        ...(patch.status !== undefined
          ? { status: patch.status as typeof components[typeof id]["status"] }
          : null),
        ...(patch.enabled !== undefined ? { enabled: patch.enabled } : null),
      };
    }
    next = { ...next, components };
  }
  if (opt.mods) {
    next = {
      ...next,
      mods: next.mods.map((mod) => (opt.mods?.[mod.id] ? { ...mod, ...opt.mods[mod.id] } : mod)),
    };
  }
  if (opt.mods2) {
    next = {
      ...next,
      mods2: (next.mods2 || []).map((mod) => (opt.mods2?.[mod.id] ? { ...mod, ...opt.mods2[mod.id] } : mod)),
    };
  }
  if (opt.servicesSelected) {
    next = { ...next, services: { ...next.services, selected: opt.servicesSelected } };
  }
  if (opt.orchestrator) {
    next = {
      ...next,
      orchestrator: {
        ...(next.orchestrator || {
          mode: "manual",
          status: "idle",
          statusText: "",
          isAuto: false,
        }),
        ...opt.orchestrator,
      },
    };
  }
  return next;
}

function sameValue(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (a && b && typeof a === "object" && typeof b === "object") {
    try {
      return JSON.stringify(a) === JSON.stringify(b);
    } catch {
      return false;
    }
  }
  return false;
}

function pruneOptimistic(base: AppState, opt: Optimistic): Optimistic {
  const next: Optimistic = { ...opt };

  if (opt.settings) {
    const kept: SettingsPatch = {};
    let keepAny = false;
    for (const [key, value] of Object.entries(opt.settings) as [keyof SettingsPatch, unknown][]) {
      if (key === "locale") {
        if (value !== base.ui.locale) {
          kept.locale = value as Locale;
          keepAny = true;
        }
        continue;
      }
      if (key === "modeOrder") {
        if (!sameValue(value, base.runtime.order)) {
          kept.modeOrder = value as RuntimeId[];
          keepAny = true;
        }
        continue;
      }
      if (key === "zapret" || key === "zapret2" || key === "vpn" || key === "tg" || key === "dns") {
        const baseNest = base.settings[key] as Record<string, unknown>;
        const patchNest = value as Record<string, unknown>;
        const nestKept: Record<string, unknown> = {};
        let nestAny = false;
        for (const [nk, nv] of Object.entries(patchNest || {})) {
          if (!sameValue(nv, baseNest?.[nk])) {
            nestKept[nk] = nv;
            nestAny = true;
          }
        }
        if (nestAny) {
          (kept as Record<string, unknown>)[key] = nestKept;
          keepAny = true;
        }
        continue;
      }
      if (!sameValue(value, (base.settings as unknown as Record<string, unknown>)[key as string])) {
        (kept as Record<string, unknown>)[key] = value;
        keepAny = true;
      }
    }
    next.settings = keepAny ? kept : undefined;
  }

  if (opt.runtime) {
    const runtime: Optimistic["runtime"] = {};
    let keep = false;
    if (opt.runtime.active !== undefined && opt.runtime.active !== base.runtime.active) {
      runtime.active = opt.runtime.active;
      keep = true;
    }
    if (opt.runtime.order && !sameValue(opt.runtime.order, base.runtime.order)) {
      runtime.order = opt.runtime.order;
      keep = true;
    }
    if (opt.runtime.status !== undefined && opt.runtime.status !== base.runtime.status) {
      // Keep starting/stopping until backend settles to on/off.
      if (opt.runtime.status === "starting" || opt.runtime.status === "stopping") {
        if (base.runtime.status === "starting" || base.runtime.status === "stopping") {
          /* backend still transitioning — drop local */
        } else if (base.runtime.status === "on" || base.runtime.status === "off" || base.runtime.status === "error") {
          /* settled */
        } else {
          runtime.status = opt.runtime.status;
          keep = true;
        }
      } else {
        runtime.status = opt.runtime.status;
        keep = true;
      }
    }
    next.runtime = keep ? runtime : undefined;
  }

  if (opt.components) {
    const components: Optimistic["components"] = {};
    let keep = false;
    for (const id of Object.keys(opt.components) as ComponentId[]) {
      const patch = opt.components[id];
      if (!patch) continue;
      const actual = base.components[id];
      if (!actual) continue;
      const nextPatch: { status?: string; enabled?: boolean } = {};
      if (patch.status !== undefined && patch.status !== actual.status) {
        if (patch.status === "starting" || patch.status === "stopping") {
          // Drop once backend settles to a terminal status (including off/error).
          if (actual.status !== "on" && actual.status !== "off" && actual.status !== "error") {
            nextPatch.status = patch.status;
          }
        } else {
          nextPatch.status = patch.status;
        }
      }
      if (patch.enabled !== undefined && patch.enabled !== Boolean(actual.enabled)) {
        nextPatch.enabled = patch.enabled;
      }
      if (nextPatch.status !== undefined || nextPatch.enabled !== undefined) {
        components[id] = nextPatch;
        keep = true;
      }
    }
    next.components = keep ? components : undefined;
  }

  if (opt.mods) {
    const mods: Optimistic["mods"] = {};
    let keep = false;
    for (const [id, patch] of Object.entries(opt.mods)) {
      const actual = base.mods.find((mod) => mod.id === id);
      if (!actual) continue;
      if (patch.enabled !== undefined && patch.enabled !== actual.enabled) {
        mods[id] = { enabled: patch.enabled };
        keep = true;
      }
    }
    next.mods = keep ? mods : undefined;
  }

  if (opt.mods2) {
    const mods2: Optimistic["mods2"] = {};
    let keep = false;
    for (const [id, patch] of Object.entries(opt.mods2)) {
      const actual = (base.mods2 || []).find((mod) => mod.id === id);
      if (!actual) continue;
      if (patch.enabled !== undefined && patch.enabled !== actual.enabled) {
        mods2[id] = { enabled: patch.enabled };
        keep = true;
      }
    }
    next.mods2 = keep ? mods2 : undefined;
  }

  if (opt.servicesSelected && sameValue(opt.servicesSelected, base.services.selected)) {
    next.servicesSelected = undefined;
  }

  if (opt.orchestrator) {
    const actual = base.orchestrator;
    if (
      actual &&
      (opt.orchestrator.mode === undefined || opt.orchestrator.mode === actual.mode) &&
      (opt.orchestrator.isAuto === undefined || opt.orchestrator.isAuto === actual.isAuto) &&
      (opt.orchestrator.status === undefined || opt.orchestrator.status === actual.status)
    ) {
      next.orchestrator = undefined;
    }
  }

  return next;
}

/** Apply an optimistic patch immediately; backend state.changed will prune it when caught up. */
export function patchOptimistic(patch: Optimistic) {
  optimistic = {
    settings: patch.settings ? mergeSettingsPatch(optimistic.settings, patch.settings) : optimistic.settings,
    runtime: patch.runtime ? { ...optimistic.runtime, ...patch.runtime } : optimistic.runtime,
    components: patch.components
      ? {
          ...optimistic.components,
          ...Object.fromEntries(
            Object.entries(patch.components).map(([id, value]) => [
              id,
              { ...(optimistic.components?.[id as ComponentId] || {}), ...value },
            ]),
          ),
        }
      : optimistic.components,
    mods: patch.mods
      ? {
          ...optimistic.mods,
          ...Object.fromEntries(
            Object.entries(patch.mods).map(([id, value]) => [
              id,
              { ...(optimistic.mods?.[id] || {}), ...value },
            ]),
          ),
        }
      : optimistic.mods,
    mods2: patch.mods2
      ? {
          ...optimistic.mods2,
          ...Object.fromEntries(
            Object.entries(patch.mods2).map(([id, value]) => [
              id,
              { ...(optimistic.mods2?.[id] || {}), ...value },
            ]),
          ),
        }
      : optimistic.mods2,
    servicesSelected: patch.servicesSelected ?? optimistic.servicesSelected,
    orchestrator: patch.orchestrator
      ? { ...optimistic.orchestrator, ...patch.orchestrator }
      : optimistic.orchestrator,
  };
  notify();
}

type Mods = NonNullable<AppState["mods"]>;
type MarketplaceModsOverride = { mods: Mods; mods2: Mods };

let marketplaceModsOverride: MarketplaceModsOverride | null = null;

function marketplaceOnly(mods: Mods) {
  return mods.filter((mod) => Boolean(String(mod.marketplaceSlug || "").trim()));
}

function marketplaceSignature(mods: Mods) {
  // Order-sensitive: reordering must keep the optimistic override until the
  // backend state matches the new sequence (not just the same set of mods).
  return marketplaceOnly(mods)
    .map((mod) => `${mod.id}:${mod.marketplaceSlug}:${mod.version || ""}`)
    .join("|");
}

function mergeMarketplaceMods(current: Mods, authoritative: Mods) {
  return [...current.filter((mod) => !String(mod.marketplaceSlug || "").trim()), ...marketplaceOnly(authoritative)];
}

function setBaseState(next: AppState, urgent = false) {
  if (marketplaceModsOverride) {
    const caughtUp =
      marketplaceSignature(next.mods || []) === marketplaceSignature(marketplaceModsOverride.mods)
      && marketplaceSignature(next.mods2 || []) === marketplaceSignature(marketplaceModsOverride.mods2);
    if (caughtUp) {
      marketplaceModsOverride = null;
    } else {
      next = {
        ...next,
        mods: mergeMarketplaceMods(next.mods || [], marketplaceModsOverride.mods),
        mods2: mergeMarketplaceMods(next.mods2 || [], marketplaceModsOverride.mods2),
      };
    }
  }
  baseState = next;
  optimistic = pruneOptimistic(next, optimistic);
  notify();
  void urgent;
}

let bridgeBootstrapped = false;
let hasState = false;

function ensureBridgeStore() {
  if (bridgeBootstrapped || typeof window === "undefined") return;
  bridgeBootstrapped = true;
  const bridge = getBridge();
  let timer = 0;
  let gotState = false;

  const apply = (next: AppState | null | undefined, urgent = false) => {
    if (!next) return;
    gotState = true;
    const first = !hasState;
    if (!first && !urgent && performance.now() < quietUntilMs) return;
    hasState = true;
    if (first) quietUntilMs = Math.max(quietUntilMs, performance.now() + 2800);
    if (urgent || first) {
      setBaseState(next, true);
      return;
    }
    startTransition(() => setBaseState(next));
  };

  bridge.subscribe("state.changed", (payload) => apply(payload));
  bridge.subscribe("marketplace.mods-changed", (payload) => {
    if (!baseState || !payload) return;
    setBaseState({ ...baseState, mods: payload.mods || [], mods2: payload.mods2 || [] }, true);
  });
  bridge.subscribe("runtime.status", (payload) => {
    if (!payload?.status || !baseState) return;
    // Power status must never be dropped during onboarding/nav quiet windows —
    // otherwise winws can already be up while the UI stays on "Запуск…".
    const current = baseState;
    const nextStatus = payload.status;
    const nextActive = payload.active ?? current.runtime.active;
    if (current.runtime.status === nextStatus && current.runtime.active === nextActive) {
      return;
    }
    setBaseState({
      ...current,
      runtime: {
        ...current.runtime,
        status: nextStatus,
        active: nextActive,
      },
    });
  });
  bridge.subscribe("orchestrator.status", (payload) => {
    if (!payload || !baseState) return;
    const current = baseState;
    setBaseState({
      ...current,
      orchestrator: {
        ...(current.orchestrator || {
          mode: "manual",
          status: "idle",
          statusText: "",
          isAuto: false,
        }),
        ...payload,
      },
      settings: {
        ...current.settings,
        zapret: {
          ...current.settings.zapret,
          controlMode: payload.mode ?? current.settings.zapret.controlMode ?? "manual",
        },
      },
    });
  });

  const poll = async () => {
    let delay = 40;
    while (!gotState) {
      try {
        const value = await bridge.call("state.get", undefined);
        if (value) {
          apply(value, true);
          return;
        }
      } catch {
        /* still starting */
      }
      await new Promise<void>((resolve) => {
        timer = window.setTimeout(resolve, delay);
      });
      delay = Math.min(250, delay + 20);
    }
  };
  void poll();
  void timer;
}

export function useAppState(): AppState | null {
  const [, setTick] = useState(0);

  useEffect(() => {
    ensureBridgeStore();
    const onChange = () => setTick((value) => value + 1);
    listeners.add(onChange);
    return () => {
      listeners.delete(onChange);
    };
  }, []);

  if (!baseState) return null;
  return mergeDisplayed(baseState, optimistic);
}
export async function refreshAppState(): Promise<AppState | null> {
  const next = await getBridge().call("state.get", undefined);
  if (next) setBaseState(next, true);
  return next;
}

export function applyMarketplaceMods(mods: AppState["mods"], mods2: AppState["mods2"]) {
  const nextMods = mods || [];
  const nextMods2 = mods2 || [];
  const override = { mods: marketplaceOnly(nextMods), mods2: marketplaceOnly(nextMods2) };
  marketplaceModsOverride = override;
  if (!baseState) {
    return;
  }
  setBaseState({
    ...baseState,
    mods: mergeMarketplaceMods(baseState.mods || [], nextMods),
    mods2: mergeMarketplaceMods(baseState.mods2 || [], nextMods2),
  }, true);
  marketplaceModsOverride = override;
}

export async function refreshMarketplaceMods(slug = "", timeoutMs = 60_000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const next = await getBridge().call("marketplace.installed", undefined);
    const mods = next?.mods || [];
    const mods2 = next?.mods2 || [];
    if (!slug || [...mods, ...mods2].some((mod) => mod.marketplaceSlug === slug)) {
      applyMarketplaceMods(mods, mods2);
      return true;
    }
    await new Promise<void>((resolve) => window.setTimeout(resolve, 300));
  }
  return false;
}

export function useBridge() {
  return getBridge();
}

function logsFingerprint(logs: AppState["logs"] | undefined): string {
  if (!logs?.length) return "0";
  const first = logs[0];
  const last = logs[logs.length - 1];
  return `${logs.length}:${first?.id ?? ""}:${last?.id ?? ""}:${last?.message ?? ""}`;
}

/** null = unknown; true/false after first probe (packaged builds may lack logs.get). */
let logsGetSupported: boolean | null = null;

/**
 * Refresh only the logs slice while the Logs page is open.
 * Uses logs.get when available; otherwise state.get but applies only `.logs`
 * (never a full urgent AppState rebuild — that hitch every 1–2s globally).
 */
export function refreshLogs() {
  ensureBridgeStore();
  const bridge = getBridge();
  const applyLogs = (logs: AppState["logs"] | undefined) => {
    if (!logs || !baseState) return;
    if (logsFingerprint(baseState.logs) === logsFingerprint(logs)) return;
    const current = baseState;
    startTransition(() => setBaseState({ ...current, logs }));
  };

  const viaFullState = () =>
    bridge
      .call("state.get", undefined)
      .then((full) => {
        if (full) applyLogs(full.logs);
      })
      .catch(() => undefined);

  if (logsGetSupported === false) {
    void viaFullState();
    return;
  }

  void bridge
    .call("logs.get", undefined)
    .then((logs) => {
      logsGetSupported = true;
      applyLogs(logs);
    })
    .catch(() => {
      logsGetSupported = false;
      void viaFullState();
    });
}
