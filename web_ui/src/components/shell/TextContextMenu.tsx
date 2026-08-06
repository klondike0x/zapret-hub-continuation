import { useEffect, useState } from "react";
import { getBridge } from "@/bridge";
import { useLocale } from "@/hooks/useLocale";

type MenuState = { x: number; y: number; canEdit: boolean; hasSelection: boolean } | null;
type EditAction = "cut" | "copy" | "paste" | "select-all";

function editableTarget(target: EventTarget | null): HTMLElement | null {
  if (!(target instanceof HTMLElement)) return null;
  const node = target.closest<HTMLElement>("input, textarea, [contenteditable='true'], [contenteditable='plaintext-only']");
  if (!node) return null;
  if (node instanceof HTMLInputElement && ["button", "checkbox", "radio", "range", "file", "color"].includes(node.type)) {
    return null;
  }
  return node;
}

function targetHasSelection(node: HTMLElement): boolean {
  if (node instanceof HTMLInputElement || node instanceof HTMLTextAreaElement) {
    return Number(node.selectionEnd || 0) > Number(node.selectionStart || 0);
  }
  return Boolean(window.getSelection()?.toString());
}

export function TextContextMenu() {
  const { locale } = useLocale();
  const ru = locale === "ru";
  const [menu, setMenu] = useState<MenuState>(null);

  useEffect(() => {
    const onContextMenu = (event: MouseEvent) => {
      event.preventDefault();
      const target = editableTarget(event.target);
      if (!target) {
        setMenu(null);
        return;
      }
      target.focus({ preventScroll: true });
      const width = 174;
      const height = 154;
      setMenu({
        x: Math.max(8, Math.min(event.clientX, window.innerWidth - width - 8)),
        y: Math.max(8, Math.min(event.clientY, window.innerHeight - height - 8)),
        canEdit: !(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)
          || (!target.readOnly && !target.disabled),
        hasSelection: targetHasSelection(target),
      });
    };
    const close = () => setMenu(null);
    window.addEventListener("contextmenu", onContextMenu, true);
    window.addEventListener("pointerdown", close);
    window.addEventListener("blur", close);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("contextmenu", onContextMenu, true);
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("blur", close);
      window.removeEventListener("resize", close);
    };
  }, []);

  if (!menu) return null;
  const labels: Record<EditAction, string> = ru
    ? { cut: "Вырезать", copy: "Копировать", paste: "Вставить", "select-all": "Выделить всё" }
    : { cut: "Cut", copy: "Copy", paste: "Paste", "select-all": "Select all" };
  const run = (action: EditAction) => {
    void getBridge().call("window.edit", { action });
    setMenu(null);
  };
  const items: Array<{ action: EditAction; disabled: boolean }> = [
    { action: "cut", disabled: !menu.canEdit || !menu.hasSelection },
    { action: "copy", disabled: !menu.hasSelection },
    { action: "paste", disabled: !menu.canEdit },
    { action: "select-all", disabled: false },
  ];

  return (
    <div
      role="menu"
      className="fixed z-[10000] w-[174px] overflow-hidden rounded-[11px] border border-line-2 bg-bg-1/95 p-1.5 shadow-[0_12px_32px_rgba(0,0,0,.28)] backdrop-blur-xl"
      style={{ left: menu.x, top: menu.y }}
      onPointerDown={(event) => event.stopPropagation()}
    >
      {items.map(({ action, disabled }, index) => (
        <button
          key={action}
          type="button"
          role="menuitem"
          disabled={disabled}
          onPointerDown={(event) => event.preventDefault()}
          onClick={() => run(action)}
          className={`flex h-8 w-full items-center rounded-[7px] px-3 text-left text-[11px] transition-colors disabled:opacity-35 ${
            index === 3 ? "mt-1 border-t border-line-1 pt-px" : ""
          } hover:bg-bg-3 hover:text-fg text-fg-dim`}
        >
          {labels[action]}
        </button>
      ))}
    </div>
  );
}
