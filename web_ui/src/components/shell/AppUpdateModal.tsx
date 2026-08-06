import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { useLocale } from "@/hooks/useLocale";
import { useBridge } from "@/hooks/useBridgeState";
import { MarkdownContent } from "@/components/ui/MarkdownContent";

export type AppUpdatePrompt = {
  currentVersion: string;
  latestVersion: string;
  currentDigest?: string;
  latestDigest?: string;
  changelog: string;
  htmlUrl: string;
  isHotfix?: boolean;
  demo?: boolean;
};

export function AppUpdateModal({
  prompt,
  onClose,
  onPlayGame,
}: {
  prompt: AppUpdatePrompt | null;
  onClose: () => void;
  onPlayGame?: () => void;
}) {
  const { locale } = useLocale();
  const bridge = useBridge();
  const ru = locale === "ru";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState({ percent: 0, messageRu: "", messageEn: "", downloadedBytes: 0, totalBytes: 0 });

  useEffect(() => bridge.subscribe("app.update-progress", (value) => {
    if (String(value.phase || "") === "error") {
      setError(String(value.messageRu || value.messageEn || (ru ? "Не удалось установить обновление." : "Failed to install the update.")));
      setBusy(false);
      return;
    }
    setError("");
    setProgress({
      percent: Math.max(0, Math.min(100, Number(value.percent || 0))),
      messageRu: String(value.messageRu || ""),
      messageEn: String(value.messageEn || ""),
      downloadedBytes: Number(value.downloadedBytes || 0),
      totalBytes: Number(value.totalBytes || 0),
    });
  }), [bridge, ru]);

  const applyNow = async () => {
    if (!prompt || prompt.demo || busy) {
      onClose();
      return;
    }
    setBusy(true);
    setError("");
    setProgress({ percent: 1, messageRu: "Подготовка обновления", messageEn: "Preparing update", downloadedBytes: 0, totalBytes: 0 });
    try {
      await bridge.call("app.apply-update", { scheduleNextLaunch: false });
      // App should quit for overlay install; keep modal until then.
    } catch {
      setBusy(false);
    }
  };

  const scheduleNext = async () => {
    if (!prompt || prompt.demo || busy) {
      onClose();
      return;
    }
    setBusy(true);
    try {
      await bridge.call("app.apply-update", { scheduleNextLaunch: true });
      onClose();
    } catch {
      setBusy(false);
    }
  };

  return (
    <AnimatePresence>
      {prompt && (
        <motion.div
          key="app-update-modal"
          className="absolute inset-0 z-[90] grid place-items-center bg-black/46"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={() => { if (!busy) onClose(); }}
        >
          <motion.div
            initial={{ opacity: 0, y: 8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.98 }}
            transition={{ duration: 0.18 }}
            onClick={(event) => event.stopPropagation()}
            className="flex w-[520px] max-w-[92%] flex-col overflow-hidden rounded-[16px] border border-line-2 bg-bg-2 shadow-[0_18px_42px_-20px_rgba(0,0,0,0.75)]"
          >
            <header className="flex h-12 items-center justify-between border-b border-line-1 px-4">
              <div className="text-[13px] font-semibold text-fg">
                {prompt.isHotfix
                  ? (ru ? "Обнаружен hotfix" : "Hotfix available")
                  : (ru ? "Доступно обновление" : "Update available")}
              </div>
              <button type="button" disabled={busy} onClick={onClose} className="grid h-7 w-7 place-items-center rounded-[8px] text-fg-dim hover:bg-bg-3 hover:text-fg disabled:opacity-40">×</button>
            </header>
            <div className="space-y-3 px-4 py-3">
              <p className="whitespace-pre-line text-[12px] leading-relaxed text-fg-dim">
                {prompt.isHotfix
                  ? (ru
                    ? `Для Zapret Hub ${prompt.currentVersion} найден hotfix.\nHotfix - необязательное обновление, но оно может содержать важные исправления, поэтому настоятельно рекомендуем обновиться.`
                    : `A hotfix is available for Zapret Hub ${prompt.currentVersion}.\nA hotfix is optional, but it may contain important fixes, so updating is strongly recommended.`)
                  : (ru
                    ? "Вышла новая версия Zapret Hub."
                    : "A new Zapret Hub version is available.")}
              </p>
              <MarkdownContent className="max-h-[180px] overflow-y-auto rounded-[12px] border border-line-1 bg-bg-1 p-3 text-[11px] leading-relaxed text-fg-dim">
                {prompt.changelog || (ru ? "Список изменений недоступен." : "Changelog is unavailable.")}
              </MarkdownContent>
              {prompt.demo && (
                <div className="rounded-[10px] border border-line-1 bg-bg-3/60 px-3 py-2 text-[10px] text-fg-mute">
                  {ru ? "Тестовый показ интерфейса обновления (один раз)." : "One-time demo of the update UI."}
                </div>
              )}
              {error && (
                <div className="rounded-[10px] border border-red-400/40 bg-red-500/10 px-3 py-2 text-[11px] leading-relaxed text-red-200">
                  {error}
                </div>
              )}
              {busy && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-3 text-[11px] text-fg-dim">
                    <span>{ru ? (progress.messageRu || "Подготовка обновления") : (progress.messageEn || "Preparing update")}</span>
                    <span className="tabular-nums text-fg-mute">{Math.round(progress.percent)}%</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-bg-3">
                    <motion.div
                      className="h-full rounded-full bg-fg"
                      animate={{ width: `${Math.max(2, progress.percent)}%` }}
                      transition={{ duration: 0.2, ease: "easeOut" }}
                    />
                  </div>
                  {progress.totalBytes > 0 && (
                    <div className="text-[10px] tabular-nums text-fg-mute">
                      {(progress.downloadedBytes / 1048576).toFixed(1)} / {(progress.totalBytes / 1048576).toFixed(1)} MB
                    </div>
                  )}
                  <p className="text-[10px] leading-relaxed text-fg-mute">
                    {ru ? "Программа самостоятельно обновится и перезапустится. Пожалуйста, подождите." : "The app will update and restart automatically. Please wait."}
                  </p>
                  {onPlayGame && (
                    <button type="button" onClick={onPlayGame} className="mx-auto block rounded-[10px] border border-line-2 bg-bg-1 px-4 py-2 text-[11px] font-medium text-fg transition-colors hover:bg-bg-3">
                      {ru ? "Играть" : "Play"}
                    </button>
                  )}
                </div>
              )}
            </div>
            {!busy && <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-line-1 px-4 py-3">
              <button type="button" disabled={busy} onClick={onClose} className="rounded-[9px] border border-line-1 bg-bg-1 px-3 py-1.5 text-[11px] text-fg-dim hover:bg-bg-3 hover:text-fg disabled:opacity-40">
                {ru ? "Закрыть" : "Close"}
              </button>
              {prompt.htmlUrl && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void bridge.call("marketplace.open-url", { url: prompt.htmlUrl })}
                  className="rounded-[9px] border border-line-1 bg-bg-2 px-3 py-1.5 text-[11px] text-fg hover:bg-bg-3"
                >
                  {ru ? "Открыть ссылку" : "Open link"}
                </button>
              )}
              {!prompt.demo && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void scheduleNext()}
                  className="rounded-[9px] border border-line-1 bg-bg-1 px-3 py-1.5 text-[11px] text-fg-dim hover:bg-bg-3 hover:text-fg disabled:opacity-40"
                >
                  {ru ? "При следующем запуске" : "On next launch"}
                </button>
              )}
              <button
                type="button"
                disabled={busy}
                onClick={() => void applyNow()}
                className="rounded-[9px] border border-line-2 bg-fg px-3 py-1.5 text-[11px] font-medium text-bg-0 hover:opacity-90 disabled:opacity-40"
              >
                {ru ? "Обновить сейчас" : "Update now"}
              </button>
            </footer>}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
