/** Run after the browser has painted pending React updates. */
export function afterPaint(task: () => void) {
  requestAnimationFrame(() => {
    requestAnimationFrame(task);
  });
}

/** Fire a bridge command without blocking UI navigation. */
export function bridgeLater(task: () => void | Promise<unknown>) {
  afterPaint(() => {
    void Promise.resolve(task()).catch(() => undefined);
  });
}

/**
 * Run bridge work after the step transition finishes so state pushes
 * do not fight opacity/blur animations on the main thread.
 */
export function bridgeAfterTransition(task: () => void | Promise<unknown>, ms = 340) {
  afterPaint(() => {
    window.setTimeout(() => {
      void Promise.resolve(task()).catch(() => undefined);
    }, ms);
  });
}

/** Next macrotask — use before any bridge.call from click/transition handlers. */
export function bridgeIdle(task: () => void | Promise<unknown>) {
  window.setTimeout(() => {
    void Promise.resolve(task()).catch(() => undefined);
  }, 0);
}
