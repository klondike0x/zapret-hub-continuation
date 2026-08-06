import { useState } from "react";
import { motion } from "framer-motion";
import { uiAssetUrl } from "@/lib/assets";
import { useBridge } from "@/hooks/useBridgeState";

export type NavKey = "quick" | "components" | "installed" | "mods" | "files" | "logs" | "settings";

const icons: Record<NavKey, string> = {
  quick: "home.svg",
  components: "components.svg",
  installed: "mods.svg",
  mods: "mods.svg",
  files: "files.svg",
  logs: "logs.svg",
  settings: "settings.svg",
};

const github = (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
    <path d="M12 .5C5.65.5.5 5.65.5 12a11.5 11.5 0 0 0 7.86 10.92c.58.11.79-.25.79-.56v-2c-3.2.7-3.87-1.36-3.87-1.36-.52-1.33-1.28-1.68-1.28-1.68-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.76 2.7 1.25 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.7 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.47.11-3.07 0 0 .97-.31 3.18 1.18a11.1 11.1 0 0 1 5.79 0c2.21-1.49 3.18-1.18 3.18-1.18.63 1.6.23 2.78.11 3.07.74.81 1.19 1.84 1.19 3.1 0 4.43-2.7 5.4-5.27 5.69.41.35.78 1.05.78 2.12v3.14c0 .31.21.68.8.56A11.5 11.5 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5z"/>
  </svg>
);

const items: { key: NavKey; label: string }[] = [
  { key: "quick", label: "Quick access" },
  { key: "components", label: "Components" },
  { key: "installed", label: "Installed mods" },
  { key: "logs", label: "Logs" },
  { key: "settings", label: "Settings" },
];

export function Sidebar({ current, onSelect, labels }: { current: NavKey; onSelect: (k: NavKey) => void; labels: Record<NavKey, string> }) {
  const bridge = useBridge();
  const [hovered, setHovered] = useState<NavKey | null>(null);

  return (
    <nav className="sidebar flex h-full w-[74px] shrink-0 flex-col items-center bg-transparent py-3">
      <ul className="flex flex-col items-center gap-1">
        {items.map((it) => {
          const active = current === it.key;
          return (
            <li key={it.key} className="relative">
              <button
                onClick={() => onSelect(it.key)}
                onPointerEnter={() => setHovered(it.key)}
                onPointerLeave={() => setHovered((key) => key === it.key ? null : key)}
                aria-label={labels[it.key]}
                title={labels[it.key]}
                className={`nav-button relative grid h-11 w-11 flex-none place-items-center rounded-[13px] text-fg-dim outline-none ${active ? "text-[var(--nav-accent)]" : "hover:bg-bg-3/65 hover:text-fg"}`}
              >
                {active && (
                  <motion.span
                    layoutId="nav-outline"
                    transition={{ type: "spring", stiffness: 500, damping: 38 }}
                    className="absolute inset-0 rounded-[13px] border border-line-2 bg-[color:rgba(184,201,231,0.045)]"
                  />
                )}
                <motion.span
                  initial={false}
                  animate={{ scale: active ? 1.055 : hovered === it.key ? 1.04 : 1 }}
                  transition={{ type: "spring", stiffness: 420, damping: 30, mass: 0.7 }}
                  className={`nav-icon relative block bg-current ${it.key === "quick" ? "h-[25px] w-[25px]" : it.key === "logs" ? "h-[23px] w-[20px]" : it.key === "settings" ? "h-[21px] w-[21px]" : it.key === "installed" ? "h-[23px] w-[23px]" : "h-6 w-6"}`}
                  style={{
                    WebkitMask: `url("${uiAssetUrl(`icons/${icons[it.key]}`)}") center / contain no-repeat`,
                    mask: `url("${uiAssetUrl(`icons/${icons[it.key]}`)}") center / contain no-repeat`,
                  }}
                  aria-hidden="true"
                />
              </button>
            </li>
          );
        })}
      </ul>
      <div className="mt-auto flex flex-col items-center">
        <button
          type="button"
          onClick={() => void bridge.call("ui.open-url", { url: "https://github.com/klondike0x/zapret-hub-continuation" })}
          aria-label="GitHub"
          title="GitHub"
          className="sidebar-link grid h-11 w-11 place-items-center text-fg-dim opacity-55"
        >
          {github}
        </button>
      </div>
    </nav>
  );
}
