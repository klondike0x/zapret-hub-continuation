import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useAppState, useBridge, patchOptimistic } from "@/hooks/useBridgeState";
import { useLocale } from "@/hooks/useLocale";
import { uiAssetUrl } from "@/lib/assets";

function BellIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 2.7a6 6 0 0 0-6 6v2.9c0 1.5-.55 2.94-1.55 4.05L3.2 17.04A1.15 1.15 0 0 0 4.05 19h15.9a1.15 1.15 0 0 0 .85-1.96l-1.25-1.39A6.05 6.05 0 0 1 18 11.6V8.7a6 6 0 0 0-6-6ZM9.5 20.2a2.7 2.7 0 0 0 5 0h-5Z" />
    </svg>
  );
}
function GearIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor">
      <path fillRule="evenodd" d="M10.7 2.3h2.6l.55 2.05c.55.2 1.08.5 1.55.9l2.05-.55 1.85 1.85-.55 2.05c.4.47.7 1 .9 1.55l2.05.55v2.6l-2.05.55c-.2.55-.5 1.08-.9 1.55l.55 2.05-1.85 1.85-2.05-.55c-.47.4-1 .7-1.55.9l-.55 2.05h-2.6l-.55-2.05a8 8 0 0 1-1.55-.9l-2.05.55-1.85-1.85.55-2.05a8 8 0 0 1-.9-1.55l-2.05-.55v-2.6l2.05-.55c.2-.55.5-1.08.9-1.55L4.7 6.55 6.55 4.7l2.05.55c.47-.4 1-.7 1.55-.9l.55-2.05ZM12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z" clipRule="evenodd" />
    </svg>
  );
}

function SidebarIcon({ active }: { active: boolean }) {
  return (
    <svg width="16" height="16" viewBox="0 0 18 18" fill="none" aria-hidden="true">
      <rect x="1.25" y="2.25" width="15.5" height="13.5" rx="3" stroke="currentColor" strokeWidth="1.5" />
      {active ? (
        <path d="M4.25 2.25h2.9v13.5h-2.9a3 3 0 0 1-3-3v-7.5a3 3 0 0 1 3-3Z" fill="currentColor" />
      ) : (
        <path d="M6.35 2.8v12.4" stroke="currentColor" strokeWidth="1.4" />
      )}
    </svg>
  );
}

function WinBtn({ onClick, children, danger, ariaLabel }: { onClick: () => void; children: React.ReactNode; danger?: boolean; ariaLabel: string }) {
  return (
    <button
      onClick={onClick}
      aria-label={ariaLabel}
      className={`grid h-9 w-9 place-items-center rounded-[9px] text-fg-dim outline-none transition-colors ${danger ? "hover:bg-[var(--err)] hover:text-white" : "hover:bg-bg-3/80 hover:text-fg"}`}
    >
      {children}
    </button>
  );
}

export function WindowFrame({
  sidebarCollapsed = false,
  onToggleSidebar,
}: {
  sidebarCollapsed?: boolean;
  onToggleSidebar?: () => void;
}) {
  const bridge = useBridge();
  const state = useAppState();
  const { t } = useLocale();
  const [notifOpen, setNotifOpen] = useState(false);
  const unread = state?.notifications.filter((n) => !n.read).length ?? 0;

  return (
    <div
      className="window-frame flex h-[50px] shrink-0 items-center justify-between bg-bg-0 select-none"
      onPointerDown={(event) => {
        if (event.button !== 0 || (event.target as HTMLElement).closest("button")) return;
        bridge.call("window.startDrag", undefined);
      }}
    >
      <div className="flex h-full items-center gap-2 pl-[14px] text-[12px]">
        <img src={uiAssetUrl("icons/app.png")} aria-hidden="true" className="h-[22px] w-[22px] shrink-0 object-contain" />
        <span className="brand-font text-[16px] font-semibold tracking-[-0.02em] text-fg">{t("app.name")}</span>
        <span className="text-[12px] text-fg-dim">{t("app.by")}</span>
      </div>
      <div className="flex h-full items-center pr-[7px]" style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}>
        <WinBtn
          ariaLabel={sidebarCollapsed ? t("nav.showSidebar") : t("nav.hideSidebar")}
          onClick={() => {
            if (onToggleSidebar) {
              onToggleSidebar();
              return;
            }
            void bridge.call("settings.apply", { patch: { sidebarCollapsed: !sidebarCollapsed } });
            patchOptimistic({ settings: { sidebarCollapsed: !sidebarCollapsed } });
          }}
        >
          <SidebarIcon active={!sidebarCollapsed} />
        </WinBtn>
        {notifOpen && <button aria-label="Close notifications" className="fixed inset-0 z-40 cursor-default" onClick={() => setNotifOpen(false)} />}
        <div className="relative">
          <WinBtn ariaLabel="Notifications" onClick={() => { setNotifOpen((v) => !v); bridge.call("notifications.markRead", {}); }}>
            <div className="relative">
              <BellIcon />
              {unread > 0 && <span className="absolute -right-1 -top-1 h-1.5 w-1.5 rounded-full bg-[var(--ok)]" />}
            </div>
          </WinBtn>
          <AnimatePresence>
            {notifOpen && (
              <motion.div
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -2 }}
                transition={{ duration: 0.15 }}
                className="notification-popover absolute right-0 top-11 z-50 w-80 overflow-hidden rounded-2xl border border-line-1 bg-bg-2"
              >
                <div className="border-b border-line-1 px-3 py-2 text-[12px] font-medium text-fg">{t("notif.title")}</div>
                <ul className="max-h-[min(22rem,70vh)] overflow-y-auto py-1">
                  {(state?.notifications ?? []).length === 0 && (
                    <li className="px-3 py-6 text-center text-[12px] text-fg-mute">{t("notif.empty")}</li>
                  )}
                  {state?.notifications.map((n) => (
                    <li key={n.id} className="group flex items-start gap-2 px-3 py-2.5 hover:bg-bg-3">
                      <span
                        className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
                        style={{ background: n.level === "success" ? "var(--ok)" : n.level === "warn" ? "var(--warn)" : n.level === "error" ? "var(--err)" : "var(--fg-mute)" }}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="whitespace-pre-wrap break-words text-[12px] font-medium leading-snug text-fg">{n.title}</div>
                        {n.body && <div className="mt-0.5 whitespace-pre-wrap break-words text-[11px] leading-snug text-fg-dim">{n.body}</div>}
                      </div>
                      <button onClick={() => bridge.call("notifications.dismiss", { id: n.id })} className="shrink-0 text-[11px] text-fg-mute opacity-0 transition-opacity group-hover:opacity-100 hover:text-fg">×</button>
                    </li>
                  ))}
                </ul>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        <WinBtn ariaLabel="Minimize" onClick={() => bridge.call("window.minimize", undefined)}>
          <svg width="12" height="12" viewBox="0 0 12 12"><rect x="2" y="6" width="8" height="1" fill="currentColor" /></svg>
        </WinBtn>
        <WinBtn ariaLabel="Close" danger onClick={() => bridge.call("window.close", undefined)}>
          <svg width="12" height="12" viewBox="0 0 12 12" stroke="currentColor" strokeWidth="1.2">
            <path d="M3 3l6 6M9 3l-6 6" />
          </svg>
        </WinBtn>
      </div>
    </div>
  );
}
