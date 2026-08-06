import { uiAssetUrl } from "@/lib/assets";

const SURF_URL = uiAssetUrl("games/surf/index.html");

export function SurfGameModal({
  open,
  locale,
  onClose,
  warm = false,
}: {
  open: boolean;
  locale: "ru" | "en";
  onClose: () => void;
  warm?: boolean;
}) {
  const ru = locale === "ru";
  if (!open && !warm) return null;

  return (
    <div
      className={
        open
          ? "fixed inset-0 z-[110] flex items-center justify-center bg-black/55 p-5"
          : "pointer-events-none fixed -left-[2000px] top-0 z-[-1] h-[460px] w-[760px] opacity-0"
      }
      onPointerDown={open ? (event) => event.stopPropagation() : undefined}
      aria-hidden={!open}
    >
      {/* Outer frame: close sits to the RIGHT of the game panel (top-aligned, not above). */}
      <div className="relative flex h-full max-h-[460px] w-full max-w-[800px] items-start gap-2">
        <div className="relative h-full min-w-0 flex-1 overflow-hidden rounded-[16px] border border-line-1 bg-[#0b1220] shadow-[0_24px_60px_-28px_rgba(0,0,0,.75)]">
          <iframe
            title={ru ? "Игра Let's Surf" : "Let's Surf game"}
            src={SURF_URL}
            className="absolute inset-0 h-full w-full border-0"
            allow="fullscreen; gamepad; autoplay"
            tabIndex={open ? 0 : -1}
          />
        </div>
        {open && (
          <button
            type="button"
            onClick={onClose}
            className="z-10 grid h-8 w-8 shrink-0 place-items-center rounded-[9px] border border-white/15 bg-black/45 text-[18px] leading-none text-white/85 transition-colors hover:bg-black/65 hover:text-white"
            aria-label={ru ? "Закрыть игру" : "Close game"}
          >
            ×
          </button>
        )}
      </div>
    </div>
  );
}
