import { type ReactNode, type RefObject, useLayoutEffect, useRef, useState } from "react";

function sanitizeMirrorClone(root: HTMLElement) {
  root.querySelectorAll<HTMLElement>("*").forEach((node) => {
    node.style.pointerEvents = "none";
  });
  root.style.pointerEvents = "none";
}

export function ScrollGlassHeader({
  scrollerRef,
  children,
  className = "",
  foregroundClassName = "",
  contentKey,
  edge = "top",
}: {
  scrollerRef: RefObject<HTMLDivElement | null>;
  children: ReactNode;
  className?: string;
  foregroundClassName?: string;
  /** Identifies the foreground content without tearing down the live mirror. */
  contentKey?: string | number;
  /** Which edge of the scroll viewport this glass layer occupies. */
  edge?: "top" | "bottom";
}) {
  const mirrorRef = useRef<HTMLDivElement>(null);
  const [initRetry, setInitRetry] = useState(0);

  useLayoutEffect(() => {
    const scroller = scrollerRef.current;
    const mirror = mirrorRef.current;
    const source = scroller?.querySelector<HTMLElement>(".scroll-content");
    if (!scroller || !mirror || !source) {
      if (initRetry >= 4) return;
      const retryFrame = requestAnimationFrame(() => setInitRetry((value) => value + 1));
      return () => cancelAnimationFrame(retryFrame);
    }

    let clone: HTMLElement | null = null;
    let syncFrame = 0;
    let rebuildTimer = 0;
    let settleTimer = 0;

    const syncAnimatedStyles = () => {
      if (!clone) return;
      const sourceNodes = [source, ...source.querySelectorAll<HTMLElement>("*")];
      const cloneNodes = [clone, ...clone.querySelectorAll<HTMLElement>("*")];
      if (sourceNodes.length !== cloneNodes.length) {
        rebuild();
        return;
      }
      sourceNodes.forEach((sourceNode, index) => {
        const cloneNode = cloneNodes[index];
        const style = sourceNode.getAttribute("style");
        if (style === null) cloneNode.removeAttribute("style");
        else cloneNode.setAttribute("style", style);
        cloneNode.style.pointerEvents = "none";
      });
      clone.classList.add("scroll-header-mirror-content");
    };

    const sync = () => {
      syncFrame = 0;
      if (clone) {
        // Map the clone to the source's actual viewport coordinates. The
        // previous footer-only offset used the opposite direction, so a bottom
        // glass panel could show content from high up the settings page.
        const sourceRect = source.getBoundingClientRect();
        const mirrorRect = mirror.getBoundingClientRect();
        clone.style.transform = `translate3d(${sourceRect.left - mirrorRect.left}px, ${sourceRect.top - mirrorRect.top}px, 0)`;
      }
    };
    const scheduleSync = () => {
      if (!syncFrame) syncFrame = requestAnimationFrame(sync);
    };
    const rebuild = () => {
      rebuildTimer = 0;
      const nextClone = source.cloneNode(true) as HTMLElement;
      clone = nextClone;
      nextClone.classList.add("scroll-header-mirror-content");
      nextClone.setAttribute("aria-hidden", "true");
      nextClone.querySelectorAll("[id]").forEach((node) => node.removeAttribute("id"));
      sanitizeMirrorClone(nextClone);
      // Keep exactly one blurred snapshot. Cross-fading snapshots leaves two
      // differently positioned copies visible while Marketplace cards update.
      mirror.replaceChildren(nextClone);
      syncAnimatedStyles();
      sync();
    };
    const scheduleRebuild = () => {
      if (rebuildTimer) return;
      // AnimatePresence can briefly remove the old page before mounting the next
      // one. Keep the last mirror during that gap instead of flashing a sharp frame.
      rebuildTimer = window.setTimeout(rebuild, 24);
      if (settleTimer) window.clearTimeout(settleTimer);
      // Catch content after tab / page enter animations finish.
      settleTimer = window.setTimeout(rebuild, 220);
    };
    const scheduleAnimatedSync = () => {
      if (syncFrame) return;
      syncFrame = requestAnimationFrame(() => {
        syncFrame = 0;
        syncAnimatedStyles();
        sync();
      });
    };

    rebuild();
    settleTimer = window.setTimeout(rebuild, 220);
    scroller.addEventListener("scroll", scheduleSync, { passive: true });
    const observer = new MutationObserver((mutations) => {
      if (mutations.some((mutation) => mutation.type === "childList")) scheduleRebuild();
      else scheduleAnimatedSync();
    });
    observer.observe(source, { childList: true, subtree: true, attributes: true, attributeFilter: ["style", "class"] });
    return () => {
      scroller.removeEventListener("scroll", scheduleSync);
      observer.disconnect();
      if (syncFrame) cancelAnimationFrame(syncFrame);
      if (rebuildTimer) window.clearTimeout(rebuildTimer);
      if (settleTimer) window.clearTimeout(settleTimer);
    };
  }, [edge, initRetry, scrollerRef]);

  return (
    <div className={`scroll-header ${edge === "bottom" ? "scroll-footer" : ""} ${className}`} data-content-key={contentKey}>
      <div ref={mirrorRef} className="scroll-header-mirror" aria-hidden="true" />
      <div className="scroll-header-glass-tint" aria-hidden="true" />
      <div className={`scroll-header-foreground ${foregroundClassName}`}>{children}</div>
    </div>
  );
}
