import { useEffect, useMemo, useState } from "react";
import { useAppState, useBridge } from "@/hooks/useBridgeState";
import { useLocale } from "@/hooks/useLocale";
import { Segmented } from "@/components/ui/Segmented";
import type { FileKind } from "@/bridge/types";
import { useToast } from "@/components/shell/ToastHost";
import { uiAssetUrl } from "@/lib/assets";

const KINDS_CLASSIC: FileKind[] = ["domains", "exclusions", "ip-lists", "ip-exclusions", "general", "hosts", "advanced"];
const KINDS_ZAPRET2: FileKind[] = ["domains", "exclusions", "ip-lists", "advanced", "hosts", "general"];
const LIST_KINDS = new Set<FileKind>(["domains", "exclusions", "ip-lists", "ip-exclusions", "hosts", "advanced"]);

const zapret2Meta: Record<string, { label: string; description: string; readonly?: boolean }> = {
  domains: { label: "Домены", description: "list-hub.txt - домены, которые передаются в Zapret 2." },
  exclusions: { label: "Исключения", description: "list-exclude.txt - адреса, которые не обрабатываются Zapret 2." },
  "ip-lists": { label: "IP-листы", description: "ipset-hub.txt - IP и подсети для правил Zapret 2." },
  advanced: { label: "Авто-дополнения", description: "list-auto.txt - данные, добавленные автоматическим подбором." },
  hosts: { label: "Lua-цели", description: "hub-targets.lua - пользовательские Lua-цели Zapret 2." },
  general: { label: "Lua-профиль", description: "hub-strategy.lua создается выбранной стратегией. Меняйте профиль в настройках Zapret 2.", readonly: true },
};

export function FilesPage({ nestedInSettings = false, onBack, runtime = "zapret" }: { nestedInSettings?: boolean; onBack?: () => void; runtime?: "zapret" | "zapret2" }) {
  const state = useAppState();
  const bridge = useBridge();
  const { t, locale } = useLocale();
  const toast = useToast();
  const isZapret2 = runtime === "zapret2";
  const kinds = isZapret2 ? KINDS_ZAPRET2 : KINDS_CLASSIC;
  const [kind, setKind] = useState<FileKind>("domains");
  const [buf, setBuf] = useState("");
  const [name, setName] = useState("");
  const [newEntry, setNewEntry] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => { if (!kinds.includes(kind)) setKind(kinds[0]); }, [isZapret2]); // eslint-disable-line react-hooks/exhaustive-deps
  const files = isZapret2 ? (state?.files2 || []) : (state?.files || []);
  const file = useMemo(() => files.find((item) => item.kind === kind), [files, kind]);
  const readOnly = Boolean(isZapret2 && zapret2Meta[kind]?.readonly);
  const listEditor = LIST_KINDS.has(kind) && !(isZapret2 && kind === "hosts");

  useEffect(() => {
    if (!file) return;
    setBuf(file.content);
    setName(file.name);
    setNewEntry("");
  }, [file?.kind, file?.name, file?.content]); // eslint-disable-line react-hooks/exhaustive-deps

  const rows = useMemo(() => buf.split(/\r?\n/).filter((line) => line.trim() && !line.trim().startsWith("#")), [buf]);
  const filteredRows = useMemo(() => {
    const query = search.trim().toLowerCase();
    return query ? rows.filter((row) => row.toLowerCase().includes(query)) : rows;
  }, [rows, search]);
  const options = kinds.map((value) => ({ value, label: isZapret2 ? zapret2Meta[value].label : t(`files.kind.${value}` as never) }));
  const prefix = isZapret2 ? "files2" : "files";
  const title = isZapret2 ? "Файлы Zapret 2" : t("files.title");
  const desc = isZapret2 ? zapret2Meta[kind]?.description : t("files.desc");

  const save = async (content = buf) => {
    if (!file || readOnly) return;
    const id = toast.push({ message: t("toast.applying") });
    try {
      await bridge.call(`${prefix}.save`, { kind: file.kind, name, content });
      setBuf(content);
      toast.push({ id, message: t("toast.applied"), kind: "success" });
    } catch {
      toast.push({ id, message: locale === "ru" ? "Не удалось сохранить файл" : "Save failed", kind: "error" });
    }
  };

  const addEntry = () => {
    const value = newEntry.trim();
    if (!value || rows.some((row) => row.trim().toLowerCase() === value.toLowerCase())) return;
    const next = `${value}\n${buf.replace(/^\s+/, "")}`;
    setNewEntry("");
    void save(next);
  };

  const removeEntry = (value: string) => {
    const removed = buf.split(/\r?\n/).filter((line) => line.trim() !== value.trim()).join("\n");
    void save(removed);
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="shrink-0 border-b border-line-1 px-6 pb-3 pt-5">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-2.5">
            {nestedInSettings && <button onClick={onBack} aria-label="Назад к настройкам" className="icon-button mt-[-2px] grid h-8 w-8 shrink-0 place-items-center rounded-[9px] text-fg-dim hover:bg-bg-3 hover:text-fg"><img src={uiAssetUrl("icons/arrow_left.svg")} className="component-icon-adaptive h-4 w-4" aria-hidden="true" /></button>}
            <div className="min-w-0"><h2 className="flex items-center gap-2 text-[15px] font-semibold text-fg">{nestedInSettings && <img src={uiAssetUrl("icons/files.svg")} className="component-icon-adaptive h-4 w-4" aria-hidden="true" />}{title}</h2><p className="mt-0.5 text-[11px] text-fg-dim">{desc}</p></div>
          </div>
          <div className="flex items-center gap-2">
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("files.search")} className="h-7 w-32 rounded-lg border border-line-1 bg-bg-1 px-2 text-[11px] text-fg outline-none placeholder:text-fg-mute focus:border-line-2" />
            {!listEditor && !readOnly && <button onClick={() => void save()} className="rounded-lg border border-line-2 bg-bg-3 px-2.5 py-1 text-[11px] text-fg hover:opacity-90">{t("files.save")}</button>}
          </div>
        </div>
        <div className="mt-3"><Segmented value={kind} onChange={setKind} options={options} size="sm" /></div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-6 py-3">
        {readOnly ? <textarea value={buf} readOnly spellCheck={false} className="h-full min-h-[260px] w-full resize-none rounded-xl border border-line-1 bg-bg-1/60 p-3 font-mono text-[12px] leading-relaxed text-fg-dim outline-none" /> : listEditor ? (
          <div className="space-y-3">
            <div className="flex gap-2"><input value={newEntry} onChange={(event) => setNewEntry(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); addEntry(); } }} placeholder={isZapret2 ? "Добавить значение в начало списка" : "Добавить правило в начало списка"} className="h-9 min-w-0 flex-1 rounded-lg border border-line-1 bg-bg-1 px-3 text-[12px] text-fg outline-none placeholder:text-fg-mute focus:border-line-2" /><button onClick={addEntry} className="rounded-lg border border-line-2 bg-bg-3 px-3 text-[11px] text-fg hover:opacity-90">Добавить</button></div>
            <p className="text-[10px] text-fg-mute">Новые записи всегда добавляются первыми. Это сохраняет приоритет пользовательских правил.</p>
            <div className="flex flex-wrap gap-2">{filteredRows.map((row, index) => <span key={`${row}-${index}`} className="group flex max-w-full items-center gap-1 rounded-lg border border-line-1 bg-bg-1 px-2 py-1 text-[11px] text-fg"><span className="max-w-[420px] truncate">{row}</span><button onClick={() => removeEntry(row)} aria-label={`Удалить ${row}`} className="ml-1 text-fg-mute hover:text-[var(--err)]">×</button></span>)}</div>
            {!filteredRows.length && <div className="py-12 text-center text-[12px] text-fg-mute">Список пока пуст.</div>}
          </div>
        ) : <textarea value={buf} onChange={(event) => setBuf(event.target.value)} spellCheck={false} className="h-full min-h-[260px] w-full resize-none rounded-xl border border-line-1 bg-bg-1 p-3 font-mono text-[12px] leading-relaxed text-fg outline-none focus:border-line-2" />}
      </div>
    </div>
  );
}
