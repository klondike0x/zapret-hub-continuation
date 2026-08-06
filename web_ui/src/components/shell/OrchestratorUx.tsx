import { useEffect, useRef } from "react";
import { useBridge } from "@/hooks/useBridgeState";
import { useLocale } from "@/hooks/useLocale";
import { useToast } from "@/components/shell/ToastHost";

/** Cooldown so conflict / long-pick toasts do not spam. */
const NOTIFY_COOLDOWN_MS = 45_000;

/**
 * Thin UX layer for Auto orchestrator notifies.
 * Long-pick comes ONLY from engine event `orchestrator.longPick` (no local timer duplicate).
 * Conflicts come ONLY from `orchestrator.conflict` when a real conflict is found.
 */
export function OrchestratorUx() {
  const bridge = useBridge();
  const { t, locale } = useLocale();
  const toast = useToast();
  const lastConflictAt = useRef(0);
  const lastLongPickAt = useRef(0);

  useEffect(() => {
    const offConflict = bridge.subscribe("orchestrator.conflict", (payload) => {
      const now = performance.now();
      if (now - lastConflictAt.current < NOTIFY_COOLDOWN_MS) return;
      lastConflictAt.current = now;
      const message = locale === "ru"
        ? (payload?.messageRu || t("orch.conflict.fallback"))
        : (payload?.messageEn || t("orch.conflict.fallback"));
      toast.push({ id: `orch-conflict-${Math.floor(now)}`, message, kind: "info" });
    });
    const offLong = bridge.subscribe("orchestrator.longPick", (payload) => {
      const now = performance.now();
      if (now - lastLongPickAt.current < NOTIFY_COOLDOWN_MS) return;
      lastLongPickAt.current = now;
      const domain = String(payload?.domain || (locale === "ru" ? "нужному сервису" : "the service"));
      const message = locale === "ru"
        ? (payload?.messageRu || t("orch.longPick").replace("{domain}", domain))
        : (payload?.messageEn || t("orch.longPick").replace("{domain}", domain));
      toast.push({ id: "orch-long-pick", message, kind: "info" });
    });
    return () => {
      offConflict();
      offLong();
    };
  }, [bridge, locale, t, toast]);

  return null;
}
