import { motion } from "framer-motion";

export function Chevron({ dir = "right", className = "" }: { dir?: "left" | "right"; className?: string }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      style={{ transform: dir === "left" ? "rotate(180deg)" : undefined }}
    >
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}

export function StatusPill({ label, tone = "muted" }: { label: string; tone?: "ok" | "warn" | "err" | "muted" }) {
  const c = tone === "ok" ? "var(--ok)" : tone === "warn" ? "var(--warn)" : tone === "err" ? "var(--err)" : "var(--fg-mute)";
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-line-1 bg-bg-1 px-2.5 py-1 text-[11px] font-medium text-fg-dim">
      <motion.span
        className="h-1.5 w-1.5 rounded-full"
        style={{ background: c }}
        animate={{ opacity: [0.5, 1, 0.5] }}
        transition={{ duration: 2, repeat: Infinity }}
      />
      {label}
    </span>
  );
}

