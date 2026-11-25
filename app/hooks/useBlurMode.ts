"use client";


import { useSyncExternalStore } from "react";

import { subscribeToStorage } from "@/lib/storageSync";

export type BlurMode = "off" | "hover" | "constant";

const STORAGE_KEY = "chatterly:blur-mode";
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
  } catch { }
}

export function useBlurMode(): [BlurMode, (next: BlurMode) => void] {
  const val = useSyncExternalStore(subscribe, readBlurMode, serverBlurMode);
  return [val, setBlurMode];
}

export function useSfw(): [boolean, () => void] {
  const [mode] = useBlurMode();
  const on = mode !== "off";
  return [on, () => setBlurMode(on ? "off" : readLastOnBlurMode())];
}

export function readLastOnBlurMode(): BlurMode {
  if (typeof window === "undefined") return "hover";
  const raw = window.localStorage.getItem(LAST_ON_KEY);
  return isMode(raw) && raw !== "off" ? raw : "hover";
}

export function blurImageClass(mode: BlurMode): string {
  if (mode === "hover") return "blur-md hover:blur-none transition-[filter] duration-200";
  if (mode === "constant") return "blur-md";
  return "";
}
