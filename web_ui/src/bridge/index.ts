import { createMockBridge } from "./mock";
import type { EventName, Events, ZapretHubBridge } from "./types";

let instance: ZapretHubBridge | null = null;

type NativeObject = {
  call(command: string, payload: string, callback: (result: string) => void): void;
  event: {
    connect(callback: (event: string, payload: string) => void): void;
  };
};

declare global {
  interface Window {
    qt?: { webChannelTransport: unknown };
    QWebChannel?: new (
      transport: unknown,
      ready: (channel: { objects: { bridge: NativeObject } }) => void,
    ) => unknown;
    /** Set by #startup-boot chrome so React reuses the same QWebChannel object. */
    __zapretNativeBridge?: NativeObject;
    zapretHubBridge?: ZapretHubBridge;
  }
}

function createNativeBridge(native: NativeObject): ZapretHubBridge {
  const listeners = new Map<EventName, Set<(payload: unknown) => void>>();
  native.event.connect((event, payload) => {
    const parsed = JSON.parse(payload || "null");
    listeners.get(event as EventName)?.forEach((callback) => callback(parsed));
  });

  const subscribe = <E extends EventName>(event: E, callback: (payload: Events[E]) => void) => {
    if (!listeners.has(event)) listeners.set(event, new Set());
    listeners.get(event)!.add(callback as (payload: unknown) => void);
    return () => listeners.get(event)?.delete(callback as (payload: unknown) => void);
  };

    const ASYNC_RESULT = new Set([
      "marketplace.installed",
      "marketplace.image",
      "marketplace.list",
      "marketplace.get",
      "marketplace.remove",
      "marketplace.check-updates",
      "vpn.import-subscription",
      "mods.delete",
      "mods2.delete",
    ]);

  return {
    call(command, payload) {
      if (ASYNC_RESULT.has(command)) {
        const requestId =
          typeof crypto !== "undefined" && "randomUUID" in crypto
            ? crypto.randomUUID()
            : `mp-${Date.now()}-${Math.random().toString(16).slice(2)}`;
        return new Promise((resolve, reject) => {
          const timer = window.setTimeout(() => {
            off();
            reject(new Error("Marketplace request timed out"));
          }, 45000);
          const off = subscribe("marketplace.result", (msg) => {
            if (msg?.requestId !== requestId) return;
            window.clearTimeout(timer);
            off();
            if (!msg.ok) reject(new Error(msg.error || "Marketplace request failed"));
            else resolve(msg.value as never);
          });
          native.call(
            command,
            JSON.stringify({ ...(payload as object), __requestId: requestId }),
            (raw) => {
              try {
                const result = JSON.parse(raw || "null");
                if (result?.error) {
                  window.clearTimeout(timer);
                  off();
                  reject(new Error(result.error));
                }
              } catch (error) {
                window.clearTimeout(timer);
                off();
                reject(error);
              }
            },
          );
        });
      }
      return new Promise((resolve, reject) => {
        native.call(command, JSON.stringify(payload ?? null), (raw) => {
          try {
            const result = JSON.parse(raw || "null");
            if (result?.error) reject(new Error(result.error));
            else resolve(result?.value as never);
          } catch (error) {
            reject(error);
          }
        });
      });
    },
    subscribe,
  };
}

export async function initializeBridge(): Promise<void> {
  if (instance || typeof window === "undefined") return;
  // Prefer the early #startup-boot channel — a second QWebChannel on the same
  // transport can break minimize/close/drag during the preloader.
  if (window.__zapretNativeBridge) {
    instance = createNativeBridge(window.__zapretNativeBridge);
    return;
  }
  if (window.qt?.webChannelTransport && window.QWebChannel) {
    instance = await new Promise<ZapretHubBridge>((resolve) => {
      new window.QWebChannel!(window.qt!.webChannelTransport, (channel) => {
        window.__zapretNativeBridge = channel.objects.bridge;
        resolve(createNativeBridge(channel.objects.bridge));
      });
    });
    return;
  }
  instance = createMockBridge();
}

export function getBridge(): ZapretHubBridge {
  if (instance) return instance;
  instance = typeof window !== "undefined" && window.zapretHubBridge
    ? window.zapretHubBridge
    : createMockBridge();
  return instance;
}

export type { ZapretHubBridge } from "./types";
