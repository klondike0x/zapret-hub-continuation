import { motion } from "framer-motion";

export function IosToggle({ on, onChange, disabled, label }: { on: boolean; onChange: (v: boolean) => void; disabled?: boolean; label?: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      data-sound="switch"
      disabled={disabled}
      onClick={() => onChange(!on)}
      className="relative inline-flex h-[22px] w-[38px] shrink-0 items-center rounded-full border border-line-1 p-[2px] outline-none transition-colors disabled:opacity-40"
      style={{ background: on ? "var(--fg)" : "var(--bg-2)" }}
    >
      <motion.span
        animate={{ x: on ? 16 : 0 }}
        transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
        className="block h-[16px] w-[16px] rounded-full"
        style={{ background: on ? "var(--bg-0)" : "var(--fg-dim)" }}
      />
    </button>
  );
}
