import { useMemo, useState, useEffect, useRef } from "react";
import { useAppState, useBridge, refreshLogs } from "@/hooks/useBridgeState";
import { useLocale } from "@/hooks/useLocale";
import { Segmented } from "@/components/ui/Segmented";
import type { LogSource } from "@/bridge/types";

const SOURCES: (LogSource | "all")[] = ["all", "app", "zapret", "zapret2"];

/** Poll only while this page is the active nav — pages stay mounted after prewarm. */
export function LogsPage({ active = false }: { active?: boolean }) {
  const state = useAppState();
  const bridge = useBridge();
  const { t, locale } = useLocale();
  const [source, setSource] = useState<LogSource | "all">("all");
  const [filter, setFilter] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const followTail = useRef(true);

  // Process stdout only appears on rebuild — poll while Logs is open.
  useEffect(() => {
    if (!active) return;
    refreshLogs();
    const timer = window.setInterval(() => refreshLogs(), 2500);
    return () => window.clearInterval(timer);
  }, [active]);

  const logs = useMemo(() => {
    const all = state?.logs ?? [];
    return all
      .filter((l) => source === "all" || l.source === source)
      .filter((l) => !filter.trim() || l.message.toLowerCase().includes(filter.toLowerCase()));
  }, [state?.logs, source, filter]);

  useEffect(() => {
    if (followTail.current) listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [logs.length]);

  const options = SOURCES.map((s) => ({ value: s, label: s === "all" ? (locale === "ru" ? "Все" : "All") : s === "app" ? "Hub" : t(`logs.source.${s}` as never) }));

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-line-1 px-6 pb-3 pt-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[15px] font-semibold text-fg">{t("logs.title")}</h2>
          </div>
          <div className="flex items-center gap-2">
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder={t("logs.filter")}
              className="h-7 w-40 rounded-lg border border-line-1 bg-bg-1 px-2 text-[11px] text-fg outline-none placeholder:text-fg-mute focus:border-line-2"
            />
            <button onClick={() => bridge.call("logs.copy", { source: source === "all" ? undefined : source })} className="rounded-lg border border-line-1 bg-bg-1 px-2.5 py-1 text-[11px] text-fg-dim transition-all duration-200 hover:bg-bg-3 hover:text-fg">{t("logs.copy")}</button>
            <button onClick={() => bridge.call("logs.export", { source: source === "all" ? undefined : source })} className="rounded-lg border border-line-1 bg-bg-1 px-2.5 py-1 text-[11px] text-fg-dim transition-all duration-200 hover:bg-bg-3 hover:text-fg">{t("logs.export")}</button>
            <button onClick={() => bridge.call("logs.clear", { source: source === "all" ? undefined : source })} className="rounded-lg border border-line-1 bg-bg-1 px-2.5 py-1 text-[11px] text-fg-dim transition-all duration-200 hover:bg-bg-3 hover:text-fg">{t("logs.clear")}</button>
          </div>
        </div>
        <div className="mt-3">
          <Segmented value={source} onChange={setSource} options={options} size="sm" />
        </div>
      </div>
      <div
        ref={listRef}
        onScroll={(event) => {
          const target = event.currentTarget;
          followTail.current = target.scrollHeight - target.scrollTop - target.clientHeight < 36;
        }}
        className="scroll-area min-w-0 flex-1 overflow-x-hidden overflow-y-auto px-6 py-3 font-mono text-[11px] leading-[1.55] text-fg-dim"
      >
        {logs.length === 0 && <div className="grid h-full place-items-center text-[12px] text-fg-mute">{locale === "ru" ? "Логов пока нет" : "No logs yet"}</div>}
        {logs.map((l) => (
          <div key={l.id} className="flex w-full min-w-0 gap-3">
            <span className="w-16 shrink-0 text-fg-mute">{new Date(l.ts).toLocaleTimeString()}</span>
            <span className="w-14 shrink-0 uppercase text-fg-mute">{l.source}</span>
            <span
              className="w-10 shrink-0 uppercase"
              style={{ color: l.level === "error" ? "var(--err)" : l.level === "warn" ? "var(--warn)" : "var(--fg-mute)" }}
            >{l.level}</span>
            <span className="min-w-0 flex-1 whitespace-pre-wrap break-words [overflow-wrap:anywhere] text-fg">{l.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
