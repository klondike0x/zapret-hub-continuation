import { startTransition, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { flushSync } from "react-dom";
import { motion, MotionConfig } from "framer-motion";
import { WindowFrame } from "@/components/shell/WindowFrame";
import { Sidebar, type NavKey } from "@/components/shell/Sidebar";
import { ToastProvider } from "@/components/shell/ToastHost";
import { OrchestratorUx } from "@/components/shell/OrchestratorUx";
import { AppUpdateModal, type AppUpdatePrompt } from "@/components/shell/AppUpdateModal";
import { ComponentUpdatesModal, type ComponentUpdateItem } from "@/components/shell/ComponentUpdatesModal";
import { SettingsModal, type SettingsTab } from "@/components/settings/SettingsModal";
import { OnboardingFlow } from "@/components/onboarding/OnboardingFlow";
import { QuickAccessPage } from "@/pages/QuickAccessPage";
import { ComponentsPage } from "@/pages/ComponentsPage";
import { ModsPage } from "@/pages/ModsPage";
import { FilesPage } from "@/pages/FilesPage";
import { InstalledModsPage } from "@/pages/InstalledModsPage";
import { LogsPage } from "@/pages/LogsPage";
import { useAppState, useBridge, patchOptimistic, pauseStatePushes } from "@/hooks/useBridgeState";
import { useLocale } from "@/hooks/useLocale";
import { useSmoothWheel } from "@/hooks/useSmoothWheel";
import { SoundEffects } from "@/components/sound/SoundEffects";
import { getBridge } from "@/bridge";
import { uiAssetUrl } from "@/lib/assets";
import { serviceIconUrl } from "@/lib/serviceAssets";
import { TextContextMenu } from "@/components/shell/TextContextMenu";
import { SurfGameModal } from "@/components/onboarding/SurfGameModal";

const NAV_KEYS: NavKey[] = ["quick", "components", "installed", "mods", "files", "logs", "settings"];
const PRELOAD_ORDER: NavKey[] = ["components", "installed", "settings", "mods", "files", "logs"];

function preloadImage(src: string, timeoutMs = 1200) {
  return new Promise<void>((resolve) => {
    const img = new Image();
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      resolve();
    };
    const timer = window.setTimeout(finish, timeoutMs);
    img.decoding = "async";
    img.onload = () => {
      window.clearTimeout(timer);
      const decoded = img.decode?.();
      if (decoded && typeof (decoded as Promise<void>).then === "function") {
        void (decoded as Promise<void>).then(finish).catch(finish);
        return;
      }
      finish();
    };
    img.onerror = () => {
      window.clearTimeout(timer);
      finish();
    };
    img.src = src;
  });
}

function waitFrames(count = 2) {
  return new Promise<void>((resolve) => {
    const step = (left: number) => {
      if (left <= 0) {
        resolve();
        return;
      }
      requestAnimationFrame(() => step(left - 1));
    };
    step(count);
  });
}

export default function App() {
  return (
    <div className="grid h-full w-full place-items-center bg-transparent p-[6px]">
      <div className="app-window relative h-full w-full overflow-hidden rounded-[18px] border border-line-1">
        <TextContextMenu />
        <ToastProvider>
          <OrchestratorUx />
          <Shell />
        </ToastProvider>
      </div>
    </div>
  );
}

function Shell() {
  useSmoothWheel();
  const bridge = useBridge();
  const [nav, setNav] = useState<NavKey>("quick");
  const [mountedPages, setMountedPages] = useState<Set<NavKey>>(() => new Set<NavKey>());
  const [settingsTab, setSettingsTab] = useState<SettingsTab>("app");
  const state = useAppState();
  const { t, locale } = useLocale();
  const [onboardingSkipped, setOnboardingSkipped] = useState(false);
  const [forcedOnboarding, setForcedOnboarding] = useState(false);
  const [forcedOnboardingMode, setForcedOnboardingMode] = useState<"zapret" | "zapret2" | "none">("zapret");
  const [onboardingExiting, setOnboardingExiting] = useState(false);
  const [onboardingFadeOut, setOnboardingFadeOut] = useState(false);
  const [focusedComponent, setFocusedComponent] = useState<string | null>(null);
  const [settingsChild, setSettingsChild] = useState<"mods" | "files" | "mods2" | "files2" | null>(null);
  const [sidebarPeek, setSidebarPeek] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const sidebarPersistTimer = useRef(0);
  const [updatePrompt, setUpdatePrompt] = useState<AppUpdatePrompt | null>(null);
  const [updateGameOpen, setUpdateGameOpen] = useState(false);
  const [componentUpdates, setComponentUpdates] = useState<ComponentUpdateItem[] | null>(null);
  const [introActive, setIntroActive] = useState(false);
  const [uiPrewarmed, setUiPrewarmed] = useState(false);
  const bootRevealedRef = useRef(false);
  const onboardingExitDoneRef = useRef(false);
  const onboardingExitFallbackRef = useRef(0);
  const onboardingExitStartedAtRef = useRef(0);
  const pendingOnboardingCompleteRef = useRef<{
    mode?: "zapret" | "zapret2" | "none";
    selected?: string[];
    dismiss?: boolean;
  } | null>(null);
  // While exiting, ignore backend completed/forceOpen — overlay must stay until fade ends.
  const onboardingExitingRef = useRef(false);
  onboardingExitingRef.current = onboardingExiting;
  const onboardingFadeOutRef = useRef(false);
  onboardingFadeOutRef.current = onboardingFadeOut;

  const showOnboarding = state
    ? forcedOnboarding || Boolean(state.onboarding.forceOpen) || (!state.onboarding.completed && !onboardingSkipped)
    : false;
  // Hard gate: exiting keeps the shell mounted even if completed flips mid-fade.
  const onboardingVisible = showOnboarding || onboardingExiting;
  const onboardingForced = forcedOnboarding || Boolean(state?.onboarding.forceOpen);
  const onboardingMode = forcedOnboarding
    ? forcedOnboardingMode
    : (state?.onboarding.initialMode ?? "zapret");

  const finishOnboardingExit = () => {
    if (onboardingExitDoneRef.current) return;
    // Never cut before the fade has had time to paint (guards instant onAnimationComplete /
    // reduced-motion / WebEngine quirks that would otherwise look like a hard snap).
    const started = onboardingExitStartedAtRef.current;
    if (started && performance.now() - started < 420) {
      window.clearTimeout(onboardingExitFallbackRef.current);
      onboardingExitFallbackRef.current = window.setTimeout(() => {
        finishOnboardingExit();
      }, Math.max(16, 450 - (performance.now() - started)));
      return;
    }
    onboardingExitDoneRef.current = true;
    onboardingExitStartedAtRef.current = 0;
    window.clearTimeout(onboardingExitFallbackRef.current);
    const payload = pendingOnboardingCompleteRef.current;
    pendingOnboardingCompleteRef.current = null;
    if (payload) {
      void getBridge().call("onboarding.complete", payload);
    }
    setForcedOnboarding(false);
    setForcedOnboardingMode("zapret");
    setOnboardingSkipped(true);
    setOnboardingFadeOut(false);
    setOnboardingExiting(false);
  };

  const beginOnboardingExit = (payload?: {
    mode?: "zapret" | "zapret2" | "none";
    selected?: string[];
    dismiss?: boolean;
  }) => {
    if (onboardingExitingRef.current) return;
    onboardingExitDoneRef.current = false;
    // Capture complete args now — after fade, forceOpen/forced flags may already be cleared.
    if (payload) {
      pendingOnboardingCompleteRef.current = payload;
    } else if (forcedOnboarding || Boolean(state?.onboarding.forceOpen)) {
      pendingOnboardingCompleteRef.current = { dismiss: true };
    } else {
      pendingOnboardingCompleteRef.current = null;
    }
    // Quiet state for the full fade — emit mid-fade drops frames → snap.
    pauseStatePushes(1200);
    onboardingExitStartedAtRef.current = performance.now();
    // Lock overlay mounted + keep main shell hidden immediately.
    setOnboardingExiting(true);
    setOnboardingFadeOut(false);
    // Double-rAF: paint one opaque frame before opacity→0 so WebEngine actually interpolates.
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        if (onboardingExitDoneRef.current) return;
        setOnboardingFadeOut(true);
      });
    });
    window.clearTimeout(onboardingExitFallbackRef.current);
    // Hard fallback if Framer onAnimationComplete never fires.
    onboardingExitFallbackRef.current = window.setTimeout(() => {
      finishOnboardingExit();
    }, 700);
  };

  useEffect(() => () => window.clearTimeout(onboardingExitFallbackRef.current), []);

  useEffect(() => {
    if (!state) return;
    setSidebarCollapsed(state.settings.sidebarCollapsed);
  }, [state?.settings.sidebarCollapsed]);

  useEffect(() => {
    return () => window.clearTimeout(sidebarPersistTimer.current);
  }, []);

  useEffect(() => {
    const off = getBridge().subscribe("component.updates-available", (payload) => {
      if (Array.isArray(payload?.updates) && payload.updates.length) setComponentUpdates(payload.updates);
    });
    return off;
  }, []);

  // Warm the FULL shell (+ onboarding panels) under the HTML preloader, then uncover.
  useEffect(() => {
    if (!state || bootRevealedRef.current) return;
    let cancelled = false;
    let armTimer = 0;
    let safetyTimer = 0;

    const uncover = () => {
      if (cancelled || bootRevealedRef.current) return;
      bootRevealedRef.current = true;
      void getBridge().call("ui.ready", undefined);
      const hideBoot = (window as Window & { __zapretHideStartupBoot?: () => void }).__zapretHideStartupBoot;
      hideBoot?.();
      armTimer = window.setTimeout(() => {
        if (!cancelled) setIntroActive(true);
      }, showOnboarding ? 120 : 40);
    };

    const forceLayout = () => {
      try {
        document.querySelector(".app-shell")?.getBoundingClientRect();
        document.querySelectorAll(
          ".page-transition, .onboarding-root, .onboarding-wave-grid, .onboarding-prewarm-services, .onboarding-prewarm-done, .onboarding-service-card",
        ).forEach((node) => {
          (node as HTMLElement).getBoundingClientRect();
        });
      } catch {
        /* ignore */
      }
    };

    const warmThenReveal = async () => {
      try {
        await Promise.race([
          document.fonts?.ready ?? Promise.resolve(),
          new Promise<void>((resolve) => window.setTimeout(resolve, 800)),
        ]);
      } catch {
        /* ignore */
      }

      // Mount every shell page once under the preloader. Do NOT flushSync-cycle
      // nav keys — that blocks the UI thread and forces the OS loading cursor.
      flushSync(() => {
        setMountedPages(new Set<NavKey>(NAV_KEYS));
        setUiPrewarmed(true);
      });

      const soundWarm = (async () => {
        try {
          const { preloadSounds } = await import("@/lib/sounds");
          await preloadSounds();
        } catch {
          /* ignore */
        }
      })();

      await Promise.all([
        preloadImage(uiAssetUrl("icons/app.png")),
        preloadImage(uiAssetUrl("icons/component_zapret.svg")),
        preloadImage(uiAssetUrl("icons/component_zapret2.svg")),
        ...state.services.available.map((service) => preloadImage(serviceIconUrl(service.id), 900)),
        soundWarm,
      ]);

      // Wait until onboarding's offscreen service grid + done page exist, then
      // force layout/paint so 1→2 / →done never cold-mount under the blur slide.
      for (let attempt = 0; attempt < 24 && !cancelled; attempt += 1) {
        const servicesWarm = document.querySelector(".onboarding-prewarm-services .onboarding-wave-grid");
        const doneWarm = document.querySelector(".onboarding-prewarm-done");
        if (!showOnboarding || (servicesWarm && doneWarm)) break;
        forceLayout();
        await waitFrames(1);
      }

      forceLayout();
      await waitFrames(6);
      forceLayout();

      if (!cancelled) uncover();
    };

    safetyTimer = window.setTimeout(uncover, 4500);
    void warmThenReveal();
    return () => {
      cancelled = true;
      window.clearTimeout(armTimer);
      window.clearTimeout(safetyTimer);
    };
  }, [state, showOnboarding]);

  useEffect(() => {
    setMountedPages((current) => {
      if (current.has(nav)) return current;
      const next = new Set(current);
      next.add(nav);
      return next;
    });
  }, [nav]);

  // Pages are already mounted in the preloader — no staggered post-onboarding mounts.
  useEffect(() => {
    if (!state || onboardingVisible || uiPrewarmed) return;
    let cancelled = false;
    let index = 0;
    let timer = 0;

    const mountNext = () => {
      if (cancelled) return;
      const key = PRELOAD_ORDER[index++];
      if (!key) return;
      startTransition(() => {
        setMountedPages((current) => {
          if (current.has(key)) return current;
          const next = new Set(current);
          next.add(key);
          return next;
        });
      });
      if (index < PRELOAD_ORDER.length) {
        timer = window.setTimeout(mountNext, 80);
      }
    };

    timer = window.setTimeout(mountNext, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [state, onboardingVisible, uiPrewarmed]);

  useEffect(() => {
    const off = getBridge().subscribe("app.update-available", (payload) => {
      setUpdatePrompt(payload);
    });
    return off;
  }, []);

  const labels: Record<NavKey, string> = {
    quick: t("nav.quick"),
    components: t("nav.components"),
    installed: t("nav.installed"),
    mods: t("nav.mods"),
    files: t("nav.files"),
    logs: t("nav.logs"),
    settings: t("settings.title"),
  };

  const pageNodes = useMemo(() => {
    const nodes: Partial<Record<NavKey, ReactNode>> = {};
    for (const key of mountedPages) {
      if (key === "quick") {
        nodes.quick = <QuickAccessPage onOpenComponent={(id) => { setFocusedComponent(id); setNav("components"); }} />;
      } else if (key === "components") {
        nodes.components = <ComponentsPage focusId={focusedComponent} onFocusHandled={() => setFocusedComponent(null)} onConfigure={(id) => {
          setSettingsTab(id === "tg-ws-proxy" ? "tg" : id === "zapret2" ? "zapret2" : "zapret");
          setNav("settings");
        }} onReconfigure={() => {
          setForcedOnboardingMode("zapret");
          setForcedOnboarding(true);
        }} onOpenManual={(backend, target) => {
          setSettingsChild(backend === "zapret2" ? (target === "mods" ? "mods2" : "files2") : target);
          setNav(target);
        }} />;
      } else if (key === "mods") {
        nodes.mods = <ModsPage
          nestedInSettings={settingsChild === "mods" || settingsChild === "mods2"}
          runtime={settingsChild === "mods2" ? "zapret2" : "zapret"}
          onBack={() => {
            const backTab = settingsChild === "mods2" ? "zapret2" : "zapret";
            setSettingsChild(null);
            setSettingsTab(backTab);
            setNav("settings");
          }}
        />;
      } else if (key === "files") {
        nodes.files = <FilesPage
          nestedInSettings={settingsChild === "files" || settingsChild === "files2"}
          runtime={settingsChild === "files2" ? "zapret2" : "zapret"}
          onBack={() => {
            const backTab = settingsChild === "files2" ? "zapret2" : "zapret";
            setSettingsChild(null);
            setSettingsTab(backTab);
            setNav("settings");
          }}
        />;
      } else if (key === "installed") {
        nodes.installed = <InstalledModsPage />;
      } else if (key === "logs") {
        nodes.logs = <LogsPage active={nav === "logs"} />;
      } else if (key === "settings") {
        nodes.settings = <SettingsModal
          open
          embedded
          initialTab={settingsTab}
          onClose={() => setNav("quick")}
          onNavigate={(target) => {
            if (target === "mods" || target === "files" || target === "mods2" || target === "files2") {
              setSettingsChild(target);
              setNav(target === "mods2" ? "mods" : target === "files2" ? "files" : target);
              return;
            }
            setNav(target);
          }}
          onReconfigureZapret={() => {
            setForcedOnboardingMode("zapret");
            setForcedOnboarding(true);
          }}
        />;
      }
    }
    return nodes;
  }, [mountedPages, focusedComponent, settingsChild, settingsTab, nav]);

  const navAccent: Record<NavKey, string> = {
    quick: "#9b69e8",
    components: "#4ebe85",
    installed: "#a78bfa",
    mods: "#9b69e8",
    files: "#e15860",
    logs: "#e15860",
    settings: "#9aa0a9",
  };

  useEffect(() => {
    const fromQuery = new URLSearchParams(window.location.search).get("theme");
    const resolved = state?.settings.theme ?? fromQuery ?? "night";
    document.documentElement.dataset.theme = resolved === "light" ? "concrete" : resolved === "night" ? "aurora" : "obsidian";
  }, [state?.settings.theme]);

  useEffect(() => {
    const raw = state?.settings.uiScale ?? "1";
    const scale = raw === "0.75" || raw === "1.25" || raw === "1" ? raw : "1";
    document.documentElement.style.zoom = scale;
    document.documentElement.dataset.uiScale = scale;
  }, [state?.settings.uiScale]);

  // HTML #startup-boot covers the window until state is ready; keep root empty underneath.
  if (!state) return <div className="h-full w-full bg-transparent" aria-hidden="true" />;
  const sidebarVisible = !sidebarCollapsed || sidebarPeek;
  const sidebarNav = settingsChild ? "settings" : nav;

  const toggleSidebar = () => {
    const next = !sidebarCollapsed;
    setSidebarCollapsed(next);
    if (next) setSidebarPeek(false);
    window.clearTimeout(sidebarPersistTimer.current);
    // Persist after the content-surface slide so emit_state never fights it.
    sidebarPersistTimer.current = window.setTimeout(() => {
      patchOptimistic({ settings: { sidebarCollapsed: next } });
      void bridge.call("settings.apply", { patch: { sidebarCollapsed: next } });
    }, 320);
  };

  return (
      <div
        className="app-shell flex h-full flex-col"
        data-page={nav}
        style={{ "--nav-accent": navAccent[nav] } as React.CSSProperties}
      >
      <SoundEffects state={state} />
      <div
        className="flex min-h-0 flex-1 flex-col"
        aria-hidden={onboardingVisible ? true : undefined}
        style={
          // Shell stays painted under onboarding (warmed at preloader). Only block
          // input — fading the overlay then reveals this UI instead of a black hole.
          onboardingVisible ? { pointerEvents: "none" } : undefined
        }
      >
      <WindowFrame sidebarCollapsed={sidebarCollapsed} onToggleSidebar={toggleSidebar} />
      <div className="shell-body relative min-h-0 flex-1 overflow-hidden bg-bg-0">
        {sidebarCollapsed && !sidebarPeek && (
          <div className="absolute bottom-0 left-0 top-0 z-30 w-10" onPointerEnter={() => setSidebarPeek(true)} aria-hidden="true" />
        )}
        {/* Sidebar stays put — only the content surface slides over it. */}
        <div
          className="absolute bottom-0 left-0 top-0 z-0 w-[74px]"
          aria-hidden={!sidebarVisible}
          onPointerLeave={() => {
            if (sidebarCollapsed) setSidebarPeek(false);
          }}
        >
          <Sidebar current={sidebarNav} onSelect={(target) => {
            setSettingsChild(null);
            if (target === "settings") setSettingsTab("app");
            setNav(target);
          }} labels={labels} />
        </div>
        <motion.main
          initial={false}
          animate={{ left: sidebarVisible ? 74 : 0 }}
          transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
          className={`content-surface absolute bottom-0 right-0 top-0 z-10 overflow-hidden border-r-0 border-b-0 border-t border-line-1 transition-[border-radius,border-color,background,background-color] duration-[400ms] ease-[cubic-bezier(0.33,0,0.2,1)] ${sidebarVisible ? "rounded-tl-[16px] border-l" : "rounded-tl-none border-l-0"}`}
          style={{ willChange: "left" }}
        >
          {NAV_KEYS.map((key) => {
            if (!mountedPages.has(key)) return null;
            const active = nav === key;
            // After prewarm, only keep the active page painted under onboarding.
            // Painting every page every frame made step slides hitch.
            return (
              <motion.div
                key={key}
                initial={false}
                animate={{ opacity: active ? 1 : 0 }}
                transition={{ duration: 0.22, ease: [0.33, 0, 0.2, 1] }}
                className="page-transition absolute inset-0"
                style={{
                  pointerEvents: active ? "auto" : "none",
                  zIndex: active ? 2 : 0,
                  visibility: active ? "visible" : "hidden",
                  contentVisibility: active ? "visible" : "hidden",
                }}
                aria-hidden={!active}
              >
                {pageNodes[key]}
              </motion.div>
            );
          })}
        </motion.main>
      </div>
      </div>
      {onboardingVisible && (
        <MotionConfig reducedMotion="never">
          <motion.div
            className={`onboarding-fade-shell absolute inset-0 z-50${onboardingFadeOut ? " is-exiting" : ""}`}
            initial={false}
            animate={{ opacity: onboardingFadeOut ? 0 : 1 }}
            transition={{ duration: 0.48, ease: [0.22, 1, 0.36, 1] }}
            onAnimationComplete={() => {
              if (!onboardingFadeOutRef.current) return;
              finishOnboardingExit();
            }}
          >
            <OnboardingFlow
              open
              exiting={onboardingExiting}
              introActive={introActive}
              uiPrewarmed={uiPrewarmed}
              startStep={onboardingForced ? 2 : 0}
              initialMode={onboardingMode}
              onDone={(payload) => beginOnboardingExit(payload)}
            />
          </motion.div>
        </MotionConfig>
      )}
      <AppUpdateModal
        prompt={updatePrompt}
        onClose={() => setUpdatePrompt(null)}
        onPlayGame={() => setUpdateGameOpen(true)}
      />
      <SurfGameModal
        open={updateGameOpen}
        locale={locale === "en" ? "en" : "ru"}
        onClose={() => setUpdateGameOpen(false)}
      />
      <ComponentUpdatesModal updates={componentUpdates} onClose={() => setComponentUpdates(null)} />
    </div>
  );
}
