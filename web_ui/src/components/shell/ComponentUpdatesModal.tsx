import { AnimatePresence, motion } from "framer-motion";
import { getBridge } from "@/bridge";
import { useLocale } from "@/hooks/useLocale";
import type { ComponentId } from "@/bridge/types";
import { uiAssetUrl } from "@/lib/assets";

export type ComponentUpdateItem = {
  id: ComponentId;
  name: string;
  currentVersion: string;
  latestVersion: string;
};

const icons: Record<string, string> = {
  zapret: "component_zapret.svg",
  zapret2: "component_zapret2.svg",
  "tg-ws-proxy": "component_tg.svg",
};

export function ComponentUpdatesModal({
  updates,
  onClose,
}: {
  updates: ComponentUpdateItem[] | null;
  onClose: () => void;
}) {
  const { locale } = useLocale();
  const ru = locale === "ru";
  if (!updates?.length) return null;

  const updateAll = () => {
    void getBridge().call("component.install-updates-all", { ids: updates.map((item) => item.id) });
    onClose();
  };

  return (
    <AnimatePresence>
      <motion.div className="absolute inset-0 z-[92] grid place-items-center bg-black/46" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
        <motion.div className="w-[470px] max-w-[92%] overflow-hidden rounded-[16px] border border-line-2 bg-bg-2 shadow-[0_18px_42px_-20px_rgba(0,0,0,0.75)]" initial={{ opacity: 0, y: 8, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} onClick={(event) => event.stopPropagation()}>
          <header className="flex items-center justify-between border-b border-line-1 px-4 py-3">
            <div className="text-[13px] font-semibold text-fg">{ru ? "Обновления компонентов" : "Component updates"}</div>
            <button type="button" onClick={onClose} className="grid h-7 w-7 place-items-center rounded-[8px] text-fg-dim hover:bg-bg-3 hover:text-fg">×</button>
          </header>
          <div className="space-y-2 px-4 py-3">
            <p className="text-[11px] text-fg-dim">{ru ? "Доступны новые версии вложенных компонентов. Обновить их сейчас?" : "New versions of bundled components are available. Update them now?"}</p>
            {updates.map((item) => (
              <div key={item.id} className="flex items-center gap-3 rounded-[11px] border border-line-1 bg-bg-1/70 px-3 py-2">
                <div className="grid h-8 w-8 shrink-0 place-items-center rounded-[9px] border border-line-1 bg-bg-2 p-1.5"><img src={uiAssetUrl(`icons/${icons[item.id]}`)} alt="" className="h-full w-full object-contain" /></div>
                <div className="min-w-0 flex-1"><div className="truncate text-[12px] font-semibold text-fg">{item.name}</div><div className="text-[10px] text-fg-mute">v{item.currentVersion} → v{item.latestVersion}</div></div>
              </div>
            ))}
          </div>
          <footer className="flex justify-end gap-2 border-t border-line-1 px-4 py-3">
            <button type="button" onClick={onClose} className="rounded-lg border border-line-1 bg-bg-1 px-3 py-1.5 text-[11px] text-fg-dim hover:bg-bg-3 hover:text-fg">{ru ? "Пропустить" : "Skip"}</button>
            <button type="button" onClick={updateAll} className="rounded-lg bg-[rgb(var(--page-accent-rgb))] px-3 py-1.5 text-[11px] font-medium text-white">{ru ? "Обновить всё" : "Update all"}</button>
          </footer>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
