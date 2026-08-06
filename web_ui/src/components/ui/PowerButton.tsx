import { type ButtonHTMLAttributes, type CSSProperties } from "react";
import { motion } from "framer-motion";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  on: boolean;
  status?: "off" | "starting" | "stopping" | "on" | "error";
  accent?: string;
  variant?: "main" | "side";
  "data-sound"?: string;
};

function onGradient(color: string) {
  return `radial-gradient(circle at 50% 27%, color-mix(in srgb, ${color} var(--power-active-top-weight), var(--power-active-top)) 0%, color-mix(in srgb, ${color} var(--power-active-mid-weight), var(--power-active-mid)) 58%, color-mix(in srgb, ${color} var(--power-active-bottom-weight), var(--power-active-bottom)) 100%)`;
}

function offGradient(color: string) {
  return `radial-gradient(circle at 48% 24%, color-mix(in srgb, ${color} 17%, var(--power-off-top)) 0%, color-mix(in srgb, ${color} 11%, var(--power-off-mid)) 60%, color-mix(in srgb, ${color} 7%, var(--power-off-bottom)) 100%)`;
}

export function PowerButton({ on, status, accent = "#6f91dd", variant = "main", className, onClick, disabled, title, type = "button", style, "data-sound": dataSound }: Props) {
  const s = status ?? (on ? "on" : "off");
  const transitioning = s === "starting" || s === "stopping";
  const color = s === "error" ? "var(--err)" : accent;
  const side = variant === "side";
  const lit = on && !transitioning;
  const diameter = side ? 88 : s === "on" ? 132 : transitioning ? 123 : 116;
  return (
    <motion.div
      initial={false}
      animate={{ width: side ? 116 : 174, height: side ? 116 : 174 }}
      transition={{ duration: 0.26, ease: [0.65, 0, 0.35, 1] }}
      className={`power-stage relative grid place-items-center ${className ?? ""}`}
      style={{ "--power-color": color, ...style } as CSSProperties}
    >
      {!side && <span className="power-aura" aria-hidden="true" />}
      {!side && s !== "off" && <span className={`power-wave power-wave-one ${s === "stopping" ? "power-wave-stopping" : ""}`} aria-hidden="true" />}
      {!side && s !== "off" && <span className={`power-wave power-wave-two ${s === "stopping" ? "power-wave-stopping" : ""}`} aria-hidden="true" />}
      <motion.button
        initial={false}
        data-sound={dataSound}
        onClick={onClick}
        disabled={disabled}
        title={title}
        type={type}
        whileTap={{ scale: 0.965 }}
        whileHover={{ scale: 1.035, filter: "brightness(1.09)" }}
        animate={{ width: diameter, height: diameter }}
        transition={{ duration: 0.24, ease: [0.65, 0, 0.35, 1] }}
        className={`power-button group relative grid place-items-center overflow-hidden rounded-full border-2 outline-none ${transitioning ? "is-transitioning" : ""}`}
        aria-pressed={on}
        aria-label={side ? (title ?? "Select runtime") : "Power"}
        style={{
          background: lit || s === "error" ? onGradient(color) : offGradient(color),
          borderColor: lit || s === "error"
            ? `color-mix(in srgb, ${color} 66%, white)`
            : transitioning
              ? `color-mix(in srgb, ${color} 40%, var(--power-off-border))`
              : `color-mix(in srgb, ${color} 25%, var(--power-off-border))`,
          boxShadow: lit || s === "error"
            ? `0 0 34px color-mix(in srgb, ${color} 32%, transparent), inset 0 2px 1px rgba(255,255,255,.23), inset 0 -14px 26px rgba(17,20,29,.22)`
            : "0 5px 15px rgba(0,0,0,.18), inset 0 2px 1px rgba(255,255,255,.07), inset 0 -12px 22px rgba(0,0,0,.2)",
        }}
      >
        {transitioning && (
          <span
            aria-hidden="true"
            className="power-breathe-tint absolute inset-0 rounded-full"
            style={{
              background: onGradient(color),
              boxShadow: `0 0 34px color-mix(in srgb, ${color} 28%, transparent), inset 0 2px 1px rgba(255,255,255,.2), inset 0 -14px 26px rgba(17,20,29,.18)`,
            }}
          />
        )}
        {(lit || s === "error") && <span aria-hidden="true" className="power-liquid absolute -inset-5 opacity-70" />}
        <motion.svg
          initial={false}
          animate={{ width: side ? 37 : s === "on" ? 50 : transitioning ? 47 : 44, height: side ? 37 : s === "on" ? 50 : transitioning ? 47 : 44 }}
          transition={{ duration: 0.24, ease: [0.65, 0, 0.35, 1] }}
          className="power-glyph relative z-[1] drop-shadow-sm"
          viewBox="0 0 64 64"
          fill="none"
          stroke="currentColor"
          strokeWidth="6"
          strokeLinecap="round"
        >
          <path d="M32 8v24" />
          <path d="M20.5 16.8A22 22 0 1 0 43.5 16.8" />
        </motion.svg>
      </motion.button>
    </motion.div>
  );
}
