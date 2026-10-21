"use client";

/**
 * useFocusModeSettings — Focus mode's settings (Infloww's, 04-messages-pro P2),
 * persisted for this browser:
 *   • pause:     "Pause incoming messages", the freeze (`useFocusMode`); on by
 *                default, so Focus mode alone behaves as it always has
 *   • hideMuted: "Hide chats with muted notifications"
 * They apply only while Focus mode is on and available. The `useBlurMode`
 * storage pattern; a stored value that is not this shape reads as the default.
 */

import { useSyncExternalStore } from "react";

import { subscribeToStorage } from "@/lib/storageSync";

export type FocusModeSettings = { pause: boolean; hideMuted: boolean };

export const FOCUS_MODE_DEFAULTS: FocusModeSettings = { pause: true, hideMuted: false };

const STORAGE_KEY = "chatterly:focus-mode-settings";
const EVENT = "chatterly-focus-mode-settings-change";
const subscribe = subscribeToStorage(EVENT);

function readRaw(): string | null {
  return window.localStorage.getItem(STORAGE_KEY);
}

function parse(raw: string | null): FocusModeSettings {
  if (raw === null) return FOCUS_MODE_DEFAULTS;
  try {
    const v = JSON.parse(raw) as Record<string, unknown>;
    if (typeof v.pause === "boolean" && typeof v.hideMuted === "boolean") {
      return { pause: v.pause, hideMuted: v.hideMuted };
    }
  } catch { /* not JSON: the default */ }
  return FOCUS_MODE_DEFAULTS;
}

// Parsed once per raw string, so the settings object keeps its identity
// between renders.
let cache: { raw: string | null; value: FocusModeSettings } = { raw: null, value: FOCUS_MODE_DEFAULTS };
function parsed(raw: string | null): FocusModeSettings {
  if (cache.raw !== raw) cache = { raw, value: parse(raw) };
  return cache.value;
}

export function useFocusModeSettings(): [FocusModeSettings, (next: FocusModeSettings) => void] {
  const raw = useSyncExternalStore(subscribe, readRaw, () => null);
  const update = (next: FocusModeSettings) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      window.dispatchEvent(new Event(EVENT));
    } catch { /* quota: silent */ }
  };
  return [parsed(raw), update];
}
