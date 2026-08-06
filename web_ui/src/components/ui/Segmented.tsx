import { motion } from "framer-motion";
import { useId } from "react";

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  size = "md",
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
  size?: "sm" | "md";
}) {
  const id = useId();
  const h = size === "sm" ? "h-7" : "h-8";
  const px = size === "sm" ? "px-2.5" : "px-3";
  return (
    <div className={`inline-flex ${h} items-center gap-0.5 rounded-lg border border-line-1 bg-bg-1 p-0.5`}>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            onClick={() => onChange(o.value)}
            className={`relative ${px} h-full rounded-md text-[12px] font-medium transition-colors ${active ? "text-fg" : "text-fg-dim hover:text-fg"}`}
          >
            {active && (
              <motion.span
                layoutId={`seg-${id}`}
                transition={{ type: "spring", stiffness: 500, damping: 36 }}
                className="absolute inset-0 rounded-md bg-bg-3"
              />
            )}
            <span className="relative">{o.label}</span>
          </button>
        );
      })}
    </div>
  );
}

