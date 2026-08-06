import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useAppState, useBridge, pauseStatePushes } from "@/hooks/useBridgeState";
import { useLocale } from "@/hooks/useLocale";
import { useToast } from "@/components/shell/ToastHost";
import { serviceIconNeedsContrast, serviceIconUrl } from "@/lib/serviceAssets";
import { uiAssetUrl } from "@/lib/assets";
import { bridgeLater, bridgeIdle, bridgeAfterTransition } from "@/lib/schedule";
import type { RuntimeId } from "@/bridge/types";
import { playSound } from "@/lib/sounds";
import { SurfGameModal } from "@/components/onboarding/SurfGameModal";

function goToStep(setter: (value: number | ((current: number) => number)) => void, next: number | ((current: number) => number)) {
  // Urgent UI update — never defer navigation behind bridge work.
  setter(next);
}

const accents = ["#f59b34", "#7082ff", "#ff3c60", "#35b7eb", "#58c982", "#8490a4", "#a47ef1", "#7f8ca0"];

function WindowControls() {
  const bridge = useBridge();
  return <div className="flex items-center" onPointerDown={(event) => event.stopPropagation()}>
    <button aria-label="Minimize" onClick={() => bridge.call("window.minimize", undefined)} className="grid h-9 w-9 place-items-center rounded-[9px] text-fg-dim transition-colors hover:bg-bg-3 hover:text-fg"><svg width="12" height="12" viewBox="0 0 12 12"><rect x="2" y="6" width="8" height="1" fill="currentColor" /></svg></button>
    <button aria-label="Close" onClick={() => bridge.call("window.close", undefined)} className="grid h-9 w-9 place-items-center rounded-[9px] text-fg-dim transition-colors hover:bg-[var(--err)] hover:text-white"><svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.3"><path d="M3 3l6 6M9 3l-6 6" /></svg></button>
  </div>;
}

export function OnboardingFlow({
  open,
  exiting = false,
  onDone,
  startStep = 0,
  initialMode = "zapret",
  introActive = true,
  uiPrewarmed = false,
}: {
  open: boolean;
  exiting?: boolean;
  onDone: (payload?: {
    mode?: RuntimeId;
    selected?: string[];
    dismiss?: boolean;
  }) => void;
  startStep?: number;
  initialMode?: RuntimeId;
  introActive?: boolean;
  /** Shell + heavy panels already laid out under the HTML preloader. */
  uiPrewarmed?: boolean;
}) {
  const state = useAppState();
  const bridge = useBridge();
  const { t, locale } = useLocale();
  const toast = useToast();
  const previewStep = window.location.protocol.startsWith("http")
    ? Math.min(5, Math.max(0, Number(new URLSearchParams(window.location.search).get("onboardingStep") ?? 0)))
    : 0;
  const [step, setStep] = useState(() => Math.max(startStep, previewStep));
  const stockDefaults = ["cloudflare", "discord", "youtube", "gaming", "clouds"];
  const [picked, setPicked] = useState<string[]>(
    (state?.services.selected?.length ? state.services.selected : stockDefaults),
  );
  const pickedInitialized = useRef(false);
  const [progress, setProgress] = useState({ current: 0, total: 1, name: "", overallCurrent: 0, overallTotal: 1 });
  const [configuration, setConfiguration] = useState<{ status: "running" | "success" | "error"; name: string }>({ status: "running", name: "" });
  const stepRef = useRef(step);
  const openRef = useRef(open);
  const [selectedMode, setSelectedMode] = useState<RuntimeId>(initialMode);
  /** First-run Zapret: Manual (services grid) vs Auto (orchestrator bootstrap). */
  const [setupMode, setSetupMode] = useState<"manual" | "auto">("manual");
  const [gameOpen, setGameOpen] = useState(false);
  const serviceScrollerRef = useRef<HTMLDivElement>(null);
  const onboardingRootRef = useRef<HTMLDivElement>(null);
  const [serviceEdges, setServiceEdges] = useState({ top: false, bottom: true });
  const readySoundPlayed = useRef(false);
  const reconfigure = startStep >= 2;
  // First-run onboarding only — not "Run setup again" from Zapret.
  const isInitialOnboarding = !reconfigure;

  useEffect(() => bridge.subscribe("onboarding.progress", (value) => setProgress({
    ...value,
    overallCurrent: value.overallCurrent ?? 1,
    overallTotal: value.overallTotal ?? 1,
  })), [bridge]);
  stepRef.current = step;
  openRef.current = open;
  useEffect(() => bridge.subscribe("onboarding.configuration", (result) => {
    setGameOpen(false);
    if (result.status === "success" && openRef.current && stepRef.current === 3) {
      // The next step already communicates success; skip the redundant technical checkmark.
      setConfiguration({ status: "success", name: result.name });
      pauseStatePushes(720);
      goToStep(setStep, 4);
      return;
    }
    setConfiguration({ status: result.status, name: result.name });
  }), [bridge]);
  useEffect(() => {
    if (open) {
      const next = Math.max(startStep, previewStep);
      setSelectedMode(initialMode);
      setSetupMode("manual");
      goToStep(setStep, next);
      readySoundPlayed.current = false;
      setGameOpen(false);
    }
  }, [open, startStep, previewStep, initialMode]);
  // Icons are decoded in App under the preloader — do not decode again mid-intro.
  useEffect(() => {
    if (!open && configuration.status === "running") {
      void bridge.call("onboarding.cancel", undefined);
      setConfiguration({ status: "error", name: "" });
      setGameOpen(false);
    }
  }, [open, configuration.status, bridge]);
  useEffect(() => {
    if (open && step === 4 && !reconfigure && state?.settings.soundsEnabled && !readySoundPlayed.current) {
      readySoundPlayed.current = true;
      // After pathLength draw (0.12 delay + 0.48s) — never during check frames / blur settle.
      window.setTimeout(() => playSound("zapret"), 700);
    }
  }, [open, step, reconfigure, state?.settings.soundsEnabled]);
  useEffect(() => {
    onboardingRootRef.current?.scrollTo({ top: 0, left: 0 });
    serviceScrollerRef.current?.scrollTo({ top: 0, left: 0 });
  }, [step]);
  useEffect(() => {
    if (!open) {
      pickedInitialized.current = false;
      return;
    }
    if (state && !pickedInitialized.current) {
      setPicked(state.services.selected);
      pickedInitialized.current = true;
    }
  }, [open, state]);
  useEffect(() => {
    if (!open || step !== 2 || !(selectedMode === "zapret" || reconfigure)) return;
    const update = () => {
      const element = serviceScrollerRef.current;
      if (!element) return;
      const canScroll = element.scrollHeight > element.clientHeight + 2;
      setServiceEdges({
        top: element.scrollTop > 2,
        bottom: canScroll && element.scrollTop + element.clientHeight < element.scrollHeight - 2,
      });
    };
    let observer: ResizeObserver | null = null;
    let cancelled = false;
    // Wait out the service stagger before ResizeObserver — measuring mid-animation hitch.
    const arm = window.setTimeout(() => {
      if (cancelled) return;
      update();
      if (typeof ResizeObserver !== "undefined" && serviceScrollerRef.current) {
        observer = new ResizeObserver(update);
        observer.observe(serviceScrollerRef.current);
      }
      window.addEventListener("resize", update);
    }, 620);
    return () => {
      cancelled = true;
      window.clearTimeout(arm);
      observer?.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [open, step, selectedMode, reconfigure, state?.services.available.length]);
  if (!state) return null;
  const selectionChanged = [...picked].sort().join("|") !== [...state.services.selected].sort().join("|");
  const flowSteps = reconfigure
    ? [2, 3, 4]
    : selectedMode === "zapret"
      ? (setupMode === "auto" ? [0, 1, 5, 3, 4] : [0, 1, 5, 2, 3, 4])
      : [0, 1, 4];

  const cancelConfiguration = () => {
    if (step !== 3 && configuration.status !== "running") return;
    setConfiguration({ status: "error", name: "" });
    setGameOpen(false);
    bridgeLater(() => bridge.call("onboarding.cancel", undefined));
  };

  const goBack = () => {
    if (step === 3) cancelConfiguration();
    const currentIndex = flowSteps.indexOf(step);
    if (currentIndex > 0) goToStep(setStep, flowSteps[currentIndex - 1]);
  };

  // Fade first; App owns opacity + calls onboarding.complete only AFTER transitionend.
  // Calling complete mid-fade (or unmounting on completed) was the Close-at-end snap.
  const finish = () => {
    if (configuration.status === "running") cancelConfiguration();
    if (reconfigure) {
      onDone();
      return;
    }
    const mode = selectedMode;
    const selected = selectedMode === "zapret" && setupMode !== "auto" ? [...picked] : undefined;
    pauseStatePushes(900);
    onDone({ mode, selected });
  };

  const saveReconfigure = () => {
    if (!selectionChanged) {
      onDone();
      return;
    }
    const id = toast.push({ message: t("toast.applying") });
    void bridge
      .call("services.set", { selected: [...picked] })
      .then(() => {
        toast.push({ id, message: t("toast.applied"), kind: "success" });
        onDone();
      })
      .catch(() => {
        toast.push({ id, message: locale === "ru" ? "Не удалось сохранить" : "Save failed", kind: "error" });
      });
  };

  const skip = () => {
    if (step === 3 || configuration.status === "running") cancelConfiguration();
    if (reconfigure) {
      onDone();
      return;
    }
    finish();
  };

  const next = () => {
    (document.activeElement as HTMLElement | null)?.blur();
    if (step === 1) {
      const mode = selectedMode;
      const target = mode === "zapret" ? 5 : 4;
      // Navigate first — native bridge.call is sync on the Qt UI thread.
      if (target === 4) pauseStatePushes(720);
      goToStep(setStep, target);
      // mode=wait ≈ exit 0.3 + enter 0.3 — keep bridge off the main thread until then.
      const schedule = target === 4 ? (task: () => void) => bridgeAfterTransition(task, 650) : bridgeIdle;
      schedule(() => {
        void bridge.call("runtime.select", { id: mode });
      });
      return;
    }
    if (step === 5) {
      if (setupMode === "auto") {
        setConfiguration({ status: "running", name: "" });
        setProgress({ current: 0, total: 1, name: "", overallCurrent: 0, overallTotal: 1 });
        goToStep(setStep, 3);
        bridgeIdle(() => {
          void bridge.call("orchestrator.setMode", { mode: "auto" });
          void bridge.call("onboarding.configure", { selected: ["cloudflare", "discord", "youtube", "gaming", "clouds"] });
        });
        return;
      }
      goToStep(setStep, 2);
      return;
    }
    if (step === 2) {
      setConfiguration({ status: "running", name: "" });
      setProgress({ current: 0, total: 1, name: "", overallCurrent: 0, overallTotal: 1 });
      const selected = [...picked];
      goToStep(setStep, 3);
      bridgeIdle(() => {
        void bridge.call("orchestrator.setMode", { mode: "manual" });
        void bridge.call("onboarding.configure", { selected });
      });
      return;
    }
    if (step === 3 && configuration.status === "running") return;
    if (step === 3) {
      pauseStatePushes(720);
      goToStep(setStep, 4);
      return;
    }
    if (step === 4) {
      finish();
      return;
    }
    goToStep(setStep, (value) => value + 1);
  };

  const ru = locale === "ru";
  const progressValue = Math.round((Math.max(0, progress.current) / Math.max(1, progress.total)) * 100);
  const hasPrimaryService = picked.some((id) => id !== "telegram" && id !== "telegram-desktop" && id !== "ai");
  const serviceSelectionRequired =
    step === 2 && (selectedMode === "zapret" || reconfigure) && setupMode !== "auto" && !hasPrimaryService;
  const stepEase = [0.22, 1, 0.36, 1] as const;
  // Stock look: mode=wait slide + sectional blur — BUT never put filter on Done's
  // ancestor. An animating filter forces the whole subtree (incl. SVG pathLength)
  // onto an expensive re-raster path; that was the checkmark hitch, not Framer itself.
  const stepTransition = { duration: 0.3, ease: stepEase } as const;
  const stepMotion = step === 4
    ? {
        initial: { opacity: 0, x: 22 },
        animate: { opacity: 1, x: 0 },
        exit: { opacity: 0, x: -22 },
        transition: stepTransition,
      }
    : {
        initial: { opacity: 0, x: 22, filter: "blur(4px)" },
        animate: { opacity: 1, x: 0, filter: "blur(0px)" },
        exit: { opacity: 0, x: -22, filter: "blur(4px)" },
        transition: stepTransition,
      };
  // Keep warm copies mounted for the whole onboarding session (including exit fade).
  // Tearing them down on open→false forced a huge React unmount in the same frame as the fade.
  const keepServicesWarm = (open || exiting) && isInitialOnboarding;
  const keepDoneWarm = (open || exiting) && isInitialOnboarding;

  // Fade is owned by App CSS wrapper — keep root fully opaque here so children
  // don't unmount mid-exit (that caused a hard cut instead of a smooth fade).
  return <AnimatePresence>
    {open && (
    <motion.div
      ref={onboardingRootRef}
      initial={false}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
      className="onboarding-root absolute inset-0 z-50 overflow-hidden bg-bg-0"
      style={{
        pointerEvents: exiting ? "none" : undefined,
        transform: "translateZ(0)",
        contain: "layout style paint",
      }}
      onPointerDown={(event) => {
        if (exiting) return;
        if (event.button !== 0 || (event.target as HTMLElement).closest("button, input, textarea, [contenteditable=true]")) return;
        bridge.call("window.startDrag", undefined);
      }}
    >
      {/* Original Framer background morph (gradient string + x/y) — not crossfade layers.
          On Done (step 4): snap with duration 0 — concurrent gradient string morph steals
          frames from pathLength draw in Qt WebEngine. */}
      <motion.div
        className="pointer-events-none absolute -inset-[30%]"
        initial={{
          background: "radial-gradient(circle at 82% 18%, rgba(72,132,210,.18), transparent 34%), radial-gradient(circle at 20% 86%, rgba(93,92,220,.14), transparent 34%)",
          x: 0,
          y: 0,
        }}
        animate={{
          background: [
            "radial-gradient(circle at 12% 78%, rgba(65,105,215,.20), transparent 34%), radial-gradient(circle at 86% 12%, rgba(118,77,205,.16), transparent 32%)",
            "radial-gradient(circle at 22% 22%, rgba(53,160,197,.17), transparent 34%), radial-gradient(circle at 78% 84%, rgba(93,92,220,.18), transparent 35%)",
            "radial-gradient(circle at 78% 20%, rgba(74,122,210,.19), transparent 34%), radial-gradient(circle at 18% 82%, rgba(78,184,143,.14), transparent 32%)",
            "radial-gradient(circle at 50% 8%, rgba(98,92,215,.19), transparent 34%), radial-gradient(circle at 76% 88%, rgba(50,151,190,.14), transparent 32%)",
            "radial-gradient(circle at 82% 18%, rgba(72,132,210,.18), transparent 34%), radial-gradient(circle at 20% 86%, rgba(93,92,220,.14), transparent 34%)",
          ][Math.min(step === 5 ? 2 : step, 4)],
          x: [0, -18, 22, -10, 0][Math.min(step === 5 ? 2 : step, 4)],
          y: [0, 14, -12, 8, 0][Math.min(step === 5 ? 2 : step, 4)],
        }}
        transition={exiting || step === 4 ? { duration: 0 } : { duration: 0.8, ease: stepEase }}
      />

      <header className="absolute inset-x-0 top-0 z-40 flex h-[50px] items-center justify-between pl-[14px] pr-[7px]">
        <AnimatePresence mode="wait">
          {step > 0 ? (
            <motion.div
              key="brand"
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.22, ease: stepEase }}
              className="flex items-center gap-2"
            >
              <img src={uiAssetUrl("icons/app.png")} alt="" className="h-[22px] w-[22px] object-contain" />
              <span className="brand-font text-[16px] font-semibold text-fg">{t("app.name")}</span>
            </motion.div>
          ) : (
            <span key="empty" />
          )}
        </AnimatePresence>
        <WindowControls />
      </header>

      <main className="absolute inset-x-0 bottom-0 top-[50px] overflow-hidden">
        {keepServicesWarm && (
          <div className="onboarding-prewarm-services pointer-events-none absolute inset-0 -z-10 opacity-0" aria-hidden="true">
            <div className="relative flex h-full flex-col">
              <div className="onboarding-service-scroll scroll-area mt-3 min-h-0 flex-1 overflow-y-auto px-[30px] pb-[86px] pt-2">
                <div className="onboarding-wave-grid mx-auto grid max-w-[820px] grid-cols-5 gap-x-3 gap-y-3">
                  {state.services.available.map((service, index) => {
                    const selected = picked.includes(service.id);
                    return (
                      <div
                        key={`warm-${service.id}`}
                        className={`onboarding-service-card relative flex h-[120px] flex-col items-start rounded-[15px] border px-3.5 pb-2 pt-2 ${selected ? "bg-bg-2" : "border-line-1 bg-bg-1"}`}
                        style={selected ? { borderColor: accents[index % accents.length] } : undefined}
                      >
                        <img src={serviceIconUrl(service.id)} alt="" className={`h-7 w-7 object-contain ${serviceIconNeedsContrast(service.id) ? "service-icon-adaptive" : ""}`} decoding="async" />
                        <div className="mt-2 truncate text-[12px] font-semibold text-fg">{service.name}</div>
                        <div className="mt-1 line-clamp-3 text-[9.5px] leading-[1.4] text-fg-dim">{service.description}</div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
            <div className="absolute inset-0" style={{ filter: "blur(4px)", transform: "translateX(22px)", opacity: 0.01 }} />
          </div>
        )}
        {keepDoneWarm && (
          <div className="onboarding-prewarm-done pointer-events-none absolute inset-0 -z-10 opacity-0" aria-hidden="true">
            <div className="flex h-full items-center justify-center text-center">
              <div className="flex -translate-y-2 flex-col items-center">
                <svg width="72" height="72" viewBox="0 0 72 72" fill="none" aria-hidden="true">
                  <circle cx="36" cy="36" r="31" fill="color-mix(in srgb, var(--ok) 16%, transparent)" />
                  <path d="M22 39.2 L31.2 48.2 L49.2 28.4" stroke="var(--ok)" strokeWidth="4.2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <h1 className="brand-font mt-4 text-[25px] font-semibold text-fg">{t("onboarding.done.title")}</h1>
                <p className="mt-2 text-[13px] text-fg-dim">{t("onboarding.done.body")}</p>
              </div>
            </div>
          </div>
        )}

        <AnimatePresence mode="wait">
          <motion.section
            key={step}
            {...stepMotion}
            className="h-full"
            style={{
              willChange: step === 4 ? "transform, opacity" : "transform, opacity, filter",
              transform: "translateZ(0)",
            }}
          >
            {step === 0 && (
              <div className="flex h-full items-center justify-center pb-2 text-center">
                <div className="flex -translate-y-3 flex-col items-center">
                  <motion.h1
                    className="brand-font text-[27px] font-semibold text-fg"
                    // Single small text blur only — keep the soft intro look without section-wide filter work.
                    initial={{ opacity: 0, y: 10, filter: "blur(10px)" }}
                    animate={introActive ? { opacity: 1, y: 0, filter: "blur(0px)" } : { opacity: 0, y: 10, filter: "blur(10px)" }}
                    transition={{ duration: 0.52, ease: stepEase }}
                  >
                    {state.onboarding.isUpdate ? (ru ? "Zapret Hub обновился" : "Zapret Hub was updated") : t("onboarding.welcome.title")}
                  </motion.h1>
                  <motion.p
                    className="mt-3 max-w-[570px] text-[13px] leading-relaxed text-fg-dim"
                    initial={{ opacity: 0, y: 8 }}
                    animate={introActive ? { opacity: 1, y: 0 } : { opacity: 0, y: 8 }}
                    transition={{ duration: 0.42, delay: introActive ? 0.18 : 0, ease: stepEase }}
                  >
                    {state.onboarding.isUpdate ? (ru ? "Мы обновили способы подключения. Пожалуйста, настройте приложение заново." : "Connection methods have changed. Please configure the app again.") : t("onboarding.welcome.body")}
                  </motion.p>
                </div>
              </div>
            )}

            {step === 1 && (
              <div className="flex h-full flex-col items-center justify-center px-16 text-center">
                <h1 className="brand-font text-[23px] font-semibold text-fg">{ru ? "Выберите способ подключения" : "Choose a connection method"}</h1>
                <p className="mt-1 max-w-[620px] text-[12px] leading-relaxed text-fg-dim">
                  {ru
                    ? "Выберите компонент, которым собираетесь пользоваться преимущественно. Другие компоненты останутся доступны, а активный способ можно изменить в любой момент."
                    : "Choose the component you expect to use most often. Other components remain available, and you can switch the active method at any time."}
                </p>
                <div className="mt-7 grid w-full max-w-[650px] grid-cols-3 gap-3">
                  {([
                    ["zapret", "Zapret", "component_zapret.svg", ru ? "Локальная обработка трафика с подбором стратегии" : "Local traffic processing with strategy selection"],
                    ["zapret2", "Zapret 2", "component_zapret2.svg", ru ? "Автоматическая настройка нового поколения" : "Automatic next-generation setup"],
                  ] as const).map(([id, title, icon, description]) => (
                    <button key={id} onClick={() => setSelectedMode(id)} className="rounded-[16px] border p-4 text-left transition-all duration-200 hover:bg-bg-2" style={{ borderColor: selectedMode === id ? "var(--fg-dim)" : "var(--line-1)", background: selectedMode === id ? "var(--bg-2)" : "var(--bg-1)" }}>
                      <img src={uiAssetUrl(`icons/${icon}`)} alt="" className="h-10 w-10 object-contain" decoding="async" loading="eager" />
                      <div className="mt-3 text-[13px] font-semibold text-fg">{title}</div>
                      <div className="mt-1 text-[10px] leading-relaxed text-fg-dim">{description}</div>
                    </button>
                  ))}
                </div>
                <button onClick={() => setSelectedMode("none")} className="mt-3 rounded-xl border border-line-1 px-4 py-2 text-[11px] text-fg-dim transition-colors hover:bg-bg-2 hover:text-fg" style={selectedMode === "none" ? { borderColor: "var(--fg-dim)", background: "var(--bg-2)" } : undefined}>{ru ? "Без основного компонента" : "No primary component"}</button>
              </div>
            )}

            {step === 5 && selectedMode === "zapret" && !reconfigure && (
              <div className="flex h-full flex-col items-center justify-center px-16 text-center">
                <h1 className="brand-font text-[23px] font-semibold text-fg">{t("onboarding.control.title")}</h1>
                <p className="mt-1 max-w-[560px] text-[12px] leading-relaxed text-fg-dim">{t("onboarding.control.body")}</p>
                <div className="mt-7 grid w-full max-w-[560px] grid-cols-2 gap-3">
                  {([
                    ["manual", t("onboarding.control.manual"), t("onboarding.control.manualDesc")] as const,
                    ["auto", t("onboarding.control.auto"), t("onboarding.control.autoDesc")] as const,
                  ]).map(([id, title, description]) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => setSetupMode(id)}
                      className="rounded-[16px] border p-4 text-left transition-all duration-200 hover:bg-bg-2"
                      style={{
                        borderColor: setupMode === id ? "var(--fg-dim)" : "var(--line-1)",
                        background: setupMode === id ? "var(--bg-2)" : "var(--bg-1)",
                      }}
                    >
                      <div className="text-[13px] font-semibold text-fg">{title}</div>
                      <div className="mt-1.5 text-[10px] leading-relaxed text-fg-dim">{description}</div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {step === 2 && (selectedMode === "zapret" || reconfigure) && (
              <div className="relative flex h-full flex-col">
                <div className="z-10 shrink-0 text-center">
                  <h1 className="brand-font text-[23px] font-semibold text-fg">{t("onboarding.services.title")}</h1>
                  <p className="mt-1 text-[12px] text-fg-dim">
                    {reconfigure
                      ? (ru ? "Выберите сервисы, затем сохраните выбор или запустите новый тест." : "Choose services, then save the selection or run a new test.")
                      : t("onboarding.services.body")}
                  </p>
                </div>
                <div
                  ref={serviceScrollerRef}
                  onScroll={(event) => {
                    const element = event.currentTarget;
                    setServiceEdges({
                      top: element.scrollTop > 2,
                      bottom: element.scrollTop + element.clientHeight < element.scrollHeight - 2,
                    });
                  }}
                  className={`onboarding-service-scroll scroll-area mt-3 min-h-0 flex-1 overflow-y-auto px-[30px] pb-[86px] pt-2 ${serviceEdges.top ? "is-faded-top" : ""} ${serviceEdges.bottom ? "is-faded-bottom" : ""}`}
                >
                  <div className="onboarding-wave-grid mx-auto grid max-w-[820px] grid-cols-5 gap-x-3 gap-y-3">
                    {state.services.available.map((service, index) => {
                      const selected = picked.includes(service.id);
                      return (
                        <motion.button
                          key={service.id}
                          type="button"
                          initial={{ opacity: 0, y: 12 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ delay: Math.min(index * 0.025, 0.32), duration: 0.35, ease: stepEase }}
                          whileTap={{ scale: 0.97 }}
                          onClick={() => setPicked(selected ? picked.filter((id) => id !== service.id) : [...picked, service.id])}
                          className={`onboarding-service-card relative flex h-[120px] flex-col items-start rounded-[15px] border px-3.5 pb-2 pt-2 text-left transition-colors duration-200 ${selected ? "bg-bg-2" : "border-line-1 bg-bg-1 hover:bg-bg-2"}`}
                          style={selected ? { borderColor: accents[index % accents.length] } : undefined}
                        >
                          {selected && <span className="absolute right-2.5 top-2.5 grid h-5 w-5 place-items-center rounded-full text-white" style={{ background: accents[index % accents.length] }}><svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="m2.5 6.2 2.1 2.1 4.9-5" /></svg></span>}
                          <img src={serviceIconUrl(service.id)} alt="" className={`h-7 w-7 object-contain ${serviceIconNeedsContrast(service.id) ? "service-icon-adaptive" : ""}`} decoding="async" />
                          <div className="mt-2 truncate text-[12px] font-semibold text-fg">{service.name}</div>
                          <div className="mt-1 line-clamp-3 text-[9.5px] leading-[1.4] text-fg-dim">{service.description}</div>
                        </motion.button>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            {step === 3 && (
              <div className="relative flex h-full flex-col items-center justify-center px-16 pb-8 text-center">
                <motion.div animate={configuration.status === "running" ? { rotate: 360 } : { rotate: 0 }} transition={{ duration: 1.4, repeat: configuration.status === "running" ? Infinity : 0, ease: "linear" }} className="grid h-16 w-16 place-items-center rounded-full border border-line-2 bg-bg-2">
                  {configuration.status === "success" ? <span className="text-2xl text-[var(--ok)]">✓</span> : configuration.status === "error" ? <span className="text-xl text-[var(--err)]">×</span> : <span className="h-7 w-7 rounded-full border-2 border-fg-mute border-t-fg" />}
                </motion.div>
                <h1 className="brand-font mt-5 text-[24px] font-semibold text-fg">
                  {ru ? "Подбор конфигурации" : "Selecting configuration"}
                </h1>
                <p className="mt-2 max-w-[560px] text-[12px] text-fg-dim">
                  {configuration.status === "running"
                    ? (progress.name || (ru ? "Подготовка проверки..." : "Preparing checks..."))
                    : configuration.status === "success"
                      ? `${ru ? "Выбрана" : "Selected"}: ${configuration.name}`
                      : (ru ? "Автоматически подобрать конфигурацию не удалось. Можно продолжить." : "Automatic selection failed. You can continue.")}
                </p>
                <div className="mt-5 h-1.5 w-[360px] overflow-hidden rounded-full bg-bg-3"><motion.div className="h-full rounded-full bg-fg" animate={{ width: `${configuration.status === "running" ? progressValue : 100}%` }} transition={{ duration: 0.35 }} /></div>
                <div className="mt-2 text-[10px] text-fg-mute">{configuration.status === "running" ? `${progressValue}% · ${ru ? `general ${Math.max(1, progress.overallCurrent)} из ${progress.overallTotal}` : `general ${Math.max(1, progress.overallCurrent)} of ${progress.overallTotal}`}` : configuration.status === "success" ? (ru ? "Настройка применена" : "Configuration applied") : (ru ? "Проверка завершена" : "Check completed")}</div>
                {configuration.status === "running" && (
                  <button
                    type="button"
                    onClick={() => setGameOpen(true)}
                    className="absolute bottom-[78px] left-1/2 -translate-x-1/2 rounded-xl border border-line-2 bg-bg-2 px-5 py-2 text-[12px] font-semibold text-fg transition-colors hover:bg-bg-3"
                  >
                    {ru ? "Играть" : "Play"}
                  </button>
                )}
              </div>
            )}

            {step === 4 && (
              <div className="flex h-full items-center justify-center text-center">
                <div className="flex -translate-y-2 flex-col items-center">
                  {/* Original pathLength draw — section has no filter blur ancestor on Done. */}
                  <motion.svg
                    key="done-check"
                    initial={{ opacity: 0, scale: 0.86 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ duration: 0.32, ease: stepEase }}
                    width="72"
                    height="72"
                    viewBox="0 0 72 72"
                    fill="none"
                    aria-hidden="true"
                    style={{ transform: "translateZ(0)" }}
                  >
                    <circle cx="36" cy="36" r="31" fill="color-mix(in srgb, var(--ok) 16%, transparent)" />
                    <motion.path
                      d="M21.5 36.5 31 46l20-22"
                      stroke="var(--ok)"
                      strokeWidth="4.2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      initial={{ pathLength: 0 }}
                      animate={{ pathLength: 1 }}
                      transition={{ duration: 0.48, delay: 0.12, ease: stepEase }}
                    />
                  </motion.svg>
                  <h1 className="brand-font mt-4 text-[25px] font-semibold text-fg">{t("onboarding.done.title")}</h1>
                  <p className="mt-2 text-[13px] text-fg-dim">{t("onboarding.done.body")}</p>
                </div>
              </div>
            )}
          </motion.section>
        </AnimatePresence>
      </main>

      <footer className="absolute inset-x-0 bottom-0 z-30 flex h-[66px] items-center justify-between px-10">
        {!reconfigure && flowSteps.indexOf(step) > 0 ? (
          <button
            onClick={skip}
            className="rounded-xl px-4 py-2 text-[12px] text-fg-dim transition-colors hover:bg-bg-3 hover:text-fg"
          >
            {t("onboarding.skip")}
          </button>
        ) : (
          <span />
        )}
        <motion.div
          className="flex items-center gap-3"
          initial={step === 0 ? { opacity: 0, y: 8 } : false}
          animate={step === 0 ? (introActive ? { opacity: 1, y: 0 } : { opacity: 0, y: 8 }) : { opacity: 1, y: 0 }}
          transition={{ duration: 0.38, delay: step === 0 && introActive ? 0.36 : 0, ease: [0.22, 1, 0.36, 1] }}
        >
          <div className="flex shrink-0 items-center gap-1.5">
            {flowSteps.map((item) => (
              <span
                key={item}
                className={`block h-1.5 shrink-0 rounded-full transition-[width,background-color] duration-200 ${
                  item === step ? "w-6 bg-fg" : "w-1.5 min-w-1.5 max-w-1.5 bg-fg-mute/60"
                }`}
              />
            ))}
          </div>
          {flowSteps.indexOf(step) > 0 && <button onClick={goBack} className="rounded-xl border border-line-1 px-4 py-2 text-[12px] text-fg-dim transition-colors hover:bg-bg-3 hover:text-fg">{t("onboarding.back")}</button>}
          {reconfigure && step === 2 && <button onClick={saveReconfigure} className="rounded-xl border border-line-2 bg-transparent px-5 py-2 text-[12px] font-semibold text-fg transition-colors hover:bg-bg-3">{ru ? "Сохранить" : "Save"}</button>}
          <button disabled={(step === 3 && configuration.status === "running") || serviceSelectionRequired} onClick={next} className="rounded-xl border border-line-2 bg-fg px-5 py-2 text-[12px] font-semibold text-bg-0 transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-35">{reconfigure && step === 2 ? (ru ? "Сохранить и протестировать" : "Save and test") : step === 4 ? t("onboarding.finish") : t("onboarding.next")}</button>
        </motion.div>
      </footer>
      <SurfGameModal
        open={gameOpen}
        locale={locale === "en" ? "en" : "ru"}
        onClose={() => setGameOpen(false)}
      />
    </motion.div>
    )}
  </AnimatePresence>;
}
