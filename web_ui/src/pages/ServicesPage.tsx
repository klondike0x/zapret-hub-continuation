import { useAppState, useBridge, patchOptimistic } from "@/hooks/useBridgeState";
import { useLocale } from "@/hooks/useLocale";
import { motion } from "framer-motion";
import { serviceIconNeedsContrast, serviceIconUrl } from "@/lib/serviceAssets";
import { useRef, useState } from "react";
import { ScrollGlassHeader } from "@/components/ui/ScrollGlassHeader";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { bridgeIdle } from "@/lib/schedule";

const serviceAccent: Record<string, string> = {
  cloudflare: "#f59b34", discord: "#6d7cf5", youtube: "#ff315b", telegram: "#35b7eb", "telegram-desktop": "#35b7eb",
  gaming: "#58c982", clouds: "#8490a4", ai: "#9f7cec", ubisoft: "#7f8ca0",
};

function ServiceIcon({ id }: { id: string }) {
  return <img src={serviceIconUrl(id)} alt="" className={`h-[28px] w-[28px] object-contain ${serviceIconNeedsContrast(id) ? "service-icon-adaptive" : ""}`} />;
}

export function ServicesPage() {
  const state = useAppState();
  const bridge = useBridge();
  const { t } = useLocale();
  const scrollerRef = useRef<HTMLDivElement>(null);
  const [confirmManualOpen, setConfirmManualOpen] = useState(false);
  if (!state) return null;

  const { available, selected } = state.services;
  const isAuto = state.orchestrator?.mode === "auto"
    || state.orchestrator?.isAuto
    || state.settings.zapret.controlMode === "auto";

  const toggle = (id: string) => {
    if (isAuto) return;
    const next = selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id];
    patchOptimistic({ servicesSelected: next });
    bridgeIdle(() => bridge.call("services.set", { selected: next }));
  };

  const switchToManual = () => {
    patchOptimistic({
      settings: { zapret: { ...state.settings.zapret, controlMode: "manual" } },
      orchestrator: { mode: "manual", isAuto: false },
    });
    void bridge.call("orchestrator.setMode", { mode: "manual" });
  };

  const allSelected = selected.length === available.length;

  return (
    <div className="relative h-full overflow-hidden">
      <div ref={scrollerRef} className="scroll-area glass-page-scroll h-full overflow-auto">
      <div className="scroll-content px-7 pb-7 pt-[86px]">
        {isAuto && (
          <div className="mb-4 rounded-[14px] border border-line-1 bg-bg-1 px-4 py-3">
            <div className="text-[13px] font-semibold text-fg">{t("services.autoManaged")}</div>
            <p className="mt-1 text-[11px] leading-relaxed text-fg-dim">{t("services.autoManagedBody")}</p>
            <button
              type="button"
              onClick={() => setConfirmManualOpen(true)}
              className="mt-2.5 rounded-lg border border-line-1 bg-bg-2 px-3 py-1.5 text-[11px] text-fg-dim transition-all duration-200 hover:bg-bg-3 hover:text-fg"
            >
              {t("services.switchManual")}
            </button>
          </div>
        )}
        <div className={`grid grid-cols-4 gap-3.5 ${isAuto ? "pointer-events-none opacity-55" : ""}`}>
          {available.map((s, index) => {
            const on = selected.includes(s.id);
            return (
              <motion.button
                key={s.id}
                type="button"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: Math.min(index * 0.025, 0.32), duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
                whileTap={isAuto ? undefined : { scale: 0.97 }}
                onClick={() => toggle(s.id)}
                disabled={isAuto}
                aria-disabled={isAuto}
                className={`service-card relative flex min-h-[140px] flex-col items-start rounded-[16px] border p-3.5 text-left transition-all duration-200 ${on ? "bg-bg-2" : "border-line-1 bg-bg-2 hover:bg-bg-3"}`}
                style={on ? { borderColor: serviceAccent[s.id] ?? "var(--line-2)", boxShadow: `inset 0 1px 0 rgba(255,255,255,0.025), 0 12px 26px color-mix(in srgb, ${serviceAccent[s.id] ?? "#8290a8"} 9%, transparent)` } : undefined}
              >
                <div className="flex w-full items-center justify-between">
                  <div className="grid h-8 w-8 place-items-center">
                    <ServiceIcon id={s.id} />
                  </div>
                  <span
                    className={`h-2 w-2 rounded-full ${on ? "" : "opacity-30"}`}
                    style={{ background: on ? "var(--ok)" : "var(--fg-mute)" }}
                  />
                </div>
                <div className="mt-3.5 text-[14px] font-semibold text-fg">{s.name}</div>
                <div className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-fg-dim">{s.description}</div>
              </motion.button>
            );
          })}
        </div>
      </div>
      </div>
      <ScrollGlassHeader scrollerRef={scrollerRef} className="absolute inset-x-0 top-0 z-20 border-b border-line-1 px-7 pb-4 pt-5" foregroundClassName="flex items-start justify-between">
        <div>
          <h2 className="text-[15px] font-semibold text-fg">{t("services.title")}</h2>
          <p className="mt-0.5 text-[11px] text-fg-dim">{isAuto ? t("services.autoManaged") : t("services.desc")}</p>
        </div>
        {!isAuto && (
          <div className="flex items-center gap-2">
            <div className="rounded-full border border-line-1 bg-bg-2 px-3 py-1.5 text-[11px] text-fg-dim">
              {t("services.selected")}: <span className="text-fg">{selected.length}</span>
            </div>
            <button
              onClick={() => {
                const next = allSelected ? [] : available.map((s) => s.id);
                patchOptimistic({ servicesSelected: next });
                bridgeIdle(() => bridge.call("services.set", { selected: next }));
              }}
              className="rounded-lg border border-line-1 bg-bg-2 px-2.5 py-1.5 text-[11px] text-fg-dim transition-all duration-200 hover:bg-bg-3 hover:text-fg"
            >
              {allSelected ? t("services.clear") : t("services.selectAll")}
            </button>
          </div>
        )}
      </ScrollGlassHeader>
      <ConfirmModal
        open={confirmManualOpen}
        title={t("component.mode.confirmTitle")}
        message={t("component.mode.confirmManual")}
        confirmLabel={t("component.mode.confirmAction")}
        cancelLabel={t("common.cancel")}
        onCancel={() => setConfirmManualOpen(false)}
        onConfirm={() => {
          setConfirmManualOpen(false);
          switchToManual();
        }}
      />
    </div>
  );
}
