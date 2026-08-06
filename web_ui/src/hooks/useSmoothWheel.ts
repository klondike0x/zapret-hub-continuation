import { useEffect } from "react";

type ScrollState = {
  target: number;
  frame: number | null;
  lastTime: number;
};

const states = new WeakMap<HTMLElement, ScrollState>();

function resetScroller(scroller: HTMLElement) {
  const state = states.get(scroller);
  if (!state) return;
  if (state.frame !== null) cancelAnimationFrame(state.frame);
  state.frame = null;
  state.lastTime = 0;
  state.target = scroller.scrollTop;
}

export function useSmoothWheel() {
  useEffect(() => {
    const onWheel = (event: WheelEvent) => {
      const target = event.target as HTMLElement | null;
      const scroller = target?.closest<HTMLElement>(".scroll-area");
      if (!scroller || target?.closest("textarea, input, select, .native-scroll")) return;

      const max = scroller.scrollHeight - scroller.clientHeight;
      if (max <= 0) return;

      const multiplier = event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 20 : event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? scroller.clientHeight : 1;
      const delta = event.deltaY * multiplier;
      if ((delta < 0 && scroller.scrollTop <= 0) || (delta > 0 && scroller.scrollTop >= max)) return;

      event.preventDefault();
      const state = states.get(scroller) ?? { target: scroller.scrollTop, frame: null, lastTime: 0 };
      state.target = Math.max(0, Math.min(max, state.target));
      if (state.frame === null) {
        state.target = scroller.scrollTop;
        state.lastTime = 0;
      }
      state.target = Math.max(0, Math.min(max, state.target + delta));
      states.set(scroller, state);

      if (state.frame !== null) return;
      const animate = (time: number) => {
        const elapsed = state.lastTime ? Math.min(34, time - state.lastTime) : 16.67;
        state.lastTime = time;
        const distance = state.target - scroller.scrollTop;
        if (Math.abs(distance) < 0.35) {
          scroller.scrollTop = state.target;
          state.frame = null;
          state.lastTime = 0;
          return;
        }
        const smoothing = 1 - Math.exp(-elapsed / 42);
        scroller.scrollTop += distance * smoothing;
        state.frame = requestAnimationFrame(animate);
      };
      state.frame = requestAnimationFrame(animate);
    };

    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as HTMLElement | null;
      const scroller = target?.closest<HTMLElement>(".scroll-area");
      if (scroller) resetScroller(scroller);
    };

    // Keep the next wheel gesture in sync after scrollbar dragging, page fades,
    // or DOM updates. A MutationObserver used to cancel active easing mid-frame.
    const onScroll = (event: Event) => {
      const scroller = event.target instanceof HTMLElement && event.target.matches(".scroll-area")
        ? event.target
        : null;
      if (!scroller) return;
      const state = states.get(scroller);
      if (state && state.frame === null) state.target = scroller.scrollTop;
    };

    document.addEventListener("wheel", onWheel, { passive: false });
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("wheel", onWheel);
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("scroll", onScroll, true);
    };
  }, []);
}
