import { uiAssetUrl } from "@/lib/assets";
import type { AppState, RuntimeId } from "@/bridge/types";

export type SoundId = "click" | "switch" | "error" | "zapret" | "zapret2" | "vpn" | "off";
export type SoundsVolume = "normal" | "louder" | "quieter";

const files: Record<SoundId, string> = {
  click: "click.mp3",
  switch: "switch.mp3",
  error: "startup-error.mp3",
  zapret: "zapret-on.mp3",
  zapret2: "zapret2-on.mp3",
  vpn: "vpn-on.mp3",
  off: "power-off.mp3",
};

/** Click/switch keep the softer scale the user already tuned. */
const CLICK_VOLUME: Record<SoundsVolume, number> = {
  normal: 0.04,
  louder: 0.1,
  quieter: 0.015,
};

/** Runtime / feedback sounds use a slightly higher master. */
const EFFECT_VOLUME: Record<SoundsVolume, number> = {
  normal: 0.06,
  louder: 0.12,
  quieter: 0.02,
};

/** Per-file loudness trim so enable/disable feel even across presets. */
const SOUND_GAIN: Record<SoundId, number> = {
  click: 1,
  switch: 1,
  error: 1,
  zapret: 1.7,
  zapret2: 1,
  vpn: 1.05,
  off: 1.65,
};

const pools = new Map<SoundId, HTMLAudioElement[]>();
let unlocked = false;
let primed = false;
let effectsEnabled = true;
let clickSoundsEnabled = true;
let volumeLevel: SoundsVolume = "normal";
let preloadPromise: Promise<void> | null = null;

function volumeFor(id: SoundId) {
  const table = id === "click" || id === "switch" ? CLICK_VOLUME : EFFECT_VOLUME;
  const base = table[volumeLevel] ?? table.normal;
  return Math.min(1, base * (SOUND_GAIN[id] ?? 1));
}

export function setSoundEffectsEnabled(enabled: boolean) {
  effectsEnabled = enabled;
  if (enabled) void preloadSounds();
}

export function setClickSoundsEnabled(enabled: boolean) {
  clickSoundsEnabled = enabled;
}

export function setSoundsVolume(level: SoundsVolume) {
  volumeLevel = level;
  for (const [id, pool] of pools.entries()) {
    const vol = volumeFor(id);
    for (const audio of pool) audio.volume = vol;
  }
}

function audioPool(id: SoundId) {
  const existing = pools.get(id);
  if (existing) return existing;
  const pool = Array.from({ length: id === "click" || id === "switch" ? 3 : 1 }, () => {
    const audio = new Audio(uiAssetUrl(`sounds/${files[id]}`));
    audio.preload = "auto";
    audio.volume = volumeFor(id);
    return audio;
  });
  pools.set(id, pool);
  return pool;
}

function waitAudioReady(audio: HTMLAudioElement, timeoutMs: number) {
  return new Promise<void>((resolve) => {
    if (audio.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
      resolve();
      return;
    }
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      audio.removeEventListener("canplaythrough", finish);
      audio.removeEventListener("loadeddata", finish);
      audio.removeEventListener("error", finish);
      window.clearTimeout(timer);
      resolve();
    };
    const timer = window.setTimeout(finish, timeoutMs);
    audio.addEventListener("canplaythrough", finish, { once: true });
    audio.addEventListener("loadeddata", finish, { once: true });
    audio.addEventListener("error", finish, { once: true });
  });
}

/** Create pools and wait until buffers are usable (or timeout) so the first click isn't silent. */
export function preloadSounds(timeoutMs = 1500): Promise<void> {
  if (preloadPromise) return preloadPromise;
  preloadPromise = (async () => {
    const ids = Object.keys(files) as SoundId[];
    const waiters: Promise<void>[] = [];
    for (const id of ids) {
      for (const audio of audioPool(id)) {
        try {
          audio.load();
        } catch {
          /* ignore */
        }
        waiters.push(waitAudioReady(audio, timeoutMs));
      }
    }
    await Promise.all(waiters);
  })().catch(() => undefined);
  return preloadPromise;
}

/**
 * Unlock autoplay in the current user-gesture stack by mute-priming every pooled element.
 * Call before playSound on the first pointerdown/change.
 */
export function unlockSounds() {
  unlocked = true;
  if (primed) return;
  primed = true;
  for (const pool of pools.values()) {
    for (const audio of pool) {
      try {
        const prevMuted = audio.muted;
        audio.muted = true;
        const playResult = audio.play();
        const settle = () => {
          try {
            audio.pause();
            audio.currentTime = 0;
          } catch {
            /* ignore */
          }
          audio.muted = prevMuted;
        };
        if (playResult && typeof playResult.then === "function") {
          void playResult.then(settle).catch(settle);
        } else {
          settle();
        }
      } catch {
        /* ignore */
      }
    }
  }
}

export function playSound(id: SoundId) {
  if (!unlocked || !effectsEnabled) return;
  if (id === "click" && !clickSoundsEnabled) return;
  const pool = audioPool(id);
  const audio = pool.find((item) => item.paused || item.ended) ?? pool[0];
  audio.volume = volumeFor(id);
  try {
    audio.currentTime = 0;
  } catch {
    /* ignore */
  }
  void audio.play().catch(() => undefined);
}

export function soundForRuntime(runtime: RuntimeId): SoundId | null {
  if (runtime === "zapret") return "zapret";
  if (runtime === "zapret2") return "zapret2";
  if (runtime === "goshkow-vpn") return "vpn";
  return null;
}

export function runtimeSoundTransition(
  previous: Pick<AppState["runtime"], "active" | "status">,
  next: Pick<AppState["runtime"], "active" | "status">,
): SoundId | null {
  if (next.status === "error" && previous.status !== "error") return "error";
  if (next.status === "on" && (previous.status !== "on" || previous.active !== next.active)) {
    return soundForRuntime(next.active);
  }
  return null;
}
