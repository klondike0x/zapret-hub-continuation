import { useEffect, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { DndContext, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useAppState, useBridge, patchOptimistic } from "@/hooks/useBridgeState";
import { useLocale } from "@/hooks/useLocale";
import { Segmented } from "@/components/ui/Segmented";
import { IosToggle } from "@/components/ui/IosToggle";
import { useToast } from "@/components/shell/ToastHost";
import { ScrollGlassHeader } from "@/components/ui/ScrollGlassHeader";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { SurfGameModal } from "@/components/onboarding/SurfGameModal";
import type { RuntimeId, Settings } from "@/bridge/types";
import type { NavKey } from "@/components/shell/Sidebar";
import { uiAssetUrl } from "@/lib/assets";

export type SettingsTab = "app" | "zapret" | "zapret2";

const THEMES = [
  { id: "oled", name: "Obsidian", swatch: ["#090a0d", "#151820", "#edf1f8"] },
  { id: "light", name: "Concrete", swatch: ["#f2f3f5", "#ffffff", "#20242b"] },
  { id: "night", name: "Aurora", swatch: ["#0b0c13", "#151827", "#aa9cff"] },
];

const inputClass = "h-8 w-[250px] rounded-[10px] border border-line-1 bg-bg-1 px-2.5 text-[11px] text-fg outline-none transition-colors focus:border-line-2";

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return <button onClick={onClick} className={`relative px-3.5 py-2 text-[12px] font-medium transition-colors ${active ? "text-fg" : "text-fg-dim hover:text-fg"}`}>
    {active && <motion.span layoutId="settings-tab" className="absolute inset-x-2 bottom-0 h-[2px] rounded-full bg-fg" transition={{ type: "spring", stiffness: 500, damping: 40 }} />}
    {children}
  </button>;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section className="mb-4 rounded-[14px] border border-line-1 bg-bg-1/55 px-3.5 py-2.5">
    <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-mute">{title}</div>
    {children}
  </section>;
}

function Row({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return <div className="flex min-h-[42px] items-center justify-between gap-5 border-b border-line-1/60 py-1.5 last:border-b-0">
    <div className="min-w-0">
      <div className="text-[12px] text-fg">{label}</div>
      {hint && <div className="mt-0.5 max-w-[260px] text-[9px] leading-snug text-fg-mute">{hint}</div>}
    </div>
    <div className="shrink-0">{children}</div>
  </div>;
}

function SelectField({ value, onChange, options, disabled = false }: { value: string; onChange: (value: string) => void; options: { value: string; label: string }[]; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  const [dropUp, setDropUp] = useState(false);
  const anchorRef = useRef<HTMLButtonElement>(null);
  const selected = options.find((option) => option.value === value) ?? options[0];
  return <div className={`relative ${disabled ? "opacity-50" : ""}`}>
    <button ref={anchorRef} type="button" disabled={disabled} onClick={() => {
      if (disabled) return;
      if (!open) {
        const rect = anchorRef.current?.getBoundingClientRect();
        setDropUp(Boolean(rect && rect.bottom + 205 > window.innerHeight));
      }
      setOpen((current) => !current);
    }} className={`${inputClass} flex items-center justify-between gap-3 text-left ${disabled ? "cursor-not-allowed" : ""}`}>
      <span className="truncate">{selected?.label ?? value}</span>
      <svg className={`shrink-0 text-fg-mute transition-transform ${open ? "rotate-180" : ""}`} width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4"><path d="m3 4.5 3 3 3-3" /></svg>
    </button>
    <AnimatePresence>
      {open && !disabled && <motion.div initial={{ opacity: 0, y: dropUp ? 4 : -4, scale: 0.985 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: dropUp ? 3 : -3, scale: 0.985 }} transition={{ duration: 0.14 }} className={`absolute right-0 z-[70] max-h-48 w-[250px] overflow-y-auto rounded-[11px] border border-line-2 bg-bg-2 p-1 shadow-[0_12px_28px_-18px_rgba(0,0,0,.65)] ${dropUp ? "bottom-[36px]" : "top-[36px]"}`}>
        {options.map((option) => <button key={option.value} type="button" onClick={() => { onChange(option.value); setOpen(false); }} className={`flex w-full items-center justify-between rounded-[8px] px-2.5 py-2 text-left text-[11px] transition-colors ${option.value === value ? "bg-bg-3 text-fg" : "text-fg-dim hover:bg-bg-3 hover:text-fg"}`}>
          <span className="truncate">{option.label}</span>
          {option.value === value && <span className="h-1.5 w-1.5 rounded-full bg-[var(--accent)]" />}
        </button>)}
      </motion.div>}
    </AnimatePresence>
  </div>;
}

function SortableMode({ id, label }: { id: RuntimeId; label: string }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });
  return <div ref={setNodeRef} {...attributes} {...listeners} style={{ transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.58 : 1 }} className="flex cursor-grab items-center gap-2 rounded-[10px] border border-line-1 bg-bg-2 px-3 py-2 text-[11px] text-fg active:cursor-grabbing">
    <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><circle cx="8" cy="6" r="1.5"/><circle cx="8" cy="12" r="1.5"/><circle cx="8" cy="18" r="1.5"/><circle cx="16" cy="6" r="1.5"/><circle cx="16" cy="12" r="1.5"/><circle cx="16" cy="18" r="1.5"/></svg>
    {label}
  </div>;
}

export function SettingsModal({
  open,
  onClose,
  initialTab = "app",
  embedded = false,
  onNavigate,
  onReconfigureZapret,
}: {
  open: boolean;
  onClose: () => void;
  initialTab?: SettingsTab;
  embedded?: boolean;
  onNavigate?: (target: NavKey | "mods2" | "files2") => void;
  onReconfigureZapret?: () => void;
}) {
  const state = useAppState();
  const bridge = useBridge();
  const { t, locale } = useLocale();
  const toast = useToast();
  const [tab, setTab] = useState<SettingsTab>(initialTab);
  const [tabDirection, setTabDirection] = useState(1);
  const [draft, setDraft] = useState<Partial<Settings> & { locale?: "ru" | "en"; modeOrder?: RuntimeId[] }>({});
  const [confirmManualOpen, setConfirmManualOpen] = useState(false);
  const [confirmManualBackend, setConfirmManualBackend] = useState<"zapret" | "zapret2">("zapret");
  const [surfOpen, setSurfOpen] = useState(false);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));
  const scrollerRef = useRef<HTMLDivElement>(null);

  useEffect(() => { if (open) setTab(initialTab); }, [open, initialTab]);
  if (!state) return null;
  const ru = locale === "ru";
  const settings = { ...state.settings, ...draft };
  const displayModeOrder = draft.modeOrder ?? state.runtime.order;
  const patch = (value: Partial<Settings> & { locale?: "ru" | "en"; modeOrder?: RuntimeId[] }) =>
    setDraft((current) => ({ ...current, ...value }));
  const applyLive = (value: Partial<Settings> & { locale?: "ru" | "en" }, preview: "click" | "switch" | null = "click") => {
    patchOptimistic({
      settings: {
        ...value,
        ...(value.locale ? { locale: value.locale } : null),
        ...(value.theme ? { theme: value.theme } : null),
      },
    });
    void bridge.call("settings.apply", { patch: value });
    const touchesSounds =
      value.soundsEnabled !== undefined ||
      value.soundsClickEnabled !== undefined ||
      value.soundsVolume !== undefined;
    if (touchesSounds || preview === "click" || preview === "switch") {
      void import("@/lib/sounds").then(({ playSound, setSoundEffectsEnabled, setClickSoundsEnabled, setSoundsVolume, unlockSounds }) => {
        const nextEnabled = value.soundsEnabled ?? settings.soundsEnabled;
        const nextClickEnabled = value.soundsClickEnabled ?? settings.soundsClickEnabled ?? true;
        const nextVolume = value.soundsVolume ?? settings.soundsVolume ?? "normal";
        setSoundEffectsEnabled(Boolean(nextEnabled));
        setClickSoundsEnabled(Boolean(nextClickEnabled));
        setSoundsVolume(nextVolume);
        // Tumblers already play switch via SoundEffects/IosToggle. Preview only when
        // requested (e.g. enabling master sounds while they were off, or volume sample).
        if (preview && nextEnabled && (preview !== "click" || nextClickEnabled)) {
          unlockSounds();
          playSound(preview);
        }
      });
    }
  };
  const L = (russian: string, english: string) => ru ? russian : english;
  const tabs: { key: SettingsTab; label: string }[] = [
    { key: "app", label: t("settings.tab.app") },
    { key: "zapret", label: "Zapret" },
    { key: "zapret2", label: "Zapret 2" },
  ];
  const modeLabels: Record<RuntimeId, string> = { zapret: "Zapret", zapret2: "Zapret2", none: L("Без основного компонента", "No primary component") };
  const selectTab = (next: SettingsTab) => {
    const currentIndex = tabs.findIndex((item) => item.key === tab);
    const nextIndex = tabs.findIndex((item) => item.key === next);
    setTabDirection(nextIndex >= currentIndex ? 1 : -1);
    setTab(next);
  };

  const onDragEnd = (event: DragEndEvent) => {
    if (!event.over || event.active.id === event.over.id) return;
    const oldIndex = displayModeOrder.indexOf(event.active.id as RuntimeId);
    const newIndex = displayModeOrder.indexOf(event.over.id as RuntimeId);
    const modeOrder = arrayMove(displayModeOrder, oldIndex, newIndex);
    // App tab: mode order needs Apply. Other tabs keep immediate apply if ever reused.
    if (tab === "app") {
      patchOptimistic({ runtime: { order: modeOrder } });
      patch({ modeOrder });
      return;
    }
    patchOptimistic({ settings: { modeOrder }, runtime: { order: modeOrder } });
    void bridge.call("settings.apply", { patch: { modeOrder } as never });
  };

  const hasPendingAppConfirm =
    tab === "app" &&
    (
      (draft.hardwareAcceleration !== undefined && draft.hardwareAcceleration !== state.settings.hardwareAcceleration) ||
      (Array.isArray(draft.modeOrder) && draft.modeOrder.join("|") !== state.runtime.order.join("|"))
    );

  const apply = () => {
    if (tab === "app" && !hasPendingAppConfirm) return;
    const toastId = toast.push({ message: t("toast.applying") });
    const appliedLocale = draft.locale ?? locale;
    const confirmPatch: Partial<Settings> & { locale?: "ru" | "en"; modeOrder?: RuntimeId[] } =
      tab === "app"
        ? {
            ...(draft.hardwareAcceleration !== undefined ? { hardwareAcceleration: draft.hardwareAcceleration } : null),
            ...(draft.modeOrder ? { modeOrder: draft.modeOrder } : null),
          }
        : draft;
    patchOptimistic({
      settings: {
        ...confirmPatch,
        ...(confirmPatch.locale ? { locale: confirmPatch.locale } : null),
        ...(confirmPatch.theme ? { theme: confirmPatch.theme } : null),
        ...(confirmPatch.modeOrder ? { modeOrder: confirmPatch.modeOrder } : null),
      },
      ...(confirmPatch.modeOrder ? { runtime: { order: confirmPatch.modeOrder } } : null),
    });
    void bridge.call("settings.apply", { patch: confirmPatch }).then(
      () => {
        toast.push({
          id: toastId,
          message: appliedLocale === "ru" ? "Изменения применены" : "Changes applied",
          kind: "success",
        });
      },
      () => {
        toast.push({
          id: toastId,
          message: appliedLocale === "ru" ? "Не удалось применить" : "Failed to apply",
          kind: "error",
        });
      },
    );
    setDraft({});
    if (!embedded) onClose();
  };

  const headerBar = (
    <div className="flex h-full items-center justify-between gap-3">
      <div className="flex h-full min-w-0 items-center gap-3">
        <div className="shrink-0 text-[13px] font-semibold text-fg">{t("settings.title")}</div>
        <div className="h-5 w-px shrink-0 bg-line-1" aria-hidden="true" />
        <div className="flex h-full min-w-0 items-center gap-1 overflow-x-auto">{tabs.map((item) => <TabButton key={item.key} active={tab === item.key} onClick={() => selectTab(item.key)}>{item.label}</TabButton>)}</div>
      </div>
      {!embedded && <button onClick={onClose} className="grid h-7 w-7 shrink-0 place-items-center rounded-[8px] text-fg-dim transition-colors hover:bg-bg-3 hover:text-fg">×</button>}
    </div>
  );

  const settingsBody = (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div key={tab} initial={{ opacity: 0, x: tabDirection * 10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: tabDirection * -8 }} transition={{ duration: 0.16, ease: [0.22, 1, 0.36, 1] }}>
        {tab === "app" && <>
          <Section title={L("О приложении", "About the app")}>
            <div className="flex items-center gap-3 rounded-[12px] border border-line-1 bg-bg-1/70 p-3">
              <img src={uiAssetUrl("icons/app.png")} alt="" className="h-11 w-11 shrink-0 object-contain" />
              <div className="min-w-0 flex-1"><div className="text-[13px] font-semibold text-fg">Zapret Hub</div><div className="text-[10px] text-fg-mute">{L("Ускоритель сетевых компонентов · версия 3.0.2", "Network components manager · version 3.0.2")}</div></div>
              <button onClick={() => bridge.call("app.check-updates", undefined)} className="shrink-0 rounded-[10px] border border-line-2 bg-bg-3 px-3 py-2 text-[11px] font-semibold text-fg transition-all hover:brightness-110">{L("Проверить обновления", "Check updates")}</button>
            </div>
          </Section>
          <Section title={L("Внешний вид", "Appearance")}>
            <div className="mb-2 grid grid-cols-3 gap-2">
              {THEMES.map((theme) => <button key={theme.id} onClick={() => { void applyLive({ theme: theme.id }, null); }} className={`rounded-[12px] border p-2 text-left transition-colors ${settings.theme === theme.id ? "border-line-2 bg-bg-3" : "border-line-1 bg-bg-2 hover:bg-bg-3"}`}>
                <div className="flex h-8 overflow-hidden rounded-[7px]">{theme.swatch.map((color) => <span key={color} className="flex-1" style={{ background: color }} />)}</div>
                <div className="mt-1.5 text-[10px] font-medium text-fg">{theme.name}</div>
              </button>)}
            </div>
            <Row label={t("settings.language")}><Segmented value={locale} onChange={(value) => { void applyLive({ locale: value }, "switch"); }} options={[{ value: "ru", label: "Русский" }, { value: "en", label: "English" }]} size="sm" /></Row>
            <Row
              label={L("Интерфейс", "Interface")}
              hint={L("Масштаб текста и блоков интерфейса", "Scale for interface text and blocks")}
            >
              <Segmented
                value={(settings.uiScale ?? "1") as "0.75" | "1" | "1.25"}
                onChange={(value) => { void applyLive({ uiScale: value as "0.75" | "1" | "1.25" }, "switch"); }}
                options={[
                  { value: "0.75", label: "0.75×" },
                  { value: "1", label: "1×" },
                  { value: "1.25", label: "1.25×" },
                ]}
                size="sm"
              />
            </Row>
            <Row label={L("Звуки интерфейса", "Interface sounds")} hint={L("Звуки нажатий, переключений, запуска и остановки", "Click, switch, startup and shutdown sounds")}><IosToggle on={settings.soundsEnabled} onChange={(value) => { void applyLive({ soundsEnabled: value }, value ? "switch" : null); }} /></Row>
            <AnimatePresence initial={false}>
              {settings.soundsEnabled && <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }} className="overflow-hidden pl-3">
                <Row label={L("Звук кликов", "Click sounds")}><IosToggle on={settings.soundsClickEnabled !== false} onChange={(value) => { void applyLive({ soundsClickEnabled: value }, null); }} /></Row>
                <Row label={L("Громкость звуков", "Sound volume")}>
                  <Segmented
                    value={settings.soundsVolume ?? "normal"}
                    onChange={(value) => { void applyLive({ soundsVolume: value as "normal" | "louder" | "quieter" }, settings.soundsClickEnabled !== false ? "click" : "switch"); }}
                    options={[
                      { value: "quieter", label: L("Тише", "Quieter") },
                      { value: "normal", label: L("Обычная", "Normal") },
                      { value: "louder", label: L("Громче", "Louder") },
                    ]}
                    size="sm"
                  />
                </Row>
              </motion.div>}
            </AnimatePresence>
            <Row label={L("Аппаратное ускорение", "Hardware acceleration")} hint={L("Использует GPU для Chromium, анимаций и композитинга", "Uses the GPU for Chromium rendering, animations and compositing")}><IosToggle on={settings.hardwareAcceleration} onChange={(value) => patch({ hardwareAcceleration: value })} /></Row>
          </Section>
          <Section title="Zapret Hub">
            <Row label={L("Проверять обновления автоматически", "Check updates automatically")}><IosToggle on={settings.checkUpdates} onChange={(value) => { void applyLive({ checkUpdates: value }, null); }} /></Row>
            <Row label={L("Проверять обновления модификаций автоматически", "Check mod updates automatically")}><IosToggle on={settings.checkModUpdates} onChange={(value) => { void applyLive({ checkModUpdates: value }, null); }} /></Row>
            <Row label={L("Проверять обновления компонентов автоматически", "Check component updates automatically")}><IosToggle on={settings.checkComponentUpdates} onChange={(value) => { void applyLive({ checkComponentUpdates: value }, null); }} /></Row>
          </Section>
          <Section title="Discord">
            <Row
              label={L("Отображать статус Zapret Hub в Discord", "Show Zapret Hub status in Discord")}
              hint={L(
                "В профиле Discord появится Zapret Hub со случайной фразой при запуске и текущим режимом. Нужен Discord Desktop.",
                "Shows Zapret Hub on your Discord profile with a random launch line and the active mode. Needs Discord Desktop.",
              )}
            >
              <IosToggle
                on={settings.discordRpcEnabled !== false}
                onChange={(value) => { void applyLive({ discordRpcEnabled: value }, null); }}
              />
            </Row>
          </Section>
          <Section title="Windows">
            <Row label={L("Запускать вместе с Windows", "Start with Windows")}><IosToggle on={settings.autoStart} onChange={(value) => { void applyLive({ autoStart: value }, null); }} /></Row>
            <AnimatePresence initial={false}>
              {settings.autoStart && <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }} className="overflow-hidden pl-3">
                <Row label={L("Стартовать в трее", "Start in tray")} hint={L("При автозапуске окно не открывается — только иконка в трее", "On Windows startup the window stays closed; only the tray icon appears")}><IosToggle on={settings.minimizeToTray} onChange={(value) => { void applyLive({ minimizeToTray: value }, null); }} /></Row>
                <Row label={L("Автозапуск компонентов", "Auto-start components")} hint={L("Включает кнопку питания с последним выбранным режимом и настройками", "Turns the power button on with your last selected mode and settings")}><IosToggle on={settings.autoRunComponents} onChange={(value) => { void applyLive({ autoRunComponents: value }, null); }} /></Row>
              </motion.div>}
            </AnimatePresence>
          </Section>
          <Section title={L("Уведомления Windows", "Windows notifications")}>
            <Row label={L("Уведомления Windows", "Windows notifications")}><IosToggle on={settings.windowsNotifications} onChange={(value) => { void applyLive({ windowsNotifications: value }, null); }} /></Row>
            <AnimatePresence initial={false}>
              {settings.windowsNotifications && <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }} className="overflow-hidden pl-3">
                <Row label={L("Дублировать уведомления приложения в Windows", "Mirror app notifications in Windows")} hint={L("События из центра уведомлений Zapret Hub также появятся в Windows", "Events from Zapret Hub notification center will also appear in Windows")}><IosToggle on={settings.notificationsEnabled} onChange={(value) => { void applyLive({ notificationsEnabled: value }, null); }} /></Row>
                <Row label={L("Уведомлять о скрытии в трей", "Notify when minimized to tray")}><IosToggle on={settings.trayNotification} onChange={(value) => { void applyLive({ trayNotification: value }, null); }} /></Row>
              </motion.div>}
            </AnimatePresence>
          </Section>
          <Section title={L("Порядок сетевых компонентов", "Network component order")}>
            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
              <SortableContext items={displayModeOrder} strategy={verticalListSortingStrategy}>
                <div className="mt-1.5 flex flex-col gap-1.5">{displayModeOrder.map((mode) => <SortableMode key={mode} id={mode} label={modeLabels[mode]} />)}</div>
              </SortableContext>
            </DndContext>
            <div className="mt-3 border-t border-line-1 pt-2.5">
              <Row
                label={L("Переключение скроллом", "Scroll switching")}
                hint={L(
                  "Позволяет переключать сетевые компоненты скроллом по странице быстрого доступа",
                  "Lets you switch network components by scrolling on the quick access page",
                )}
              >
                <IosToggle
                  on={settings.scrollModeSwitch !== false}
                  onChange={(value) => { void applyLive({ scrollModeSwitch: value }, null); }}
                />
              </Row>
            </div>
          </Section>
          <div className="mt-1 flex justify-center pb-1 pt-2">
            <button
              type="button"
              onClick={() => setSurfOpen(true)}
              className="text-[10px] tracking-[0.04em] text-fg-mute/35 transition-colors hover:text-fg-mute/70"
            >
              {L("играть", "play")}
            </button>
          </div>
        </>}

        {tab === "zapret" && <>
          <Section title={L("Конфигурация", "Configuration")}>
            <Row
              label={L("Режим управления", "Control mode")}
              hint={L("Автоматический режим ведёт сервисы и стратегии сам", "Automatic mode manages services and strategies for you")}
            >
              <Segmented
                size="sm"
                value={(settings.zapret.controlMode ?? state.orchestrator?.mode ?? "manual") as "manual" | "auto"}
                onChange={(mode) => {
                  const current = (settings.zapret.controlMode ?? state.orchestrator?.mode ?? "manual") as "manual" | "auto";
                  if (mode === current) return;
                  if (mode === "manual" && current === "auto") {
                    setConfirmManualBackend("zapret");
                    setConfirmManualOpen(true);
                    return;
                  }
                  const nextZapret = { ...settings.zapret, controlMode: mode };
                  patchOptimistic({
                    settings: { zapret: nextZapret },
                    orchestrator: { mode, isAuto: mode === "auto" },
                  });
                  patch({ zapret: nextZapret });
                  void bridge.call("orchestrator.setMode", { mode, backend: "zapret" });
                }}
                options={[
                  { value: "auto", label: L("Автоматический", "Automatic") },
                  { value: "manual", label: L("Вручную", "Manual") },
                ]}
              />
            </Row>
            <Row
              label={L("Сброс авто-кэша", "Reset Auto cache")}
              hint={L(
                "Стирает только то, чему научился Авто (overlay + память). Списки сервисов и ваши файлы не трогает.",
                "Clears only what Auto learned (overlay + memory). Service lists and your files stay intact.",
              )}
            >
              <button
                type="button"
                onClick={() => {
                  void bridge.call("orchestrator.resetAuto", { backend: "zapret" });
                }}
                className="rounded-[10px] border border-line-1 bg-bg-2 px-3 py-1.5 text-[11px] text-fg transition-colors hover:bg-bg-3"
              >
                {L("Сбросить авто-режим", "Reset Auto mode")}
              </button>
            </Row>
            {((settings.zapret.controlMode ?? state.orchestrator?.mode ?? "manual") === "auto") && (
              <div className="mb-2 rounded-[10px] border border-line-1 bg-bg-2/70 px-3 py-2 text-[10px] text-fg-dim">
                {L("Стратегию, IPSet и Gaming сейчас ведёт автоматика — переключитесь на «Вручную», чтобы менять их сами.", "Strategy, IPSet and Gaming are managed by Auto — switch to Manual to edit them yourself.")}
              </div>
            )}
            <Row label={L("Текущая стратегия", "Current strategy")}><SelectField disabled={(settings.zapret.controlMode ?? state.orchestrator?.mode ?? "manual") === "auto"} value={settings.zapret.selectedGeneral} onChange={(value) => patch({ zapret: { ...settings.zapret, selectedGeneral: value } })} options={[
              ...(!settings.zapret.selectedGeneral ? [{ value: "", label: L("Выберите стратегию", "Choose a strategy") }] : []),
              ...settings.zapret.generals.map((item) => ({ value: item.id, label: item.name })),
            ]} /></Row>
            <div className="mt-2 flex gap-2">
              {(settings.zapret.controlMode ?? state.orchestrator?.mode ?? "manual") !== "auto" && (
                <button onClick={() => {
                  if (onReconfigureZapret) onReconfigureZapret();
                  else void bridge.call("onboarding.configure", undefined);
                }} className="rounded-[10px] border border-line-1 bg-bg-2 px-3 py-2 text-[11px] text-fg transition-all duration-200 hover:bg-bg-3">{L("Подобрать настройки заново", "Run setup again")}</button>
              )}
              <button onClick={() => bridge.call("zapret.rebuild-runtime", undefined)} className="rounded-[10px] border border-line-1 bg-bg-2 px-3 py-2 text-[11px] text-fg transition-all duration-200 hover:bg-bg-3">{L("Пересобрать runtime", "Rebuild runtime")}</button>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2">
              <button onClick={() => onNavigate?.("mods")} className="flex items-center gap-2 rounded-[11px] border border-line-1 bg-bg-2 px-3 py-2.5 text-left text-[11px] text-fg transition-all duration-200 hover:bg-bg-3"><span className="h-4 w-4 bg-current" style={{ WebkitMask: `url("${uiAssetUrl("icons/mods.svg")}") center / contain no-repeat`, mask: `url("${uiAssetUrl("icons/mods.svg")}") center / contain no-repeat` }} />{L("Пользовательские модификации Zapret", "Custom Zapret modifications")}</button>
              <button onClick={() => onNavigate?.("files")} className="flex items-center gap-2 rounded-[11px] border border-line-1 bg-bg-2 px-3 py-2.5 text-left text-[11px] text-fg transition-all duration-200 hover:bg-bg-3"><span className="h-4 w-4 bg-current" style={{ WebkitMask: `url("${uiAssetUrl("icons/files.svg")}") center / contain no-repeat`, mask: `url("${uiAssetUrl("icons/files.svg")}") center / contain no-repeat` }} />{L("Файлы Zapret", "Zapret files")}</button>
            </div>
            <div className="mt-2 text-[10px] leading-relaxed text-fg-mute">
              {L(
                "Свои моды и файлы Zapret. Моды из Marketplace - в левом меню «Установленные».",
                "Custom Zapret mods and files. Marketplace mods are under Installed in the sidebar.",
              )}
            </div>
          </Section>
          <Section title={L("Фильтрация", "Filtering")}>
            <Row label="IPSet mode" hint={L("Какие IP-списки применяются к фильтрации", "Which IP lists are used for filtering")}><SelectField disabled={(settings.zapret.controlMode ?? state.orchestrator?.mode ?? "manual") === "auto"} value={settings.zapret.ipsetMode} onChange={(value) => patch({ zapret: { ...settings.zapret, ipsetMode: value } })} options={[{ value: "loaded", label: L("Загруженные списки", "Loaded lists") }, { value: "none", label: L("Без IPSet", "No IPSet") }, { value: "any", label: L("Любые IP", "Any IP") }]} /></Row>
            <Row label="Gaming mode"><SelectField disabled={(settings.zapret.controlMode ?? state.orchestrator?.mode ?? "manual") === "auto"} value={settings.zapret.gameFilterMode} onChange={(value) => patch({ zapret: { ...settings.zapret, gameFilterMode: value } })} options={[{ value: "disabled", label: L("Выключен", "Disabled") }, { value: "tcp", label: "TCP" }, { value: "udp", label: "UDP" }, { value: "tcpudp", label: "TCP + UDP" }]} /></Row>
            <Row label="Gaming Set"><SelectField disabled={(settings.zapret.controlMode ?? state.orchestrator?.mode ?? "manual") === "auto"} value={settings.zapret.gamingSet} onChange={(value) => patch({ zapret: { ...settings.zapret, gamingSet: value } })} options={[
              { value: "base", label: "Base" },
              { value: "stun-wide-base", label: "STUN · Wide · Base" },
              { value: "stun-wide-base-local-exclude", label: "STUN · Wide · Base + local exclude" },
              { value: "wide-stun-base", label: "Wide · STUN · Base" },
              { value: "base-wide-stun", label: "Base · Wide · STUN" },
              { value: "udp-first", label: "UDP first" },
              { value: "tcp-first", label: "TCP first" },
              { value: "stun-between", label: "STUN between" },
            ]} /></Row>
            <Row label={L("Исключить UDP-порты", "Exclude UDP ports")} hint={L("Порты и диапазоны через запятую: 443, 5000-5100", "Comma-separated ports and ranges: 443, 5000-5100")}><input disabled={(settings.zapret.controlMode ?? state.orchestrator?.mode ?? "manual") === "auto"} value={settings.zapret.udpExclusions} onChange={(event) => patch({ zapret: { ...settings.zapret, udpExclusions: event.target.value } })} className={`${inputClass} disabled:cursor-not-allowed disabled:opacity-50`} /></Row>
          </Section>
        </>}

        {tab === "zapret2" && <>
          <Section title={L("Авто-режим", "Auto mode")}>
            <Row label={L("Управление", "Control")}>
              <SelectField
                value={(settings.zapret2.controlMode ?? "manual") as "manual" | "auto"}
                onChange={(value) => {
                  const mode = value as "manual" | "auto";
                  const current = (settings.zapret2.controlMode ?? "manual") as "manual" | "auto";
                  if (mode === current) return;
                  if (mode === "manual" && current === "auto") {
                    setConfirmManualBackend("zapret2");
                    setConfirmManualOpen(true);
                    return;
                  }
                  const nextZapret2 = { ...settings.zapret2, controlMode: mode };
                  patchOptimistic({
                    settings: { zapret2: nextZapret2 },
                    orchestrator: { mode, isAuto: mode === "auto", backend: "zapret2" },
                  });
                  patch({ zapret2: nextZapret2 });
                  void bridge.call("orchestrator.setMode", { mode, backend: "zapret2" });
                }}
                options={[{ value: "manual", label: L("Вручную", "Manual") }, { value: "auto", label: L("Авто", "Auto") }]}
              />
            </Row>
            <Row
              label={L("Сброс авто-кэша", "Reset Auto cache")}
              hint={L(
                "Стирает overlay и память Auto для Zapret 2. Боевые list-hub / ваши правки не меняются.",
                "Clears Auto overlay and memory for Zapret 2. Battle list-hub / your edits stay intact.",
              )}
            >
              <button
                type="button"
                onClick={() => {
                  void bridge.call("orchestrator.resetAuto", { backend: "zapret2" });
                }}
                className="rounded-[10px] border border-line-1 bg-bg-2 px-3 py-1.5 text-[11px] text-fg transition-colors hover:bg-bg-3"
              >
                {L("Сбросить авто-режим", "Reset Auto mode")}
              </button>
            </Row>
            {((settings.zapret2.controlMode ?? "manual") === "auto") && (
              <div className="mt-2 text-[10px] leading-relaxed text-fg-dim">
                {L(
                  "Авто пишет hostlist/ipset и Lua (hub-orchestrator.lua). Домены, IP и смена Lua-профиля подхватываются без рестарта winws2.",
                  "Auto writes hostlist/ipset and Lua (hub-orchestrator.lua). Domains, IPs, and Lua profile changes reload without restarting winws2.",
                )}
              </div>
            )}
            <div className="mt-2 grid grid-cols-2 gap-2">
              <button onClick={() => onNavigate?.("mods2")} className="flex items-center gap-2 rounded-[11px] border border-line-1 bg-bg-2 px-3 py-2.5 text-left text-[11px] text-fg transition-all duration-200 hover:bg-bg-3"><span className="h-4 w-4 bg-current" style={{ WebkitMask: `url("${uiAssetUrl("icons/mods.svg")}") center / contain no-repeat`, mask: `url("${uiAssetUrl("icons/mods.svg")}") center / contain no-repeat` }} />{L("Пользовательские модификации Zapret 2", "Custom Zapret 2 modifications")}</button>
              <button onClick={() => onNavigate?.("files2")} className="flex items-center gap-2 rounded-[11px] border border-line-1 bg-bg-2 px-3 py-2.5 text-left text-[11px] text-fg transition-all duration-200 hover:bg-bg-3"><span className="h-4 w-4 bg-current" style={{ WebkitMask: `url("${uiAssetUrl("icons/files.svg")}") center / contain no-repeat`, mask: `url("${uiAssetUrl("icons/files.svg")}") center / contain no-repeat` }} />{L("Файлы Zapret 2", "Zapret 2 files")}</button>
            </div>
            <div className="mt-2 text-[10px] leading-relaxed text-fg-mute">
              {L(
                "Свои моды и файлы Zapret 2. Моды из Marketplace - в левом меню «Установленные».",
                "Custom Zapret 2 mods and files. Marketplace mods are under Installed in the sidebar.",
              )}
            </div>
          </Section>
          <Section title="winws2">
            <Row label="TCP ports" hint="--wf-tcp-out (Discord media ports merge automatically)"><input disabled={(settings.zapret2.controlMode ?? "manual") === "auto"} value={settings.zapret2.tcpPorts} onChange={(event) => patch({ zapret2: { ...settings.zapret2, tcpPorts: event.target.value } })} className={`${inputClass} disabled:cursor-not-allowed disabled:opacity-50`} /></Row>
            <Row label="UDP ports" hint="--wf-udp-out (Discord voice ports merge automatically)"><input disabled={(settings.zapret2.controlMode ?? "manual") === "auto"} value={settings.zapret2.udpPorts} onChange={(event) => patch({ zapret2: { ...settings.zapret2, udpPorts: event.target.value } })} className={`${inputClass} disabled:cursor-not-allowed disabled:opacity-50`} /></Row>
            <Row label="WinDivert filter" hint={L("Дополнительный фильтр --wf-raw-part", "Additional --wf-raw-part filter")}><textarea disabled={(settings.zapret2.controlMode ?? "manual") === "auto"} value={settings.zapret2.rawFilter} onChange={(event) => patch({ zapret2: { ...settings.zapret2, rawFilter: event.target.value } })} className="h-16 w-[250px] resize-none rounded-[10px] border border-line-1 bg-bg-1 p-2.5 text-[11px] text-fg outline-none focus:border-line-2 disabled:cursor-not-allowed disabled:opacity-50" /></Row>
          </Section>
          <Section title="Lua desync">
            <Row label={L("Профиль Lua", "Lua profile")} hint={L("Hub-стратегия для Manual и Auto (hot-reload без рестарта).", "Hub strategy for Manual and Auto (hot-reload, no restart).")}>
              <SelectField
                value={settings.zapret2.strategyId || "balanced"}
                onChange={(value) => patch({ zapret2: { ...settings.zapret2, strategyId: value } })}
                options={[
                  { value: "balanced", label: L("Сбалансированная", "Balanced") },
                  { value: "fake_heavy", label: L("Агрессивный fake", "Aggressive fake") },
                  { value: "multisplit", label: "Multisplit" },
                ]}
              />
            </Row>
            <Row label={L("Своя стратегия", "Custom strategy")} hint={L("Доп. --filter/--lua-desync после стандартных профилей (Discord не отключается). В Auto игнорируется.", "Extra --filter/--lua-desync after default profiles (Discord stays). Ignored in Auto.")}><textarea disabled={(settings.zapret2.controlMode ?? "manual") === "auto"} value={settings.zapret2.luaStrategy} onChange={(event) => patch({ zapret2: { ...settings.zapret2, luaStrategy: event.target.value } })} className="h-28 w-[250px] resize-none rounded-[10px] border border-line-1 bg-bg-1 p-2.5 font-mono text-[10px] text-fg outline-none focus:border-line-2 disabled:cursor-not-allowed disabled:opacity-50" /></Row>
          </Section>
        </>}

      </motion.div>
    </AnimatePresence>
  );

  const renderFooter = (className: string) => (
    <footer className={className}>
      <div className="max-w-[470px] whitespace-pre-line text-[9px] leading-relaxed text-fg-mute">{L("Благодарности: Zapret от Flowseal; Zapret 2 от bol-van.\nОригинальный Zapret Hub (goshkow, MIT).", "Credits: Zapret by Flowseal; Zapret 2 by bol-van.\nOriginal Zapret Hub by goshkow (MIT).")}</div>
      <div className="flex items-center gap-2">
        {!embedded && <button onClick={onClose} className="rounded-[9px] border border-line-1 bg-bg-1 px-3 py-1.5 text-[11px] text-fg-dim hover:bg-bg-3 hover:text-fg">{t("settings.close")}</button>}
        <button
          onClick={apply}
          disabled={tab === "app" ? !hasPendingAppConfirm : Object.keys(draft).length === 0}
          className="rounded-[9px] border border-line-2 bg-fg px-3 py-1.5 text-[11px] font-medium text-bg-0 hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-35"
        >{t("settings.apply")}</button>
      </div>
    </footer>
  );
  const footer = renderFooter("flex min-h-11 shrink-0 items-center justify-between gap-3 border-t border-line-1 bg-bg-2/72 px-6 py-2 backdrop-blur-md");

  return <AnimatePresence>{open && <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.14 }} className={embedded ? "relative h-full w-full" : "absolute inset-0 z-40 grid place-items-center bg-black/46"} onClick={embedded ? undefined : onClose}>
    <motion.div initial={{ opacity: 0, scale: embedded ? 1 : 0.975, y: embedded ? 0 : 5 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: embedded ? 1 : 0.98 }} transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }} onClick={(event) => event.stopPropagation()} className={embedded ? "flex h-full w-full flex-col overflow-hidden bg-transparent" : "flex h-[452px] w-[590px] flex-col overflow-hidden rounded-[16px] border border-line-2 bg-bg-2 shadow-[0_18px_42px_-20px_rgba(0,0,0,0.75)]"}>
      {embedded ? (
        <>
          <div className="relative min-h-0 flex-1 overflow-hidden">
            <div ref={scrollerRef} className="settings-scroll scroll-area glass-page-scroll h-full overflow-y-auto" style={{ "--glass-header-height": "78px" } as React.CSSProperties}>
              <div className="scroll-content px-6 pb-[68px] pt-[78px]">
                {settingsBody}
              </div>
            </div>
            <ScrollGlassHeader scrollerRef={scrollerRef} contentKey={tab} className="absolute inset-x-0 top-0 z-20 border-b border-line-1 px-6 pb-3 pt-4" foregroundClassName="flex h-10 items-center">
              {headerBar}
            </ScrollGlassHeader>
            <ScrollGlassHeader edge="bottom" scrollerRef={scrollerRef} contentKey={tab} className="absolute inset-x-0 bottom-0 z-20 border-t border-line-1 px-6 py-2" foregroundClassName="flex min-h-11 items-center justify-between gap-3">
              {renderFooter("contents")}
            </ScrollGlassHeader>
          </div>
        </>
      ) : (
        <>
          <header className="flex h-12 shrink-0 items-center border-b border-line-1 px-6">{headerBar}</header>
          <div className="settings-scroll scroll-area min-h-0 flex-1 overflow-y-auto px-6 py-3">{settingsBody}</div>
          {footer}
        </>
      )}
    </motion.div>
    <ConfirmModal
      open={confirmManualOpen}
      title={t("component.mode.confirmTitle")}
      message={t("component.mode.confirmManual")}
      confirmLabel={t("component.mode.confirmAction")}
      cancelLabel={t("common.cancel")}
      onCancel={() => setConfirmManualOpen(false)}
      onConfirm={() => {
        setConfirmManualOpen(false);
        if (confirmManualBackend === "zapret2") {
          const nextZapret2 = { ...settings.zapret2, controlMode: "manual" as const };
          patchOptimistic({
            settings: { zapret2: nextZapret2 },
            orchestrator: { mode: "manual", isAuto: false, backend: "zapret2" },
          });
          patch({ zapret2: nextZapret2 });
          void bridge.call("orchestrator.setMode", { mode: "manual", backend: "zapret2" });
          return;
        }
        const nextZapret = { ...settings.zapret, controlMode: "manual" as const };
        patchOptimistic({
          settings: { zapret: nextZapret },
          orchestrator: { mode: "manual", isAuto: false },
        });
        patch({ zapret: nextZapret });
        void bridge.call("orchestrator.setMode", { mode: "manual", backend: "zapret" });
      }}
    />
    <SurfGameModal
      open={surfOpen}
      locale={locale === "en" ? "en" : "ru"}
      onClose={() => setSurfOpen(false)}
    />
  </motion.div>}</AnimatePresence>;
}
