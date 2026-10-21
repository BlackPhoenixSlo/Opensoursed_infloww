"use client";

/**
 * useBlurMode — persisted "should images be blurred?" toggle.
 *
 * Three states:
 *   • "off"      — no blur, render images as-is (default)
 *   • "hover"    — blurred until the user hovers the tile
 *   • "constant" — blurred always (NSFW / over-the-shoulder mode)
 *
 * Applied to chat-message media tiles, vault picker thumbnails, and the
 * top-bar SFW toggle. Backed by useSyncExternalStore over localStorage
 * (custom event for same-window sync, storage event for cross-window),
 * with an "off" server snapshot so server-rendered consumers like the top bar
 * hydrate cleanly.
 */

import { useSyncExternalStore } from "react";

import { subscribeToStorage } from "@/lib/storageSync";

export type BlurMode = "off" | "hover" | "constant";

const STORAGE_KEY = "chatterly:blur-mode";
// Last non-off mode the user picked, so the top-bar SFW toggle can restore
// their preferred variant (hover vs constant) instead of hardcoding one.
const LAST_ON_KEY = "chatterly:blur-mode-last";
const EVENT = "chatterly-blur-mode-change";

function isMode(v: unknown): v is BlurMode {
  return v === "off" || v === "hover" || v === "constant";
}

export function readBlurMode(): BlurMode {
  if (typeof window === "undefined") return "off";
  const raw = window.localStorage.getItem(STORAGE_KEY);
  return isMode(raw) ? raw : "off";
}

function serverBlurMode(): BlurMode {
  return "off";
}

const subscribe = subscribeToStorage(EVENT);

export function setBlurMode(next: BlurMode): void {
  try {
    if (next === "off") window.localStorage.removeItem(STORAGE_KEY);
    else {
      window.localStorage.setItem(STORAGE_KEY, next);
      window.localStorage.setItem(LAST_ON_KEY, next);
    }
    window.dispatchEvent(new Event(EVENT));
  } catch { /* quota — silent */ }
}

export function useBlurMode(): [BlurMode, (next: BlurMode) => void] {
  const val = useSyncExternalStore(subscribe, readBlurMode, serverBlurMode);
  return [val, setBlurMode];
}

/** The SFW switch: on is any blurred mode, and flipping it on restores the
 *  last blurred variant. Every SFW switch (the app top bar's and Messages
 *  Pro's Window header's) reads this one store, so they always agree. */
export function useSfw(): [boolean, () => void] {
  const [mode] = useBlurMode();
  const on = mode !== "off";
  return [on, () => setBlurMode(on ? "off" : readLastOnBlurMode())];
}

/** The blurred mode the quick-toggle should restore when flipping blur
 *  back on: whatever non-off mode the user last used, else hover. */
export function readLastOnBlurMode(): BlurMode {
  if (typeof window === "undefined") return "hover";
  const raw = window.localStorage.getItem(LAST_ON_KEY);
  return isMode(raw) && raw !== "off" ? raw : "hover";
}

/** Tailwind classes for the currently selected mode. Empty string when
 *  blur is off so the original image styling isn't disturbed. */
export function blurImageClass(mode: BlurMode): string {
  if (mode === "hover") return "blur-md hover:blur-none transition-[filter] duration-200";
  if (mode === "constant") return "blur-md";
  return "";
}
