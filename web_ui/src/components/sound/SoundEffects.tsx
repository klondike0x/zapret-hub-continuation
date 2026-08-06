import { useEffect, useRef } from "react";
import type { AppState } from "@/bridge/types";
import {
  playSound,
  preloadSounds,
  runtimeSoundTransition,
  setClickSoundsEnabled,
  setSoundEffectsEnabled,
  setSoundsVolume,
  unlockSounds,
} from "@/lib/sounds";

export function SoundEffects({ state }: { state: AppState }) {
  const previousRuntime = useRef(state.runtime);
  const enabled = useRef(state.settings.soundsEnabled);

  useEffect(() => {
    enabled.current = state.settings.soundsEnabled;
    setSoundEffectsEnabled(state.settings.soundsEnabled);
  }, [state.settings.soundsEnabled]);

  useEffect(() => {
    setClickSoundsEnabled(state.settings.soundsClickEnabled !== false);
  }, [state.settings.soundsClickEnabled]);

  useEffect(() => {
    setSoundsVolume(state.settings.soundsVolume ?? "normal");
  }, [state.settings.soundsVolume]);

  useEffect(() => {
    preloadSounds();
    const onPointerDown = (event: PointerEvent) => {
      if (!enabled.current) return;
      if (event.button !== 0) return;
      unlockSounds();
      const control = (event.target as HTMLElement | null)?.closest<HTMLElement>("button, [role='button'], [role='switch']");
      if (!control || control.matches(":disabled, [aria-disabled='true']")) return;
      const requested = control.dataset.sound;
      if (requested === "none") return;
      const isSwitch =
        requested === "switch" ||
        control.getAttribute("role") === "switch" ||
        control.getAttribute("aria-checked") != null;
      playSound(isSwitch ? "switch" : requested === "off" ? "off" : "click");
    };
    const onChange = (event: Event) => {
      if (!enabled.current) return;
      unlockSounds();
      const target = event.target as HTMLInputElement | HTMLSelectElement | null;
      if (target?.dataset.sound !== "none" && target?.matches("select, input[type='radio'], input[type='checkbox']")) playSound("switch");
    };
    window.addEventListener("pointerdown", onPointerDown, true);
    window.addEventListener("change", onChange, true);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown, true);
      window.removeEventListener("change", onChange, true);
    };
  }, []);

  useEffect(() => {
    const sound = runtimeSoundTransition(previousRuntime.current, state.runtime);
    previousRuntime.current = state.runtime;
    if (sound && state.settings.soundsEnabled) playSound(sound);
  }, [state.runtime, state.settings.soundsEnabled]);
  return null;
}
